"""Clerk gate for the hosted app: the page shell is open, everything else needs this instance's session."""

import base64
import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI, WebSocket
from fastapi.middleware import Middleware
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from src import auth

HOST = "fine-cat-12.clerk.accounts.dev"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def token(issuer=f"https://{HOST}", azp="https://app.example.com", exp=60):
    now = int(time.time())
    return jwt.encode({"iss": issuer, "sub": "user_1", "azp": azp, "iat": now, "exp": now + exp}, KEY, algorithm="RS256")


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(auth, "ISSUER", f"https://{HOST}")
    monkeypatch.setattr(auth, "AUTHORIZED_PARTIES", ["https://app.example.com"])
    monkeypatch.setattr(auth, "_jwks", SimpleNamespace(get_signing_key_from_jwt=lambda t: SimpleNamespace(key=KEY.public_key())))
    app = FastAPI(middleware=[Middleware(auth.ClerkGate)])
    app.get("/")(lambda: {"page": True})
    app.get("/health")(lambda: {"ok": True})
    app.get("/chats/conversations")(lambda: {"data": True})

    @app.websocket("/ws/omni/c1")
    async def ws(websocket: WebSocket):
        await websocket.accept()
        await websocket.send_text("hi")
        await websocket.close()

    return TestClient(app)


def test_issuer_comes_from_the_publishable_key():
    pk = "pk_test_" + base64.b64encode(f"{HOST}$".encode()).decode().rstrip("=")
    assert auth._issuer(pk) == f"https://{HOST}"


def test_page_shell_and_health_are_open_data_is_not(client):
    assert client.get("/").status_code == 200 and client.get("/health").status_code == 200
    assert client.get("/assets/index-abc.js").status_code == 404  # open path (no such file here), not a 401
    assert client.get("/chats/conversations").status_code == 401


def test_a_valid_session_cookie_or_bearer_token_gets_in(client):
    assert client.get("/chats/conversations", cookies={"__session": token()}).json() == {"data": True}
    assert client.get("/chats/conversations", headers={"Authorization": f"Bearer {token()}"}).status_code == 200


def test_expired_foreign_or_other_site_tokens_are_refused(client):
    for bad in (token(exp=-120), token(issuer="https://other.clerk.accounts.dev"), token(azp="https://evil.example.com")):
        assert client.get("/chats/conversations", cookies={"__session": bad}).status_code == 401


def test_websockets_need_the_session_too(client):
    with client.websocket_connect("/ws/omni/c1", cookies={"__session": token()}) as ws:
        assert ws.receive_text() == "hi"
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/omni/c1") as ws:
            ws.receive_text()
