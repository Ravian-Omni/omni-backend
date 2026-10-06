"""Ratings are stored per conversation (chat_id) and run (task_id); rating a run again replaces it."""

import asyncio

import pytest

from src.database import connection, load_feedback, save_feedback


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(connection.settings, "ROOT_DIR", str(tmp_path))
    monkeypatch.setattr(connection, "_db", None)
    asyncio.run(connection.init_db())
    yield
    asyncio.run(connection.close_db())


def test_feedback_is_bound_to_the_conversation(temp_db):
    async def scenario():
        await save_feedback("chat-a", "run-1", "local_user", 4, "Good plan")
        await save_feedback("chat-a", "run-1", "local_user", 5, "Better after the edit")  # same run: replaced
        await save_feedback("chat-a", "run-2", "local_user", 2, "")
        await save_feedback("chat-b", "run-1", "local_user", 3, "Other conversation")
        return await load_feedback("chat-a"), await load_feedback("chat-b")

    a, b = asyncio.run(scenario())
    assert [(f["task_id"], f["rating"], f["description"]) for f in a] == [("run-1", 5, "Better after the edit"), ("run-2", 2, "")]
    assert [f["rating"] for f in b] == [3]
