"""Per-mode switches: a server's `modes` sets the default, the user's switch wins."""

from src.mcp_client import config


def test_modes_default_and_user_switch(monkeypatch):
    monkeypatch.setattr(config, "options", lambda server: {"modes": ["task"]} if server == "intel" else {})
    monkeypatch.setattr(config, "_flags", {})
    assert config.in_mode("intel", "task") and not config.in_mode("intel", "chat")
    assert config.in_mode("other", "chat") and config.in_mode("other", "task")
    monkeypatch.setattr(config, "_flags", {"chat:intel": True})
    assert config.in_mode("intel", "chat")


def test_url_override_per_deployment(monkeypatch):
    monkeypatch.setattr(config, "_config", lambda: {"knightwatch": {"url": "http://localhost:8765/mcp"}})
    monkeypatch.delenv("MCP_URL_KNIGHTWATCH", raising=False)
    assert config.server_url("knightwatch") == "http://localhost:8765/mcp"
    monkeypatch.setenv("MCP_URL_KNIGHTWATCH", "https://kw.example.com/mcp")
    assert config.server_url("knightwatch") == "https://kw.example.com/mcp"
