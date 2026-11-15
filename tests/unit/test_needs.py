"""DAX needs Brain_Hands' input (signals contract [7]): a question carries its id, task, agenda and raw card, is answered
once by that id, is pushed when nobody polls for it, and is closed as run_lost when its process is gone."""

import asyncio
import json
import os
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src import database
from src.database import answer_decision, connection, get_chat_repository, list_open_decisions, log_decision, save_pref, set_chat_title
from src.managers.connection import WebSocketManager
from src.routers import hands_mcp as hm
from src.services import needs
from tests.unit.test_brain_hands_push import server

CARD = {"card": "confirm_send", "id": 42, "title": "Send 2 emails?", "message": "Send step 1 to 2 people?", "channel": "email",
        "recipients": ["a@x.com", "b@x.com"], "draft_only": False}


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(connection.settings, "ROOT_DIR", str(tmp_path))
    monkeypatch.setattr(connection, "_db", None)
    monkeypatch.setattr(database, "_chat_repository", None)
    asyncio.run(connection.init_db())
    yield
    asyncio.run(connection.close_db())


def thread(chat_id="chat-1", agenda_id="agd_1"):
    """A HandsThread without the omni WebSocket behind it."""
    t = object.__new__(hm.HandsThread)
    t.chat_id, t.queue, t.ask_text, t.plan = chat_id, asyncio.Queue(), "", []
    t.agenda_id, t.polling, t.last_poll = agenda_id, 0, time.monotonic()
    t.pending, t.ready, t.notes, t.say, t.task = False, False, {}, AsyncMock(), SimpleNamespace(done=lambda: False)
    return t


def question_event(request_id="42", card=CARD):
    return {"type": "input_request", "input_type": "decision_card", "request_id": request_id, "timestamp": "2026-11-15T22:00:00+05:30",
            "data": {"source": "outreach", "content": card}}


def fake_manager(monkeypatch, pending):
    async def manager():
        return SimpleNamespace(pending_request=lambda _chat: pending)

    monkeypatch.setattr(hm, "get_websocket_manager", manager)


def test_every_event_echoes_the_agenda_and_a_question_is_a_need(temp_db, monkeypatch):
    monkeypatch.setattr(needs, "UNATTENDED_S", 3600)

    async def scenario():
        await (await get_chat_repository()).create_chat({"user_id": hm.USER_ID, "chat_id": "chat-1"}, "omni")
        await set_chat_title("chat-1", "Dentists in Austin")
        await save_pref(hm.USER_ID, "agenda:chat-1", "agd_1")
        t = thread()
        await t.send_json(question_event())
        await t.send_json({"type": "completion", "status": "complete"})
        return t.queue.get_nowait(), t.queue.get_nowait()

    asked, done = asyncio.run(scenario())
    assert done["agenda_id"] == "agd_1"  # every event, not only questions
    assert (asked["request_id"], asked["task_id"], asked["task_title"], asked["agenda_id"]) == ("42", "chat-1", "Dentists in Austin", "agd_1")
    assert asked["card"] == CARD and asked["card_kind"] == "send_approval" and asked["answer_with"].startswith('"yes" to send')
    assert asked["options"] == [] and asked["asked_at"] == "2026-11-15T16:30:00+00:00"  # UTC


