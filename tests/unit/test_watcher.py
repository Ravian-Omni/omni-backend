"""The reply watcher: runs only when switched on and in working time; records the routine routes, hands off the rest."""

import asyncio
import json
from datetime import datetime, timedelta

import pytest

from src.agent_runtime import inbox, prefs, watcher
from src.agent_runtime.prefs import InboxRules
from src.agent_runtime.tools import campaign
from src.database import connection, save_artifact

ON = {**InboxRules().model_dump(), "watch": True}
REAL_FETCH, REAL_RECORD_REPLY = campaign.fetch_replies, campaign.record_reply
MONDAY_10 = datetime(2026, 10, 5, 10, 0).astimezone()


def test_due_only_when_on_in_working_time_and_after_the_interval():
    assert not watcher.due({**ON, "watch": False}, MONDAY_10, None)
    assert watcher.due(ON, MONDAY_10, None)
    assert not watcher.due(ON, MONDAY_10.replace(hour=21), None)
    assert not watcher.due(ON, MONDAY_10 - timedelta(days=1), None)  # Sunday
    assert watcher.due({**ON, "weekends": True}, MONDAY_10 - timedelta(days=1), None)
    assert not watcher.due(ON, MONDAY_10, MONDAY_10 - timedelta(minutes=2))
    assert watcher.due(ON, MONDAY_10, MONDAY_10 - timedelta(minutes=6))


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(connection.settings, "ROOT_DIR", str(tmp_path))
    monkeypatch.setattr(connection, "_db", None)
    asyncio.run(connection.init_db())
    path = tmp_path / "send_log-plan0001.json"
    path.write_text(json.dumps({"rows": [{"plan_id": "campaign_plan-plan0001", "to": "a@x.com", "status": "sent"}]}))
    asyncio.run(save_artifact({"id": "send_log-plan0001", "chat_id": "chat-1", "task_id": None, "persona": "outreach", "kind": "send_log",
                               "title": "log", "path": str(path), "row_count": 1, "source": "", "created_at": "2026-10-01T00:00:00"}))
    recorded, handed = [], []

    async def fetch(ctx, plan_id):
        return {"threads_checked": 2, "decided_by": "jev", "errors": [], "bounces": [], "replies": [
            {"to": "a@x.com", "thread_id": "t1", "message_id": "m1", "text": "Please remove me", "route": "suppress", "read": {"intent": "unsubscribe"}},
            {"to": "b@x.com", "thread_id": "t2", "message_id": "m2", "text": "What does it cost?", "route": "answer", "read": {"intent": "question"}},
        ]}

    async def record_reply(ctx, plan_id, to, intent, route="", summary="", message_id="", **_):
        recorded.append((to, intent, route, message_id))

    async def open_handoff(ctx, **kw):
        handed.append(kw)
        return {"id": "handoff-1", "contact": kw["contact"], "owner": "", "notified": []}

    async def draft(*a):
        return "Plans start at..."

    monkeypatch.setattr(campaign, "fetch_replies", fetch)
    monkeypatch.setattr(campaign, "record_reply", record_reply)
    monkeypatch.setattr(inbox, "open_handoff", open_handoff)
    monkeypatch.setattr(watcher, "_draft", draft)
    yield recorded, handed
    asyncio.run(connection.close_db())


def test_routine_routes_are_recorded_and_the_rest_handed_off(world):
    recorded, handed = world
    summary = asyncio.run(watcher.sweep("u"))
    assert recorded == [("a@x.com", "unsubscribe", "suppress", "m1"), ("b@x.com", "question", "answer", "m2")]
    assert [(h["contact"], h["route"], h["draft"]) for h in handed] == [("b@x.com", "answer", "Plans start at...")]
    assert summary["replies"] == 2 and summary["routes"] == {"suppress": 1, "answer": 1} and len(summary["handoffs"]) == 1


