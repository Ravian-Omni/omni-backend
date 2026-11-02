"""Chat repository for SQLite-based local persistence.

Provides CRUD operations for chat documents, replacing the previous
cloud MongoDB API calls with local SQLite storage.
"""

import asyncio
import json
from typing import Any

import aiosqlite
from loguru import logger

from src.configs.datetime_utils import dt


class ChatRepository:
    """Repository for chat document CRUD operations against SQLite."""

    def __init__(self, db: aiosqlite.Connection):
        """Initialize with a database connection.

        Args:
            db: Active aiosqlite connection.
        """
        self.db = db
        # append_message reads a row and writes it back; parallel agents append to the same chat row, so one at a time
        self._append = asyncio.Lock()

    async def create_chat(self, document: dict[str, Any], collection: str) -> dict:
        """Insert a new chat document.

        Args:
            document: Chat document containing user_id, chat_id, etc.
            collection: Collection/table discriminator (e.g. "omni", "chats").

        Returns:
            The inserted document dict.
        """
        now = dt.now_iso()
        await self.db.execute(
            """INSERT INTO chats
               (user_id, chat_id, collection, chat_dir, call_id, capability_id,
                messages, raw_messages, feedback, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                document.get("user_id", ""),
                document["chat_id"],
                collection,
                document.get("chat_dir", ""),
                document.get("call_id"),
                document.get("capability_id"),
                json.dumps(document.get("messages", [])),
                json.dumps(document.get("raw_messages", [])),
                json.dumps(document.get("feedback", {})),
                document.get("created_at", now),
                document.get("updated_at", now),
            ),
        )
        await self.db.commit()

        logger.info(
            f"Created chat {document['chat_id']} in collection '{collection}'"
        )
        return document

    async def append_message(
        self,
        chat_id: str,
        raw_message: dict[str, Any],
        content_message: dict[str, Any] | None,
        collection: str,
        filter_criteria: dict[str, Any] | None = None,
    ) -> bool:
        """Append a message to the chat's messages and raw_messages arrays.

        Replaces the MongoDB $push pattern with a read-modify-write in a
        transaction.

        Args:
            chat_id: The chat session ID.
            raw_message: Full message data for raw_messages array.
            content_message: Content-only message for messages array (if any).
            collection: Collection discriminator.
            filter_criteria: Additional filter fields (call_id, capability_id, etc.).

        Returns:
            True if the update succeeded.
        """
        where_clauses = ["chat_id = ?", "collection = ?"]
        params: list[Any] = [chat_id, collection]

        if filter_criteria:
            if "call_id" in filter_criteria:
                where_clauses.append("call_id = ?")
                params.append(filter_criteria["call_id"])
            if "capability_id" in filter_criteria:
                where_clauses.append("capability_id = ?")
                params.append(filter_criteria["capability_id"])

        where_sql = " AND ".join(where_clauses)

        async with self._append:
            cursor = await self.db.execute(
                f"SELECT id, messages, raw_messages FROM chats WHERE {where_sql}",
                params,
            )
            row = await cursor.fetchone()

            if not row:
                logger.error(f"Chat not found: {chat_id} in collection '{collection}'")
                return False

            row_id = row[0]
            messages = json.loads(row[1])
            raw_messages = json.loads(row[2])

            raw_messages.append(raw_message)
            if content_message and content_message.get("content"):
                messages.append(content_message)

            await self.db.execute(
                "UPDATE chats SET messages = ?, raw_messages = ?, updated_at = ? WHERE id = ?",
                (json.dumps(messages), json.dumps(raw_messages), dt.now_iso(), row_id),
            )
            await self.db.commit()

        logger.debug(f"Appended message to chat {chat_id}")
        return True

    async def get_chat(
        self,
        user_id: str,
        chat_id: str,
        collection: str,
        call_id: str | None = None,
        capability_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Fetch a single chat document.

        Args:
            user_id: The user ID.
            chat_id: The chat session ID.
            collection: Collection discriminator.
            call_id: Optional call_id filter (for capability chats).
            capability_id: Optional capability_id filter.

        Returns:
            Chat document dict, or None if not found.
        """
        where_clauses = ["user_id = ?", "chat_id = ?", "collection = ?"]
        params: list[Any] = [user_id, chat_id, collection]

        if call_id is not None:
            where_clauses.append("call_id = ?")
            params.append(call_id)
        if capability_id is not None:
            where_clauses.append("capability_id = ?")
            params.append(capability_id)

        where_sql = " AND ".join(where_clauses)

        cursor = await self.db.execute(
            f"SELECT * FROM chats WHERE {where_sql}", params
        )
        row = await cursor.fetchone()

        if not row:
            return None

        return self._row_to_dict(row)

    async def get_chat_by_task(
        self,
        task_id: str,
        user_id: str,
        chat_id: str,
        collection: str,
    ) -> dict[str, Any] | None:
        """Fetch a chat and filter raw_messages by task_id.

        Args:
            task_id: The task ID to filter messages by.
            user_id: The user ID.
            chat_id: The chat session ID.
            collection: Collection discriminator.

        Returns:
            Chat document with raw_messages filtered to the given task_id.
        """
        doc = await self.get_chat(user_id, chat_id, collection)
        if not doc:
            return None

        doc["raw_messages"] = [
            msg
            for msg in doc.get("raw_messages", [])
            if msg.get("task_id") == task_id
        ]
        return doc

    def _row_to_dict(self, row: aiosqlite.Row) -> dict[str, Any]:
        """Convert a SQLite row to a plain dict with JSON fields parsed."""
        return {
            "user_id": row[1],
            "chat_id": row[2],
            "collection": row[3],
            "chat_dir": row[4],
            "call_id": row[5],
            "capability_id": row[6],
            "messages": json.loads(row[7]),
            "raw_messages": json.loads(row[8]),
            "feedback": json.loads(row[9]),
            "created_at": row[10],
            "updated_at": row[11],
        }
