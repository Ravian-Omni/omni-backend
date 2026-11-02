"""Only Azure Bot Service gets in; a Teams message becomes the thread's task and is acknowledged."""
import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from src.routers import teams


def test_only_bot_framework_tokens_for_our_app_pass(monkeypatch):
    monkeypatch.setenv("DAXAGENT_TEAMS_APP_ID", "app-1")
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setattr(teams._jwks, "get_signing_key_from_jwt", lambda token: SimpleNamespace(key=key.public_key()))
    url = "https://smba.trafficmanager.net/teams/"

    def token(**claims):
        payload = {"iss": "https://api.botframework.com", "aud": "app-1", "serviceurl": url, "exp": int(time.time()) + 60, **claims}
        return "Bearer " + jwt.encode(payload, key, algorithm="RS256")

    teams.verify(token(), url)
    for bad in (token(aud="other-app"), token(iss="https://evil.example"), token(exp=int(time.time()) - 1), ""):
        with pytest.raises(HTTPException):
            teams.verify(bad, url)
    with pytest.raises(HTTPException):
        teams.verify(token(), "https://elsewhere.example/")


def _activity(text, conversation="19:thread@1"):
    return {"type": "message", "id": "m1", "text": text, "serviceUrl": "https://smba.trafficmanager.net/teams/",
            "from": {"id": "u1", "name": "Ana"}, "recipient": {"id": "28:bot", "name": "DAXAGENT"}, "conversation": {"id": conversation}}


@pytest.fixture
def bot(monkeypatch):
    monkeypatch.setenv("DAXAGENT_TEAMS_APP_ID", "app-1")
    monkeypatch.setattr(teams, "verify", lambda authorization, service_url: None)
    opened, sent = [], []

    async def open_thread(app, key, say):
        opened.append((app, key))
        return SimpleNamespace(send=lambda text: opened.append(text))

    async def reply(activity, text, kind="message"):
        sent.append((kind, text))

    monkeypatch.setattr(teams, "open_thread", open_thread)
    monkeypatch.setattr(teams, "reply", reply)
    app = FastAPI()
    app.include_router(teams.router, prefix="/teams")
    return TestClient(app), opened, sent


def test_a_message_becomes_the_threads_task(bot):
    client, opened, sent = bot
    assert client.post("/teams/messages", json=_activity("<at>DAXAGENT</at> find dentists in Austin")).json() == {}
    assert opened == [("teams", "19:thread@1"), "find dentists in Austin"] and sent == [("typing", "")]
    assert client.post("/teams/messages", json={**_activity("hi"), "type": "conversationUpdate"}).json() == {}
    assert len(opened) == 2


def test_unconfigured_bot_refuses(monkeypatch):
    monkeypatch.delenv("DAXAGENT_TEAMS_APP_ID", raising=False)
    app = FastAPI()
    app.include_router(teams.router, prefix="/teams")
    assert TestClient(app).post("/teams/messages", json=_activity("hi")).status_code == 503
