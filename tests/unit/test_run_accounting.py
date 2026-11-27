"""What Brain_Hands reads of a run: the credits it was charged (every completion carries them) and the
campaign plan a send card belongs to."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.agent_runtime.decisions import DecisionCards
from src.agent_runtime.tools import sales
from src.database import record_spend
from src.routers import hands_mcp as hm
from tests.unit.test_leads import tally, temp_db, thread  # noqa: F401 - the temp_db fixture

SINCE = "2026-11-16T10:00:00+00:00"


def test_a_completion_carries_the_credits_the_run_was_charged(temp_db, monkeypatch):
    monkeypatch.setattr(hm.leads, "tally", AsyncMock(return_value=tally(0, 0)))

    async def scenario():
        await record_spend("chat-1", "salesgenie_business_enrichment", 100)  # before this run began: not its credits
        t = thread()
        t.started_at = (await (_now())).isoformat()
        await record_spend("chat-1", "salesgenie_business_enrichment", 4)
        await record_spend("chat-1", "salesgenie_business_enrichment", 6)
        await record_spend("chat-2", "salesgenie_business_enrichment", 70)  # another chat
        await t.send_json({"type": "completion", "status": "complete"})
        return t.queue.get_nowait()

    assert asyncio.run(scenario())["credits_spent"] == 10


async def _now():
    from src.configs.datetime_utils import dt

    await asyncio.sleep(0.01)
    return dt.now()


def test_credits_add_up_across_the_sourcing_rounds_of_one_run(temp_db, monkeypatch):
    tallies = iter([tally(1, 8), tally(3, 14)])
    monkeypatch.setattr(hm.leads, "tally", AsyncMock(side_effect=lambda _chat, _since="": next(tallies)))
    monkeypatch.setattr(hm, "get_websocket_manager", AsyncMock(return_value=SimpleNamespace(add_note=lambda *_: None)))

    async def scenario():
        t = thread()
        t.started_at = (await _now()).isoformat()
        await record_spend("chat-1", "salesgenie_business_enrichment", 5)
        await t.send_json({"type": "completion", "status": "complete"})  # round one: swallowed, another round starts
        await record_spend("chat-1", "salesgenie_business_enrichment", 7)
        await t.send_json({"type": "completion", "status": "complete"})
        return t.queue.get_nowait()

    done = asyncio.run(scenario())
    assert done["credits_spent"] == 12 and done["leads"]["stopped_because"] == "target_met"


def sends(ask=None):
    cards = []

    class Cards:
        async def confirm_send(self, **kw):
            cards.append(kw)
            return SimpleNamespace(approved=True, suggestion="")

    ctx = SimpleNamespace(chat_id="chat-1", artifacts_dir="/nowhere", decisions=Cards(), send_allowance={}, send_approved=set(), user_id="u", remote_tool_classes={})
    return next(t for t in sales.build(ctx) if t.name == "request_send_approval").handler, cards


def test_a_send_card_for_a_campaign_plan_names_the_plan_and_the_step():
    ask, cards = sends()
    asyncio.run(ask({"channel": "email", "recipients": ["a@x.com"], "subject": "Hi", "body_preview": "Hello", "plan_id": "campaign_plan-p1", "step": 2}))
    asyncio.run(ask({"channel": "email", "recipients": ["b@x.com"], "subject": "One-off", "body_preview": "Hello"}))
    assert (cards[0]["plan_id"], cards[0]["step"]) == ("campaign_plan-p1", 2)
    assert cards[1]["plan_id"] == "" and cards[1]["step"] is None  # a one-off email has no plan


def test_the_plan_is_on_the_raw_card_the_caller_gets(temp_db):
    ws = SimpleNamespace(request_input=AsyncMock(return_value="no"))
    asyncio.run(DecisionCards(ws, "chat-1", "outreach").confirm_send(
        tool="gmail_send_email", server="composio", channel="email", recipients=["a@x.com"], plan_id="campaign_plan-p1", step=1))
    asyncio.run(DecisionCards(ws, "chat-1", "outreach").confirm_send(tool="gmail_send_email", server="composio", channel="email", recipients=["a@x.com"]))
    with_plan, without = (c.args[1]["data"]["content"] for c in ws.request_input.await_args_list)
    assert (with_plan["plan_id"], with_plan["step"]) == ("campaign_plan-p1", 1) and "plan_id" not in without
