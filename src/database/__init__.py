"""Local SQLite database package for chat persistence and usage tracking.

Provides singleton access to the ChatRepository and adapter functions
that serve as drop-in replacements for the previous cloud API calls.
"""

import json
import os
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
        """INSERT INTO decision_log (chat_id, task_id, persona, card, request, created_at, owner_pid)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (chat_id, task_id, persona, card, json.dumps(request), dt.now_iso(), os.getpid()),
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


async def save_link(link: dict) -> None:
    db = await get_db()
    await db.execute("INSERT INTO tracked_links (token, url, recipient, plan_id, step, subject, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                     (link["token"], link["url"], link["recipient"], link.get("plan_id") or "", link.get("step"), link.get("subject") or "", dt.now_iso()))
    await db.commit()


async def get_link(token: str) -> dict | None:
    cursor = await (await get_db()).execute("SELECT token, url, recipient, plan_id, step, subject FROM tracked_links WHERE token = ?", (token,))
    row = await cursor.fetchone()
    return dict(zip(("token", "url", "recipient", "plan_id", "step", "subject"), row)) if row else None


async def record_click(token: str) -> int:
    """One click on a tracked link; returns its number."""
    db = await get_db()
    cursor = await db.execute("INSERT INTO link_clicks (token, clicked_at) VALUES (?, ?)", (token, dt.now_iso()))
    await db.commit()
    return cursor.lastrowid


async def mark_run(chat_id: str, task: str, files: list | None) -> None:
    """A run began on this chat in this process. A run that resumes keeps the request it began with."""
    db = await get_db()
    await db.execute("INSERT INTO active_runs (chat_id, owner_pid, task, files, started_at) VALUES (?, ?, ?, ?, ?) "
                     "ON CONFLICT (chat_id) DO UPDATE SET owner_pid = excluded.owner_pid",
                     (chat_id, os.getpid(), task, json.dumps(files or []), dt.now_iso()))
    await db.commit()


async def unmark_run(chat_id: str) -> None:
    """The run ended (finished, failed or was stopped by someone): nothing to resume."""
    db = await get_db()
    await db.execute("DELETE FROM active_runs WHERE chat_id = ?", (chat_id,))
    await db.commit()


async def list_marked_runs() -> list[dict]:
    cursor = await (await get_db()).execute("SELECT chat_id, owner_pid, task, files, resumes FROM active_runs ORDER BY started_at")
    return [{"chat_id": r[0], "owner_pid": r[1], "task": r[2], "files": json.loads(r[3]), "resumes": r[4]} for r in await cursor.fetchall()]


async def count_resume(chat_id: str) -> None:
    db = await get_db()
    await db.execute("UPDATE active_runs SET resumes = resumes + 1 WHERE chat_id = ?", (chat_id,))
    await db.commit()


async def chat_of_agenda(user_id: str, agenda_id: str) -> str | None:
    """The chat a goal (agenda) already has, newest if several: a goal has one chat."""
    cursor = await (await get_db()).execute(
        "SELECT substr(key, 8) FROM user_prefs WHERE user_id = ? AND key LIKE 'agenda:%' AND value = ? "
        "AND substr(key, 8) IN (SELECT chat_id FROM chats WHERE collection = 'omni') ORDER BY updated_at DESC LIMIT 1",
        (user_id, json.dumps(agenda_id)))
    row = await cursor.fetchone()
    return row[0] if row else None


_RUN_COLUMNS = ("id", "chat_id", "key", "task", "files", "lead_target", "credit_budget")


async def enqueue_run(run: dict) -> int:
    """Queue a run behind the ones before it; returns its place (1 = next to start)."""
    db = await get_db()
    cursor = await db.execute(
        "INSERT INTO run_queue (chat_id, run_key, task, files, lead_target, credit_budget, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (run["chat_id"], run["key"], run["task"], json.dumps(run["files"]), run["lead_target"], run["credit_budget"], dt.now_iso()))
    await db.commit()
    return (await (await db.execute("SELECT count(*) FROM run_queue WHERE id <= ?", (cursor.lastrowid,))).fetchone())[0]


async def list_queued_runs() -> list[dict]:
    """The queued runs, oldest first."""
    cursor = await (await get_db()).execute("SELECT id, chat_id, run_key, task, files, lead_target, credit_budget FROM run_queue ORDER BY id")
    return [{**dict(zip(_RUN_COLUMNS, r)), "files": json.loads(r[4])} for r in await cursor.fetchall()]


async def pop_queued_run(run_id: int) -> None:
    db = await get_db()
    await db.execute("DELETE FROM run_queue WHERE id = ?", (run_id,))
    await db.commit()


TASK_COLUMNS = ("id", "run_key", "chat_id", "agenda_id", "title", "state", "step", "waiting_on", "started_at", "last_progress_at", "ended_at", "result")


async def save_task(task: dict) -> None:
    """Create a task, or change the fields given of one that exists (by id)."""
    db = await get_db()
    fields = {k: json.dumps(v) if k in ("waiting_on", "result") and not isinstance(v, str) else v for k, v in task.items() if k in TASK_COLUMNS}
    changes = {k: v for k, v in fields.items() if k != "id"}
    cursor = await db.execute(f"UPDATE tasks SET {', '.join(f'{k} = ?' for k in changes)} WHERE id = ?", (*changes.values(), fields["id"]))
    if cursor.rowcount == 0:  # not an upsert: SQLite checks NOT NULL before ON CONFLICT, so a partial change would be refused
        await db.execute(f"INSERT INTO tasks ({', '.join(fields)}) VALUES ({', '.join('?' * len(fields))})", tuple(fields.values()))
    await db.commit()


def _task(row) -> dict:
    task = dict(zip(TASK_COLUMNS, row))
    for k in ("waiting_on", "result"):
        task[k] = json.loads(task[k]) if task[k] else None
    return task


async def find_task(ref: str) -> dict | None:
    """The task with this id, else the newest one with this run key or chat_id."""
    cursor = await (await get_db()).execute(
        f"SELECT {', '.join(TASK_COLUMNS)} FROM tasks WHERE id = ? OR run_key = ? OR chat_id = ? "
        "ORDER BY (id = ?) DESC, started_at DESC LIMIT 1", (ref, ref, ref, ref))
    row = await cursor.fetchone()
    return _task(row) if row else None


async def list_task_rows(active: bool = False, agenda_id: str = "", limit: int = 50) -> list[dict]:
    """Tasks newest first; active: only those not ended (queued, running, waiting)."""
    where, args = [], []
    if active:
        where.append("state IN ('queued', 'running', 'waiting')")
    if agenda_id:
        where.append("agenda_id = ?"); args.append(agenda_id)
    cursor = await (await get_db()).execute(
        f"SELECT {', '.join(TASK_COLUMNS)} FROM tasks {'WHERE ' + ' AND '.join(where) if where else ''} ORDER BY started_at DESC LIMIT ?",
        (*args, limit))
    return [_task(r) for r in await cursor.fetchall()]


async def queued_run(key: str) -> dict | None:
    """A queued run by its key, with its place in the queue (1 = next)."""
    for place, run in enumerate(await list_queued_runs(), 1):
        if run["key"] == key:
            return {**run, "position": place}
    return None


async def chat_agenda(chat_id: str) -> str:
    """The goal (agenda) a chat belongs to, or ""."""
    cursor = await (await get_db()).execute("SELECT value FROM user_prefs WHERE key = ? LIMIT 1", (f"agenda:{chat_id}",))
    row = await cursor.fetchone()
    return (json.loads(row[0]) if row else "") or ""


async def budget_scope(chat_id: str) -> str:
    """What a chat's spend budget is kept under: its agenda, else the chat itself."""
    return await chat_agenda(chat_id) or chat_id


