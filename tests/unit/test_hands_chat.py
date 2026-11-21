"""chat on /hands/mcp: a quick job in DAX's chat mode, answered in the same call; a question is answered by calling again."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.routers import hands_mcp as hm
from src.routers import websocket
from src.services import chat_bridge


def said(text: str, kind: str = "message") -> dict:
    """An assistant event as the persona session streams it."""
    return {"type": "message", "data": {"source": "assistant", "content": {"name": "assistant", "type": kind, "content": {"type": kind, "content": text}}}}


def status(state: str) -> dict:
    return said("", "agent_status") | {"data": {"source": "assistant", "content": {"type": "agent_status", "content": {"type": "agent_status", "status": state, "persona": "assistant"}}}}


@pytest.fixture
def route(monkeypatch):
    """The chat route, faked: it answers each message with the events listed for it, and records what it was sent."""
    script, got = {}, []

    async def chat_websocket(ws, chat_id, user_id, manager):
        await ws.send_json({"type": "init_status", "status": "ready"})
        while True:
            message = json.loads(await ws.receive_text())
            got.append(message)
            for event in script[message.get("task") or message.get("response")]:
                await ws.send_json(event)

    monkeypatch.setattr(websocket, "chat_websocket", chat_websocket)
    monkeypatch.setattr(chat_bridge, "get_websocket_manager", AsyncMock(return_value=SimpleNamespace(is_running=lambda c: False)))
    monkeypatch.setattr(hm, "_chats", {})
    monkeypatch.setattr(hm.ChatService, "create_chat_mode_session", AsyncMock(return_value={"chat_id": "chat-q"}))
    monkeypatch.setattr(hm, "get_chat_repository", AsyncMock(return_value=SimpleNamespace(get_chat=AsyncMock(side_effect=lambda u, c, coll: c == "chat-q" and coll == "chats"))))
    return script, got


def test_a_quick_job_is_answered_in_the_same_call(route):
    script, _ = route
    script["Any new mail from Acme?"] = [status("started"), said("Checking your inbox…"), said("One new email from Ana at Acme, about pricing."),
                                         status("finished"), {"type": "completion", "status": "complete"}]
    out = asyncio.run(hm.chat("Any new mail from Acme?"))
    assert out == {"chat_id": "chat-q", "reply": "One new email from Ana at Acme, about pricing.", "done": True}


def test_a_question_stops_the_turn_and_the_next_call_answers_it(route):
    script, got = route
    card = {"type": "input_request", "data": {"content": {"agent": "send_approval", "prompt": "Send this email to ana@acme.com?"}}}
    script["Reply to Ana: thanks"] = [status("started"), said("Drafted the reply."), status("finished"), card]
    script["yes"] = [status("started"), said("Sent."), status("finished"), {"type": "completion", "status": "complete"}]

    async def two_calls():
        first = await hm.chat("Reply to Ana: thanks")
        return first, await hm.chat("yes", chat_id="chat-q")

    first, second = asyncio.run(two_calls())
    assert first["done"] is False and first["reply"] == "Drafted the reply." and first["question"]
    assert second == {"chat_id": "chat-q", "reply": "Sent.", "done": True}
    assert [m["type"] for m in got] == ["start", "input_response"]  # the answer went to the open question, not as a new task


def test_chat_says_when_a_task_is_needed(route):
    script, _ = route
    suggestion = {"type": "message", "data": {"source": "assistant", "content": {"type": "task_suggestion", "content": {
        "type": "task_suggestion", "suggestion": {"title": "Lead list", "request": "Find 25 marketing leads in the Bay Area"}}}}}
    script["Find 25 leads"] = [suggestion, {"type": "completion", "status": "complete"}]
    out = asyncio.run(hm.chat("Find 25 leads"))
    assert out["done"] and "This needs a task (Lead list)" in out["reply"] and "Find 25 marketing leads in the Bay Area" in out["reply"]


def test_a_chat_id_that_is_not_a_chat_is_refused(route):
    with pytest.raises(ValueError, match="no chat nope"):
        asyncio.run(hm.chat("hi", chat_id="nope"))


def test_a_chat_that_cannot_run_is_an_error_not_an_empty_answer(route, monkeypatch):
    async def broken(ws, chat_id, user_id, manager):
        raise RuntimeError("WebSocket manager not initialized")

    monkeypatch.setattr(websocket, "chat_websocket", broken)
    with pytest.raises(RuntimeError, match="the chat could not run: WebSocket manager not initialized"):
        asyncio.run(hm.chat("hi"))


def test_request_routes_chat_and_task_and_gives_back_the_id(route, monkeypatch):
    script, _ = route
    script["Any new mail?"] = [status("started"), said("None today."), status("finished"), {"type": "completion", "status": "complete"}]
    started = AsyncMock(return_value={"key": "chat-t", "chat_id": "chat-t"})
    monkeypatch.setattr(hm, "start_run", started)
    ctx = SimpleNamespace()

    chat_out = asyncio.run(hm.request("chat", "Any new mail?", ctx))
    assert (chat_out["request"], chat_out["request_id"], chat_out["reply"], chat_out["done"]) == ("chat", "chat-q", "None today.", True)
    task_out = asyncio.run(hm.request("task", "Find 25 marketing leads", ctx, request_id="chat-t", lead_target=25))
    assert (task_out["request"], task_out["request_id"]) == ("task", "chat-t")
    assert started.await_args.kwargs["chat_id"] == "chat-t" and started.await_args.kwargs["lead_target"] == 25
    with pytest.raises(ValueError, match='request is "chat" or "task"'):
        asyncio.run(hm.request("other", "x", ctx))


def test_what_a_chat_saved_is_read_by_its_id(route, monkeypatch):
    saved = [{"id": "analysis-1", "kind": "analysis", "title": "Inbox summary", "row_count": 3, "persona": "assistant", "created_at": "t", "chat_id": "chat-q"}]
    monkeypatch.setattr(hm, "db_list_artifacts", AsyncMock(return_value=saved))
    monkeypatch.setattr(hm, "get_websocket_manager", AsyncMock(return_value=SimpleNamespace(is_running=lambda c: False)))
    assert asyncio.run(hm.task_status(chat_id="chat-q")) == {
        "chat_id": "chat-q", "request": "chat", "stage": "done", "saved": [{"id": "analysis-1", "kind": "analysis", "title": "Inbox summary", "rows": 3}]}
    assert [a["id"] for a in asyncio.run(hm.list_artifacts(chat_id="chat-q"))["artifacts"]] == ["analysis-1"]
    with pytest.raises(ValueError, match="no task or chat nope"):
        asyncio.run(hm.list_artifacts(chat_id="nope"))
