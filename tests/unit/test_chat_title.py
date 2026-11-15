"""A chat is named once from its first message, never over an existing title, and the sidebar's lists carry it."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from src import database
from src.database import connection, get_chat_repository, get_chat_title, list_conversations, set_chat_title, update_chat_history
from src.services import chat_title
from src.services.chat_service import ChatService

MSG = {"role": "user", "name": "chat_manager", "raw_message": "x", "usage": {}, "task_id": "t"}


async def chat_with_messages(chat_id: str, collection: str) -> None:
    await (await get_chat_repository()).create_chat({"user_id": "local_user", "chat_id": chat_id}, collection)
    for _ in range(3):
        await update_chat_history(chat_id, MSG, collection)


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(connection.settings, "ROOT_DIR", str(tmp_path))
    monkeypatch.setattr(connection, "_db", None)
    monkeypatch.setattr(database, "_chat_repository", None)  # the repository holds the connection it was made with
    asyncio.run(connection.init_db())
    yield
    asyncio.run(connection.close_db())


def test_the_title_is_written_once_and_a_set_one_is_never_overwritten(temp_db):
    async def scenario():
        await chat_with_messages("c1", "chats")
        assert await get_chat_title("c1") is None
        assert await set_chat_title("c1", "Dentists in Austin") is True
        assert await set_chat_title("c1", "Something else") is False
        with patch("src.services.chat_title.llm.complete", AsyncMock(return_value="A model title")) as model:
            assert await chat_title.name_chat("c1", "Find dentists") is None  # already titled: the model is not even asked
            model.assert_not_called()
        history = await ChatService.get_omni_chat_history("local_user", "c1", "chats")
        listed = [c for c in await list_conversations("local_user") if c["chat_id"] == "c1"]
        return await get_chat_title("c1"), history["title"], listed

    title, history_title, listed = asyncio.run(scenario())
    assert title == history_title == "Dentists in Austin"
    assert [c["title"] for c in listed] == ["Dentists in Austin"]  # the sidebar's list carries it


def test_the_first_message_names_the_chat_in_at_most_six_words(temp_db):
    async def scenario():
        await chat_with_messages("c2", "omni")
        with patch("src.services.chat_title.llm.complete", AsyncMock(return_value='"Find HVAC buyers in Texas for our new fall service plan."')) as model:
            named = await chat_title.name_chat("c2", "Find HVAC buyers in Texas")
            assert model.await_args.kwargs["max_tokens"] == 24
        with patch("src.services.chat_title.llm.complete", AsyncMock(side_effect=RuntimeError("down"))):
            failed = await chat_title.name_chat("c3", "Another request")  # a model failure leaves the chat unnamed
        return named, failed, await get_chat_title("c2")

    named, failed, stored = asyncio.run(scenario())
    assert named == stored == "Find HVAC buyers in Texas for"
    assert failed is None
