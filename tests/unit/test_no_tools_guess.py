"""Chat 817f8f3c: a task closed on a guess that "this chat has no tools". The first empty plan of a run goes back to the
planner once, and a Composio server whose app has no active account is not offered as an agent."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

from src.agent_runtime import specialists
from src.omni.manager import EMPTY_PLAN_NOTE, Omni


def m(name, content):
    return {"role": "user", "name": name, "content": content}


EMPTY = json.dumps({"breakdown": [], "overall_status": "completed"})
PAST = [m("chat_manager", "earlier"), m("agent_executor", "ran"), m("process_completion_agent", "Browser Tool not connected.")]


def select(messages):
    sent = []
    planner = SimpleNamespace(name="planner_agent")
    me = SimpleNamespace(_check_cancellation=lambda: None, _empty_first_plan=Omni._empty_first_plan, planner=planner,
                         manager=SimpleNamespace(send=lambda msg, to, **kw: sent.append((msg["content"], to.name))))
    chat = SimpleNamespace(messages=messages, agent_by_name=lambda n: SimpleNamespace(name=n))
    return Omni.custom_speaker_selection_func(me, SimpleNamespace(name="planner_agent"), chat).name, sent


def test_a_first_empty_plan_goes_back_to_the_planner_with_the_note_and_a_second_one_stands():
    messages = PAST + [m("chat_manager", "find buyers"), m("planner_agent", EMPTY)]
    assert select(messages) == ("planner_agent", [(EMPTY_PLAN_NOTE, "planner_agent")])
    assert messages[-1]["content"] == EMPTY_PLAN_NOTE
    messages.append(m("planner_agent", EMPTY))
    assert select(messages) == ("process_completion_agent", [])


def test_an_empty_plan_after_agents_ran_closes_the_run():
    messages = [m("chat_manager", "find buyers"), m("agent_router", "{}"), m("agent_executor", "done"), m("planner_agent", EMPTY)]
    assert select(messages)[0] == "process_completion_agent"


def test_a_composio_server_without_an_active_app_is_not_offered(monkeypatch):
    monkeypatch.setattr(specialists, "specialist_eligible", lambda s: True)
    monkeypatch.setattr(specialists, "is_connected", AsyncMock(return_value=True))
    monkeypatch.setattr(specialists, "options", lambda s: {"composio": {"toolkits": ["browser_tool"]}})
    monkeypatch.setattr(specialists, "list_tools", AsyncMock(side_effect=AssertionError("never reached")))
    assert asyncio.run(specialists.build("composio-browser-tool", {"GMAIL", "GOOGLECALENDAR"})) is None