def test_dry_run_records_nothing(world, monkeypatch):
    recorded, handed = world
    asyncio.run(prefs.put("u", "inbox", {"dry_run": True}))
    summary = asyncio.run(watcher.sweep("u"))
    assert summary["dry_run"] and summary["routes"] == {"suppress": 1, "answer": 1} and recorded == [] and handed == []


def test_a_bounce_holds_the_address_and_hands_the_notice_to_a_person(world, tmp_path, monkeypatch):
    from src.agent_runtime.tools import sales

    recorded, handed = world
    monkeypatch.setattr(campaign, "fetch_replies", REAL_FETCH)
    monkeypatch.setattr(campaign, "record_reply", REAL_RECORD_REPLY)
    log = tmp_path / "send_log-plan0001.json"
    log.write_text(json.dumps({"rows": [{"plan_id": "campaign_plan-plan0001", "to": to, "status": "sent", "step": 1, "thread_id": t}
                                        for to, t in (("a@x.com", "t1"), ("b@x.com", "t2"))]}))
    ours = {"messageId": "s1", "sender": "Me <me@co.com>", "subject": "Quick idea"}
    delay = {"messageId": "d0", "sender": "Mail Delivery Subsystem <mailer-daemon@googlemail.com>",
             "subject": "Delivery Status Notification (Delay)", "messageText": "Delivery to b@x.com has been delayed."}
    failed = {"messageId": "d1", "sender": "Mail Delivery Subsystem <mailer-daemon@googlemail.com>",
              "subject": "Delivery Status Notification (Failure)", "messageText": "Address not found: a@x.com"}

    async def gmail_call(user_id, slug, arguments):
        return {"successful": True, "data": {"messages": [ours, failed] if arguments["thread_id"] == "t1" else [ours, delay]}}

    monkeypatch.setattr(sales, "gmail_call", gmail_call)
    summary = asyncio.run(watcher.sweep("u"))
    assert summary["bounces"] == 1 and summary["replies"] == 0  # a delay notice is not a bounce
    assert [(h["contact"], h["route"], h["subject"], h["reply"]) for h in handed] == [
        ("mailer-daemon@googlemail.com", "bounce", "Delivery Status Notification (Failure)", "Address not found: a@x.com")]
    rows = json.loads(log.read_text())["rows"]
    assert [(r["to"], r["status"]) for r in rows if r["status"] == "bounced"] == [("a@x.com", "bounced")]
    watcher.state["running"] = False
    assert asyncio.run(watcher.sweep("u"))["bounces"] == 0 and len(handed) == 1  # held: not checked or handed off again


def test_a_check_brain_hands_asked_for_hands_over_the_facts_and_drafts_nothing(world, monkeypatch):
    from unittest.mock import AsyncMock

    from src.routers import hands_mcp as hm

    recorded, handed = world
    REAL_FETCHED = campaign.fetch_replies

    async def fetch(ctx, plan_id):
        found = await REAL_FETCHED(ctx, plan_id)
        found["replies"].append({"to": "c@x.com", "thread_id": "t3", "message_id": "m3", "text": "Can we talk Tuesday?",
                                 "route": "propose_meeting", "read": {"intent": "meeting"}})
        return found

    drafted = AsyncMock(return_value="drafted")
    monkeypatch.setattr(campaign, "fetch_replies", fetch)
    monkeypatch.setattr(watcher, "_draft", drafted)
    monkeypatch.setattr(inbox, "free_slots", AsyncMock(return_value=["Tue 10:00", "Tue 14:00"]))
    monkeypatch.setattr(hm, "USER_ID", "u")
    asyncio.run(hm.sweep())
    assert [(h["contact"], h["route"], h["draft"], h["read"]) for h in handed] == [
        ("b@x.com", "answer", "", {"intent": "question"}),
        ("c@x.com", "propose_meeting", "", {"intent": "meeting", "free_times": ["Tue 10:00", "Tue 14:00"]})]
    drafted.assert_not_called()  # no model writes a word; the watcher's own sweep still drafts (the test above)
