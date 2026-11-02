"""Every MCP server can be removed (a bundled one is hidden for good, its file untouched), and a pasted key goes
out as the key itself."""

import asyncio

from src import database
from src.mcp_client import client, config
from src.routers import mcp


def test_a_pasted_key_is_sent_as_the_key(monkeypatch):
    monkeypatch.setattr(client, "auth_type", lambda server: "bearer")
    for pasted in ("kw_abc", " Bearer kw_abc ", '"kw_abc"', "bearer   kw_abc"):
        async def token(server, pasted=pasted):
            return pasted
        monkeypatch.setattr(client, "get_access_token", token)
        assert asyncio.run(client.auth_headers("market-watch")) == {"Authorization": "Bearer kw_abc"}, pasted


def test_removing_a_bundled_server_hides_it_for_good(monkeypatch):
    saved, forgotten = {}, []

    async def save(key, on):
        saved[key] = on

    async def forget(server):
        forgotten.append(server)

    async def noop():
        return None

    monkeypatch.setattr(config, "_bundled", {"knightwatch": {"url": "http://localhost:8765/mcp"}, "data-axle": {"url": "x"}})
    monkeypatch.setattr(config, "_runtime", {})
    monkeypatch.setattr(config, "_flags", {})
    monkeypatch.setattr(database, "save_mcp_server_flag", save)
    monkeypatch.setattr(mcp, "forget_tokens", forget)
    monkeypatch.setattr(mcp.specialists, "refresh", noop)
    assert asyncio.run(mcp.delete_server("knightwatch"))["success"]
    assert forgotten == ["knightwatch"] and saved == {"removed:knightwatch": True}
    assert config.server_names() == ["data-axle"]