async def set_budget(chat_id: str, credits: float) -> None:
    """Set what the chat's goal may spend without asking (the caller's figure for what is left)."""
    db = await get_db()
    await db.execute("INSERT INTO budgets (scope, credits_left, updated_at) VALUES (?, ?, ?) "
                     "ON CONFLICT (scope) DO UPDATE SET credits_left = excluded.credits_left, updated_at = excluded.updated_at",
                     (await budget_scope(chat_id), credits, dt.now_iso()))
    await db.commit()


async def budget_left(chat_id: str) -> float | None:
    """Credits the chat's goal may still spend without asking; None when it has no budget."""
    cursor = await (await get_db()).execute("SELECT credits_left FROM budgets WHERE scope = ?", (await budget_scope(chat_id),))
    row = await cursor.fetchone()
    return row[0] if row else None


async def spend_budget(chat_id: str, credits: float) -> float | None:
    """Take credits from the goal's budget if that much is left; returns what is left after, None when nothing was taken."""
    db = await get_db()
    taken = await db.execute("UPDATE budgets SET credits_left = credits_left - ?, updated_at = ? WHERE scope = ? AND credits_left >= ?",
                             (credits, dt.now_iso(), await budget_scope(chat_id), credits))  # one statement: two spends cannot both fit
    await db.commit()
    return await budget_left(chat_id) if taken.rowcount else None


