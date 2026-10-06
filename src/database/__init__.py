"""Local SQLite database package for chat persistence and usage tracking.

Provides singleton access to the ChatRepository and adapter functions
that serve as drop-in replacements for the previous cloud API calls.
"""

import json
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


async def create_share_link(
    token: str, chat_id: str, user_id: str, collection: str
) -> None:
    """Store a public share token for a chat.

    Args:
        token: Opaque token used in the public URL.
        chat_id: Chat being shared.
        user_id: Owner of the chat.
        collection: Collection the chat lives in.
    """
    db = await get_db()
    await db.execute(
        """INSERT INTO shared_chats (token, chat_id, user_id, collection, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        (token, chat_id, user_id, collection, dt.now_iso()),
    )
    await db.commit()
    logger.info(f"Share link created for chat {chat_id}")


async def get_share_link(token: str) -> dict | None:
    """Look up a share token.

    Args:
        token: Token from the public URL.

    Returns:
        The share row, or None when unknown or revoked.
    """
    db = await get_db()
    cursor = await db.execute(
        """SELECT chat_id, user_id, collection, created_at FROM shared_chats
           WHERE token = ? AND revoked = 0""",
        (token,),
    )
    row = await cursor.fetchone()
    if not row:
        return None
    return {
        "chat_id": row[0],
        "user_id": row[1],
        "collection": row[2],
        "created_at": row[3],
    }


async def revoke_share_link(token: str) -> bool:
    """Revoke a share token so the public link stops working.

    Args:
        token: Token to revoke.

    Returns:
        True when a live link was revoked.
    """
    db = await get_db()
    cursor = await db.execute(
        "UPDATE shared_chats SET revoked = 1 WHERE token = ? AND revoked = 0", (token,)
    )
    await db.commit()
    return cursor.rowcount > 0


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


# =========================================================================
# MCP SERVERS, DECISIONS AND ARTIFACTS
# =========================================================================


async def save_mcp_server(name: str, config: dict) -> None:
    """Insert or replace a runtime-added MCP server definition.

    Args:
        name: Server name, used as the key everywhere else.
        config: One entry in the ``mcpServers`` shape of configs/mcp_servers.json.
    """
    db = await get_db()
    now = dt.now_iso()
    await db.execute(
        """INSERT INTO mcp_servers (name, config, created_at, updated_at)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(name) DO UPDATE SET config = ?, updated_at = ?""",
        (name, json.dumps(config), now, now, json.dumps(config), now),
    )
    await db.commit()


async def delete_mcp_server(name: str) -> bool:
    """Remove a runtime-added MCP server and its tool settings."""
    db = await get_db()
    cursor = await db.execute("DELETE FROM mcp_servers WHERE name = ?", (name,))
    await db.execute("DELETE FROM mcp_tool_settings WHERE server = ?", (name,))
    await db.commit()
    return cursor.rowcount > 0


async def load_mcp_servers() -> dict[str, dict]:
    """All runtime-added MCP servers, keyed by name."""
    db = await get_db()
    cursor = await db.execute("SELECT name, config FROM mcp_servers")
    return {row[0]: json.loads(row[1]) for row in await cursor.fetchall()}


async def save_mcp_tool_class(server: str, tool: str, tool_class: str | None) -> None:
    """Override how a tool is classed (read, spend or send); None clears it."""
    db = await get_db()
    if tool_class is None:
        await db.execute(
            "DELETE FROM mcp_tool_settings WHERE server = ? AND tool = ?", (server, tool)
        )
    else:
        await db.execute(
            """INSERT INTO mcp_tool_settings (server, tool, tool_class, updated_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(server, tool) DO UPDATE SET tool_class = ?, updated_at = ?""",
            (server, tool, tool_class, dt.now_iso(), tool_class, dt.now_iso()),
        )
    await db.commit()


async def load_mcp_tool_classes(server: str) -> dict[str, str]:
    """Tool class overrides for one server, keyed by tool name."""
    db = await get_db()
    cursor = await db.execute(
        "SELECT tool, tool_class FROM mcp_tool_settings WHERE server = ?", (server,)
    )
    return {row[0]: row[1] for row in await cursor.fetchall() if row[1]}


async def save_mcp_server_flag(name: str, enabled: bool) -> None:
    """Switch a server on or off for every mode."""
    db = await get_db()
    await db.execute(
        """INSERT INTO mcp_server_flags (name, enabled, updated_at) VALUES (?, ?, ?)
           ON CONFLICT(name) DO UPDATE SET enabled = ?, updated_at = ?""",
        (name, int(enabled), dt.now_iso(), int(enabled), dt.now_iso()),
    )
    await db.commit()


async def load_mcp_server_flags() -> dict[str, bool]:
    """Enabled flags per server name."""
    db = await get_db()
    cursor = await db.execute("SELECT name, enabled FROM mcp_server_flags")
    return {row[0]: bool(row[1]) for row in await cursor.fetchall()}


async def log_decision(
    chat_id: str, task_id: str | None, persona: str, card: str, request: dict
) -> int:
    """Record a confirmation card the moment it is shown; returns its row id."""
    db = await get_db()
    cursor = await db.execute(
        """INSERT INTO decision_log (chat_id, task_id, persona, card, request, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (chat_id, task_id, persona, card, json.dumps(request), dt.now_iso()),
    )
    await db.commit()
    return cursor.lastrowid


async def answer_decision(decision_id: int, response: Any) -> None:
    """Store what the user answered to a card."""
    db = await get_db()
    await db.execute(
        "UPDATE decision_log SET response = ?, answered_at = ? WHERE id = ?",
        (json.dumps(response), dt.now_iso(), decision_id),
    )
    await db.commit()


async def list_decisions(chat_id: str) -> list[dict]:
    """The audit trail of cards for a chat, oldest first."""
    db = await get_db()
    cursor = await db.execute(
        """SELECT id, task_id, persona, card, request, response, created_at, answered_at
           FROM decision_log WHERE chat_id = ? ORDER BY id""",
        (chat_id,),
    )
    return [
        {
            "id": r[0],
            "task_id": r[1],
            "persona": r[2],
            "card": r[3],
            "request": json.loads(r[4]),
            "response": json.loads(r[5]) if r[5] else None,
            "created_at": r[6],
            "answered_at": r[7],
        }
        for r in await cursor.fetchall()
    ]


async def save_artifact(record: dict) -> None:
    """Insert or replace an artifact record (the file itself lives in the chat dir)."""
    db = await get_db()
    await db.execute(
        """INSERT OR REPLACE INTO artifacts
           (id, chat_id, task_id, persona, kind, title, path, row_count, source, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            record["id"], record["chat_id"], record.get("task_id"), record["persona"],
            record["kind"], record["title"], record["path"], record.get("row_count", 0),
            record.get("source"), record.get("created_at") or dt.now_iso(),
        ),
    )
    await db.commit()


async def get_artifact(artifact_id: str) -> dict | None:
    """One artifact record by id, regardless of chat."""
    db = await get_db()
    cursor = await db.execute(
        """SELECT id, chat_id, task_id, persona, kind, title, path, row_count, source, created_at
           FROM artifacts WHERE id = ?""",
        (artifact_id,),
    )
    row = await cursor.fetchone()
    if not row:
        return None
    keys = ["id", "chat_id", "task_id", "persona", "kind", "title", "path", "row_count", "source", "created_at"]
    return dict(zip(keys, row))


async def list_artifacts(chat_id: str) -> list[dict]:
    """Artifacts of a chat, newest first."""
    db = await get_db()
    cursor = await db.execute(
        """SELECT id, task_id, persona, kind, title, path, row_count, source, created_at
           FROM artifacts WHERE chat_id = ? ORDER BY created_at DESC""",
        (chat_id,),
    )
    keys = ["id", "task_id", "persona", "kind", "title", "path", "row_count", "source", "created_at"]
    return [dict(zip(keys, r)) for r in await cursor.fetchall()]


async def recent_artifacts(user_id: str, limit: int = 20) -> list[dict]:
    """A user's latest artifacts across chats, newest first (send logs left out)."""
    db = await get_db()
    cursor = await db.execute(
        """SELECT kind, title, row_count FROM artifacts
           WHERE kind != 'send_log' AND chat_id IN (SELECT chat_id FROM chats WHERE user_id = ?)
           ORDER BY created_at DESC LIMIT ?""",
        (user_id, limit),
    )
    return [{"kind": r[0], "title": r[1], "rows": r[2]} for r in await cursor.fetchall()]


async def load_pref(user_id: str, key: str, default: Any = None) -> Any:
    """One of the user's stored preferences (JSON), or the default."""
    db = await get_db()
    cursor = await db.execute("SELECT value FROM user_prefs WHERE user_id = ? AND key = ?", (user_id, key))
    row = await cursor.fetchone()
    return json.loads(row[0]) if row else default


async def save_pref(user_id: str, key: str, value: Any) -> None:
    db = await get_db()
    await db.execute(
        "INSERT OR REPLACE INTO user_prefs (user_id, key, value, updated_at) VALUES (?, ?, ?, ?)",
        (user_id, key, json.dumps(value), dt.now_iso()),
    )
    await db.commit()


async def save_feedback(chat_id: str, task_id: str, user_id: str, rating: int, description: str) -> dict:
    """Store the user's rating of a run in a conversation; rating the same run again replaces it."""
    db = await get_db()
    row = {"chat_id": chat_id, "task_id": task_id, "rating": rating, "description": description, "created_at": dt.now_iso()}
    await db.execute(
        "INSERT INTO feedback (chat_id, task_id, user_id, rating, description, created_at) VALUES (?, ?, ?, ?, ?, ?) "
        "ON CONFLICT (chat_id, task_id) DO UPDATE SET rating = excluded.rating, description = excluded.description, "
        "created_at = excluded.created_at",
        (chat_id, task_id, user_id, rating, description, row["created_at"]),
    )
    await db.commit()
    return row


async def load_feedback(chat_id: str) -> list[dict]:
    """Every rating given in a conversation, oldest first."""
    db = await get_db()
    cursor = await db.execute(
        "SELECT task_id, rating, description, created_at FROM feedback WHERE chat_id = ? ORDER BY id", (chat_id,)
    )
    return [
        {"chat_id": chat_id, "task_id": r[0], "rating": r[1], "description": r[2], "created_at": r[3]}
        for r in await cursor.fetchall()
    ]


_HANDOFF_COLUMNS = ("id", "user_id", "chat_id", "plan_id", "contact", "thread_id", "owner", "route", "subject",
                    "reply", "read", "draft", "status", "created_at", "updated_at")


def _handoff(row) -> dict:
    h = dict(zip(_HANDOFF_COLUMNS, row))
    h["read"] = json.loads(h["read"] or "{}")
    return h


_CREATIVE_COLUMNS = ("id", "chat_id", "plan_id", "name", "mime", "path", "size", "url", "summary", "created_at")


async def save_creative(c: dict) -> dict:
    db = await get_db()
    await db.execute(f"INSERT INTO creatives ({', '.join(_CREATIVE_COLUMNS)}) VALUES ({', '.join('?' * len(_CREATIVE_COLUMNS))})",
                     tuple(c.get(k, "") for k in _CREATIVE_COLUMNS))
    await db.commit()
    return c


async def list_creatives(chat_id: str, plan_id: str) -> list[dict]:
    """A campaign plan's creatives, oldest first."""
    db = await get_db()
    cursor = await db.execute(f"SELECT {', '.join(_CREATIVE_COLUMNS)} FROM creatives WHERE chat_id = ? AND plan_id = ? ORDER BY created_at",
                              (chat_id, plan_id))
    return [dict(zip(_CREATIVE_COLUMNS, r)) for r in await cursor.fetchall()]


async def get_creative(creative_id: str) -> dict | None:
    db = await get_db()
    cursor = await db.execute(f"SELECT {', '.join(_CREATIVE_COLUMNS)} FROM creatives WHERE id = ?", (creative_id,))
    row = await cursor.fetchone()
    return dict(zip(_CREATIVE_COLUMNS, row)) if row else None


async def update_creative(creative_id: str, url: str) -> dict | None:
    db = await get_db()
    await db.execute("UPDATE creatives SET url = ? WHERE id = ?", (url, creative_id))
    await db.commit()
    return await get_creative(creative_id)


async def delete_creative(creative_id: str) -> None:
    db = await get_db()
    await db.execute("DELETE FROM creatives WHERE id = ?", (creative_id,))
    await db.commit()


async def list_conversations(user_id: str) -> list[dict]:
    """Every task and chat-mode conversation with something in it, newest first (the sidebar's source of truth)."""
    db = await get_db()
    cursor = await db.execute(
        "SELECT chat_id, collection, chat_dir, created_at, updated_at FROM chats "
        "WHERE user_id = ? AND collection IN ('omni', 'chats') AND length(raw_messages) > 2 "
        "AND chat_id NOT IN (SELECT chat_id FROM hidden_chats)",
        (user_id,),
    )
    rows = [dict(zip(("chat_id", "collection", "chat_dir", "created_at", "updated_at"), r)) for r in await cursor.fetchall()]
    return sorted(rows, key=lambda r: str(r["updated_at"]).replace(" ", "T"), reverse=True)


async def hide_chat(chat_id: str) -> None:
    """The user deleted it from the sidebar: keep its history, stop listing it."""
    db = await get_db()
    await db.execute("INSERT OR REPLACE INTO hidden_chats (chat_id, hidden_at) VALUES (?, ?)", (chat_id, dt.now_iso()))
    await db.commit()


async def list_artifacts_of_kind(kind: str) -> list[dict]:
    """Every chat's artifacts of one kind (the reply watcher reads all send logs), newest first."""
    db = await get_db()
    cursor = await db.execute(
        "SELECT id, chat_id, task_id, kind, title, path, created_at FROM artifacts WHERE kind = ? ORDER BY created_at DESC", (kind,)
    )
    keys = ["id", "chat_id", "task_id", "kind", "title", "path", "created_at"]
    return [dict(zip(keys, r)) for r in await cursor.fetchall()]


async def chat_collection(chat_id: str) -> str | None:
    """Where a chat's own history lives: "omni" for a task, "chats" for chat mode (None if unknown)."""
    db = await get_db()
    cursor = await db.execute(
        "SELECT collection FROM chats WHERE chat_id = ? AND collection IN ('omni', 'chats') ORDER BY collection = 'omni' DESC LIMIT 1",
        (chat_id,),
    )
    row = await cursor.fetchone()
    return row[0] if row else None


async def save_handoff(h: dict) -> dict:
    """Open a handoff, or reopen the thread's existing one with the new reply (it keeps its id)."""
    db = await get_db()
    now = dt.now_iso()
    await db.execute(
        "INSERT INTO handoffs (id, user_id, chat_id, plan_id, contact, thread_id, owner, route, subject, reply, read, draft, "
        "status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?) "
        "ON CONFLICT (chat_id, contact, thread_id) DO UPDATE SET owner = excluded.owner, route = excluded.route, "
        "reply = excluded.reply, read = excluded.read, draft = excluded.draft, status = 'open', updated_at = excluded.updated_at",
        (h["id"], h["user_id"], h["chat_id"], h.get("plan_id", ""), h["contact"], h.get("thread_id", ""), h.get("owner", ""),
         h["route"], h.get("subject", ""), h["reply"], json.dumps(h.get("read") or {}), h.get("draft", ""), now, now),
    )
    await db.commit()
    cursor = await db.execute(
        f"SELECT {', '.join(_HANDOFF_COLUMNS)} FROM handoffs WHERE chat_id = ? AND contact = ? AND thread_id = ?",
        (h["chat_id"], h["contact"], h.get("thread_id", "")),
    )
    return _handoff(await cursor.fetchone())


async def get_handoff(handoff_id: str) -> dict | None:
    db = await get_db()
    cursor = await db.execute(f"SELECT {', '.join(_HANDOFF_COLUMNS)} FROM handoffs WHERE id = ?", (handoff_id,))
    row = await cursor.fetchone()
    return _handoff(row) if row else None


async def list_handoffs(user_id: str, status: str | None = None, chat_id: str | None = None) -> list[dict]:
    """Newest first; status "active" means open or claimed."""
    where, args = ["user_id = ?"], [user_id]
    if status == "active":
        where.append("status IN ('open', 'claimed')")
    elif status:
        where.append("status = ?"); args.append(status)
    if chat_id:
        where.append("chat_id = ?"); args.append(chat_id)
    db = await get_db()
    cursor = await db.execute(
        f"SELECT {', '.join(_HANDOFF_COLUMNS)} FROM handoffs WHERE {' AND '.join(where)} ORDER BY updated_at DESC", args
    )
    return [_handoff(r) for r in await cursor.fetchall()]


async def update_handoff(handoff_id: str, **fields: Any) -> dict | None:
    """Change owner, draft or status; returns the updated handoff (None if it does not exist)."""
    allowed = {k: v for k, v in fields.items() if k in ("owner", "draft", "status") and v is not None}
    if allowed:
        db = await get_db()
        sets = ", ".join(f"{k} = ?" for k in allowed)
        await db.execute(f"UPDATE handoffs SET {sets}, updated_at = ? WHERE id = ?", (*allowed.values(), dt.now_iso(), handoff_id))
        await db.commit()
    return await get_handoff(handoff_id)


async def get_geocode(place: str) -> dict | None:
    """Cached coordinates for a normalised place key; lat/lng are None for a known miss."""
    db = await get_db()
    cursor = await db.execute("SELECT lat, lng FROM geocode_cache WHERE place = ?", (place,))
    row = await cursor.fetchone()
    return {"lat": row[0], "lng": row[1]} if row else None


async def save_geocode(place: str, lat: float | None, lng: float | None) -> None:
    """Remember a geocoding result (or miss) so the network is asked once per place."""
    db = await get_db()
    await db.execute(
        "INSERT OR REPLACE INTO geocode_cache (place, lat, lng, resolved_at) VALUES (?, ?, ?, ?)",
        (place, lat, lng, dt.now_iso()),
    )
    await db.commit()


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
    "save_mcp_server",
    "delete_mcp_server",
    "load_mcp_servers",
    "save_mcp_tool_class",
    "load_mcp_tool_classes",
    "save_mcp_server_flag",
    "load_mcp_server_flags",
    "log_decision",
    "answer_decision",
    "list_decisions",
    "save_artifact",
    "list_artifacts",
    "get_artifact",
    "get_geocode",
    "save_geocode",
]
