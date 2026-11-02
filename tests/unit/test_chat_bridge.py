"""An app thread is a task: the agents' questions come back as text and the next message answers them."""
import asyncio
import json
from types import SimpleNamespace

import pytest

from src.routers import websocket
from src.services import chat_bridge as bridge


def _omni(name, content):
    return {"type": "message", "data": {"source": "OMNI", "content": {"name": name, "content": content}}}


def _persona(inner):
    return {"type": "message", "data": {"source": "lead_finder", "content": {"name": "lead_finder", "type": inner["type"], "content": inner}}}


def test_events_read_like_the_web_app():
    notes = {}
    plan = json.dumps({"breakdown": [{"task": "Find dentists in Austin", "capability": "lead_finder"}]})
    assert bridge.text_of(_omni("planner_agent", plan), notes) == "Plan:\n\n1. Find dentists in Austin (lead_finder)"
    assert bridge.text_of(_omni("judge_question", "{}"), notes) is None
    approve = {"type": "input_request", "data": {"source": "system", "content": json.dumps({"agent": "get_user_acceptance", "prompt": "x"})}}
    assert "approve this plan" in bridge.text_of(approve, notes)
    spend = {"type": "input_request", "data": {"source": "lead_finder", "content": {
        "card": "confirm_spend", "title": "Confirm credit spend", "message": "Enriching 10 records will consume 10 credits, do you want to proceed?"}}}
    assert bridge.text_of(spend, notes) == (
        "Confirm credit spend\n\nEnriching 10 records will consume 10 credits, do you want to proceed?\n\nReply **yes** or **no**.")
    form = {"type": "input_request", "data": {"source": "user_verification", "content": json.dumps({
        "card": "form", "title": "A few details", "message": "", "questions": [{"label": "Which city?", "options": [{"label": "Austin"}, {"label": "Dallas"}]}]})}}
    assert bridge.text_of(form, notes) == "A few details\n\n- Which city? (Austin, Dallas)"
    # a running agent's text is held back; the last line is shown when it finishes, like the activity line
    assert bridge.text_of(_persona({"type": "agent_status", "status": "started", "persona": "lead_finder"}), notes) is None
    assert bridge.text_of(_persona({"type": "message", "content": "Searching..."}), notes) is None
    assert bridge.text_of(_persona({"type": "message", "content": "Found 25 dentists."}), notes) is None
    assert bridge.text_of(_persona({"type": "artifact", "artifact": {"kind": "table", "title": "Austin dentists"}}), notes) == "Saved table: Austin dentists"
    assert bridge.text_of(_persona({"type": "agent_status", "status": "finished", "persona": "lead_finder"}), notes) == "Found 25 dentists."
    assert bridge.text_of(_persona({"type": "message", "content": "Anything else?"}), notes) == "Anything else?"
    assert bridge.text_of({"type": "completion", "status": "cancelled"}, notes) == "Stopped."
    assert bridge.text_of({"type": "completion", "status": "complete"}, notes) is None
    assert bridge.text_of({"type": "error", "message": "boom"}, notes) == "Something went wrong: boom"


@pytest.fixture
def fakes(monkeypatch):
    said, received, prefs = [], [], {}

    async def fake_omni(socket, chat_id, user_id, ws_manager):  # the omni route: one question per task
        await socket.send_json({"type": "init_status", "status": "ready"})
        while True:
            received.append(json.loads(await socket.receive_text()))
            if received[-1]["type"] == "start":
                await socket.send_json({"type": "input_request", "data": {"source": "system", "content": json.dumps({"agent": "get_user_acceptance"})}})
            else:
                await socket.send_json({"type": "completion", "status": "complete"})

    async def load_pref(user_id, key, default=None):
        return prefs.get((user_id, key), default)

    async def save_pref(user_id, key, value):
        prefs[(user_id, key)] = value

    async def create_chat(user_id, chat_dir=None):
        return {"chat_id": "chat-1"}

    async def manager():
        return SimpleNamespace(is_running=lambda chat_id: False)

    monkeypatch.setattr(bridge, "load_pref", load_pref)
    monkeypatch.setattr(bridge, "save_pref", save_pref)
    monkeypatch.setattr(bridge, "get_websocket_manager", manager)
    monkeypatch.setattr(bridge.ChatService, "create_omni_chat", create_chat)
    monkeypatch.setattr(websocket, "omni_websocket", fake_omni)
    monkeypatch.setattr(bridge, "_threads", {})
    return said, received, prefs


def test_a_thread_is_a_task_and_the_next_message_answers_the_agents(fakes):
    said, received, prefs = fakes

    async def say(text):
        said.append(text)

    async def until(condition):
        for _ in range(100):
            if condition():
                return
            await asyncio.sleep(0.01)
        assert condition()

    async def run():
        thread = await bridge.open_thread("slack", "C1:1.2", say)
        assert await bridge.open_thread("slack", "C1:1.2", say) is thread and prefs[("slack", "C1:1.2")] == "chat-1"
        thread.send("find dentists in Austin")
        await until(lambda: said)
        assert received[0] == {"type": "start", "task": "find dentists in Austin", "files": []}
        assert "approve this plan" in said[-1]
        thread.send("yes")
        await until(lambda: len(received) == 2)
        assert received[1] == {"type": "input_response", "response": "yes"}
        thread.send("stop")
        await until(lambda: len(received) == 3)
        assert received[2] == {"type": "stop"}
        thread.task.cancel()

    asyncio.run(run())
