"""Jev, TypeSafe AI's decision model: typed answers with calibrated probabilities, never text.

Every campaign reply is read by Jev with the same questions, and plain rules turn the answers
into what happens next. Jev decides, the rules route, an agent writes, a person approves.
API: https://docs.typesafe.ai/api (POST /v1/systemone, Bearer key from Settings, API keys).
"""

import asyncio
import os
from typing import Any

import httpx

from src.configs.settings import settings

URL = os.getenv("DAXAGENT_JEV_URL", "https://api.typesafe.ai/v1/systemone")
MODEL = os.getenv("DAXAGENT_JEV_MODEL", "jev-latest")
RETRY_STATUSES = (429, 529)  # rate limited or overloaded: back off and retry

INTENTS = {
    "interested": "Wants to talk, see a demo or learn more now",
    "question": "Asks about the offer, pricing, data or fit before deciding",
    "objection": "Pushes back with a reason: has a provider, too expensive, not a fit",
    "referral": "Points to someone else who handles this",
    "not_now": "Not now, maybe later; not a hard no",
    "out_of_office": "An automatic away or out-of-office message",
    "unsubscribe": "Asks to stop the emails or be removed",
    "other": "None of these, or unclear",
}

QUESTIONS = {
    "intent": {"type": "choice", "instructions": "What does the person replying want?", "criteria": INTENTS},
    "needs_human": {
        "type": "noul",
        "instructions": "Should a person on the sales team read and answer this themselves, rather than an automated assistant?",
    },
    "urgency": {
        "type": "score",
        "instructions": "How soon should this reply be answered?",
        "criteria": ["Whenever; no time pressure", "Within a day or two", "Today", "Within the hour"],
    },
    "buying_signal": {
        "type": "score",
        "instructions": "How strong is the sign that they may buy?",
        "criteria": ["None", "Weak: polite or curious", "Clear: asks about price, timing or next steps", "Strong: wants a meeting or a trial now"],
    },
    "competitor": {"type": "noul", "instructions": "Does the reply name a competitor or a provider they use today?"},
    "meeting_ok": {"type": "noul", "instructions": "Does the reply clearly accept or ask for a meeting or a call?"},
}

# Routes, and whether a person is involved before anything goes out.
ROUTES = {
    "suppress": "Unsubscribe: stop every campaign to this person",
    "auto_reply": "Out of office: keep the sequence going",
    "snooze": "Not now: stop this campaign, try again later",
    "handoff": "A person on the team answers",
    "propose_meeting": "Draft a reply with meeting times; the owner approves the send",
    "answer": "Draft an answer (KnightWatch for competitors); the owner approves the send",
}


class JevError(RuntimeError):
    pass


def configured() -> bool:
    return bool(getattr(settings, "JEV_API_KEY", None))


async def ask(state: Any, questions: dict, client: httpx.AsyncClient | None = None, attempts: int = 3) -> dict:
    """One Jev request; returns {"model", "answers"}. Retries rate limits and overloads with backoff."""
    if not configured():
        raise JevError("Jev is not connected: add the key in Settings, API keys")
    body = {"model": MODEL, "state": state, "questions": questions}
    headers = {"Authorization": f"Bearer {settings.JEV_API_KEY}", "Content-Type": "application/json"}
    own = client is None
    client = client or httpx.AsyncClient(timeout=20)
    try:
        for attempt in range(attempts):
            response = await client.post(URL, json=body, headers=headers)
            if response.status_code in RETRY_STATUSES and attempt < attempts - 1:
                await asyncio.sleep(0.5 * 2**attempt)
                continue
            if response.status_code != 200:
                raise JevError(f"Jev {response.status_code}: {response.text[:200]}")
            data = response.json()
            return {"model": data.get("model", MODEL), "answers": data.get("answers") or {}}
        raise JevError("Jev stayed busy; try again in a minute")
    finally:
        if own:
            await client.aclose()


def _level(answer: dict) -> float:
    """A score answer on 0..1 (Jev returns 0..highest level)."""
    top = max((int(k) for k in (answer.get("legend") or answer.get("probabilities") or {"1": 0})), default=1) or 1
    return round(float(answer.get("score") or 0) / top, 3)


async def read_reply(reply: str, context: dict | None = None, client: httpx.AsyncClient | None = None) -> dict:
    """Jev's reading of one reply: the intent with its confidence and distribution, and the signals the rules use."""
    state = {"reply": reply[:4000], **{k: v for k, v in (context or {}).items() if v}}
    result = await ask(state, QUESTIONS, client=client)
    a = result["answers"]
    intent = a.get("intent") or {}
    return {
        "intent": intent.get("choice", "other"),
        "intent_confidence": round(float(intent.get("confidence") or 0), 3),
        "intents": {k: round(float(v), 3) for k, v in (intent.get("probabilities") or {}).items()},
        "needs_human": round(float((a.get("needs_human") or {}).get("noul") or 0), 3),
        "urgency": _level(a.get("urgency") or {}),
        "buying_signal": _level(a.get("buying_signal") or {}),
        "competitor": round(float((a.get("competitor") or {}).get("noul") or 0), 3),
        "meeting_ok": round(float((a.get("meeting_ok") or {}).get("noul") or 0), 3),
        "model": result["model"],
    }


def route(read: dict, t: dict) -> str:
    """What happens to a reply, from Jev's reading: plain rules over the user's thresholds (prefs "inbox")."""
    p = read.get("intents") or {read.get("intent", "other"): read.get("intent_confidence", 0)}
    if p.get("unsubscribe", 0) >= t["suppress"]:
        return "suppress"
    if p.get("out_of_office", 0) >= t["suppress"]:
        return "auto_reply"
    if read.get("needs_human", 0) >= t["handoff"] or read.get("urgency", 0) >= t["urgent"]:
        return "handoff"
    if read.get("intent_confidence", 0) < t["confident"]:
        return "handoff"  # unsure: a person reads it
    if p.get("interested", 0) >= t["meeting"] and read.get("meeting_ok", 0) >= t["meeting"]:
        return "propose_meeting"
    if p.get("not_now", 0) >= t["handoff"]:
        return "snooze"
    if read.get("intent") in ("question", "objection", "referral") or read.get("competitor", 0) >= t["handoff"]:
        return "answer"
    return "handoff"
