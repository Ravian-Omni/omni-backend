"""A run's open questions as needs for Brain_Hands (signals contract [7]): one object, pulled with next_event, pushed when
nobody polls for it, and closed as run_lost when the process that was waiting for the answer is gone."""

import os
from datetime import datetime, timezone

from src.agent_runtime.decisions import parse_response
from src.database import answer_decision, get_chat_title, list_decisions, list_open_decisions, load_pref
from src.services import brain_hands, task_status
from src.services.chat_bridge import USER_ID

UNATTENDED_S = 60  # a need nobody polls for this long is pushed


async def agenda_of(chat_id: str) -> str:
    return await load_pref(USER_ID, f"agenda:{chat_id}") or ""


async def credits_approved(chat_id: str, since: str) -> float:
    """Credits approved in the chat since `since` (an ISO time), by a card or by the budget: what a run spent."""
    return sum(float((d["request"] or {}).get("credits") or 0) for d in await list_decisions(chat_id)
               if d["card"] == "confirm_spend" and d["created_at"] >= since and d["response"] is not None
               and parse_response("confirm_spend", d["response"]).approved)


def _utc(timestamp: str) -> str:
    try:
        return datetime.fromisoformat(timestamp).astimezone(timezone.utc).isoformat(timespec="seconds")
    except (TypeError, ValueError):
        return datetime.now(timezone.utc).isoformat(timespec="seconds")


async def build(chat_id: str, request_id: str, question: dict, card: dict, asked_at: str) -> dict:
    """The need as contract [7] shapes it: `card` is the raw card (what a grant reads recipients and credits from) and
    `question` is task_status.question_of's reading of it."""
    options = [(o.get("label") or str(o.get("value"))) if isinstance(o, dict) else str(o) for o in question.get("options") or []]
    asked = [q.get("label") or q.get("question") or "" for q in question.get("questions") or [] if isinstance(q, dict)]
    data = {"request_id": request_id, "task_id": chat_id, "task_title": await get_chat_title(chat_id) or "", "agenda_id": await agenda_of(chat_id),
            "card": card, "card_kind": question["kind"], "answer_with": question["answer_with"], "options": options, "asked_at": _utc(asked_at)}
    if not data["agenda_id"]:
        data.pop("agenda_id")
    message = question.get("message") or question.get("title") or ""
    return {"app": "daxagent", "kind": "dax.need", "id": request_id, "title": (question.get("title") or message).split("\n")[0],
            "text": "\n".join([message, *(f"- {a}" for a in asked if a)]), "data": data}


async def push(need: dict, **extra) -> bool:
    return await brain_hands.push(need["kind"], need["id"], need["title"], need["text"], **need["data"], **extra)


def alive(pid: int | None) -> bool:
    if not pid or pid == os.getpid():  # no pid: made before it was recorded; our own: left by an earlier process with the same pid
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass  # another user's process, still running
    return True


async def close_lost(resumed: set[str] = frozenset()) -> int:
    """At startup: a question whose process is gone can never be answered. If its run resumed, the step asks again and the
    old question is closed quietly. Otherwise close it as run_lost and tell Brain_Hands, which restarts the step (as
    "<request_id>:run_lost", because the open one may have been pushed already and Brain_Hands drops a repeated id).
    Needs made before pids were recorded close quietly."""
    closed = 0
    for row in await list_open_decisions():
        if alive(row["owner_pid"]):
            continue
        await answer_decision(row["id"], {"closed": "resumed" if row["chat_id"] in resumed else "run_lost"})
        closed += 1
        if row["chat_id"] not in resumed and row["owner_pid"] and await agenda_of(row["chat_id"]):
            need = await build(row["chat_id"], str(row["id"]), task_status.question_of(row["request"], row["persona"]), row["request"], row["created_at"])
            await push({**need, "id": f"{row['id']}:run_lost"}, reason="run_lost")
    return closed
