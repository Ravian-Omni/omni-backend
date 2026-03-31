"""Chat management REST API endpoints.

This module provides endpoints for:
- Creating new chat sessions
- Retrieving chat history
"""

import os

from fastapi import APIRouter, HTTPException, Path, status

from src.configs.settings import settings
from src.schemas.chat import SimplifiedChatHistory
from src.services.chat_service import ChatService

router = APIRouter()


@router.post("/new")
async def create_chat_session(
    user_id: str = "default_user",
    chat_dir: str = None,
):
    """Create a new chat session.

    Args:
        user_id: User identifier. Defaults to "default_user".
        chat_dir: Directory path for storing chat data. Defaults to ROOT_DIR/ravian.

    Returns:
        dict: Created chat document containing chat_id, user_id, and timestamps.

    Raises:
        HTTPException: If chat creation fails with appropriate status code.
    """
    try:
        chat_dir = chat_dir or os.path.join(settings.ROOT_DIR, "ravian")
        return await ChatService.create_chat_session(user_id, chat_dir)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Chat creation failed: {e}",
        )


@router.get("/history/{user_id}/{chat_id}", response_model=SimplifiedChatHistory)
async def get_chat_history(
    user_id: str = Path(..., description="User ID"),
    chat_id: str = Path(..., description="Chat ID"),
):
    """Get chat history for a specific user and chat.

    Args:
        user_id: User identifier.
        chat_id: Chat session identifier.

    Returns:
        SimplifiedChatHistory: Chat history containing chat_id, chat_dir, and raw_messages.

    Raises:
        HTTPException: 404 if chat not found, 500 if retrieval fails.
    """
    try:
        return await ChatService.get_chat_history(user_id, chat_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch chat: {str(e)}",
        )


@router.delete("/{chat_id}")
async def delete_chat_session(
    chat_id: str = Path(..., description="Chat ID"),
    user_id: str = "default_user",
):
    """Delete a chat session.

    Args:
        chat_id: Chat session identifier.
        user_id: User identifier.

    Returns:
        dict: Success message.

    Raises:
        HTTPException: 404 if chat not found, 500 if deletion fails.
    """
    try:
        return await ChatService.delete_chat_session(user_id, chat_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete chat: {str(e)}",
        )
