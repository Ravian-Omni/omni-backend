"""A goal has one chat, a chat's runs go one after another (a second start_run queues instead of failing), and chats run in
parallel up to a limit."""

import asyncio
import time
import itertools
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.database import get_chat_repository, list_queued_runs
from src.routers import hands_mcp as hm
from tests.unit.test_leads import temp_db  # noqa: F401 - the temp_db fixture

CTX = SimpleNamespace(session=SimpleNamespace(client_params=None))
REAL_THREAD = hm.HandsThread  # the fixture swaps in a recording one


@pytest.fixture
def env(temp_db, monkeypatch):
    """start_run against a temp DB, with threads that record what they are told to start and a manager whose busy chats we set."""
    web_runs, started, chats = [], [], itertools.count(1)

    class Thread:
        def __init__(self, key, chat_id):
            self.chat_id, self.queue, self.inbox = chat_id, asyncio.Queue(), asyncio.Queue()
            self.task, self.ask_text, self.plan = SimpleNamespace(done=lambda: False), "", []

    async def create_omni_chat(_user):
        chat_id = f"chat-new-{next(chats)}"
        await (await get_chat_repository()).create_chat({"user_id": hm.USER_ID, "chat_id": chat_id}, "omni")
        return {"chat_id": chat_id}

    monkeypatch.setattr(hm, "_threads", {})
    monkeypatch.setattr(hm, "_active", set())
    monkeypatch.setattr(hm, "_watching", set())  # tasks other tests left on their own, closed event loops
    monkeypatch.setattr(hm, "_lock", asyncio.Lock())
    monkeypatch.setattr(hm, "HandsThread", Thread)
    monkeypatch.setattr(hm, "MAX_PARALLEL", 3)
    monkeypatch.setattr(hm, "get_chat_repository", AsyncMock(return_value=SimpleNamespace(get_chat=AsyncMock(return_value={"chat_id": "x"}))))
    monkeypatch.setattr(hm, "get_websocket_manager", AsyncMock(return_value=SimpleNamespace(running_chats=lambda: list(web_runs), is_running=lambda c: c in web_runs)))
    monkeypatch.setattr(hm, "ChatService", SimpleNamespace(create_omni_chat=create_omni_chat))

    def tasks_started():
        """Every task handed to a thread to start, in order."""
        return [json.loads(m)["task"] for t in {id(t): t for t in hm._threads.values()}.values() for m in list(t.inbox._queue)]

    return SimpleNamespace(web_runs=web_runs, tasks_started=tasks_started, started=started)


def run(coro):
    return asyncio.run(coro)


def test_an_agenda_without_a_chat_continues_the_chat_it_already_has(env):
    async def scenario():
        first = await hm.start_run("find buyers", CTX, agenda_id="agd_1")
        hm._active.clear(); hm._threads.clear()  # the first run ended
        again = await hm.start_run("follow up", CTX, agenda_id="agd_1")  # no chat_id: the goal's chat
        other = await hm.start_run("another goal", CTX, agenda_id="agd_2")
        return first, again, other

    first, again, other = run(scenario())
    assert first["chat_id"] == again["chat_id"] != other["chat_id"] and again["agenda_id"] == "agd_1"


def test_a_second_run_on_a_running_chat_queues_then_runs_in_order(env):
    async def scenario():
        a = await hm.start_run("first", CTX, key="k1", chat_id="chat-a")
        b = await hm.start_run("second", CTX, key="k2", chat_id="chat-a")  # no longer "run k1 is still going"
        c = await hm.start_run("third", CTX, key="k3", chat_id="chat-a")
        waiting = await hm.next_event("k2", timeout=1)
        before = env.tasks_started()
        hm._run_ended("chat-a"); await asyncio.gather(*hm._watching)  # the first run ends
        after_first = env.tasks_started()
        hm._run_ended("chat-a"); await asyncio.gather(*hm._watching)
        return a, b, c, waiting, before, after_first, env.tasks_started(), await list_queued_runs()

    a, b, c, waiting, before, after_first, after_second, left = run(scenario())
    assert "queued" not in a and (b["queued"], b["position"], c["position"]) == (True, 1, 2)
    assert waiting == {"chat_id": "chat-a", "events": [], "closed": False, "pending": False, "queued": True, "position": 1}
    assert (before, after_first, after_second) == (["first"], ["first", "second"], ["first", "second", "third"]) and left == []


def test_chats_run_in_parallel_up_to_the_limit_and_web_runs_count(env, monkeypatch):
    monkeypatch.setattr(hm, "MAX_PARALLEL", 3)
    env.web_runs.append("web-chat")  # a task running in the web app takes one of the three slots

    async def scenario():
        runs = [await hm.start_run(f"task {n}", CTX, key=f"k{n}", chat_id=f"chat-{n}") for n in (1, 2, 3)]
        queued_task = [r.get("queued") for r in runs]
        hm._run_ended("chat-1"); await asyncio.gather(*hm._watching)  # a slot frees: the queued third chat starts
        return queued_task, env.tasks_started(), await list_queued_runs()

    flags, started, left = run(scenario())
    assert flags == [None, None, True] and sorted(started) == ["task 1", "task 2", "task 3"] and left == []


def test_a_completion_event_frees_the_chat_for_its_next_queued_run(env, monkeypatch):
    monkeypatch.setattr(hm.leads, "tally", AsyncMock(return_value={"passed": 0, "seen": 0, "failed": {}}))
    monkeypatch.setattr(hm.needs, "credits_approved", AsyncMock(return_value=0))

    async def scenario():
        t = object.__new__(REAL_THREAD)  # the real send_json, on a thread running chat-a
        t.chat_id, t.queue, t.inbox, t.ask_text, t.plan = "chat-a", asyncio.Queue(), asyncio.Queue(), "", []
        t.agenda_id, t.lead_target, t.rounds, t.seen, t.started_at, t.polling, t.last_poll = "", 0, 0, 0, "2000-01-01T00:00:00+00:00", 0, 0.0
        t.key, t.request = "k1", ""
        t.stop_reason, t.asked_at, t.last_event = "", None, time.monotonic()  # working: it just showed it is alive
        t.pending, t.ready, t.notes, t.say, t.task = False, False, {}, AsyncMock(), SimpleNamespace(done=lambda: False)
        hm._threads["k1"] = t
        hm._active.add("chat-a")
        queued = await hm.start_run("second", CTX, key="k2", chat_id="chat-a")
        await t.send_json({"type": "completion", "status": "complete"})  # the first run ends
        await asyncio.gather(*hm._watching)
        return queued, env.tasks_started()

    queued, started = run(scenario())
    assert queued["queued"] is True and started == ["second"]


def test_the_queue_is_in_the_database_so_a_restart_does_not_lose_it(env):
    async def scenario():
        await hm.start_run("running", CTX, key="k1", chat_id="chat-a")
        await hm.start_run("waiting", CTX, key="k2", chat_id="chat-a", lead_target=5, credit_budget=40)
        waiting = await list_queued_runs()
        hm._threads.clear(); hm._active.clear()  # the process restarted: nothing is running
        await hm._dispatch()
        return waiting, env.tasks_started(), await list_queued_runs()

    waiting, started, left = run(scenario())
    assert [(w["task"], w["lead_target"], w["credit_budget"]) for w in waiting] == [("waiting", 5, 40.0)]
    assert started == ["waiting"] and left == []
