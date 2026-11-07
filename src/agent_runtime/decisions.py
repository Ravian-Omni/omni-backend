"""Decision cards: the typed questions a persona asks the user before it acts.

Every card is one ``input_request`` WebSocket message with
``input_type="decision_card"`` and a ``card`` field naming its kind, and the
user's answer comes back as the ``response`` of an ``input_response``. The
card and the answer are written to the decision log so the chat has an audit
trail of everything that spent credits, sent a message, or changed the plan.

Card kinds and their fields (all cards also carry ``id``, ``title`` and ``message``):

- ``confirm_spend``: tool, server, count, unit, credits, balance_before, balance_after, detail
- ``confirm_send``: tool, server, channel, recipients, recipient_count, subject, body_preview, detail
- ``choose``: question, options [{label, value, description}], multi
- ``provide_data``: prompt, accept (file extensions), allow_text
- ``review_artifact``: artifact_id, kind, columns, rows (preview), row_count
- ``text``: prompt (free-form answer)

Answers are dicts ``{"action": "approve" | "reject" | "submit", "value": ...,
"selected": [...]}``; a bare string is accepted too ("yes"/"no" or the text).
"""

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any

from loguru import logger

from src.configs.datetime_utils import dt
from src.database import answer_decision, log_decision

_YES = {"yes", "y", "approve", "approved", "ok", "okay", "proceed", "confirm", "send", "go", "go ahead", "sure"}
_NO = {"no", "n", "reject", "rejected", "cancel", "stop", "deny", "denied", "terminate", "skip"}


@dataclass
class Decision:
    """What the user answered to a card."""

    card: str
    approved: bool
    value: Any = None
    selected: list[Any] = field(default_factory=list)
    text: str = ""
    raw: Any = None

    @property
    def action(self) -> str:
        return str(self.raw.get("action", "")).lower() if isinstance(self.raw, dict) else ""

    @property
    def skipped(self) -> bool:
        """The user left the decision to the agent."""
        return self.action == "skip"

    @property
    def suggestion(self) -> str:
        """What the user typed instead of approving or rejecting ("" when they did not)."""
        return self.text if self.action == "revise" else ""

    def summary(self) -> str:
        if self.skipped:
            return "skipped: agent decides"
        if self.suggestion:
            return self.suggestion
        if self.card in ("confirm_spend", "confirm_send"):
            return "approved" if self.approved else "rejected"
        if self.card == "choose":
            return f"chose {self.selected or self.value}"
        if self.card == "provide_data":
            return f"provided {self.value}" if self.value else "provided nothing"
        return self.text or ("approved" if self.approved else "rejected")


def parse_response(card: str, raw: Any) -> Decision:
    """Normalise whatever the client sent into a Decision."""
    if isinstance(raw, str):
        text = raw.strip()
        low = text.lower()
        if card == "text":
            return Decision(card, approved=bool(text), text=text, value=text, raw=raw)
        if low in _YES:
            return Decision(card, approved=True, text=text, raw=raw)
        if low in _NO:
            return Decision(card, approved=False, text=text, raw=raw)
        try:
            raw = json.loads(text)
        except (TypeError, ValueError):
            if card in ("confirm_spend", "confirm_send"):
                # Free text to a spend or send is an instruction, never a yes ("draft only" once read as approval)
                return Decision(card, approved=False, text=text, raw={"action": "revise", "text": text})
            # A free-text reply to a choice or data card is the answer itself.
            return Decision(card, approved=bool(text), text=text, value=text, raw=raw)
    if isinstance(raw, dict):
        action = str(raw.get("action", "")).lower()
        approved = action in ("approve", "submit", "choose", "send", "yes", "ok", "confirm") or (
            action == "" and raw.get("approved") is True
        )
        return Decision(
            card,
            approved=approved,
            value=raw.get("value"),
            selected=list(raw.get("selected") or ([] if raw.get("value") is None else [raw.get("value")])),
            text=str(raw.get("text") or raw.get("note") or ""),
            raw=raw,
        )
    return Decision(card, approved=False, raw=raw)


