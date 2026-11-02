"""Admin dashboard: history becomes turns (request, steps, tools, answer), tokens are counted once per model call or
agent run, and only admins get in."""

import asyncio
import json
from datetime import date

import pytest

from src import auth
from src.database import admin_rows, connection, get_chat_repository, save_account, save_feedback, update_chat_history
from src.routers import admin


def msg(name, raw, task="t1", usage=None, role="assistant"):
    return {"role": role, "name": name, "raw_message": raw, "usage": usage or {}, "task_id": task, "timestamp": f"2026-10-29T10:00:{len(name):02d}"}


def chat_turn(task, question, answer, running_total=None, per_run=None):
    """One chat-mode turn as PersonaSession stores it: old records keep the running total on the final message,
    new ones keep this run's usage on the finish line."""
    finish = {"type": "agent_status", "status": "finished", "persona": "assistant", "display_name": "DAXAGENT", "model": "gpt-5.6-luna"}
    return [
        msg("user", {"role": "user", "content": question}, task, role="user"),
        msg("assistant", {"type": "agent_status", "status": "started", "persona": "assistant", "task": question}, task),
        msg("assistant", {"role": "assistant", "content": "Searching."}, task),
        msg("assistant", {"type": "tool_use", "tool_use_id": f"c-{task}", "tool_name": "business_search",
                          "tool_full_name": "mcp__data-axle__business_search", "tool_input": {"sic": "8021"}}, task),
        msg("assistant", {"type": "tool_result", "tool_use_id": f"c-{task}", "status": "completed", "content": "5 found"}, task),
        msg("assistant", {"role": "assistant", "content": answer}, task),
        msg("assistant", finish, task, usage=per_run and {**per_run, "model": "gpt-5.6-luna", "per_run": True}),
        msg("assistant", {"role": "assistant", "content": answer, "final": True}, task,
            usage=running_total and {"prompt_tokens": running_total[0], "completion_tokens": running_total[1]} | {"total_tokens": sum(running_total)}),
    ]


def test_a_chat_turn_reads_as_request_tool_answer():
    [turn] = admin.turns(admin.steps(chat_turn("t1", "Find dentists in Austin", "Found 5."), chat_mode=True))
    assert (turn["request"], turn["answer"], turn["status"]) == ("Find dentists in Austin", "Found 5.", "answered")
    tool = next(s for s in turn["steps"] if s["kind"] == "tool")
    assert (tool["server"], tool["input"], tool["result"]) == ("data-axle", {"sic": "8021"}, "5 found")
    assert [s["text"] for s in turn["steps"] if s["kind"] == "answer"] == ["Found 5."]
    assert [s["kind"] for s in turn["steps"]].count("agent") == 1  # the narration; the repeated answer is kept once
    assert (turn["tool_calls"], turn["mcp_calls"], turn["servers"]) == (1, 1, ["data-axle"])


def test_old_chat_running_totals_become_per_turn_and_new_records_are_exact():
    history = (chat_turn("t1", "a", "A", running_total=(100, 10)) + chat_turn("t2", "b", "B", running_total=(250, 30))
               + chat_turn("t3", "c", "C", running_total=(120, 5))  # dropped: a new connection
               + chat_turn("t4", "d", "D", per_run={"prompt_tokens": 90, "completion_tokens": 9, "total_tokens": 99}))
    assert [t["tokens"] for t in admin.turns(admin.steps(history, chat_mode=True))] == [110, 170, 125, 99]


