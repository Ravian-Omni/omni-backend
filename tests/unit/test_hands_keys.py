"""DAX MCP keys: made in Settings, shown once, accepted by the /hands/mcp gate beside the env token, gone when revoked."""

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.database import connection
from src.routers import hands_keys, hands_mcp


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(connection.settings, "ROOT_DIR", str(tmp_path))
    monkeypatch.setattr(connection, "_db", None)
    asyncio.run(connection.init_db())
    monkeypatch.setenv("DAXAGENT_HANDS_TOKEN", "env-secret")
    app = FastAPI()
    app.include_router(hands_keys.router, prefix="/settings/hands-keys")
    app.mount("/hands", hands_mcp.app())
    return TestClient(app)


def gate(client, bearer):  # 503 = accepted but the MCP app is not running in a test; 401 = refused
    return client.post("/hands/mcp", json={}, headers={"Authorization": f"Bearer {bearer}"} if bearer else {}).status_code


def test_keys_open_the_gate_until_revoked(client):
    assert gate(client, "") == 401 and gate(client, "env-secret") == 503
    made = client.post("/settings/hands-keys", json={"name": "Brain_Hands"}).json()
    assert made["key"].startswith("dax_")
    assert gate(client, made["key"]) == 503 and gate(client, "dax_wrong") == 401
    listed = client.get("/settings/hands-keys").json()
    assert listed["url"].endswith("/hands/mcp") and [k["name"] for k in listed["keys"]] == ["Brain_Hands"]
    assert listed["keys"][0]["last_used_at"] and "key" not in listed["keys"][0]
    assert client.delete(f"/settings/hands-keys/{made['id']}").status_code == 200
    assert gate(client, made["key"]) == 401 and client.get("/settings/hands-keys").json()["keys"] == []


def test_source_names_the_client_and_the_key(client):
    from types import SimpleNamespace

    made = client.post("/settings/hands-keys", json={"name": "Brain_Hands"}).json()
    ctx = lambda name, key: SimpleNamespace(  # noqa: E731
        session=SimpleNamespace(client_params=SimpleNamespace(clientInfo=SimpleNamespace(name=name, version="2.1"))),
        request_context=SimpleNamespace(request=SimpleNamespace(scope={"state": {"dax_key": key}})))
    assert asyncio.run(hands_mcp._source(ctx("claude-code", {"id": made["id"], "name": "Brain_Hands"}))) == "claude-code 2.1 · Brain_Hands"
    assert asyncio.run(hands_mcp._source(ctx("mcp", {"id": "", "name": "server token"}))) == "AI agent · server token"
    assert client.get("/settings/hands-keys").json()["keys"][0]["last_client"] == "claude-code 2.1"