async def run_started(chat_id: str) -> str:
    """When the chat's run in progress began ("" when none is marked)."""
    cursor = await (await get_db()).execute("SELECT started_at FROM active_runs WHERE chat_id = ?", (chat_id,))
    row = await cursor.fetchone()
    return row[0] if row else ""


async def note_source_emails(chat_id: str, server: str, emails: set[str]) -> None:
    db = await get_db()
    await db.executemany("INSERT OR IGNORE INTO source_emails (chat_id, email, server, seen_at) VALUES (?, ?, ?, ?)",
                         [(chat_id, e.lower(), server, dt.now_iso()) for e in emails])
    await db.commit()


async def source_emails(chat_id: str) -> set[str]:
    """The addresses a data source's own answers held in this chat."""
    cursor = await (await get_db()).execute("SELECT email FROM source_emails WHERE chat_id = ?", (chat_id,))
    return {r[0] for r in await cursor.fetchall()}


async def was_pushed(notice_id: str) -> bool:
    cursor = await (await get_db()).execute("SELECT 1 FROM pushed_notices WHERE id = ?", (notice_id,))
    return await cursor.fetchone() is not None


async def mark_pushed(notice_id: str) -> None:
    db = await get_db()
    await db.execute("INSERT OR IGNORE INTO pushed_notices (id, pushed_at) VALUES (?, ?)", (notice_id, dt.now_iso()))
    await db.commit()


async def suppress_email(user_id: str, email: str, reason: str) -> None:
    """No campaign of this user writes to this address again."""
    db = await get_db()
    await db.execute("INSERT OR IGNORE INTO suppressions (user_id, email, reason, created_at) VALUES (?, ?, ?, ?)",
                     (user_id, email.strip().lower(), reason, dt.now_iso()))
    await db.commit()


async def list_suppressed(user_id: str) -> set[str]:
    cursor = await (await get_db()).execute("SELECT email FROM suppressions WHERE user_id = ?", (user_id,))
    return {r[0] for r in await cursor.fetchall()}


async def list_open_decisions() -> list[dict]:
    """The cards shown and not answered yet, oldest first, with the process that shows each (None: made before that was recorded)."""
    cursor = await (await get_db()).execute(
        "SELECT id, chat_id, persona, request, created_at, owner_pid FROM decision_log WHERE answered_at IS NULL ORDER BY id")
    return [{"id": r[0], "chat_id": r[1], "persona": r[2], "request": json.loads(r[3]), "created_at": r[4], "owner_pid": r[5]}
            for r in await cursor.fetchall()]


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