def test_start_run_stores_the_agenda_on_the_chat_and_a_continued_chat_keeps_it(temp_db, monkeypatch):
    seen = []

    class Thread:
        def __init__(self, key, chat_id):
            self.chat_id, self.queue, self.inbox = chat_id, asyncio.Queue(), asyncio.Queue()
            self.task, self.ask_text, self.plan = SimpleNamespace(done=lambda: False), "", []
            seen.append(self)

    async def repo():
        return SimpleNamespace(get_chat=AsyncMock(return_value={"chat_id": "old"}))

    async def manager():
        return SimpleNamespace(is_running=lambda _chat: False)

    monkeypatch.setattr(hm, "_threads", {})
    monkeypatch.setattr(hm, "HandsThread", Thread)
    monkeypatch.setattr(hm, "get_chat_repository", repo)
    monkeypatch.setattr(hm, "get_websocket_manager", manager)
    ctx = SimpleNamespace(session=SimpleNamespace(client_params=None))

    async def scenario():
        first = await hm.start_run("find buyers", ctx, key="k1", chat_id="old", agenda_id="agd_9")
        hm._threads.clear()
        again = await hm.start_run("follow up", ctx, key="k2", chat_id="old")  # no agenda given: the chat's own
        hm._threads.clear()
        plain = await hm.start_run("other", ctx, key="k3", chat_id="old", agenda_id="")
        return first, again, plain

    first, again, plain = asyncio.run(scenario())
    assert first["agenda_id"] == again["agenda_id"] == plain["agenda_id"] == "agd_9"
    assert [t.agenda_id for t in seen] == ["agd_9"] * 3


def test_a_stale_request_id_is_refused_and_an_answer_applies_once(monkeypatch):
    manager = WebSocketManager()

    async def scenario():
        await manager.connect(SimpleNamespace(accept=AsyncMock(), send_json=AsyncMock()), "c1")
        monkeypatch.setattr(hm, "get_websocket_manager", AsyncMock(return_value=manager))
        monkeypatch.setattr(hm, "get_chat_repository", AsyncMock(return_value=SimpleNamespace(get_chat=AsyncMock(return_value={"chat_id": "c1"}))))
        asking = asyncio.create_task(manager.request_input("c1", {"input_type": "decision_card", "prompt": "Send?", "data": {"source": "outreach", "content": CARD}}))
        await asyncio.sleep(0.1)
        assert manager.pending_request("c1")["request_id"] == "42"
        stale = await hm.answer("c1", "yes", request_id="41")  # an old question's id
        assert stale["ok"] is False and stale["reason"] == "not_open" and not asking.done()  # nothing changed
        web = await manager.handle_input_response("c1", "no")  # the web app answers first
        late = await hm.answer("c1", "yes", request_id="42")  # then Brain_Hands, to the same question
        assert web is True and late == {"ok": False, "reason": "not_open", "note": late["note"]}
        return await asyncio.wait_for(asking, 10)

    assert asyncio.run(scenario()) == "no"  # the run got one answer, the first


def test_the_answer_carries_the_ids_and_request_id_stays_optional(monkeypatch):
    manager = WebSocketManager()

    async def scenario():
        await manager.connect(SimpleNamespace(accept=AsyncMock(), send_json=AsyncMock()), "c1")
        monkeypatch.setattr(hm, "get_websocket_manager", AsyncMock(return_value=manager))
        monkeypatch.setattr(hm, "get_chat_repository", AsyncMock(return_value=SimpleNamespace(get_chat=AsyncMock(return_value={"chat_id": "c1"}))))
        results = []
        for given in ("42", ""):  # with the id, then without (Brain_Hands' current caller)
            asking = asyncio.create_task(manager.request_input("c1", {"input_type": "decision_card", "prompt": "Send?", "data": {"source": "outreach", "content": CARD}}))
            await asyncio.sleep(0.1)
            results.append((await hm.answer("c1", "yes", request_id=given), await asyncio.wait_for(asking, 10)))
        return results

    (first, reply), (second, _) = asyncio.run(scenario())
    assert first == {"ok": True, "chat_id": "c1", "task_id": "c1", "request_id": "42"} and reply == "yes"
    assert second["ok"] is True


def test_a_plan_approval_gets_a_request_id_and_is_logged_until_answered(temp_db):
    manager = WebSocketManager()

    async def scenario():
        await manager.connect(SimpleNamespace(accept=AsyncMock(), send_json=AsyncMock()), "c1")
        ask = manager._create_input_func("c1")
        asking = asyncio.create_task(ask(json.dumps({"agent": "get_user_acceptance", "prompt": "Proceed?"}), source="user_input"))
        await asyncio.sleep(0.1)
        request_id = manager.pending_request("c1")["request_id"]
        open_before = [d["id"] for d in await list_open_decisions()]
        await manager.handle_input_response("c1", "yes", request_id)
        await asyncio.wait_for(asking, 10)
        return request_id, open_before, [d["id"] for d in await list_open_decisions()]

    request_id, before, after = asyncio.run(scenario())
    assert before == [int(request_id)] and after == []


