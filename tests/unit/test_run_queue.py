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
    monkeypatch.setattr(hm, "credits_spent", AsyncMock(return_value=0))

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


def test_a_reused_thread_answers_the_run_that_reused_it(env, monkeypatch):
    """Chat 776cad9a: run sch_13daa1ff86 was reported lost with in_reply_to the key of the run that opened its thread."""
    monkeypatch.setattr(hm.leads, "tally", AsyncMock(return_value={"passed": 0, "seen": 0, "failed": {}}))

    async def scenario():
        t = object.__new__(REAL_THREAD)
        t.chat_id, t.key, t.queue, t.inbox, t.task = "chat-a", "k1", asyncio.Queue(), asyncio.Queue(), SimpleNamespace(done=lambda: False)
        hm._threads["k1"] = t  # the first run ended; its thread is still open on the chat
        await hm.start_run("second", CTX, key="k2", chat_id="chat-a")
        t.lost("the run ended without finishing")
        return hm._threads["k2"], t.queue.get_nowait()

    thread, lost = run(scenario())
    assert thread.key == "k2" and lost["result"]["in_reply_to"] == "k2"


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


def test_a_key_not_running_here_answers_closed_at_once_so_its_poller_stops(env):
    async def poll():
        started = time.monotonic()
        return await hm.next_event("run-before-a-restart", timeout=25), time.monotonic() - started

    out, took = run(poll())
    assert out == {"chat_id": "run-before-a-restart", "events": [], "closed": True, "pending": False, "unknown": True} and took < 1


@pytest.fixture
def blocked(env, monkeypatch):
    """chat-a runs from the web app and waits on its plan approval (request 41); a Brain_Hands run is queued behind it."""
    pending = {"chat-a": {"request_id": "41", "timestamp": "2026-11-20T09:17:13+00:00", "answered": False}}
    manager = SimpleNamespace(running_chats=lambda: ["chat-a"], is_running=lambda c: c == "chat-a", pending_request=pending.get,
                              handle_input_response=AsyncMock(return_value=True))
    pushed = []

    async def push(need, **extra):
        pushed.append({**need, **extra})
        return True

    monkeypatch.setattr(hm, "get_websocket_manager", AsyncMock(return_value=manager))
    monkeypatch.setattr(hm, "_told_blocked", set())
    monkeypatch.setattr(hm.needs, "push", push)
    monkeypatch.setattr(hm.status, "card_of", lambda event: ({"agent": "get_user_acceptance"}, "planner"))
    monkeypatch.setattr(hm.status, "question_of", lambda *a: {"kind": "plan_approval", "answer_with": "yes or no", "title": "Approve the plan?"})
    monkeypatch.setattr(hm.status, "task_status", AsyncMock(return_value={"stage": "awaiting_plan_approval"}))
    monkeypatch.setattr(hm, "run_started", AsyncMock(return_value="2026-11-20T09:16:45+00:00"))
    run(hm.start_run("a question for DAX", CTX, key="sch_1", chat_id="chat-a"))
    return pending, pushed, manager


def test_a_queued_key_says_what_it_waits_behind(blocked):
    out = run(hm.task_status(key="sch_1"))
    assert {k: out[k] for k in ("queued", "position", "chat_id", "state", "parent_id")} == {"queued": True, "position": 1, "chat_id": "chat-a",
                                                                                           "state": "queued", "parent_id": "sch_1"}
    assert out["waiting_on"] == {"started_at": "2026-11-20T09:16:45+00:00", "source": "web_app", "state": "awaiting_plan_approval"}
    assert out["id"].startswith("dt_")


def test_a_web_app_question_blocking_a_queued_run_is_told_once_and_cannot_be_answered_from_here(blocked):
    pending, pushed, manager = blocked
    run(hm._tell_blocked()); run(hm._tell_blocked())  # two tend turns: one need
    [need] = pushed
    assert (need["id"], need["reason"], need["queued_key"], need["answerable"], need["data"]["task_id"]) == ("41:blocks:sch_1", "blocks_queued", "sch_1", False, "chat-a")
    assert run(hm.answer("chat-a", "yes"))["reason"] == "web_app_question" and manager.handle_input_response.await_count == 0
    pending["chat-a"] = {"request_id": "42", "timestamp": "x", "answered": False}  # a new question: told again
    run(hm._tell_blocked())
    assert [p["id"] for p in pushed] == ["41:blocks:sch_1", "42:blocks:sch_1"]


def test_no_question_or_a_run_of_ours_tells_nothing(blocked):
    pending, pushed, _ = blocked
    hm._active.add("chat-a")  # Brain_Hands' own run: its questions reach it as events already
    run(hm._tell_blocked())
    hm._active.clear(); pending.clear()
    run(hm._tell_blocked())
    assert pushed == []