async def chat_owner(chat_id: str) -> str | None:
    """Whose chat this is, or None for a chat the database does not know."""
    db = await get_db()
    cursor = await db.execute("SELECT user_id FROM chats WHERE chat_id = ? LIMIT 1", (chat_id,))
    row = await cursor.fetchone()
    return row[0] if row else None


async def find_artifacts(user_id: str, search: str = "", kind: str = "", limit: int = 30) -> list[dict]:
    """A user's artifacts across all their chats, newest first; every word of search must be in the title, source or id."""
    where, args = "", [user_id]
    for word in search.split():
        where += " AND (title LIKE ? OR source LIKE ? OR id LIKE ?)"
        args += [f"%{word}%"] * 3
    if kind:
        where += " AND kind = ?"
        args.append(kind)
    db = await get_db()
    cursor = await db.execute(
        f"""SELECT id, chat_id, persona, kind, title, path, row_count, source, created_at FROM artifacts
            WHERE chat_id IN (SELECT chat_id FROM chats WHERE user_id = ?){where}
            ORDER BY created_at DESC LIMIT ?""",  # nosec B608 - where holds fixed text only; every value is bound
        (*args, limit),
    )
    keys = ["id", "chat_id", "persona", "kind", "title", "path", "row_count", "source", "created_at"]
    return [dict(zip(keys, r)) for r in await cursor.fetchall()]


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


async def get_chat_title(chat_id: str) -> str | None:
    cursor = await (await get_db()).execute("SELECT title FROM chats WHERE chat_id = ? AND collection IN ('omni', 'chats') AND title IS NOT NULL", (chat_id,))
    row = await cursor.fetchone()
    return row[0] if row else None


async def get_title_state(chat_id: str) -> tuple[str | None, str | None, str | None]:
    """(title, who set it, what it was made from) of a chat; who is "user" for a name a person gave, else a generated one."""
    cursor = await (await get_db()).execute("SELECT title, title_by, title_basis FROM chats WHERE chat_id = ? AND collection IN ('omni', 'chats')", (chat_id,))
    row = await cursor.fetchone()
    return (row[0], row[1], row[2]) if row else (None, None, None)


async def set_chat_title(chat_id: str, title: str, by: str = "auto", basis: str | None = None) -> bool:
    """Name the chat; True when written. A generated name (by "auto") never replaces one a person gave ("user")."""
    db = await get_db()
    cursor = await db.execute(
        "UPDATE chats SET title = ?, title_by = ?, title_basis = ? WHERE chat_id = ? AND collection IN ('omni', 'chats') "
        "AND (? = 'user' OR COALESCE(title_by, '') != 'user')", (title, by, basis, chat_id, by))
    await db.commit()
    return cursor.rowcount > 0


async def list_untitled_chats() -> list[str]:
    """Task chats with something in them and no title, newest first."""
    cursor = await (await get_db()).execute(
        "SELECT chat_id FROM chats WHERE collection = 'omni' AND title IS NULL AND length(raw_messages) > 2 "
        "AND chat_id NOT IN (SELECT chat_id FROM hidden_chats) ORDER BY updated_at DESC")
    return [r[0] for r in await cursor.fetchall()]


async def list_conversations(user_id: str) -> list[dict]:
    """Every task and chat-mode conversation with something in it, newest first (the sidebar's source of truth)."""
    db = await get_db()
    cursor = await db.execute(
        "SELECT chat_id, collection, chat_dir, created_at, updated_at, title, title_by FROM chats "
        "WHERE user_id = ? AND collection IN ('omni', 'chats') AND length(raw_messages) > 2 "
        "AND chat_id NOT IN (SELECT chat_id FROM hidden_chats)",
        (user_id,),
    )
    rows = [dict(zip(("chat_id", "collection", "chat_dir", "created_at", "updated_at", "title", "title_by"), r)) for r in await cursor.fetchall()]
    # tasks an AI started over the MCP (hands_mcp.start_run saves who)
    cursor = await db.execute("SELECT key, value FROM user_prefs WHERE user_id = ? AND key LIKE 'run_by:%'", (user_id,))
    run_by = {key.removeprefix("run_by:"): json.loads(value) for key, value in await cursor.fetchall()}
    for r in rows:
        r["run_by"] = run_by.get(r["chat_id"])
    return sorted(rows, key=lambda r: str(r["updated_at"]).replace(" ", "T"), reverse=True)


