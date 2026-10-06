"""Who answers a reply, when the owner can meet, and the handoff row that waits for them."""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from src.agent_runtime.inbox import owner_for, pick_slots
from src.database import connection, list_handoffs, save_handoff, update_handoff

TEAM = {"members": [{"name": "Sam", "email": "sam@acme.com"}, {"name": "Ana", "email": "ana@acme.com"}],
        "default_owner": "Sam", "account_owners": {"bigco.com": "Ana"}}


def test_owner_is_the_contact_owner_then_the_domain_owner_then_the_default():
    assert owner_for(TEAM, "x@bigco.com", "sam")["name"] == "Sam"
    assert owner_for(TEAM, "x@bigco.com")["name"] == "Ana"
    assert owner_for(TEAM, "x@other.com")["name"] == "Sam"
    assert owner_for({**TEAM, "default_owner": ""}, "x@other.com") is None  # the shared inbox


def test_slots_skip_busy_times_weekends_and_the_next_two_hours():
    tz = timezone.utc
    start = datetime(2026, 10, 2, 8, 0, tzinfo=tz)  # a Friday
    busy = [(datetime(2026, 10, 2, 9, 0, tzinfo=tz), datetime(2026, 10, 2, 11, 0, tzinfo=tz))]
    slots = pick_slots(busy, start, days=5)
    assert slots[0] == datetime(2026, 10, 2, 11, 0, tzinfo=tz)  # after the meeting, and 2h from now
    assert slots[1].weekday() == 0 and slots[1].hour == 9  # Monday, the weekend skipped
    assert len(slots) == 3 and len({s.date() for s in slots}) == 3  # one per day


def test_a_fully_busy_calendar_offers_nothing():
    start = datetime(2026, 10, 5, 8, 0, tzinfo=timezone.utc)
    assert pick_slots([(start, start + timedelta(days=10))], start) == []


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(connection.settings, "ROOT_DIR", str(tmp_path))
    monkeypatch.setattr(connection, "_db", None)
    asyncio.run(connection.init_db())
    yield
    asyncio.run(connection.close_db())


def test_a_new_reply_in_the_same_thread_reopens_its_handoff(temp_db):
    async def scenario():
        base = {"user_id": "u", "chat_id": "c", "contact": "x@bigco.com", "thread_id": "t1", "route": "answer"}
        first = await save_handoff({**base, "id": "handoff-1", "reply": "What does it cost?", "read": {"intent": "question"}})
        await update_handoff(first["id"], status="done")
        again = await save_handoff({**base, "id": "handoff-2", "reply": "Following up on my question"})
        return first, again, await list_handoffs("u", "active")

    first, again, active = asyncio.run(scenario())
    assert first["read"] == {"intent": "question"} and first["status"] == "open"
    assert again["id"] == "handoff-1" and again["status"] == "open" and again["reply"] == "Following up on my question"
    assert [h["id"] for h in active] == ["handoff-1"]
