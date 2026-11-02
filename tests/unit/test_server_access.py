"""Each MCP server reaches only the agents its config names: Data Axle the three finders, MarketWatch the
Strategizer and Builder, Newton the Data Analyst; chat's assistant gets every server."""

import json
from pathlib import Path

from src.agent_runtime.personas import PERSONAS
from src.agent_runtime.session import offered
from src.mcp_client import config

SERVERS = {
    "data-axle": {"reserved": True, "personas": ["lead_finder", "buyer_finder", "contact_enricher"]},
    "marketwatch": {"personas": ["campaign_strategizer", "campaign_builder"], "specialist": False},
    "newton": {"personas": ["ml_engineer"], "specialist": False},
    "old-reserved": {"reserved": True},
    "gmail": {},
}


def test_each_server_reaches_only_its_agents(monkeypatch):
    monkeypatch.setattr(config, "options", lambda s: SERVERS.get(s, {}))
    got = lambda s: sorted(n for n, p in PERSONAS.items() if n != "assistant" and offered(p, s))  # noqa: E731
    assert got("data-axle") == ["buyer_finder", "contact_enricher", "lead_finder"]
    assert got("marketwatch") == ["campaign_builder", "campaign_strategizer"]
    assert got("newton") == ["ml_engineer"]
    assert got("gmail") == []  # belongs to its own specialist
    assert "outreach" in got("old-reserved")  # reserved without a list: every job persona, as before
    assert all(offered(PERSONAS["assistant"], s) for s in SERVERS)


def test_bundled_lists_name_agents_that_can_use_remote_servers():
    bundled = json.loads((Path(__file__).parents[2] / "configs" / "mcp_servers.json").read_text())["mcpServers"]
    for name, server in bundled.items():
        for persona in server.get("daxagent", {}).get("personas") or []:
            assert persona == "assistant" or PERSONAS[persona].remote_mcp, (name, persona)
