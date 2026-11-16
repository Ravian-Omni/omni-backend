"""Contract [8], "Queue never sticks": every way a run ends frees its chat and lets the next queued run start, and nothing
between a run's end and that can hang or raise it away."""

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.database import enqueue_run, list_queued_runs
from src.routers import hands_mcp as hm
from tests.unit.test_leads import temp_db, thread  # noqa: F401 - the temp_db fixture


@pytest.fixture
def ended(monkeypatch):
    """The chats _run_ended was called for; and a run with no lead target, a task status and no learnings."""
    out = []
    monkeypatch.setattr(hm, "_run_ended", out.append)
    monkeypatch.setattr(hm.needs, "credits_approved", AsyncMock(return_value=0))
    monkeypatch.setattr(hm.leads, "tally", AsyncMock(return_value={"passed": 0, "seen": 0, "failed": {}}))
    monkeypatch.setattr(hm, "get_chat_title", AsyncMock(return_value=""))
    return out


def deliver(t, *events):
    async def go():
        for e in events:
            await t.send_json(e)
    asyncio.run(go())
    return [t.queue.get_nowait() for _ in range(t.queue.qsize())]


def test_a_failed_run_frees_its_chat(ended, monkeypatch):
    monkeypatch.setattr(hm.status, "task_status", AsyncMock(side_effect=ValueError("no task")))
    out = deliver(thread(target=0), {"type": "error", "error_code": hm.FAILED_RUN, "message": "boom"})
    assert out[0]["result"]["status"] == "failed" and ended == ["chat-1"]


def test_a_result_that_raises_still_delivers_the_end_and_frees_the_chat(ended, monkeypatch):
    t = thread(target=0)
    monkeypatch.setattr(t, "_result", AsyncMock(side_effect=RuntimeError("learnings exploded")), raising=False)
    out = deliver(t, {"type": "completion", "status": "complete"})
    assert out[0]["type"] == "completion" and out[0]["result"]["status"] == "completed" and ended == ["chat-1"]


def test_a_result_that_hangs_still_delivers_the_end_within_the_limit(ended, monkeypatch):
    monkeypatch.setattr(hm, "RESULT_S", 0.05)
    t = thread(target=0)

    async def forever(_end):
        await asyncio.sleep(3600)

    monkeypatch.setattr(t, "_result", forever, raising=False)
    started = time.monotonic()
    out = deliver(t, {"type": "completion", "status": "complete"})
    assert time.monotonic() - started < 2 and out[0]["result"]["type"] == "result" and ended == ["chat-1"]


def test_extras_that_raise_before_the_result_still_let_the_end_out(ended, monkeypatch):
    monkeypatch.setattr(hm.leads, "tally", AsyncMock(side_effect=RuntimeError("db gone")))
    out = deliver(thread(target=0), {"type": "completion", "status": "complete"})
    assert out[0]["type"] == "completion" and ended == ["chat-1"]


def manager(running=(), pending=None):
    return SimpleNamespace(is_running=lambda c: c in running, running_chats=lambda: list(running),
                           pending_request=lambda c: pending, stop_session=AsyncMock())


def test_a_run_that_ends_without_a_word_is_freed_and_reported_lost(monkeypatch):
    t = thread(target=0)
    t.key, t.request, t.last_event = "run-9", "find buyers", time.monotonic() - hm.QUIET_S - 1
    monkeypatch.setattr(hm, "_threads", {"run-9": t})
    monkeypatch.setattr(hm, "_active", {"chat-1"})
    monkeypatch.setattr(hm, "get_websocket_manager", AsyncMock(return_value=manager()))
    assert asyncio.run(hm._busy()) == set()
    lost = t.queue.get_nowait()
    assert (lost["type"], lost["status"], lost["result"]["status"], lost["result"]["retryable"]) == ("completion", "lost", "stopped", True)
    assert lost["result"]["reason"] == "the run ended without finishing" and lost["result"]["in_reply_to"] == "run-9"


