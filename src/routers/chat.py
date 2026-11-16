"""Chat management REST API endpoints.

This module provides endpoints for:
- Creating new chat sessions (general and capability-specific)
- Retrieving chat history
- Filtering chat messages by task ID
- Managing capability-specific conversations
"""

import os
import re

from fastapi import APIRouter, File, HTTPException, Path, Query, Request, UploadFile, status
from pydantic import BaseModel, Field

from src.configs.settings import settings
from src.schemas.chat import (
    ChatHistoryByTaskId,
    EnhancedChatHistory,
    SimplifiedChatHistory,
)
from src.services.chat_service import ChatService

router = APIRouter()

MAX_UPLOAD_BYTES = 25 * 1024 * 1024


def _unique_path(folder: str, name: str) -> str:
    """A path in folder for name, adding -1, -2, … when the name is taken."""
    stem, ext = os.path.splitext(name)
    path, n = os.path.join(folder, name), 1
    while os.path.exists(path):
        path, n = os.path.join(folder, f"{stem}-{n}{ext}"), n + 1
    return path


@router.post("/upload")
async def upload_files(files: list[UploadFile] = File(...)) -> dict:
    """Save files picked in the browser so a message can attach them by path.

    The web UI has no access to local paths, so it uploads here and attaches the
    returned paths exactly as the desktop app attaches local ones; a persona then
    copies them into its chat's files folder and reads them from there.
    """
    folder = os.path.join(settings.ROOT_DIR, "uploads")
    os.makedirs(folder, exist_ok=True)
    saved = []
    for f in files:
        data = await f.read()
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail=f"{f.filename} is over 25 MB")
        name = re.sub(r"[^\w.\-]+", "_", os.path.basename(f.filename or "file")) or "file"
        path = _unique_path(folder, name)
        with open(path, "wb") as out:
            out.write(data)
        saved.append({"fileName": os.path.basename(path), "filePath": path, "size": len(data)})
    return {"files": saved}


# =============================================================================
# OMNI MODE ROUTES
# =============================================================================


@router.post("/new_chat")
async def create_omni_chat(
    request: Request,
    user_id: str = "local_user",
    chat_dir: str = None,
):
    """Create a new general chat session.

    Args:
        request: The FastAPI request object.
        user_id: User identifier. Defaults to "local_user".
        chat_dir: Directory path for storing chat data. Defaults to ROOT_DIR/daxagent.

    Returns:
        dict: Created chat document containing chat_id, user_id, and timestamps.

    Raises:
        HTTPException: If chat creation fails with appropriate status code.
    """
    try:
        chat_dir = chat_dir or os.path.join(settings.ROOT_DIR, "daxagent")
        return await ChatService.create_omni_chat(user_id, chat_dir)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Chat creation failed due to server error: {e}",
        )


@router.post("/capability/new-chat")
async def create_capability_chat(
    request: Request,
    capability_name: str = Query(..., description="Capability name"),
    user_id: str = "local_user",
    chat_dir: str = None,
):
    """Create a new capability-specific chat session.

    Args:
        request: The FastAPI request object.
        capability_name: Name of the capability (e.g., browser, email, file_finder).
        user_id: User identifier. Defaults to "local_user".
        chat_dir: Directory path for storing chat data. Defaults to ROOT_DIR/daxagent.

    Returns:
        dict: Created capability chat document with chat_id, capability_id, and metadata.

    Raises:
        HTTPException: If capability is invalid or chat creation fails.
    """
    try:
        chat_dir = chat_dir or os.path.join(settings.ROOT_DIR, "daxagent")
        return await ChatService.create_capability_chat(
            capability_name, user_id, chat_dir
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Chat creation failed due to server error: {e}",
        )


GENERIC_FOLDERS = ("daxagent", "daxagent-chats")  # the folders every plain chat shares: no one chose them as a name


def _names(c: dict) -> dict:
    """What the sidebar calls a conversation: a name a person gave it, else its task folder's name, else a generated title (which
    also replaces a shared folder's name). auto_name: the name is generated, so it may change as the work does."""
    folder = os.path.basename(str(c["chat_dir"] or "").rstrip("/")) if c["collection"] == "omni" else ""
    titled = bool(c["title"]) and (c["title_by"] == "user" or folder in ("", *GENERIC_FOLDERS))
    return {"name": c["title"] if titled else folder or c["title"] or "", "auto_name": titled and c["title_by"] != "user"}


class ChatTitle(BaseModel):
    title: str = Field(min_length=1, max_length=80)


@router.put("/{chat_id}/title")
async def rename_chat(chat_id: str, body: ChatTitle) -> dict:
    """A person names the chat: it keeps that name, whatever the work does after."""
    from src.database import set_chat_title

    if not body.title.strip() or not await set_chat_title(chat_id, body.title.strip(), "user"):
        raise HTTPException(status_code=404, detail="No such chat")
    return {"chat_id": chat_id, "title": body.title.strip()}


