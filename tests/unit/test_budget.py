"""A credit budget in place of approval cards: a spend that fits what the goal may still spend is approved by DAXAGENT and
logged, one above it raises a card as before, and the budget is kept per agenda (per chat without one)."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.agent_runtime import leads
from src.agent_runtime.decisions import DecisionCards
from src.database import budget_left, list_decisions, save_pref, set_budget, spend_budget
from src.routers import agents, hands_mcp as hm
from tests.unit.test_leads import run_completions, tally, temp_db  # noqa: F401 - the temp_db fixture


def cards(answer="no"):
    ws = SimpleNamespace(request_input=AsyncMock(return_value=answer))
    return DecisionCards(ws, "chat-a", "contact_enricher"), ws


def test_a_spend_inside_the_budget_is_approved_and_logged_with_no_card(temp_db):
    async def scenario():
        await set_budget("chat-a", 10)
        dc, ws = cards()
        decision = await dc.confirm_spend(tool="contact_enrichment", server="data-axle", count=4, credits=4)
        return decision, ws, await budget_left("chat-a"), await list_decisions("chat-a")

    decision, ws, left, log = asyncio.run(scenario())
    assert decision.approved and left == 6
    ws.request_input.assert_not_called()  # no card
    assert log[0]["response"] == {"action": "approve", "auto": "budget", "left": 6} and log[0]["answered_at"]


def test_a_spend_above_what_is_left_raises_a_card_and_leaves_the_budget_alone(temp_db):
    async def scenario():
        await set_budget("chat-a", 10)
        dc, ws = cards("no")
        first = await dc.confirm_spend(tool="contact_enrichment", server="data-axle", count=7, credits=7)  # fits: 3 left
        above = await dc.confirm_spend(tool="contact_enrichment", server="data-axle", count=4, credits=4)  # does not
        return first, above, ws, await budget_left("chat-a")

    first, above, ws, left = asyncio.run(scenario())
    assert first.approved and not above.approved and left == 3  # the declined card spent nothing
    assert ws.request_input.await_count == 1 and ws.request_input.await_args.args[1]["data"]["content"]["card"] == "confirm_spend"


def test_without_a_budget_every_spend_raises_a_card_as_before(temp_db):
    async def scenario():
        dc, ws = cards("yes")
        return await dc.confirm_spend(tool="contact_enrichment", server="data-axle", count=2), ws

    decision, ws = asyncio.run(scenario())
    assert decision.approved and ws.request_input.await_count == 1


def test_the_budget_belongs_to_the_agenda_and_to_the_chat_when_there_is_none(temp_db):
    async def scenario():
        for chat in ("chat-a", "chat-b"):
            await save_pref("u", f"agenda:{chat}", "agd_1")
        await set_budget("chat-a", 10)
        await spend_budget("chat-b", 4)  # another chat of the same goal draws on the same budget
        same = await budget_left("chat-a")
        await set_budget("chat-c", 5)  # no agenda: its own
        return same, await budget_left("chat-b"), await budget_left("chat-c"), await budget_left("chat-d")

    assert asyncio.run(scenario()) == (6, 6, 5, None)


def test_two_spends_cannot_both_fit_the_same_credits(temp_db):
    async def scenario():
        await set_budget("chat-a", 10)
        return await asyncio.gather(spend_budget("chat-a", 6), spend_budget("chat-a", 6)), await budget_left("chat-a")

    taken, left = asyncio.run(scenario())
    assert sorted(t is not None for t in taken) == [False, True] and left == 4


def test_start_run_sets_the_goals_budget_under_its_agenda(temp_db, monkeypatch):
    class Thread:
        def __init__(self, key, chat_id):
            self.chat_id, self.queue, self.inbox = chat_id, asyncio.Queue(), asyncio.Queue()
            self.task, self.ask_text, self.plan = SimpleNamespace(done=lambda: False), "", []

    monkeypatch.setattr(hm, "_threads", {})
    monkeypatch.setattr(hm, "HandsThread", Thread)
    monkeypatch.setattr(hm, "get_chat_repository", AsyncMock(return_value=SimpleNamespace(get_chat=AsyncMock(return_value={"chat_id": "old"}))))
    monkeypatch.setattr(hm, "get_websocket_manager", AsyncMock(return_value=SimpleNamespace(is_running=lambda _chat: False, running_chats=lambda: [])))
    ctx = SimpleNamespace(session=SimpleNamespace(client_params=None))

    async def scenario():
        await hm.start_run("find buyers", ctx, key="k1", chat_id="old", agenda_id="agd_1", credit_budget=120)
        first = await budget_left("old")
        hm._threads.clear()
        await hm.start_run("go on", ctx, key="k2", chat_id="old")  # no figure given: what is left stays
        return first, await budget_left("old")

    assert asyncio.run(scenario()) == (120, 120)


def test_a_lead_run_ends_as_budget_used_up_when_what_is_left_cannot_buy_a_credit(temp_db, monkeypatch):
    assert leads.stop_reason(3, tally(1, 9), 5, 0.5, 0) == "budget_used_up" and leads.stop_reason(3, tally(1, 9), 5, 1, 0) is None

    async def go():
        await set_budget("chat-1", 0)

    asyncio.run(go())
    t, notes, done = run_completions(monkeypatch, [tally(1, 9)])  # still short of the target, new contacts found, but no credits
    assert notes == [] and done[0]["leads"]["stopped_because"] == "budget_used_up"


def test_the_web_app_sets_and_reads_a_tasks_budget(temp_db):
    app = FastAPI()
    app.include_router(agents.router, prefix="/agents")
    client = TestClient(app)
    assert client.get("/agents/budget/chat-w").json() == {"chat_id": "chat-w", "credits_left": None}
    assert client.put("/agents/budget/chat-w", json={"credits": 40}).json()["credits_left"] == 40
    assert client.get("/agents/budget/chat-w").json()["credits_left"] == 40
    assert client.put("/agents/budget/chat-w", json={"credits": -1}).status_code == 422


def test_a_spend_approval_finds_a_tool_by_the_name_its_vendor_prefixed():
    """16 Nov 2026: the instructions say business_enrichment, the server lists salesgenie_business_enrichment, and a
    13-record batch was dropped as "Unknown tool"."""
    from src.agent_runtime.tools.context import ToolContext
    known = {"mcp__data-axle__salesgenie_business_enrichment": "spend", "mcp__data-axle__salesgenie_business_search": "read",
             "mcp__data-axle__salesgenie_consumer_enrichment": "spend"}
    find = lambda name: ToolContext.resolve_tool(SimpleNamespace(remote_tool_classes=known), name)  # noqa: E731
    assert find("business_enrichment") == "mcp__data-axle__salesgenie_business_enrichment"
    assert find("salesgenie_business_search") == "mcp__data-axle__salesgenie_business_search"  # the exact short name, as before
    assert find("contact_enrichment") is None  # no such tool: still unknown
    assert find("enrichment") is None  # two tools end with it: never a guess


def test_an_approval_counts_records_so_one_batch_call_cannot_spend_past_it_and_each_spend_is_recorded(temp_db):
    from src.agent_runtime.session import PersonaSession
    from src.database.connection import get_db

    tool = "mcp__data-axle__salesgenie_business_enrichment"
    s = object.__new__(PersonaSession)
    s._classes = {tool: "spend"}
    s.tool_context = SimpleNamespace(spend_allowance={tool: 3}, send_allowance={})
    s.context = SimpleNamespace(chat_id="chat-a", call_id="call-1")

    async def go():
        above = await s._permission_gate(tool, {"records": [{"name": n} for n in "abcd"]}, None)  # 4 records, 3 approved
        fits = await s._permission_gate(tool, {"records": [{"name": n} for n in "abc"]}, None)
        rows = await (await (await get_db()).execute("SELECT endpoint, credits, usd FROM data_spend")).fetchall()
        return above, fits, rows, s.tool_context.spend_allowance[tool]

    above, fits, rows, left = asyncio.run(go())
    assert type(above).__name__ == "PermissionResultDeny" and type(fits).__name__ == "PermissionResultAllow"
    assert [tuple(r) for r in rows] == [("salesgenie_business_enrichment", 6.0, 0.0)] and left == 0