def test_a_run_that_is_starting_or_waiting_on_an_answer_is_not_freed(monkeypatch):
    t = thread(target=0)
    t.last_event = time.monotonic()  # just begun: the manager has not picked it up yet
    monkeypatch.setattr(hm, "_threads", {"k": t})
    monkeypatch.setattr(hm, "_active", {"chat-1"})
    monkeypatch.setattr(hm, "get_websocket_manager", AsyncMock(return_value=manager()))
    assert asyncio.run(hm._busy()) == {"chat-1"}
    t.last_event = 0.0  # quiet for long, but the manager runs it (it waits on a question)
    monkeypatch.setattr(hm, "get_websocket_manager", AsyncMock(return_value=manager(running=["chat-1"])))
    assert asyncio.run(hm._busy()) == {"chat-1"} and t.queue.empty()


def test_a_queued_run_starts_without_another_run_ending(monkeypatch):
    dispatched = AsyncMock()
    monkeypatch.setattr(hm, "_dispatch", dispatched)
    monkeypatch.setattr(hm, "queued_run", AsyncMock(return_value={"chat_id": "chat-2", "position": 1}))
    monkeypatch.setattr(hm, "_threads", {})
    asyncio.run(hm.next_event("k2", timeout=1))  # polling a queued key moves the queue
    assert dispatched.await_count == 1

    monkeypatch.setattr(hm, "TEND_S", 0.01)
    monkeypatch.setattr(hm, "_expire_questions", AsyncMock())

    async def tend_a_little():
        task = asyncio.create_task(hm._tend())
        await asyncio.sleep(0.1)
        task.cancel()

    asyncio.run(tend_a_little())  # and so does the timer, with nobody polling
    assert dispatched.await_count > 2


def test_an_unanswered_question_stops_the_run_after_the_limit_and_pushes_no_answer(monkeypatch):
    t = thread(target=0)
    t.key, t.asked_at = "run-5", time.monotonic() - hm.QUESTION_WAIT_S - 1
    card = {"card": "confirm_spend", "id": 12, "title": "Spend 4 credits?", "message": "Enrich 4 contacts"}
    m = manager(running=["chat-1"], pending={"request_id": "12", "data": {"content": card}})
    monkeypatch.setattr(hm, "_threads", {"run-5": t})
    monkeypatch.setattr(hm, "_active", {"chat-1"})
    monkeypatch.setattr(hm, "get_websocket_manager", AsyncMock(return_value=m))
    closed, pushed = AsyncMock(), AsyncMock()
    monkeypatch.setattr(hm, "answer_decision", closed)
    monkeypatch.setattr(hm.needs, "build", AsyncMock(return_value={"id": "12", "kind": "dax.need", "title": "t", "text": "x", "data": {}}))
    monkeypatch.setattr(hm.needs, "push", pushed)
    asyncio.run(hm._expire_questions())
    closed.assert_awaited_once_with(12, {"closed": "no_answer"})
    assert pushed.await_args.args[0]["id"] == "12:no_answer" and pushed.await_args.kwargs == {"reason": "no_answer"}
    m.stop_session.assert_awaited_once_with("chat-1", "no answer to: Spend 4 credits?")
    # the stop's own completion then ends the run with that reason
    monkeypatch.setattr(hm, "_run_ended", lambda chat: None)
    monkeypatch.setattr(hm.status, "task_status", AsyncMock(side_effect=ValueError("no task")))
    monkeypatch.setattr(hm.needs, "credits_approved", AsyncMock(return_value=0))
    monkeypatch.setattr(hm.leads, "tally", AsyncMock(return_value={"passed": 0, "seen": 0, "failed": {}}))
    monkeypatch.setattr(hm, "get_chat_title", AsyncMock(return_value=""))
    (done,) = deliver(t, {"type": "completion", "status": "cancelled"})
    assert (done["result"]["status"], done["result"]["reason"]) == ("stopped", "no answer to: Spend 4 credits?")