@router.get("/conversations")
async def conversations(user_id: str = "local_user") -> dict:
    """Every stored task and chat, newest first: what the sidebar can restore when the browser lost its list."""
    from src.database import list_conversations

    return {"conversations": [
        {"chat_id": c["chat_id"], "type": "task" if c["collection"] == "omni" else "chat",
         **_names(c),
         "folder": c["chat_dir"] or "", "created_at": str(c["created_at"]).replace(" ", "T"), "updated_at": str(c["updated_at"]).replace(" ", "T"),
         "run_by": c["run_by"]}
        for c in await list_conversations(user_id)
    ]}


@router.post("/conversations/{chat_id}/hide")
async def hide_conversation(chat_id: str) -> dict:
    """Deleted from the sidebar: the history stays, but the sidebar never lists it again."""
    from src.database import hide_chat

    await hide_chat(chat_id)
    return {"hidden": chat_id}


@router.get("/chat-history/{_user}/{chat_id}", response_model=SimplifiedChatHistory)
async def get_omni_chat_history(
    user_id: str = "local_user",  # the path segment is ignored: signed in, the gate supplies user_id (src/auth.py)
    chat_id: str = Path(..., description="Chat ID"),
    capability: str = Query("omni", description="Chat collection/capability type"),
):
    """Get a specific chat by user_id and chat_id.

    Args:
        user_id: User identifier.
        chat_id: Chat session identifier.
        capability: Collection name (omni, chats, etc.).

    Returns:
        SimplifiedChatHistory: Chat history containing chat_id, chat_dir, and raw_messages.

    Raises:
        HTTPException: 404 if chat not found, 500 if retrieval fails.
    """
    try:
        return await ChatService.get_omni_chat_history(user_id, chat_id, capability)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch chat: {str(e)}",
        )


@router.post("/chat-history/task_id")
async def get_chat_history_by_task(filter_criteria: ChatHistoryByTaskId, user_id: str = "local_user"):
    """Get chat messages filtered by task ID.

    Args:
        filter_criteria: Filter parameters including task_id, user_id, chat_id, and capability.

    Returns:
        dict: Filtered chat history for the specified task.

    Raises:
        HTTPException: 404 if chat not found, 500 if retrieval fails.
    """
    try:
        return await ChatService.get_chat_history_by_task(
            task_id=filter_criteria.task_id,
            user_id=user_id,  # the body's user_id is ignored: signed in, the gate supplies it (src/auth.py)
            chat_id=filter_criteria.chat_id,
            capability=filter_criteria.capability,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch chat: {str(e)}",
        )


@router.get(
    "/chat-history/capability/{_user}/{chat_id}", response_model=EnhancedChatHistory
)
async def get_capability_chat_history(
    user_id: str = "local_user",  # the path segment is ignored: signed in, the gate supplies user_id (src/auth.py)
    chat_id: str = Path(..., description="Chat ID"),
    call_id: str = Query(..., description="Call ID"),
    capability_name: str = Query(..., description="Capability name"),
):
    """Get capability-specific chat messages.

    Args:
        user_id: User identifier.
        chat_id: Chat session identifier.
        call_id: Capability call identifier.
        capability_name: Name of the capability (must be valid CapabilityType).

    Returns:
        EnhancedChatHistory: Chat history with call_id, capability_name, chat_id, and raw_messages.

    Raises:
        HTTPException: 400 if capability invalid, 404 if chat not found, 500 if retrieval fails.
    """
    try:
        return await ChatService.get_capability_chat_history(
            user_id, chat_id, call_id, capability_name
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch chat: {str(e)}",
        )


# =============================================================================
# CHAT MODE ROUTES
# =============================================================================


@router.post("/chat_mode/new_chat")
async def create_chat_mode_session(
    request: Request,
    user_id: str = "local_user",
    chat_dir: str = None,
):
    """Create a new chat mode session.

    Args:
        request: The FastAPI request object.
        user_id: User identifier. Defaults to "local_user".
        chat_dir: Directory path for storing chat data. Defaults to ROOT_DIR/daxagent.

    Returns:
        dict: Created chat document containing chat_id, user_id, and timestamps.

    Raises:
        HTTPException: If chat creation fails with appropriate status code.
    """
    try:
        chat_dir = chat_dir or os.path.join(settings.ROOT_DIR, "daxagent")
        return await ChatService.create_chat_mode_session(user_id, chat_dir)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Chat creation failed due to server error: {e}",
        )


@router.get(
    "/chat_mode/chat-history/{_user}/{chat_id}", response_model=SimplifiedChatHistory
)
async def get_chat_mode_history(
    user_id: str = "local_user",  # the path segment is ignored: signed in, the gate supplies user_id (src/auth.py)
    chat_id: str = Path(..., description="Chat ID"),
):
    """Get a specific chat mode history by user_id and chat_id.

    Args:
        user_id: User identifier.
        chat_id: Chat session identifier.

    Returns:
        SimplifiedChatHistory: Chat history containing chat_id, chat_dir, and raw_messages.

    Raises:
        HTTPException: 404 if chat not found, 500 if retrieval fails.
    """
    try:
        return await ChatService.get_chat_mode_history(user_id, chat_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch chat: {str(e)}",
        )
