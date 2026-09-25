"""Public read-only sharing of chat transcripts.

A share link is an opaque token mapped to one chat. Anyone holding the token can
read that transcript without signing in, so links are revocable and the public
response carries only the messages, never file paths or workspace details.
"""

import secrets

from fastapi import APIRouter, HTTPException, Request
from loguru import logger

from src.database import create_share_link, get_share_link, revoke_share_link
from src.services.chat_service import ChatService

router = APIRouter()


@router.post("/{chat_id}")
async def share_chat(chat_id: str, request: Request, user_id: str = "local_user"):
    """Create a public read-only link for a chat."""
    # Fail before minting a token if the chat does not exist
    await ChatService.get_chat_mode_history(user_id, chat_id)

    token = secrets.token_urlsafe(16)
    await create_share_link(token, chat_id, user_id, "chats")
    base = str(request.base_url).rstrip("/")
    return {
        "success": True,
        "chat_id": chat_id,
        "token": token,
        "share_url": f"{base}/share/{token}",
    }


@router.get("/{token}")
async def view_shared_chat(token: str):
    """Return the shared transcript. Public: no authentication required."""
    link = await get_share_link(token)
    if not link:
        raise HTTPException(status_code=404, detail="This share link is invalid or has been revoked.")

    history = await ChatService.get_chat_mode_history(link["user_id"], link["chat_id"])
    # Only the conversation is public; chat_dir and other local details are dropped.
    return {
        "chat_id": link["chat_id"],
        "shared_at": link["created_at"],
        "messages": history.get("raw_messages", []),
    }


@router.delete("/{token}")
async def revoke_shared_chat(token: str):
    """Revoke a share link."""
    if not await revoke_share_link(token):
        raise HTTPException(status_code=404, detail="This share link is invalid or already revoked.")
    logger.info(f"Share link revoked: {token}")
    return {"success": True, "message": "Share link revoked"}
