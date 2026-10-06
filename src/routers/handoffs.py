"""Replies handed to a person by the Inbox Agent: list them, claim or reassign them, edit and send the answer.

Send is the owner's own click, so it is the approval: the answer goes out as a reply in the contact's
Gmail thread (or a new email when there is no thread), exactly as the owner left it.
"""

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.database import get_handoff, list_handoffs, update_handoff

router = APIRouter()


class HandoffUpdate(BaseModel):
    owner: str | None = Field(None, max_length=80)
    draft: str | None = Field(None, max_length=10000)
    status: Literal["open", "claimed", "done"] | None = None


class HandoffSend(BaseModel):
    body: str = Field(..., min_length=1, max_length=10000)


class ReplyText(BaseModel):
    text: str = Field(..., min_length=1, max_length=4000)


@router.get("")
async def handoffs(status: str | None = "active", chat_id: str | None = None, user_id: str = "local_user") -> dict:
    """Newest first; status "active" (default) = open or claimed, "" = all."""
    return {"handoffs": await list_handoffs(user_id, status or None, chat_id)}


@router.post("/jev/read")
async def jev_read(body: ReplyText, user_id: str = "local_user") -> dict:
    """Jev's reading of a pasted reply and the route the user's rules give it (Settings, Try a reply)."""
    from src.agent_runtime import jev, prefs

    try:
        read = await jev.read_reply(body.text)
    except jev.JevError as e:
        raise HTTPException(status_code=400, detail=str(e))
    route = jev.route(read, await prefs.get(user_id, "inbox"))
    return {"read": read, "route": route, "meaning": jev.ROUTES[route]}


@router.get("/watch/status")
async def watch_status() -> dict:
    """When the reply watcher last ran and what it found."""
    from src.agent_runtime import watcher

    s = watcher.state
    return {"last_sweep": s["last_sweep"].isoformat() if s["last_sweep"] else None, "running": s["running"], "summary": s["summary"]}


@router.post("/watch/sweep")
async def sweep_now(user_id: str = "local_user") -> dict:
    """Check every campaign thread now (the Check now button), whatever the schedule says."""
    from src.agent_runtime import watcher

    return await watcher.sweep(user_id)


@router.get("/{handoff_id}")
async def one_handoff(handoff_id: str) -> dict:
    h = await get_handoff(handoff_id)
    if not h:
        raise HTTPException(status_code=404, detail="No such handoff")
    return h


@router.patch("/{handoff_id}")
async def change_handoff(handoff_id: str, body: HandoffUpdate) -> dict:
    h = await update_handoff(handoff_id, **body.model_dump())
    if not h:
        raise HTTPException(status_code=404, detail="No such handoff")
    return h


@router.post("/{handoff_id}/send")
async def send_handoff(handoff_id: str, body: HandoffSend) -> dict:
    from src.agent_runtime.tools.sales import gmail_call

    h = await get_handoff(handoff_id)
    if not h:
        raise HTTPException(status_code=404, detail="No such handoff")
    if h["status"] == "sent":
        raise HTTPException(status_code=409, detail="Already sent")
    if h["thread_id"]:
        slug, args = "GMAIL_REPLY_TO_THREAD", {"thread_id": h["thread_id"], "recipient_email": h["contact"], "message_body": body.body}
    else:
        subject = h["subject"] if h["subject"].lower().startswith("re:") else f"Re: {h['subject']}".strip()
        slug, args = "GMAIL_SEND_EMAIL", {"recipient_email": h["contact"], "subject": subject, "body": body.body}
    try:
        result = await gmail_call(h["user_id"], slug, {**args, "user_id": "me", "is_html": False})
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not (result or {}).get("successful", True):
        raise HTTPException(status_code=502, detail=f"Gmail did not send it: {(result or {}).get('error')}")
    return await update_handoff(handoff_id, draft=body.body, status="sent")