def test_a_need_nobody_polls_for_is_pushed_once_with_the_raw_card(temp_db, monkeypatch):
    monkeypatch.setattr(needs, "UNATTENDED_S", 0.1)
    seen = server(monkeypatch, 200)
    fake_manager(monkeypatch, {"request_id": "42"})

    async def scenario():
        await save_pref(hm.USER_ID, "agenda:chat-1", "agd_1")
        t = thread()
        await t.send_json(question_event())
        await asyncio.sleep(0.6)
        return t.queue.get_nowait()

    asked = asyncio.run(scenario())
    assert len(seen) == 1
    body = json.loads(seen[0].read())
    assert (body["app"], body["kind"], body["id"], body["title"]) == ("daxagent", "dax.need", "42", "Send 2 emails?")
    assert body["data"]["card"] == asked["card"] == CARD  # the pushed card is the one next_event gives
    assert body["data"]["card_kind"] == "send_approval" and body["data"]["agenda_id"] == "agd_1" and body["data"]["task_id"] == "chat-1"


def test_a_need_that_is_polled_for_or_already_answered_is_not_pushed(temp_db, monkeypatch):
    monkeypatch.setattr(needs, "UNATTENDED_S", 0.1)
    seen = server(monkeypatch, 200, 200)

    async def scenario():
        t = thread()
        fake_manager(monkeypatch, {"request_id": "42"})
        t.polling = 1  # Brain_Hands is waiting in next_event
        await t.send_json(question_event())
        await asyncio.sleep(0.4)
        fake_manager(monkeypatch, {"request_id": "42", "answered": True})  # the web app answered; the next check ends it
        t.polling = 0
        t.last_poll = 0.0
        await t.send_json(question_event(request_id="43"))
        await asyncio.sleep(0.4)

    asyncio.run(scenario())
    assert seen == []


def test_open_needs_survive_in_the_log_and_a_lost_run_is_closed_and_pushed(temp_db, monkeypatch):
    seen = server(monkeypatch, 200)

    async def scenario():
        ids = {}
        for name, chat in (("lost", "chat-a"), ("quiet", "chat-b"), ("noagenda", "chat-c"), ("live", "chat-a"), ("answered", "chat-a")):
            ids[name] = await log_decision(chat, None, "outreach", "confirm_send", CARD)  # stamped with this process's pid
        db = await connection.get_db()
        await db.execute("UPDATE decision_log SET owner_pid = NULL WHERE id = ?", (ids["quiet"],))  # made before pids were recorded
        await db.execute("UPDATE decision_log SET owner_pid = ? WHERE id = ?", (os.getppid(), ids["live"]))  # another running process
        await db.commit()
        await answer_decision(ids["answered"], "yes")
        for chat in ("chat-a", "chat-b"):
            await save_pref(hm.USER_ID, f"agenda:{chat}", "agd_1")
        opened = [d["id"] for d in await list_open_decisions()]
        closed = await needs.close_lost()
        return ids, opened, closed, [d["id"] for d in await list_open_decisions()]

    ids, opened, closed, still_open = asyncio.run(scenario())
    assert opened == [ids["lost"], ids["quiet"], ids["noagenda"], ids["live"]]  # logged, not only in memory
    assert closed == 3 and still_open == [ids["live"]]  # the other process's question is left alone
    assert len(seen) == 1  # only the one with a pid and an agenda is pushed
    body = json.loads(seen[0].read())
    assert body["id"] == f"{ids['lost']}:run_lost" and body["data"]["reason"] == "run_lost" and body["data"]["task_id"] == "chat-a"
    assert body["data"]["card"] == CARD and body["data"]["request_id"] == str(ids["lost"])
