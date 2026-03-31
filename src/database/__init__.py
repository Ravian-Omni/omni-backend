"""Local SQLite database package for chat persistence and usage tracking.

Provides singleton access to the ChatRepository and adapter functions
that serve as drop-in replacements for the previous cloud API calls.
"""

from typing import Any

from loguru import logger

from src.configs.datetime_utils import dt

from .connection import close_db, get_db, init_db
from .repository import ChatRepository

_chat_repository: ChatRepository | None = None


async def get_chat_repository() -> ChatRepository:
    """Get or create the global ChatRepository singleton."""
    global _chat_repository
    if _chat_repository is None:
        db = await get_db()
        _chat_repository = ChatRepository(db)
    return _chat_repository


async def reset_chat_repository() -> None:
    """Reset the repository singleton (for testing or reconnection)."""
    global _chat_repository
    _chat_repository = None


async def update_chat_history(
    chat_id: str, message: dict, collection_name: str
) -> bool:
    """Update chat history by appending a message.

    Drop-in replacement for the functions previously in storage.py,
    chat/manager.py, and the simple form in custom_manager.py.

    Args:
        chat_id: Unique identifier for the chat session.
        message: Message dict with role, name, content, raw_message, usage, task_id.
        collection_name: Collection discriminator (e.g. "omni", "chats").

    Returns:
        True if the update succeeded.
    """
    try:
        repo = await get_chat_repository()

        required_fields = ["role", "name", "raw_message", "usage", "task_id"]
        content_fields = ["role", "name", "content"]

        raw_message_data = {
            field: message[field] for field in required_fields if field in message
        }
        content_message_data = {
            field: message[field] for field in content_fields if field in message
        }

        raw_message_data["timestamp"] = dt.now_iso()

        result = await repo.append_message(
            chat_id=chat_id,
            raw_message=raw_message_data,
            content_message=content_message_data if content_message_data.get("content") else None,
            collection=collection_name,
        )

        logger.info(f"Chat history updated for chat_id: {chat_id}")
        return result

    except Exception as e:
        logger.error(f"Failed to update chat history for chat_id {chat_id}: {e}")
        raise


async def update_chat_history_by_context(
    context: Any, message: dict[str, Any]
) -> bool:
    """Update chat history using a ChatContext object.

    Drop-in replacement for the context-based update_chat_history
    in custom_manager.py. Uses extended filter criteria including
    call_id and capability_id.

    Args:
        context: ChatContext dataclass with user_id, chat_id, call_id, etc.
        message: Message dict with role, name, content, raw_message, usage, task_id.

    Returns:
        True if the update succeeded.
    """
    try:
        repo = await get_chat_repository()

        required_fields = ["role", "name", "raw_message", "usage", "task_id"]
        content_fields = ["role", "name", "content"]

        raw_message_data = {
            field: message[field] for field in required_fields if field in message
        }
        content_message_data = {
            field: message[field] for field in content_fields if field in message
        }

        raw_message_data["timestamp"] = dt.now_iso()

        filter_criteria = {
            "call_id": context.call_id,
            "capability_id": context.capability_id,
        }

        result = await repo.append_message(
            chat_id=context.chat_id,
            raw_message=raw_message_data,
            content_message=content_message_data if content_message_data.get("content") else None,
            collection=context.collection_name,
            filter_criteria=filter_criteria,
        )

        logger.info(f"Chat history updated for chat_id: {context.chat_id}")
        return result

    except Exception as e:
        logger.error(
            f"Failed to update chat history for chat_id {context.chat_id}: {e}"
        )
        raise


async def create_capability_chat(context: Any) -> dict:
    """Create a capability-specific chat document.

    Drop-in replacement for create_capability_chat in custom_manager.py.

    Args:
        context: ChatContext dataclass.

    Returns:
        The created chat document dict.
    """
    repo = await get_chat_repository()

    chat_document = {
        "user_id": context.user_id,
        "chat_id": context.chat_id,
        "chat_dir": context.chat_dir,
        "call_id": context.call_id,
        "capability_id": context.capability_id,
        "messages": [],
        "raw_messages": [],
        "created_at": dt.now_iso(),
        "updated_at": dt.now_iso(),
    }

    return await repo.create_chat(chat_document, context.collection_name)


# =========================================================================
# API KEY PERSISTENCE
# =========================================================================


async def save_api_key(provider: str, api_key: str) -> None:
    """Save or update an API key in the database.

    Args:
        provider: Provider name (e.g. "openai", "anthropic").
        api_key: The API key value.
    """
    db = await get_db()
    await db.execute(
        """INSERT INTO api_keys (provider, api_key, updated_at)
           VALUES (?, ?, ?)
           ON CONFLICT(provider) DO UPDATE SET api_key = ?, updated_at = ?""",
        (provider, api_key, dt.now_iso(), api_key, dt.now_iso()),
    )
    await db.commit()
    logger.debug(f"API key saved for provider: {provider}")


async def delete_api_key(provider: str) -> None:
    """Delete an API key from the database.

    Args:
        provider: Provider name to delete.
    """
    db = await get_db()
    await db.execute("DELETE FROM api_keys WHERE provider = ?", (provider,))
    await db.commit()
    logger.debug(f"API key deleted for provider: {provider}")


async def load_all_api_keys() -> dict[str, str]:
    """Load all API keys from the database.

    Returns:
        Dict mapping provider names to API key values.
    """
    db = await get_db()
    cursor = await db.execute("SELECT provider, api_key FROM api_keys")
    rows = await cursor.fetchall()
    keys = {row[0]: row[1] for row in rows}
    logger.info(f"Loaded {len(keys)} API keys from database")
    return keys


# =========================================================================
# USER PROFILE PERSISTENCE
# =========================================================================


async def save_user_profile(profile: dict) -> None:
    """Save or update user profile in the database.

    Args:
        profile: Dict with profile fields (first_name, last_name, etc.).
    """
    db = await get_db()
    await db.execute(
        """INSERT INTO user_profile (id, first_name, last_name, email, dob, gender, country, updated_at)
           VALUES (1, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET
             first_name = ?, last_name = ?, email = ?, dob = ?, gender = ?, country = ?, updated_at = ?""",
        (
            profile.get("first_name", ""), profile.get("last_name", ""),
            profile.get("email", ""), profile.get("dob", ""),
            profile.get("gender", ""), profile.get("country", ""),
            dt.now_iso(),
            profile.get("first_name", ""), profile.get("last_name", ""),
            profile.get("email", ""), profile.get("dob", ""),
            profile.get("gender", ""), profile.get("country", ""),
            dt.now_iso(),
        ),
    )
    await db.commit()


async def load_user_profile() -> dict:
    """Load user profile from the database.

    Returns:
        Dict with profile fields, or empty dict if not set.
    """
    db = await get_db()
    cursor = await db.execute(
        "SELECT first_name, last_name, email, dob, gender, country FROM user_profile WHERE id = 1"
    )
    row = await cursor.fetchone()
    if not row:
        return {}
    return {
        "first_name": row[0] or "",
        "last_name": row[1] or "",
        "email": row[2] or "",
        "dob": row[3] or "",
        "gender": row[4] or "",
        "country": row[5] or "",
    }


__all__ = [
    "init_db",
    "close_db",
    "get_db",
    "get_chat_repository",
    "reset_chat_repository",
    "update_chat_history",
    "update_chat_history_by_context",
    "create_capability_chat",
    "ChatRepository",
    "save_api_key",
    "delete_api_key",
    "load_all_api_keys",
    "save_user_profile",
    "load_user_profile",
]
