"""WebSocket business logic service.

This module provides helper functions and utilities for WebSocket endpoints including:
- User context extraction and formatting
- Chat history loading
- Capability class mapping
- WebSocket message handling utilities
"""

import os
from typing import Any

from loguru import logger

from src.capabilities.browser_manager.manager import BrowserManager
from src.agent_runtime import persona_capability_class
from src.capabilities.software_developer.manager import SoftwareDeveloper
from src.configs.datetime_utils import dt
from src.configs.settings import settings
from src.database import get_chat_repository
from src.omni.manager import Omni
from src.omni.memory import OmniMemory
from src.utilities.custom_manager import ChatContext

# Mapping of capability names to their class implementations
CAPABILITY_CLASS_MAP = {
    "omni": Omni,
    "web_browser": BrowserManager,
    "software_developer": SoftwareDeveloper,
    **{
        name: persona_capability_class(name)
        for name in ("ml_engineer", "python_developer", "web_surfer", "lead_finder", "buyer_finder", "contact_enricher", "campaign_strategizer", "campaign_builder", "outreach", "inbox_agent", "signal_play", "meeting_prep", "recovery_note")
    },
}


def extract_user_summary(data: dict) -> dict:
    """Extract and format user information summary.

    Args:
        data: Raw API response containing user information.

    Returns:
        dict: Cleaned dictionary with selected user fields including name, email, dob, etc.
    """
    first_name = data.get("first_name", "").strip()
    last_name = data.get("last_name", "").strip()
    full_name = f"{first_name} {last_name}".strip() if last_name else first_name

    return {
        "name": first_name,
        "email": data.get("email", ""),
        "full_name": full_name,
        "dob": data.get("dob", ""),
        "gender": data.get("gender", ""),
        "country": data.get("country", ""),
        "date": dt.today_date_iso(),
    }


def build_user_context(ctx: dict) -> str:
    """Build user context string from extracted user information.

    Args:
        ctx: Dictionary containing user information fields.

    Returns:
        str: Formatted user context string for system message injection.
    """
    fields = [
        ("User", "full_name"),
        ("Birth Date", "dob"),
        ("Email", "email"),
        ("Gender", "gender"),
        ("Location", "country"),
        ("Date", "date"),
    ]

    lines = [f"- {label}: {ctx[key]}" for label, key in fields if ctx.get(key)]

    if not lines:
        return ""

    return (
        "<user_identity>User Information:\n"
        + "\n".join(lines)
        + "\n\nPlease take this context into account when responding.</user_identity> }}"
    )


def get_default_chat_dir() -> str:
    """Get the default chat directory path.

    Returns:
        str: Default chat directory path.
    """
    return os.path.join(settings.ROOT_DIR, "daxagent")


async def load_omni_chat_history(chat_id: str, user_id: str) -> dict | None:
    """Load omni chat history from local database.

    Args:
        chat_id: Chat session identifier.
        user_id: User identifier.

    Returns:
        dict | None: Chat history data or None if not found.
    """
    repo = await get_chat_repository()
    return await repo.get_chat(user_id, chat_id, "omni")


async def load_chat_mode_history(chat_id: str, user_id: str) -> dict | None:
    """Load chat mode history from local database.

    Args:
        chat_id: Chat session identifier.
        user_id: User identifier.

    Returns:
        dict | None: Chat history data or None if not found.
    """
    repo = await get_chat_repository()
    return await repo.get_chat(user_id, chat_id, "chats")


async def load_capability_chat_history(
    chat_id: str, user_id: str, collection_name: str
) -> dict | None:
    """Load capability-specific chat history from local database.

    Args:
        chat_id: Chat session identifier.
        user_id: User identifier.
        collection_name: Name of the capability collection.

    Returns:
        dict | None: Chat history data or None if not found.
    """
    repo = await get_chat_repository()
    return await repo.get_chat(
        user_id, chat_id, collection_name,
        call_id="Individual", capability_id=chat_id,
    )


async def get_user_details() -> dict | None:
    """Get user details from local settings.

    Returns:
        dict | None: User profile data from local settings.
    """
    return {
        "first_name": settings.USER_FIRST_NAME or "",
        "last_name": settings.USER_LAST_NAME or "",
        "email": settings.USER_EMAIL or "",
        "dob": settings.USER_DOB or "",
        "gender": settings.USER_GENDER or "",
        "country": settings.USER_COUNTRY or "",
    }


def get_capability_class(capability_name: str) -> type | None:
    """Get the capability class for a given capability name.

    Args:
        capability_name: Name of the capability.

    Returns:
        type | None: Capability class or None if not found.
    """
    if capability_name in CAPABILITY_CLASS_MAP:
        return CAPABILITY_CLASS_MAP[capability_name]
    if capability_name.startswith("mcp_"):
        try:
            return persona_capability_class(capability_name)
        except ValueError:
            return None
    return None


def create_capability_context(
    user_id: str,
    chat_id: str,
    chat_dir: str,
    capability_name: str,
    collection_name: str,
) -> ChatContext:
    """Create a ChatContext for capability-specific sessions.

    Args:
        user_id: User identifier.
        chat_id: Chat session identifier.
        chat_dir: Directory path for chat storage.
        capability_name: Name of the capability.
        collection_name: Name of the capability collection.

    Returns:
        ChatContext: Configured chat context instance.
    """
    return ChatContext(
        user_id=user_id,
        chat_id=chat_id,
        chat_dir=chat_dir,
        call_id="Individual",
        capability_id=chat_id,
        capability_name=capability_name,
        collection_name=collection_name,
        omni_memory=OmniMemory(),
    )


def create_error_response(error_message: str) -> dict[str, Any]:
    """Create a standardized error response for WebSocket.

    Args:
        error_message: Error message to include.

    Returns:
        dict: Error response with type, error message, and timestamp.
    """
    return {
        "type": "error",
        "error": error_message,
        "timestamp": dt.now_iso(),
    }


def create_pong_response() -> dict[str, Any]:
    """Create a pong response for WebSocket ping.

    Returns:
        dict: Pong response with type and timestamp.
    """
    return {"type": "pong", "timestamp": dt.now_iso()}
