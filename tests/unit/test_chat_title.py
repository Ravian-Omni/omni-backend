"""A chat's title follows its work (a run starts, its plan is approved, a run completes), keeps a goal's subject, is never
renamed once a person gave it, and reaches the page, the sidebar's list and Brain_Hands."""

import asyncio
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src import database
from src.database import (connection, get_chat_repository, get_chat_title, get_title_state, hide_chat, list_conversations, save_pref,
                          set_chat_title)
from src.managers.connection import WebSocketManager
from src.routers import chat as chat_router
from src.routers import hands_mcp as hm
from src.services import chat_title, needs
from tests.unit.test_brain_hands_push import server
from tests.unit.test_needs import fake_manager, question_event, thread

REQUEST = str({"task": "Find dentists in Austin", "files": []})
PLAN = json.dumps({"overall_status": "in_progress", "breakdown": [{"task": "Find dentists", "capability": "lead_finder"}, {"task": "Enrich them", "capability": "contact_enricher"}]})
MESSAGES = [{"name": "chat_manager", "content": REQUEST}, {"name": "planner_agent", "content": PLAN},
            {"name": "get_user_acceptance", "content": "yes"}, {"name": "process_completion_agent", "content": "Found 25 dentists and enriched them."}]


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(connection.settings, "ROOT_DIR", str(tmp_path))
    monkeypatch.setattr(connection, "_db", None)
    monkeypatch.setattr(database, "_chat_repository", None)
    asyncio.run(connection.init_db())
    yield
    asyncio.run(connection.close_db())


async def chat(chat_id, messages=MESSAGES, collection="omni"):
    await (await get_chat_repository()).create_chat({"user_id": "local_user", "chat_id": chat_id, "messages": messages, "raw_messages": [{"x": 1}]}, collection)


def titles(*words):
    """A model that answers with these titles in turn."""
    return patch("src.services.chat_title.llm.complete", AsyncMock(side_effect=list(words)))


def test_the_title_follows_the_work_at_each_moment(temp_db):
    async def scenario():
        await chat("c1")
        out = [await chat_title.retitle("c1", "request", "Find dentists in Austin"), await chat_title.retitle("c1", "plan"), await chat_title.retitle("c1", "done")]
        return out, await get_chat_title("c1")

    with titles("Dentists in Austin", "Find and enrich dentists", '"25 Austin dentists enriched."') as model:
        out, final = asyncio.run(scenario())
    assert out == ["Dentists in Austin", "Find and enrich dentists", "25 Austin dentists enriched"] and final == out[-1]
    _, plan_call, done_call = model.call_args_list
    assert "plan sets out" in plan_call.args[0] and plan_call.args[1] == "Find dentists; Enrich them"  # the approved plan's steps
    assert "what was done" in done_call.args[0].lower() and done_call.args[1] == "Found 25 dentists and enriched them."  # the closing summary


def test_the_model_is_not_asked_when_nothing_changed_since_the_last_title(temp_db):
    async def scenario():
        await chat("c1")
        return [await chat_title.retitle("c1", "plan"), await chat_title.retitle("c1", "plan")]

    with titles("Find and enrich dentists", "Something else") as model:
        first, again = asyncio.run(scenario())
    assert (first, again) == ("Find and enrich dentists", None) and model.await_count == 1


def test_a_title_a_person_gave_is_never_renamed(temp_db):
    async def scenario():
        await chat("c1")
        await set_chat_title("c1", "My dentist pipeline", "user")
        out = [await chat_title.retitle("c1", m, "Find dentists") for m in ("request", "plan", "done")]
        wrote = await set_chat_title("c1", "A generated title", "auto")
        return out, wrote, await get_title_state("c1")

    with titles("Never used") as model:
        out, wrote, state = asyncio.run(scenario())
    assert out == [None, None, None] and wrote is False and state[:2] == ("My dentist pipeline", "user") and model.await_count == 0


def test_a_goals_chat_keeps_its_subject_while_the_work_after_it_moves(temp_db):
    async def scenario():
        await chat("goal")
        await save_pref("local_user", "agenda:goal", "agd_1")
        await chat("plain")
        seen = [await chat_title.retitle("goal", "request", "GOAL: get 3 B2B clients for MarketWatch")]
        seen += [await chat_title.retitle("goal", "plan"), await chat_title.retitle("goal", "done"), await chat_title.retitle("goal", "request", "Now draft the outreach copy")]
        return seen, await chat_title.retitle("plain", "request", "Find dentists"), await chat_title.retitle("plain", "done")

    with titles("3 B2B clients for MarketWatch", "Find buyers at SaaS firms", "25 buyers enriched", "Draft the outreach copy", "Dentists in Austin", "25 dentists enriched"):
        goal, first, second = asyncio.run(scenario())
    assert goal == ["3 B2B clients for MarketWatch",  # the first name is the subject
                    "3 B2B clients for MarketWatch · Find buyers at SaaS firms",
                    "3 B2B clients for MarketWatch · 25 buyers enriched",
                    "3 B2B clients for MarketWatch · Draft the outreach copy"]
    assert (first, second) == ("Dentists in Austin", "25 dentists enriched")  # a chat with no goal is just renamed


def test_a_title_is_three_to_six_words(temp_db):
    async def scenario():
        await chat("c1")
        return await chat_title.retitle("c1", "request", "x")

    with titles("One two three four five six seven eight nine"):
        assert asyncio.run(scenario()) == "One two three four five six"


