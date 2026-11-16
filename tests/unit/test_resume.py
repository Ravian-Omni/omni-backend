"""A run survives a closed tab, and a run the process left unfinished resumes at the next start: an approved plan from its
unfinished step, anything earlier from its request, with the old question closed and the step asking again."""

import asyncio
import json
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.database import (answer_decision, connection, count_resume, get_chat_repository, list_marked_runs, list_open_decisions,
                          log_decision, mark_run, save_pref)
from src.managers.connection import WebSocketManager
from src.routers import hands_mcp as hm
from tests.unit.test_brain_hands_push import server
from tests.unit.test_leads import temp_db  # noqa: F401 - the temp_db fixture

CARD = {"card": "confirm_spend", "title": "Spend?", "message": "Spend 4 credits?", "credits": 4, "count": 4}


def ws():
    return SimpleNamespace(accept=AsyncMock(), send_json=AsyncMock())


# --- a page leaving does not stop a run
def test_the_last_page_leaving_does_not_stop_a_run_and_its_question_waits_for_the_next_page():
    manager = WebSocketManager()

    async def scenario():
        page = ws()
        await manager.connect(page, "c1")
        manager._active_tasks["c1"] = asyncio.create_task(asyncio.sleep(30))  # the run
        card = {"input_type": "decision_card", "prompt": "Spend?", "data": {"source": "enricher", "content": {**CARD, "id": 7}}}
        asking = asyncio.create_task(manager.request_input("c1", card))
        await asyncio.sleep(0.1)
        await manager.disconnect("c1", page)  # the tab is closed
        survived = (not manager._closed_connections, not manager._stop_flags["c1"], "c1" not in manager._connections, not manager._active_tasks["c1"].done())
        back = ws()
        await manager.connect(back, "c1")  # a page comes back
        await manager.resend_pending("c1", back)
        shown = back.send_json.await_args.args[0]["request_id"]
        await manager.handle_input_response("c1", "yes", "7")
        answer = await asyncio.wait_for(asking, 3)  # answered at once: the queue the question waits on was kept
        manager._active_tasks["c1"].cancel()
        return survived, shown, answer

    assert asyncio.run(scenario()) == ((True, True, True, True), "7", "yes")


def test_a_page_leaving_an_idle_session_closes_it_as_before():
    manager = WebSocketManager()

    async def scenario():
        page = ws()
        await manager.connect(page, "c2")
        await manager.disconnect("c2", page)

    asyncio.run(scenario())
    assert "c2" in manager._closed_connections and "c2" not in manager._connections


# --- which runs are marked
def omni(a_initiate):
    return MagicMock(refresh_user_context=AsyncMock(), manager=SimpleNamespace(a_initiate_chat=a_initiate))


def stream(a_initiate):
    manager = WebSocketManager()

    async def scenario():
        await manager.connect(ws(), "c1")
        try:
            await manager.start_chat_stream("c1", {"type": "start", "task": "find buyers", "files": ["a.csv"]}, omni(a_initiate))
        except BaseException:
            pass
        return await list_marked_runs()

    return asyncio.run(scenario())


def test_a_run_is_marked_while_it_goes_and_unmarked_when_it_ends_or_fails(temp_db):
    assert stream(AsyncMock()) == []  # finished
    assert stream(AsyncMock(side_effect=RuntimeError("boom"))) == []  # failed: not resumed


def test_a_run_cut_short_by_the_process_stays_marked_and_a_stop_unmarks_it(temp_db):
    left = stream(AsyncMock(side_effect=asyncio.CancelledError))  # shutdown cancels the task: nothing stopped it on purpose
    assert [(r["chat_id"], r["task"], r["files"]) for r in left] == [("c1", "find buyers", ["a.csv"])]

    async def stopped():
        await WebSocketManager().stop_session("c1", "User requested stop/cancellation")
        return await list_marked_runs()

    assert asyncio.run(stopped()) == []


# --- the resume at startup
async def chat(chat_id, messages):
    await (await get_chat_repository()).create_chat({"user_id": hm.USER_ID, "chat_id": chat_id, "messages": messages}, "omni")


PLAN = {"name": "planner_agent", "content": json.dumps({"overall_status": "in_progress", "breakdown": []})}
APPROVED = [{"name": "chat_manager", "content": "x"}, PLAN, {"name": "get_user_acceptance", "content": "yes"}]
UNAPPROVED = [{"name": "chat_manager", "content": "x"}, PLAN]


