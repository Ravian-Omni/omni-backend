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
from src.capabilities.email_manager.manager import EmailManager
from src.capabilities.file_finder.manager import FileFinder
from src.capabilities.image_generator.manager import ImageGenerator
from src.capabilities.python_developer.manager import PythonDeveloper
from src.configs.datetime_utils import dt
from src.configs.routes import RoutesConfig
from src.configs.settings import settings
from src.omni.manager import Omni
from src.omni.memory import OmniMemory
from src.utilities.api_client import api_client
from src.utilities.custom_manager import ChatContext

# Mapping of capability names to their class implementations
CAPABILITY_CLASS_MAP = {
    "omni": Omni,
    "email_sender": EmailManager,
    "web_browser": BrowserManager,
    "python_coder": PythonDeveloper,
    "file_finder": FileFinder,
    "image_generator": ImageGenerator,
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
    return os.path.join(settings.ROOT_DIR, "ravian")


async def load_omni_chat_history(chat_id: str, user_id: str) -> dict | None:
    """Load omni chat history from API.

    Args:
        chat_id: Chat session identifier.
        user_id: User identifier.

    Returns:
        dict | None: Chat history data or None if not found.
    """
    response = await api_client.post(
        RoutesConfig.API_OMNI_CHAT_HISTORY,
        params={"capability": "omni"},
        data={"chat_id": chat_id, "user_id": user_id},
    )
    result = response.standard_response()

    if not result.get("success"):
        logger.error(result)
        return None

    return result.get("data")


async def load_chat_mode_history(chat_id: str, user_id: str) -> dict | None:
    """Load chat mode history from API.

    Args:
        chat_id: Chat session identifier.
        user_id: User identifier.

    Returns:
        dict | None: Chat history data or None if not found.
    """
    response = await api_client.post(
        RoutesConfig.API_CHAT_HISTORY,
        params={"capability": "chats"},
        data={"chat_id": chat_id, "user_id": user_id},
    )
    result = response.standard_response()

    if not result.get("success"):
        logger.error(result)
        return None

    return result.get("data")


async def load_capability_chat_history(
    chat_id: str, user_id: str, collection_name: str
) -> dict | None:
    """Load capability-specific chat history from API.

    Args:
        chat_id: Chat session identifier.
        user_id: User identifier.
        collection_name: Name of the capability collection.

    Returns:
        dict | None: Chat history data or None if not found.
    """
    query = {
        "user_id": user_id,
        "chat_id": chat_id,
        "call_id": "Individual",
        "capability_id": chat_id,
    }

    response = await api_client.post(
        RoutesConfig.API_OMNI_CHAT_HISTORY,
        params={"capability": collection_name},
        data=query,
    )
    result = response.standard_response()

    if not result.get("success"):
        logger.error(result)
        return None

    return result.get("data")


async def get_user_details() -> dict | None:
    """Fetch user details from API.

    Returns:
        dict | None: User details data or None if request fails.

    Raises:
        Exception: If API request fails.
    """
    response = await api_client.get(RoutesConfig.API_USER_DETAILS)
    result = response.standard_response()

    if not result.get("success"):
        raise Exception(
            f"Failed to fetch user details: {result.get('message', 'Unknown error')}"
        )

    return result.get("data")


def get_capability_class(capability_name: str) -> type | None:
    """Get the capability class for a given capability name.

    Args:
        capability_name: Name of the capability.

    Returns:
        type | None: Capability class or None if not found.
    """
    return CAPABILITY_CLASS_MAP.get(capability_name)


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