async def hide_chat(chat_id: str) -> None:
    """The user deleted it from the sidebar: keep its history, stop listing it."""
    db = await get_db()
    await db.execute("INSERT OR REPLACE INTO hidden_chats (chat_id, hidden_at) VALUES (?, ?)", (chat_id, dt.now_iso()))
    await db.commit()


async def save_user(email: str, password_hash: str, name: str = "") -> None:
    """Add an account, or reset its password and name."""
    db = await get_db()
    await db.execute(
        "INSERT INTO users (email, name, password_hash, created_at) VALUES (?, ?, ?, ?) "
        "ON CONFLICT (email) DO UPDATE SET name = excluded.name, password_hash = excluded.password_hash",
        (email.lower(), name, password_hash, dt.now_iso()),
    )
    await db.commit()


async def get_user(email: str) -> dict | None:
    db = await get_db()
    cursor = await db.execute("SELECT email, name, password_hash FROM users WHERE email = ?", (email.lower(),))
    row = await cursor.fetchone()
    return {"email": row[0], "name": row[1], "password_hash": row[2]} if row else None


async def start_session(email: str, token: str, days: int) -> None:
    from datetime import timedelta

    db = await get_db()
    await db.execute("INSERT INTO sessions (token, email, expires_at) VALUES (?, ?, ?)",
                     (token, email.lower(), (dt.now() + timedelta(days=days)).isoformat()))
    await db.commit()


async def session_user(token: str) -> dict | None:
    """The signed-in account behind a session cookie, while the session lasts."""
    if not token:
        return None
    db = await get_db()
    cursor = await db.execute(
        "SELECT u.email, u.name, s.expires_at FROM sessions s JOIN users u ON u.email = s.email WHERE s.token = ?", (token,)
    )
    row = await cursor.fetchone()
    if not row or row[2] < dt.now().isoformat():
        return None
    return {"email": row[0], "name": row[1]}


async def end_session(token: str) -> None:
    db = await get_db()
    await db.execute("DELETE FROM sessions WHERE token = ?", (token,))
    await db.commit()


async def save_account(user_id: str, email: str, name: str) -> None:
    """Who a signed-in person is (the admin dashboard's label for their user id) and when they last opened the app."""
    db = await get_db()
    now = dt.now_iso()
    await db.execute(
        "INSERT INTO accounts (user_id, email, name, first_seen, last_seen) VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT (user_id) DO UPDATE SET email = excluded.email, name = excluded.name, last_seen = excluded.last_seen",
        (user_id, email, name, now, now),
    )
    await db.commit()


async def admin_rows(chat_id: str | None = None) -> dict[str, list[tuple]]:
    """What the admin dashboard reads, for every conversation or one: its history rows (the task or chat and each
    agent run's own row), feedback, saved artifacts, the people's labels and the chats they deleted from their sidebar."""
    db = await get_db()
    where, args = ("WHERE chat_id = ?", (chat_id,)) if chat_id else ("", ())

    async def rows(sql: str, params: tuple = ()) -> list[tuple]:
        return [tuple(r) for r in await (await db.execute(sql, params)).fetchall()]

    return {
        "chats": await rows(f"SELECT chat_id, user_id, collection, created_at, updated_at, raw_messages FROM chats {where}", args),
        "feedback": await rows(f"SELECT chat_id, task_id, user_id, rating, description, created_at FROM feedback {where} ORDER BY id", args),
        "artifacts": await rows(f"SELECT chat_id, task_id, kind, title, row_count FROM artifacts {where}", args),
        "accounts": await rows("SELECT user_id, email, name, first_seen, last_seen FROM accounts"),
        "hidden": await rows("SELECT chat_id FROM hidden_chats"),
    }


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