class DecisionCards:
    """Ask the user structured questions over the chat WebSocket."""

    def __init__(
        self,
        websocket_manager,
        chat_id: str,
        persona: str,
        task_id: str | None = None,
        call_id: str | None = None,
        capability_id: str | None = None,
        timeout: int = 900,
    ):
        self.ws = websocket_manager
        self.chat_id = chat_id
        self.persona = persona
        self.task_id = task_id
        self.call_id = call_id
        self.capability_id = capability_id
        self.timeout = timeout
        self.history: list[dict[str, Any]] = []
        # Optional: async callable that writes a card record into chat history.
        self.persist = None

    async def _ask(self, card: str, title: str, message: str, **fields: Any) -> Decision:
        payload = {"card": card, "title": title, "message": message, **fields}
        decision_id = await log_decision(self.chat_id, self.task_id, self.persona, card, payload)
        payload["id"] = decision_id
        if self.ws is None:
            logger.warning(f"No websocket for decision card '{card}' in chat {self.chat_id}; rejecting")
            return Decision(card, approved=False)
        try:
            raw = await self.ws.request_input(
                self.chat_id,
                {
                    "input_type": "decision_card",
                    "prompt": message,
                    "data": {
                        "source": self.persona,
                        "content": {
                            **payload,
                            "task_id": self.task_id,
                            "call_id": self.call_id,
                            "capability_id": self.capability_id,
                        },
                        "timestamp": dt.now_iso(),
                    },
                },
                timeout=self.timeout,
            )
        except (asyncio.CancelledError, TimeoutError, ValueError):
            await answer_decision(decision_id, {"action": "abandoned"})
            raise
        decision = parse_response(card, raw)
        await answer_decision(decision_id, decision.raw if decision.raw is not None else raw)
        self.history.append({"card": card, "title": title, "answer": decision.summary()})
        if self.persist is not None:
            try:
                await self.persist({
                    "type": "decision_card",
                    **payload,
                    "answered": True,
                    "answer": decision.raw if decision.raw is not None else raw,
                    "answer_summary": decision.summary(),
                })
            except Exception as e:
                logger.warning(f"[{self.persona}] could not persist decision card: {e}")
        logger.info(f"[{self.persona}] card {card} #{decision_id}: {decision.summary()}")
        return decision

    async def confirm_spend(
        self,
        tool: str,
        server: str,
        count: int,
        credits: int | None = None,
        balance_before: int | None = None,
        unit: str = "records",
        detail: str = "",
    ) -> Decision:
        """Ask before credits are consumed."""
        credits = count if credits is None else credits
        balance_after = None if balance_before is None else balance_before - credits
        message = f"Enriching {count} {unit} will consume {credits} credits, do you want to proceed?"
        if "enrich" not in tool.lower():
            message = f"Running {tool} on {count} {unit} will consume {credits} credits, do you want to proceed?"
        return await self._ask(
            "confirm_spend", "Confirm credit spend", message,
            tool=tool, server=server, count=count, unit=unit, credits=credits,
            balance_before=balance_before, balance_after=balance_after, detail=detail,
        )

    async def confirm_send(
        self,
        tool: str,
        server: str,
        channel: str,
        recipients: list[str],
        subject: str = "",
        body_preview: str = "",
        detail: str = "",
        recipient_count: int | None = None,
    ) -> Decision:
        """Ask before anything leaves the system."""
        n = recipient_count if recipient_count is not None else len(recipients)
        message = f"Send this {channel} to {n} recipient{'s' if n != 1 else ''}?"
        return await self._ask(
            "confirm_send", f"Confirm {channel}", message,
            tool=tool, server=server, channel=channel, recipients=recipients[:50],
            recipient_count=n, subject=subject, body_preview=body_preview[:2000], detail=detail,
        )

    async def choose(
        self, question: str, options: list[dict[str, Any]], multi: bool = False, title: str = "Your call", why: str = ""
    ) -> Decision:
        """Offer options; each option is {label, value, description?}."""
        return await self._ask("choose", title, question, question=question, options=options, multi=multi, why=why)

    async def provide_data(
        self, prompt: str, accept: list[str] | None = None, allow_text: bool = True, title: str = "Data needed", why: str = ""
    ) -> Decision:
        """Ask for a file (path) or pasted data."""
        return await self._ask(
            "provide_data", title, prompt, prompt=prompt,
            accept=accept or ["csv", "xlsx", "json"], allow_text=allow_text, why=why,
        )

    async def review_artifact(
        self,
        artifact_id: str,
        kind: str,
        title: str,
        columns: list[str],
        rows: list[dict[str, Any]],
        row_count: int,
        message: str = "Review this list before I continue. Untick anything you want left out.",
        why: str = "",
    ) -> Decision:
        """Show a table for approval; the answer may carry excluded row ids."""
        return await self._ask(
            "review_artifact", title, message, artifact_id=artifact_id, kind=kind,
            columns=columns, rows=rows[:25], row_count=row_count, why=why,
        )

    async def text(self, prompt: str, title: str = "Question") -> Decision:
        """Free-form question."""
        return await self._ask("text", title, prompt, prompt=prompt)