def test_a_task_counts_orchestrator_calls_and_shows_the_brief_as_a_step():
    delta = {"current_total": {"model": "gpt-5.6-luna"}, "message_delta": {"prompt_tokens": 40, "completion_tokens": 2, "total_tokens": 42}}
    history = [
        msg("chat_manager", "{'task': 'Find 10 HVAC contractors', 'files': []}", role="user"),
        msg("planner_agent", '{"breakdown": []}', usage=delta, role="user"),
        msg("user", {"role": "user", "content": "Brief for Lead Finder"}, role="user"),
        msg("lead_finder", {"type": "agent_status", "status": "failed", "persona": "lead_finder", "display_name": "Lead Finder"},
            usage={"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10, "model": "gpt-5.6-luna", "per_run": True}),
        msg("process_completion_agent", "Done: 10 contractors", role="user"),
    ]
    [turn] = admin.turns(admin.steps(history, chat_mode=False))
    assert turn["request"] == "Find 10 HVAC contractors"
    assert [s["kind"] for s in turn["steps"]] == ["user", "step", "step", "run", "answer"]
    assert (turn["tokens"], turn["models"], turn["status"], turn["agents"]) == (52, {"gpt-5.6-luna": 52}, "failed", ["Lead Finder"])


def test_an_agent_run_kept_only_in_its_own_row_is_merged_once():
    mirrored = msg("lead_finder", {"type": "tool_use", "tool_use_id": "x", "tool_name": "s", "tool_full_name": "mcp__data-axle__s"})
    lone = msg("buyer_finder", {"type": "tool_use", "tool_use_id": "y", "tool_name": "s", "tool_full_name": "mcp__data-axle__s"})
    main = [msg("chat_manager", "find", role="user"), mirrored]
    assert admin.merged(main, [[dict(mirrored, timestamp="later")], [lone]]) == sorted(main + [lone], key=lambda m: m["timestamp"])


def test_only_admins_get_in(monkeypatch):
    monkeypatch.setenv("DAXAGENT_AUTH", "clerk")
    monkeypatch.setenv("DAXAGENT_OWNER", "user_owner")
    monkeypatch.delenv("DAXAGENT_ADMINS", raising=False)
    assert auth.is_admin("user_owner") and not auth.is_admin("user_other")
    monkeypatch.setenv("DAXAGENT_ADMINS", "user_a, user_b")
    assert auth.is_admin("user_b") and not auth.is_admin("user_owner")
    monkeypatch.delenv("DAXAGENT_AUTH")
    assert auth.is_admin("local_user")  # a local run: sign-in off, nothing to protect


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(connection.settings, "ROOT_DIR", str(tmp_path))
    monkeypatch.setattr(connection, "_db", None)
    asyncio.run(connection.init_db())
    yield
    asyncio.run(connection.close_db())


def test_overview_names_people_and_ties_feedback_to_the_request(temp_db):
    async def scenario():
        now = "2026-10-29T10:00:00"
        await (await get_chat_repository()).create_chat(
            {"user_id": "user_ann", "chat_id": "chat-1", "messages": [], "raw_messages": [], "created_at": now, "updated_at": now}, "chats")
        for m in chat_turn("t1", "Find dentists", "Found 5.", per_run={"prompt_tokens": 50, "completion_tokens": 5, "total_tokens": 55}):
            await update_chat_history("chat-1", m, "chats")
        await save_account("user_ann", "ann@example.com", "Ann")
        await save_account("user_bo", "bo@example.com", "Bo")  # signed in, never asked anything
        await save_feedback("chat-1", "t1", "user_ann", 2, "Wrong city")
        return admin.overview(await admin_rows(), date(2026, 10, 29))

    o = asyncio.run(scenario())
    assert (o["totals"]["users"], o["totals"]["conversations"], o["totals"]["mcp_calls"], o["totals"]["tokens"]) == (2, 1, 1, 55)
    assert {u["email"]: u.get("conversations", 0) for u in o["users"]} == {"ann@example.com": 1, "bo@example.com": 0}
    [f] = o["feedback"]
    assert (f["request"], f["rating"], o["totals"]["negative"]) == ("Find dentists", 2, 1)
    assert json.dumps(o)  # the response serializes


def test_tool_calls_per_day_by_server(monkeypatch):
    from collections import Counter

    from src.routers import admin

    monkeypatch.setattr("src.mcp_client.options", lambda s: {"display_name": s.upper()})
    days = {"2026-10-28": {"requests": 1}, "2026-10-29": {"requests": 2}}
    calls = {"2026-10-28": Counter({"data-axle": 3, "": 2}), "2026-10-29": Counter({"gmail": 1, "newton": 1, "data-axle": 1})}
    out = admin.tool_days(days, calls, most=2)
    assert out["tool_series"] == ["DATA-AXLE", "GMAIL", "Other MCP servers", "Built-in tools"]  # busiest first, built-in last
    assert out["days"][0]["tools"] == {"DATA-AXLE": 3, "Built-in tools": 2} and out["days"][0]["tool_calls"] == 5
    assert out["days"][1]["tools"] == {"GMAIL": 1, "Other MCP servers": 1, "DATA-AXLE": 1} and out["days"][1]["requests"] == 2
