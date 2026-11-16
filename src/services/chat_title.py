"""A chat's title follows its work. It is renamed when a run starts, when its plan is approved and when a run completes,
each with one cheap model call that is skipped when what the title would be made from did not change. A goal's chat keeps
its subject and changes the part after it ("<subject> · <work>"). A title a person gave is never renamed."""

import ast
import asyncio
import hashlib
import json

from loguru import logger

from src.agent_runtime import llm
from src.database import (chat_agenda, chat_owner, get_chat_repository, get_chat_title, get_title_state, list_untitled_chats,
                          set_chat_title)

SEP = " · "
REPLY = " Reply with the title only: no quotes, no final period."
PROMPTS = {
    "request": "Title the work this request asks for, in 3 to 6 words.",
    "plan": "Title what this plan sets out to do, in 3 to 6 words.",
    "done": "Title what was done, as a result, in 3 to 6 words (for example: 25 Bay Area buyers enriched).",
    "past": "Title this conversation in 3 to 6 words from its request and its result.",
}


async def _title(moment: str, text: str) -> str:
    """Three to six words for the text, or "" when the model fails."""
    try:
        return " ".join((await llm.complete(PROMPTS[moment] + REPLY, text[:1500], max_tokens=24)).strip("\"'. \n").split()[:6])
    except Exception as e:
        logger.warning(f"[chat_title] not named: {e}")
        return ""


async def _messages(chat_id: str) -> list[dict]:
    owner = await chat_owner(chat_id)
    chat = await (await get_chat_repository()).get_chat(owner, chat_id, "omni") if owner else None
    return (chat or {}).get("messages") or []


def _closing(messages: list[dict]) -> str:
    last = next((m for m in reversed(messages) if m.get("name") in ("process_completion_agent", "conversation_agent")), None)
    return str((last or {}).get("content") or "")


async def source(chat_id: str, moment: str) -> str:
    """What a title is made from at a moment the chat itself holds: the approved plan's steps, or the run's closing summary."""
    messages = await _messages(chat_id)
    if moment == "done":
        return _closing(messages)
    plan = next((m for m in reversed(messages) if m.get("name") == "planner_agent"), None)
    try:
        return "; ".join(str(s.get("task") or "") for s in json.loads(plan["content"]).get("breakdown") or [])
    except (TypeError, ValueError, KeyError):
        return ""


async def retitle(chat_id: str, moment: str, text: str = "") -> str | None:
    """Follow the work: the new title, or None when it did not change (a person gave it, what it is made from is as it was
    at the last title, or the model failed). text: what to title when it is not in the chat yet (a new request)."""
    title, by, basis = await get_title_state(chat_id)
    if by == "user":
        return None
    text = (text or await source(chat_id, moment)).strip()
    key = hashlib.sha1(f"{moment}|{text}".encode()).hexdigest()
    if not text or key == basis:
        return None
    if not (work := await _title(moment, text)):
        return None
    subject = (title or "").split(SEP)[0] if title and await chat_agenda(chat_id) else ""  # a goal's chat keeps the subject it began with
    new = f"{subject}{SEP}{work}" if subject else work
    await set_chat_title(chat_id, new, "auto", key)
    return new if new != title else None


def _request(messages: list[dict]) -> str:
    """The first request of a chat (its text is stored as str({"task": ..., "files": ...}))."""
    first = next((m for m in messages if m.get("name") == "chat_manager"), None)
    content = str((first or {}).get("content") or "")
    try:
        return str(ast.literal_eval(content).get("task") or "")
    except (ValueError, SyntaxError, AttributeError):
        return content


async def _name_once(chat_id: str) -> bool:
    """Give an untitled chat a name from its first request and its last result; False when the model failed."""
    messages = await _messages(chat_id)
    text = f"Request: {_request(messages)[:800]}\nResult: {_closing(messages)[:500]}".strip()
    work = await _title("past", text)
    if work and not await get_chat_title(chat_id):  # not named meanwhile
        await set_chat_title(chat_id, work, "auto", hashlib.sha1(f"past|{text}".encode()).hexdigest())
    return bool(work)


async def backfill(at_a_time: int = 3) -> int:
    """Name the task chats that have no title, once, a few at a time; stops when a whole batch fails (no model reachable).
    Returns how many were named."""
    named, todo = 0, await list_untitled_chats()
    for i in range(0, len(todo), at_a_time):
        done = await asyncio.gather(*(_name_once(c) for c in todo[i:i + at_a_time]))
        named += sum(done)
        if not any(done):
            break
    return named