# --- LLM as judge (src/judge.py) ---------------------------------------------------------------------------------

EVAL_COLUMNS = ["id", "chat_id", "task_id", "user_id", "request", "turn_at", "judge_version", "model", "ground_truth",
                "relevancy", "completeness", "tool_selection", "final_score", "severity", "root_cause", "failing_step",
                "rationale", "suggested_fix", "facts", "created_at"]
TRUTH_COLUMNS = ["id", "case_id", "version", "request", "expected_agents", "expected_answer", "query_class",
                 "source_chat_id", "source_task_id", "author", "retired", "created_at"]
SUITE_COLUMNS = ["id", "user_id", "config_version", "config", "cases", "passed", "score", "results", "created_at"]


def _row(columns: list[str], row, json_fields: tuple = ()) -> dict:
    out = dict(zip(columns, row))
    for f in json_fields:
        out[f] = json.loads(out[f] or "null")
    return out


async def save_eval(result: dict) -> int:
    """Add one verdict; earlier verdicts on the same turn stay."""
    db = await get_db()
    cols = [c for c in EVAL_COLUMNS if c not in ("id", "created_at")]
    values = [json.dumps(result[c]) if c == "facts" else result[c] for c in cols]
    cursor = await db.execute(
        f"INSERT INTO eval_results ({', '.join(cols)}, created_at) VALUES ({', '.join('?' * len(cols))}, ?)", (*values, dt.now_iso()))
    await db.commit()
    return cursor.lastrowid


async def latest_evals(judge_version: str, chat_id: str | None = None) -> list[dict]:
    """The newest verdict of one judge version on each turn (of one conversation, or every one)."""
    db = await get_db()
    where, args = ("AND chat_id = ?", (chat_id,)) if chat_id else ("", ())
    cursor = await db.execute(
        f"SELECT {', '.join(EVAL_COLUMNS)} FROM eval_results WHERE id IN "
        f"(SELECT MAX(id) FROM eval_results WHERE judge_version = ? {where} GROUP BY chat_id, task_id)", (judge_version, *args))
    return [_row(EVAL_COLUMNS, r, ("facts",)) for r in await cursor.fetchall()]


async def add_truth_version(case: dict) -> dict:
    """A new version of an expected answer (a new case when case_id is new); nothing is overwritten."""
    db = await get_db()
    cursor = await db.execute("SELECT COALESCE(MAX(version), 0) FROM ground_truth WHERE case_id = ?", (case["case_id"],))
    version = (await cursor.fetchone())[0] + 1
    cols = [c for c in TRUTH_COLUMNS if c not in ("id", "version", "created_at")]
    values = [json.dumps(case[c]) if c == "expected_agents" else case[c] for c in cols]
    await db.execute(
        f"INSERT INTO ground_truth ({', '.join(cols)}, version, created_at) VALUES ({', '.join('?' * len(cols))}, ?, ?)",
        (*values, version, dt.now_iso()))
    await db.commit()
    return {**case, "version": version}


async def current_truths(include_retired: bool = False) -> list[dict]:
    """Each expected answer at its newest version, newest case first; retired ones only when asked."""
    db = await get_db()
    cursor = await db.execute(
        f"SELECT {', '.join(TRUTH_COLUMNS)} FROM ground_truth WHERE id IN (SELECT MAX(id) FROM ground_truth GROUP BY case_id) ORDER BY id DESC")
    rows = [_row(TRUTH_COLUMNS, r, ("expected_agents",)) for r in await cursor.fetchall()]
    return [r for r in rows if include_retired or not r["retired"]]