@pytest.fixture
def started(temp_db, monkeypatch):
    """start_run's thread machinery with recording threads; what each run was told to do is read from them."""
    class Thread:
        def __init__(self, key, chat_id):
            self.chat_id, self.queue, self.inbox = chat_id, asyncio.Queue(), asyncio.Queue()
            self.task, self.ask_text, self.plan = SimpleNamespace(done=lambda: False), "", []

    monkeypatch.setattr(hm, "_threads", {})
    monkeypatch.setattr(hm, "_active", set())
    monkeypatch.setattr(hm, "_watching", set())
    monkeypatch.setattr(hm, "_lock", asyncio.Lock())
    monkeypatch.setattr(hm, "HandsThread", Thread)
    monkeypatch.setattr(hm, "get_websocket_manager", AsyncMock(return_value=SimpleNamespace(running_chats=lambda: [])))

    def told():
        return {t.chat_id: [json.loads(m) for m in t.inbox._queue] for t in {id(t): t for t in hm._threads.values()}.values()}

    return told


def test_a_cut_short_run_resumes_and_its_old_question_closes_quietly(started, monkeypatch):
    pushed = server(monkeypatch, 200)

    async def scenario():
        await chat("approved", APPROVED)
        await chat("unapproved", UNAPPROVED)
        await chat("mine-elsewhere", APPROVED)
        await chat("worn-out", APPROVED)
        for c in ("approved", "unapproved", "mine-elsewhere", "worn-out"):
            await mark_run(c, f"request of {c}", ["a.csv"] if c == "unapproved" else [])
        db = await connection.get_db()
        await db.execute("UPDATE active_runs SET owner_pid = ? WHERE chat_id = 'mine-elsewhere'", (os.getppid(),))  # alive: another backend's
        await db.commit()
        for _ in range(hm.MAX_RESUMES):
            await count_resume("worn-out")
        await save_pref(hm.USER_ID, "run_params:approved", {"key": "bh-key", "lead_target": 5})
        old = {c: await log_decision(c, None, "contact_enricher", "confirm_spend", CARD) for c in ("approved", "worn-out")}  # open questions
        await save_pref(hm.USER_ID, "agenda:approved", "agd_1")
        await save_pref(hm.USER_ID, "agenda:worn-out", "agd_2")
        await hm.recover()
        await asyncio.gather(*hm._watching)
        open_after = [d["chat_id"] for d in await list_open_decisions()]
        db = await connection.get_db()
        closed = dict(await (await db.execute("SELECT chat_id, response FROM decision_log WHERE answered_at IS NOT NULL")).fetchall())
        return old, open_after, closed, await list_marked_runs()

    old, open_after, closed, marked = asyncio.run(scenario())
    assert hm._threads["bh-key"].chat_id == "approved"  # back under the key its caller knows
    assert started() == {"approved": [{"type": "start", "task": "continue", "files": []}],  # Omni goes on from the unfinished step
                         "unapproved": [{"type": "start", "task": "request of unapproved", "files": ["a.csv"]}]}  # never approved: from the request
    assert hm._threads["bh-key"].lead_target == 5  # the lead target came back with it
    assert sorted(m["chat_id"] for m in marked) == ["approved", "mine-elsewhere", "unapproved"]  # the worn-out one was given up on
    assert json.loads(closed["approved"]) == {"closed": "resumed"} and json.loads(closed["worn-out"]) == {"closed": "run_lost"}
    assert open_after == []
    assert len(pushed) == 1 and json.loads(pushed[0].read())["data"]["reason"] == "run_lost"  # only the lost one is reported: the other asks again
    assert {r["chat_id"]: r["resumes"] for r in marked}["approved"] == 1


def test_an_answer_to_the_old_question_of_a_resumed_run_is_refused(started):
    async def scenario():
        await chat("approved", APPROVED)
        old = await log_decision("approved", None, "contact_enricher", "confirm_spend", CARD)
        monkey = hm.get_websocket_manager
        hm.get_websocket_manager = AsyncMock(return_value=WebSocketManager())
        try:
            return await hm.answer("approved", "yes", request_id=str(old))
        finally:
            hm.get_websocket_manager = monkey

    assert asyncio.run(scenario())["reason"] == "not_open"


def test_a_queued_run_waits_for_the_resumed_run_on_its_chat(started):
    async def scenario():
        await chat("approved", APPROVED)
        await mark_run("approved", "the request", [])
        await hm.enqueue_run({"key": "k2", "chat_id": "approved", "task": "next", "files": [], "lead_target": 0, "credit_budget": None})
        await hm.recover()
        return started(), [q["task"] for q in await hm.list_queued_runs()]

    told, queued = asyncio.run(scenario())
    assert [m["task"] for m in told["approved"]] == ["continue"] and queued == ["next"]  # still waiting behind it
