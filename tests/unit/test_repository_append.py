"""Parallel agents append to the same chat row; no entry may be lost."""

import asyncio
import json

import aiosqlite
import pytest

from src.database.connection import SCHEMA_SQL
from src.database.repository import ChatRepository


@pytest.mark.asyncio
async def test_concurrent_appends_keep_every_entry():
    async with aiosqlite.connect(":memory:") as db:
        await db.executescript(SCHEMA_SQL)
        repo = ChatRepository(db)
        await repo.create_chat({"user_id": "u", "chat_id": "c"}, "omni")
        await asyncio.gather(*(
            repo.append_message("c", {"name": f"agent{i}", "raw_message": "x"}, None, "omni") for i in range(20)
        ))
        row = await (await db.execute("SELECT raw_messages FROM chats WHERE chat_id = 'c'")).fetchone()
        assert sorted(m["name"] for m in json.loads(row[0])) == sorted(f"agent{i}" for i in range(20))