def test_a_question_inside_the_limit_or_a_web_app_run_is_left_waiting(monkeypatch):
    t = thread(target=0)
    t.asked_at = time.monotonic()
    m = manager(running=["chat-1"], pending={"request_id": "12", "data": {"content": {"card": "text", "message": "?"}}})
    monkeypatch.setattr(hm, "_threads", {"k": t})
    monkeypatch.setattr(hm, "_active", {"chat-1"})
    monkeypatch.setattr(hm, "get_websocket_manager", AsyncMock(return_value=m))
    asyncio.run(hm._expire_questions())
    monkeypatch.setattr(hm, "_threads", {})  # a run started in the web app has no thread here
    t.asked_at = 0.0
    asyncio.run(hm._expire_questions())
    m.stop_session.assert_not_awaited()


def test_a_new_run_waits_behind_its_chats_queued_runs(temp_db, monkeypatch):
    begun = AsyncMock()
    monkeypatch.setattr(hm, "_begin", begun)
    monkeypatch.setattr(hm, "_threads", {})
    monkeypatch.setattr(hm, "_active", set())
    monkeypatch.setattr(hm, "_lock", asyncio.Lock())
    monkeypatch.setattr(hm, "get_websocket_manager", AsyncMock(return_value=manager()))
    run = lambda task: {"key": task, "chat_id": "chat-a", "task": task, "files": [], "lead_target": 0, "credit_budget": None}  # noqa: E731

    async def scenario():
        await enqueue_run(run("first"))  # queued earlier, the chat now free
        place = await hm._admit(run("second"))
        return place, [r["task"] for r in await list_queued_runs()]

    place, queued = asyncio.run(scenario())
    assert place == 2 and queued == ["first", "second"] and begun.await_count == 0


def test_a_queued_run_that_cannot_start_is_retried_then_dropped_and_reported_without_holding_up_the_rest(temp_db, monkeypatch):
    begun = []

    async def begin(run):
        if run["chat_id"] == "chat-bad":
            raise RuntimeError("chat was deleted")
        begun.append(run["key"])

    pushed = AsyncMock(return_value=True)
    monkeypatch.setattr(hm, "_begin", begin)
    monkeypatch.setattr(hm.brain_hands, "push", pushed)
    monkeypatch.setattr(hm.needs, "agenda_of", AsyncMock(return_value="agd_1"))
    monkeypatch.setattr(hm, "_threads", {})
    monkeypatch.setattr(hm, "_active", set())
    monkeypatch.setattr(hm, "_begin_failures", {})
    monkeypatch.setattr(hm, "_dropped", {})
    monkeypatch.setattr(hm, "_lock", asyncio.Lock())
    monkeypatch.setattr(hm, "get_websocket_manager", AsyncMock(return_value=manager()))
    run = lambda key, chat: {"key": key, "chat_id": chat, "task": f"task {key}", "files": [], "lead_target": 0, "credit_budget": None}  # noqa: E731

    async def scenario():
        for key, chat in (("k-bad", "chat-bad"), ("k-bad-2", "chat-bad"), ("k-ok", "chat-ok")):
            await enqueue_run(run(key, chat))
        for n in range(hm.BEGIN_TRIES):
            await hm._dispatch()
            queued = [r["key"] for r in await list_queued_runs()]
            if n < hm.BEGIN_TRIES - 1:
                assert queued == ["k-bad", "k-bad-2"]  # kept, in order, while it is retried; the run behind it on another chat started
        return [r["key"] for r in await list_queued_runs()], await hm.next_event("k-bad", timeout=1)

    queued, polled = asyncio.run(scenario())
    assert begun == ["k-ok"] and queued == ["k-bad-2"]  # dropped after its tries; the next on its chat now gets its turn
    (end,) = polled["events"]
    assert polled["closed"] and (end["type"], end["status"], end["result"]["status"]) == ("completion", "failed", "failed")
    assert end["result"]["reason"] == "the run could not start after 3 tries: chat was deleted" and not end["result"]["retryable"]
    assert pushed.await_args.args[:2] == ("dax.run_failed", "k-bad:not_started") and pushed.await_args.kwargs["retryable"] is False
