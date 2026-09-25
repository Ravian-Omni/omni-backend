"""Chat management REST API endpoints.

This module provides endpoints for:
- Creating new chat sessions (general and capability-specific)
- Retrieving chat history
- Filtering chat messages by task ID
- Managing capability-specific conversations
"""

import os

from fastapi import APIRouter, HTTPException, Path, Query, Request, status

from src.configs.settings import settings
from src.schemas.chat import (
    ChatHistoryByTaskId,
    EnhancedChatHistory,
    SimplifiedChatHistory,
)
from src.services.chat_service import ChatService

router = APIRouter()


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


@router.get("/chat-history/{user_id}/{chat_id}", response_model=SimplifiedChatHistory)
async def get_omni_chat_history(
    user_id: str = Path(..., description="User ID"),
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
async def get_chat_history_by_task(filter_criteria: ChatHistoryByTaskId):
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
            user_id=filter_criteria.user_id,
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
    "/chat-history/capability/{user_id}/{chat_id}", response_model=EnhancedChatHistory
)
async def get_capability_chat_history(
    user_id: str = Path(..., description="User ID"),
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
    "/chat_mode/chat-history/{user_id}/{chat_id}", response_model=SimplifiedChatHistory
)
async def get_chat_mode_history(
    user_id: str = Path(..., description="User ID"),
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
