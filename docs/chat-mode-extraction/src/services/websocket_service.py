"""WebSocket service helpers for Chat Service.

This module provides utility functions for WebSocket operations:
- Loading chat history
- User context building
- Default configurations
"""

import os
from typing import Any

from loguru import logger

from src.configs.routes import RoutesConfig
from src.configs.settings import settings
from src.utilities.api_client import api_client


def get_default_chat_dir() -> str:
    """Get the default chat directory path.

    Returns:
        str: Default chat directory path.
    """
    return os.path.join(settings.ROOT_DIR, "chats")


async def load_chat_history(chat_id: str, user_id: str) -> dict | None:
    """Load chat history from the backend API.

    Args:
        chat_id: Unique identifier for the chat session.
        user_id: User identifier.

    Returns:
        dict | None: Chat history data or None if not found.
    """
    try:
        query = {"user_id": user_id, "chat_id": chat_id}
        
        response = await api_client.post(
            RoutesConfig.API_CHAT_HISTORY,
            params={"capability": settings.CHAT_COLLECTION},
            data=query,
        )
        result = response.standard_response()

        if not result.get("success"):
            logger.warning(f"Chat history not found: {chat_id}")
            return None

        document = result.get("data", {})
        
        # Transform messages for the chat manager
        messages = []
        if "messages" in document:
            messages = document["messages"]

        return {
            "chat_id": document.get("chat_id", chat_id),
            "chat_dir": document.get("chat_dir", get_default_chat_dir()),
            "messages": messages,
            "raw_messages": document.get("raw_messages", []),
        }

    except Exception as e:
        logger.error(f"Error loading chat history for {chat_id}: {e}")
        return None


async def get_user_details() -> dict[str, Any]:
    """Get user details from the backend API.

    Returns:
        dict: User details or empty dict if not available.
    """
    try:
        response = await api_client.get(RoutesConfig.API_USER_DETAILS)
        result = response.standard_response()
        
        if result.get("success"):
            return result.get("data", {})
        return {}
    except Exception as e:
        logger.warning(f"Could not fetch user details: {e}")
        return {}


def extract_user_summary(user_details: dict) -> dict[str, Any]:
    """Extract relevant user information for context.

    Args:
        user_details: Full user details dictionary.

    Returns:
        dict: Summarized user context.
    """
    if not user_details:
        return {}

    return {
        "name": user_details.get("name", ""),
        "email": user_details.get("email", ""),
        "preferences": user_details.get("preferences", {}),
        "timezone": user_details.get("timezone", "UTC"),
    }


def build_user_context(user_summary: dict) -> str:
    """Build a context string from user summary for the AI.

    Args:
        user_summary: Summarized user information.

    Returns:
        str: Formatted context string to append to system message.
    """
    if not user_summary:
        return ""

    context_parts = ["\n\n--- User Context ---"]
    
    if user_summary.get("name"):
        context_parts.append(f"User Name: {user_summary['name']}")
    
    if user_summary.get("email"):
        context_parts.append(f"User Email: {user_summary['email']}")
    
    if user_summary.get("timezone"):
        context_parts.append(f"Timezone: {user_summary['timezone']}")
    
    if user_summary.get("preferences"):
        prefs = user_summary["preferences"]
        if prefs:
            context_parts.append(f"Preferences: {prefs}")

    if len(context_parts) > 1:
        return "\n".join(context_parts)
    
    return ""


def create_error_response(message: str) -> dict:
    """Create a standardized error response.

    Args:
        message: Error message.

    Returns:
        dict: Error response dictionary.
    """
    return {
        "type": "error",
        "error": message,
    }


def create_pong_response() -> dict:
    """Create a pong response for ping messages.

    Returns:
        dict: Pong response dictionary.
    """
    return {"type": "pong"}