async def save_suite_run(run: dict) -> int:
    db = await get_db()
    cols = [c for c in SUITE_COLUMNS if c not in ("id", "created_at")]
    values = [json.dumps(run[c]) if c in ("config", "results") else run[c] for c in cols]
    cursor = await db.execute(
        f"INSERT INTO suite_runs ({', '.join(cols)}, created_at) VALUES ({', '.join('?' * len(cols))}, ?)", (*values, dt.now_iso()))
    await db.commit()
    return cursor.lastrowid


async def suite_runs(user_id: str, limit: int = 20) -> list[dict]:
    """One person's gate runs, newest first."""
    db = await get_db()
    cursor = await db.execute(
        f"SELECT {', '.join(SUITE_COLUMNS)} FROM suite_runs WHERE user_id = ? ORDER BY id DESC LIMIT ?", (user_id, limit))
    return [_row(SUITE_COLUMNS, r, ("config", "results")) for r in await cursor.fetchall()]


__all__ = [
    "init_db",
    "close_db",
    "get_db",
    "get_chat_repository",
    "reset_chat_repository",
    "update_chat_history",
    "get_chat_title",
    "get_title_state",
    "set_chat_title",
    "list_untitled_chats",
    "chat_agenda",
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
    "list_open_decisions",
    "run_started",
    "save_task",
    "find_task",
    "list_task_rows",
    "note_source_emails",
    "source_emails",
    "was_pushed",
    "mark_pushed",
    "suppress_email",
    "budget_scope",
    "chat_of_agenda",
    "save_link",
    "get_link",
    "record_click",
    "mark_run",
    "unmark_run",
    "list_marked_runs",
    "count_resume",
    "enqueue_run",
    "list_queued_runs",
    "pop_queued_run",
    "queued_run",
    "set_budget",
    "budget_left",
    "spend_budget",
    "list_suppressed",
    "save_artifact",
    "list_artifacts",
    "get_artifact",
    "chat_owner",
    "find_artifacts",
    "get_geocode",
    "save_geocode",
    "save_eval",
    "latest_evals",
    "add_truth_version",
    "current_truths",
    "save_suite_run",
    "suite_runs",
]


# ---- DAX MCP keys (Settings > Connections > DAX MCP) -------------------------------------------
async def save_hands_key(key_id: str, name: str, key_hash: str, created_by: str) -> None:
    db = await get_db()
    await db.execute("INSERT INTO hands_keys (id, name, key_hash, created_by, created_at) VALUES (?, ?, ?, ?, ?)",
                     (key_id, name, key_hash, created_by, dt.now_iso()))
    await db.commit()


async def list_hands_keys() -> list[dict]:
    db = await get_db()
    cols = ("id", "name", "created_by", "created_at", "last_used_at", "last_client")
    cursor = await db.execute(f"SELECT {', '.join(cols)} FROM hands_keys ORDER BY created_at DESC")
    return [dict(zip(cols, row)) for row in await cursor.fetchall()]


async def delete_hands_key(key_id: str) -> bool:
    db = await get_db()
    cursor = await db.execute("DELETE FROM hands_keys WHERE id = ?", (key_id,))
    await db.commit()
    return cursor.rowcount > 0


async def touch_hands_key(key_hash: str) -> dict | None:
    """The key with this hash ({id, name}), or None; records the use."""
    db = await get_db()
    row = await (await db.execute("SELECT id, name FROM hands_keys WHERE key_hash = ?", (key_hash,))).fetchone()
    if not row:
        return None
    await db.execute("UPDATE hands_keys SET last_used_at = ? WHERE id = ?", (dt.now_iso(), row[0]))
    await db.commit()
    return {"id": row[0], "name": row[1]}


async def note_hands_client(key_id: str, client: str) -> None:
    """Which outside agent (its own name and version) last used a key."""
    db = await get_db()
    await db.execute("UPDATE hands_keys SET last_client = ? WHERE id = ?", (client, key_id))
    await db.commit()
