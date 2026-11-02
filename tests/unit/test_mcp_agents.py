"""Which agents an MCP server is hooked to: chosen in Settings (a bundled server's file stays as shipped),
reported as the runtime really resolves it, and never an agent that doesn't exist."""

import asyncio

import pytest
from fastapi import HTTPException

from src import database
from src.mcp_client import config
from src.routers import mcp


@pytest.fixture
def flags(monkeypatch):
    saved = {}

    async def save(key, on):
        saved[key] = on

    monkeypatch.setattr(config, "_flags", {})
    monkeypatch.setattr(database, "save_mcp_server_flag", save)
    return saved


def test_a_bundled_servers_agents_chosen_in_settings_win(monkeypatch, flags):
    monkeypatch.setattr(config, "options", lambda server: {"personas": ["lead_finder"]})
    assert config.personas_for("brain") == ["lead_finder"]
    asyncio.run(config.set_personas("brain", ["user_context", "ml_engineer"]))
    assert sorted(config.personas_for("brain")) == ["ml_engineer", "user_context"]
    asyncio.run(config.set_personas("brain", []))  # none at all sticks too
    assert config.personas_for("brain") == [] and flags["agents:brain"] is True
    assert config.wants_specialist("brain")
    asyncio.run(config.set_specialist("brain", False))
    assert not config.wants_specialist("brain") and not config.specialist_eligible("brain")


def test_hooked_to_is_what_the_runtime_gives(monkeypatch, flags):
    opts = {"brain": {"personas": ["user_context"]}, "data-axle": {"reserved": True}, "mine": {}}
    monkeypatch.setattr(config, "options", lambda server: opts[server])
    assert mcp._hooked_to("brain") == ["user_context"]
    assert mcp._hooked_to("data-axle") == mcp.server_agents()  # reserved with no list: every agent that takes servers
    assert mcp._hooked_to("mine") == []  # only its own sub-agent
    assert "assistant" not in mcp.server_agents() and "software_developer" not in mcp.server_agents()
    asyncio.run(config.set_mode("brain", "task", False))
    assert mcp._hooked_to("brain") == []  # not offered in tasks


def test_update_stores_a_bundled_servers_agents_as_switches(monkeypatch):
    calls = []

    async def record(*args):
        calls.append(args)

    async def noop():
        return None

    async def describe(server):
        return {"name": server}

    monkeypatch.setattr(mcp, "_require", lambda server: None)
    monkeypatch.setattr(mcp, "is_bundled", lambda server: True)
    monkeypatch.setattr(mcp, "set_personas", record)
    monkeypatch.setattr(mcp, "set_specialist", record)
    monkeypatch.setattr(mcp.specialists, "refresh", noop)
    monkeypatch.setattr(mcp, "_describe", describe)
    asyncio.run(mcp.update_server("user-context", mcp.ServerUpdate(personas=["user_context"], specialist=False)))
    assert calls == [("user-context", ["user_context"]), ("user-context", False)]
    with pytest.raises(HTTPException) as e:
        asyncio.run(mcp.update_server("user-context", mcp.ServerUpdate(personas=["nobody"])))
    assert e.value.status_code == 400 and "nobody" in e.value.detail
