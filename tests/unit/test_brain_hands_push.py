"""A campaign reply is pushed to Brain_Hands as it becomes a handoff, with the route DAX stored, and nowhere without a URL."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from src.agent_runtime import inbox
from src.agent_runtime.tools import campaign
from src.database import connection, get_handoff
from src.services import brain_hands


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(connection.settings, "ROOT_DIR", str(tmp_path))
    monkeypatch.setattr(connection, "_db", None)
    asyncio.run(connection.init_db())
    yield
    asyncio.run(connection.close_db())


REAL_CLIENT = httpx.AsyncClient


def server(monkeypatch, *statuses):
    """Brain_Hands answering with these statuses in turn; returns the requests it got."""
    seen, answers = [], iter(statuses)

    def handler(request):
        seen.append(request)
        return httpx.Response(next(answers))

    monkeypatch.setattr(brain_hands.httpx, "AsyncClient", lambda **kw: REAL_CLIENT(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setattr(brain_hands, "RETRY_AFTER_S", (0, 0))
    monkeypatch.setenv("BRAIN_HANDS_URL", "http://hands.test/")
    monkeypatch.setenv("BRAIN_HANDS_TOKEN", "tok")
    return seen


def test_the_pushed_route_is_the_stored_one_for_every_route(temp_db, monkeypatch):
    seen = server(monkeypatch, *[200] * 7)
    monkeypatch.setattr(inbox, "notify", AsyncMock(return_value=[]))
    monkeypatch.setattr(inbox.prefs, "get", AsyncMock(return_value={}))
    ctx = SimpleNamespace(user_id="u", chat_id="c", emit=AsyncMock())

    async def scenario():
        for i, route in enumerate(("answer", "propose_meeting", "suppress", "snooze", "auto_reply", "bounce", "handoff")):
            h = await inbox.open_handoff(ctx, contact=f"p{i}@x.com", route=route, reply="hi", thread_id=f"t{i}")
            assert (await get_handoff(h["id"]))["route"] == route
            sent = seen[i].read().decode()
            assert f'"route":"{route}"' in sent.replace(" ", "") and f'"handoff_id":"{h["id"]}"' in sent.replace(" ", "")

    asyncio.run(scenario())
    assert len(seen) == 7


def test_the_reply_is_pushed_in_the_contract_shape(monkeypatch):
    seen = server(monkeypatch, 200)
    fields = dict(email="x@bigco.com", thread_id="t1", intent="meeting_request", route="propose_meeting", draft="How about Tuesday?",
                  campaign_id="plan-9", handoff_id="handoff-1")
    assert asyncio.run(brain_hands.push_reply("handoff-1", "Re: hello", "R" * 4000, **fields)) is True
    request = seen[0]
    assert str(request.url) == "http://hands.test/notifications" and request.headers["authorization"] == "Bearer tok"
    assert json.loads(request.read()) == {"app": "daxagent", "kind": "reply", "id": "handoff-1", "title": "Re: hello", "text": "R" * 3000,
                                          "data": fields}
    seen = server(monkeypatch, 200)
    asyncio.run(brain_hands.push_reply("handoff-2", "", "hi", email="x@bigco.com", draft="", campaign_id=""))
    assert json.loads(seen[0].read())["data"] == {"email": "x@bigco.com"}  # empty values are left out


def test_nothing_is_sent_without_a_url_and_only_a_5xx_is_retried(monkeypatch):
    monkeypatch.delenv("BRAIN_HANDS_URL", raising=False)
    assert asyncio.run(brain_hands.push_reply("h", "", "hi")) is False
    seen = server(monkeypatch, 503, 502, 200)
    assert asyncio.run(brain_hands.push_reply("h", "", "hi")) is True and len(seen) == 3
    seen = server(monkeypatch, 500, 500, 500, 200)
    assert asyncio.run(brain_hands.push_reply("h", "", "hi")) is False and len(seen) == 3  # gives up after three tries
    seen = server(monkeypatch, 400)
    assert asyncio.run(brain_hands.push_reply("h", "", "hi")) is False and len(seen) == 1  # a 4xx is never retried


def test_a_settled_reply_is_pushed_from_record_reply_without_a_handoff_id(monkeypatch):
    seen = server(monkeypatch, 200)
    monkeypatch.setattr(campaign, "record", AsyncMock())
    ctx = SimpleNamespace(user_id="u")

    async def scenario():
        row = await campaign.record_reply(ctx, "plan-1", "X@Big.com", "unsubscribe", "suppress", "", "msg-77",
                                          text="Please remove me", subject="Re: hello", thread_id="t1")
        await campaign.record_reply(ctx, "plan-1", "y@big.com", "interested", "answer", "", "msg-78")  # becomes a handoff: pushed there
        await campaign.record_reply(ctx, "plan-1", "z@big.com", "unsubscribe", "suppress", "", "")  # no message id: nothing to key on
        await asyncio.gather(*brain_hands._tasks)
        return row

    row = asyncio.run(scenario())
    assert row["status"] == "replied" and len(seen) == 1  # record_reply returned without waiting on the push
    assert json.loads(seen[0].read()) == {"app": "daxagent", "kind": "reply", "id": "reply:msg-77", "title": "Re: hello", "text": "Please remove me",
                                          "data": {"email": "x@big.com", "thread_id": "t1", "intent": "unsubscribe", "route": "suppress",
                                                   "campaign_id": "plan-1"}}


def test_a_push_that_fails_never_breaks_record_reply(monkeypatch):
    seen = server(monkeypatch, 500, 500, 500)
    monkeypatch.setattr(campaign, "record", AsyncMock())

    async def scenario():
        row = await campaign.record_reply(SimpleNamespace(user_id="u"), "plan-1", "x@big.com", "out_of_office", "auto_reply", "", "msg-1")
        await asyncio.gather(*brain_hands._tasks)
        return row

    assert asyncio.run(scenario())["status"] == "auto_reply" and len(seen) == 3