# --- contract [26]: every task has its own id, kept in storage; state, stalled, cancel
def test_each_task_has_its_own_id_and_a_chat_may_hold_several(env, monkeypatch):
    monkeypatch.setattr(hm.status, "task_status", AsyncMock(return_value={"stage": "running"}))  # the chat's own progress
    async def scenario():
        a = await hm.start_run("first", CTX, chat_id="chat-a")
        b = await hm.start_run("second", CTX, chat_id="chat-a")  # same chat: queued behind, told apart by id
        return a, b, await hm.task_status(key=a["id"]), await hm.task_status(key=b["id"]), await hm.list_tasks(active=True)

    a, b, sa, sb, listed = run(scenario())
    assert a["id"] != b["id"] and a["key"] == a["id"] and b["queued"]
    assert (sb["state"], sb["position"], sb["chat_id"]) == ("queued", 1, "chat-a")
    assert {t["id"]: t["state"] for t in listed["tasks"]} == {a["id"]: "running", b["id"]: "queued"}


def test_a_task_waits_on_a_question_ends_with_its_result_and_reads_stalled_when_quiet(env, monkeypatch):
    monkeypatch.setattr(hm.status, "task_status", AsyncMock(return_value={"stage": "running"}))  # the chat's own progress
    monkeypatch.setattr(hm.leads, "tally", AsyncMock(return_value={"passed": 0, "seen": 0, "failed": {}}))
    monkeypatch.setattr(hm, "credits_spent", AsyncMock(return_value=0))
    monkeypatch.setattr(hm, "get_chat_title", AsyncMock(return_value=""))

    async def scenario():
        started = await hm.start_run("find buyers", CTX, chat_id="chat-a")
        t = object.__new__(REAL_THREAD)
        t.chat_id, t.queue, t.inbox, t.ask_text, t.plan = "chat-a", asyncio.Queue(), asyncio.Queue(), "", []
        t.agenda_id, t.lead_target, t.rounds, t.seen, t.started_at, t.polling, t.last_poll = "", 0, 0, 0, "2000-01-01T00:00:00+00:00", 0, 0.0
        t.key, t.request, t.stop_reason, t.asked_at, t.last_event = started["key"], "", "", None, time.monotonic()
        t.pending, t.ready, t.notes, t.say, t.task, t.task_id = False, False, {}, AsyncMock(), SimpleNamespace(done=lambda: False), started["id"]
        monkeypatch.setattr(t, "_announce", AsyncMock())
        monkeypatch.setattr(t, "_safe_result", AsyncMock(return_value={"status": "complete", "summary": "done"}))
        hm._threads[started["key"]] = t
        card = {"type": "input_request", "data": {"content": {"agent": "get_user_acceptance", "prompt": "Approve the plan?"}}}
        await t.send_json(card)
        waiting = await hm.task_status(key=started["id"])
        await hm.save_task({"id": started["id"], "state": "running", "last_progress_at": "2026-11-20T10:04:08+00:00"})
        stalled = await hm.task_status(key=started["id"])
        await t.send_json({"type": "completion", "status": "complete"})
        await asyncio.gather(*hm._watching)
        return waiting, stalled, await hm.task_status(key=started["id"])

    waiting, stalled, done = run(scenario())
    assert waiting["state"] == "waiting" and waiting["waiting_on"]["who"] == "user"
    assert stalled["state"] == "stalled"  # running, no progress for more than STALL_MIN
    assert done["state"] == "done" and done["result"] == {"status": "complete", "summary": "done"} and done["waiting_on"] is None


def test_cancel_frees_a_queued_task_and_stops_a_running_one(env, monkeypatch):
    stopped = AsyncMock()
    manager = SimpleNamespace(running_chats=lambda: [], is_running=lambda c: False, stop_session=stopped)
    monkeypatch.setattr(hm, "get_websocket_manager", AsyncMock(return_value=manager))

    async def scenario():
        a = await hm.start_run("first", CTX, chat_id="chat-a")
        b = await hm.start_run("second", CTX, chat_id="chat-a")
        return await hm.cancel(b["id"]), await list_queued_runs(), await hm.cancel(a["id"])

    queued, left, running = run(scenario())
    assert queued["state"] == "cancelled" and left == []
    assert running["state"] == "cancelled" and stopped.await_args.args[0] == "chat-a"


def test_a_task_is_still_known_after_a_restart(env, monkeypatch):
    monkeypatch.setattr(hm.status, "task_status", AsyncMock(return_value={"stage": "running"}))  # the chat's own progress
    async def scenario():
        a = await hm.start_run("first", CTX, chat_id="chat-a")
        hm._threads.clear(); hm._active.clear()  # the process restarted: nothing in memory
        return a, await hm.task_status(key=a["id"]), await hm.list_tasks(active=True)

    a, status_after, listed = run(scenario())
    assert status_after["id"] == a["id"] and status_after["parent_id"] == a["key"] and [t["id"] for t in listed["tasks"]] == [a["id"]]