def test_every_rename_is_pushed_to_the_page_with_the_chat_title_event(temp_db):
    manager = WebSocketManager()
    page = SimpleNamespace(accept=AsyncMock(), send_json=AsyncMock())

    async def scenario():
        await chat("c1")
        await manager.connect(page, "c1")
        await manager._retitle("c1", "request", "Find dentists")
        await manager._retitle("c1", "request", "Find dentists")  # nothing changed: nothing sent
        await manager._retitle("c1", "plan")

    with titles("Dentists in Austin", "Find and enrich dentists"):
        asyncio.run(scenario())
    sent = [c.args[0] for c in page.send_json.await_args_list if c.args[0].get("type") == "chat_title"]
    assert [s["title"] for s in sent] == ["Dentists in Austin", "Find and enrich dentists"]


def test_only_a_yes_to_the_plan_approval_question_counts_as_the_plan_being_approved():
    prompt = json.dumps({"agent": "get_user_acceptance", "prompt": "Proceed?"})
    assert WebSocketManager._approves_plan(prompt, "yes, looks good.") and WebSocketManager._approves_plan(prompt, "ok")
    assert not WebSocketManager._approves_plan(prompt, "change the plan: drop outreach")
    assert not WebSocketManager._approves_plan(json.dumps({"agent": "user_input", "prompt": "?"}), "yes")


def test_the_current_title_is_task_title_in_every_event_and_in_the_push(temp_db, monkeypatch):
    monkeypatch.setattr(needs, "UNATTENDED_S", 0.1)
    seen = server(monkeypatch, 200)
    fake_manager(monkeypatch, {"request_id": "42"})

    async def scenario():
        await chat("chat-1")
        await set_chat_title("chat-1", "Old name", "auto")
        t = thread()
        await t.send_json(question_event())  # asked while it was "Old name"
        await set_chat_title("chat-1", "Renamed while waiting", "auto")
        await t.send_json({"type": "completion", "status": "complete"})
        await asyncio.sleep(0.6)
        return [t.queue.get_nowait() for _ in range(t.queue.qsize())]

    events = asyncio.run(scenario())
    assert [e["task_title"] for e in events] == ["Old name", "Renamed while waiting"]  # every event carries the name it has then
    assert json.loads(seen[0].read())["data"]["task_title"] == "Renamed while waiting"  # the push carries the name it has when it goes


def test_chats_without_a_name_get_one_once_a_few_at_a_time(temp_db):
    live = {"now": 0, "most": 0, "calls": 0}

    async def model(system, user, max_tokens=24):
        live["now"] += 1
        live["most"] = max(live["most"], live["now"])
        live["calls"] += 1
        await asyncio.sleep(0.02)
        live["now"] -= 1
        return f"Named {live['calls']}"

    async def scenario():
        for n in range(7):
            await chat(f"c{n}")
        await chat("done")
        await set_chat_title("done", "Already named", "auto")
        await chat("mine")
        await set_chat_title("mine", "My name", "user")
        await chat("hidden")
        await hide_chat("hidden")
        await chat("chat-mode", collection="chats")  # chat mode is not a task chat
        first = await chat_title.backfill()
        calls = live["calls"]
        return first, calls, await chat_title.backfill(), live["calls"], {c: await get_chat_title(c) for c in ("c0", "done", "mine", "hidden", "chat-mode")}

    with patch("src.services.chat_title.llm.complete", model):
        first, calls, again, calls_after, named = asyncio.run(scenario())
    assert (first, calls, again, calls_after) == (7, 7, 0, 7) and live["most"] <= 3  # once each, never more than three at a time
    assert named["c0"].startswith("Named") and named["done"] == "Already named" and named["mine"] == "My name" and named["hidden"] is None and named["chat-mode"] is None


def test_the_backfill_stops_when_a_whole_batch_fails(temp_db):
    async def scenario():
        for n in range(8):
            await chat(f"c{n}")
        return await chat_title.backfill()

    with patch("src.services.chat_title.llm.complete", AsyncMock(side_effect=RuntimeError("no key"))) as model:
        named = asyncio.run(scenario())
    assert named == 0 and model.await_count == 3  # one batch of three, not all eight


def test_the_sidebar_shows_a_title_for_a_shared_folder_and_keeps_a_chosen_name():
    names = chat_router._names
    base = {"collection": "omni", "chat_dir": "/home/me/.daxagent/daxagent", "title": "25 buyers enriched", "title_by": "auto"}
    assert names(base) == {"name": "25 buyers enriched", "auto_name": True}  # the shared folder names nobody's work
    assert names({**base, "chat_dir": "/x/daxagent-agent-tasks/Demo_task"}) == {"name": "Demo_task", "auto_name": False}  # a name chosen at creation stays
    assert names({**base, "chat_dir": "/x/daxagent-agent-tasks/Demo_task", "title_by": "user"}) == {"name": "25 buyers enriched", "auto_name": False}  # a hand-set one wins
    assert names({**base, "collection": "chats", "chat_dir": ""}) == {"name": "25 buyers enriched", "auto_name": True}
    assert names({**base, "title": None}) == {"name": "daxagent", "auto_name": False}


def test_a_person_renames_a_chat_and_it_stays_through_the_work_and_the_list(temp_db):
    app = FastAPI()
    app.include_router(chat_router.router, prefix="/chats")
    client = TestClient(app)

    async def make():
        await chat("c1")

    asyncio.run(make())
    assert client.put("/chats/c1/title", json={"title": "  My dentist pipeline "}).json() == {"chat_id": "c1", "title": "My dentist pipeline"}
    assert client.put("/chats/c1/title", json={"title": ""}).status_code == 422
    assert client.put("/chats/nope/title", json={"title": "x"}).status_code == 404
    with titles("Generated") as model:
        assert asyncio.run(chat_title.retitle("c1", "done")) is None and model.await_count == 0
    listed = [c for c in asyncio.run(list_conversations("local_user")) if c["chat_id"] == "c1"]
    assert listed[0]["title"] == "My dentist pipeline" and listed[0]["title_by"] == "user"
