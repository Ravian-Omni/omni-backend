"""Email and password sign-in for the hosted app: the page shell is open, everything else needs a session."""

import asyncio
import base64
import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI, WebSocket
from fastapi.middleware import Middleware
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from src import auth
from src.database import connection
from src.routers import auth as auth_router


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(connection.settings, "ROOT_DIR", str(tmp_path))
    monkeypatch.setattr(connection, "_db", None)
    asyncio.run(connection.init_db())
    monkeypatch.setenv("DAXAGENT_AUTH", "on")
    monkeypatch.setenv("DAXAGENT_ADMIN_TOKEN", "admin-secret")
    app = FastAPI(middleware=[Middleware(auth.SessionGate)])
    app.include_router(auth_router.router, prefix="/auth")
    app.get("/")(lambda: {"page": True})
    app.get("/chats/conversations")(lambda: {"data": True})

    @app.websocket("/ws/omni/c1")
    async def ws(websocket: WebSocket):
        await websocket.accept()
        await websocket.send_text("hi")
        await websocket.close()

    yield TestClient(app)
    asyncio.run(connection.close_db())


def test_passwords_are_hashed_and_checked():
    stored = auth.hash_password("Demouser@123")
    assert stored.startswith("scrypt$") and "Demouser" not in stored
    assert auth.check_password("Demouser@123", stored) and not auth.check_password("demouser@123", stored)


def test_page_shell_is_open_data_is_not(client):
    assert client.get("/").status_code == 200 and client.get("/auth/me").json() == {"auth": True, "user": None}
    assert client.get("/chats/conversations").status_code == 401
    assert client.post("/teams/messages").status_code == 404  # open for Azure Bot Service and Slack: they sign their posts
    assert client.post("/slack/events").status_code == 404


def test_accounts_need_the_admin_token_and_the_right_password(client):
    new = {"email": "GrowthHacker@abc.com", "password": "Demouser@123", "name": "Growth Hacker"}
    assert client.post("/auth/users", json=new).status_code == 403
    assert client.post("/auth/users", json=new, headers={"X-Admin-Token": "admin-secret"}).json()["email"] == "growthhacker@abc.com"
    assert client.post("/auth/login", json={"email": "growthhacker@abc.com", "password": "wrong"}).status_code == 401


def test_login_opens_http_and_websockets_and_logout_closes_them(client):
    client.post("/auth/users", json={"email": "growthhacker@abc.com", "password": "Demouser@123"}, headers={"X-Admin-Token": "admin-secret"})
    assert client.post("/auth/login", json={"email": "GrowthHacker@abc.com", "password": "Demouser@123"}).status_code == 200
    assert client.get("/chats/conversations").json() == {"data": True}
    assert client.get("/auth/me").json()["user"]["email"] == "growthhacker@abc.com"
    with client.websocket_connect("/ws/omni/c1") as ws:
        assert ws.receive_text() == "hi"
    client.post("/auth/logout")
    assert client.get("/chats/conversations").status_code == 401
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/omni/c1") as ws:
            ws.receive_text()


def test_a_signed_in_request_acts_only_as_its_own_account(client):
    client.app.get("/whose")(lambda user_id="local_user": {"user_id": user_id})
    for email in ("a@abc.com", "b@abc.com"):
        client.post("/auth/users", json={"email": email, "password": "pw"}, headers={"X-Admin-Token": "admin-secret"})
    client.post("/auth/login", json={"email": "b@abc.com", "password": "pw"})
    assert client.get("/whose").json() == {"user_id": "b@abc.com"}
    assert client.get("/whose?user_id=a@abc.com&user_id=local_user").json() == {"user_id": "b@abc.com"}


def test_clerk_mode_admits_a_session_token_issued_to_this_site(client, monkeypatch):
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    monkeypatch.setenv("DAXAGENT_AUTH", "clerk")
    monkeypatch.setenv("CLERK_PUBLISHABLE_KEY", "pk_test_" + base64.b64encode(b"cheerful-dog-12.clerk.accounts.dev$").decode())
    auth.clerk.cache_clear()
    assert auth.clerk().frontend_api == "cheerful-dog-12.clerk.accounts.dev"
    monkeypatch.setattr(auth.clerk()._keys, "get_signing_key_from_jwt", lambda token: SimpleNamespace(key=private.public_key()))

    def token(**claims):
        now = int(time.time())
        return jwt.encode({"sub": "user_1", "exp": now + 60, "iat": now, "azp": "http://testserver", **claims}, pem, algorithm="RS256")

    me = client.get("/auth/me").json()
    assert me["mode"] == "clerk" and me["publishable_key"].startswith("pk_test_") and me["user"] is None
    assert client.get("/chats/conversations").status_code == 401
    client.app.get("/whose")(lambda user_id="local_user": {"user_id": user_id})
    client.cookies.set(auth.CLERK_COOKIE, token())
    assert client.get("/whose?user_id=org_1").json() == {"user_id": "user_1"}  # their own workspace
    assert client.get("/chats/conversations").json() == {"data": True}
    assert client.get("/auth/me").json()["user"] == {"id": "user_1"}
    with client.websocket_connect("/ws/omni/c1") as ws:
        assert ws.receive_text() == "hi"
    for rejected in (token(azp="https://elsewhere.example"), token(sts="pending"), token(exp=int(time.time()) - 120)):
        client.cookies.set(auth.CLERK_COOKIE, rejected)
        assert client.get("/chats/conversations").status_code == 401
    auth.clerk.cache_clear()


def test_the_owner_takes_over_what_local_user_made(client, monkeypatch):
    db = asyncio.run(connection.get_db())
    for sql in ("INSERT INTO chats (user_id, chat_id, collection, created_at, updated_at) VALUES ('local_user', 'c1', 'omni', 'now', 'now')",
                "INSERT INTO user_prefs VALUES ('local_user', 'agents', '{}', 'now')",
                "INSERT INTO user_prefs VALUES ('local_user', 'memory', '{}', 'now')",
                "INSERT INTO user_prefs VALUES ('user_9', 'memory', '{\"mine\": 1}', 'now')"):
        asyncio.run(db.execute(sql))
    asyncio.run(db.commit())
    asyncio.run(connection.close_db())
    monkeypatch.setenv("DAXAGENT_OWNER", "user_9")
    db = asyncio.run(connection.get_db())
    rows = lambda sql: asyncio.run(_all(db, sql))
    assert rows("SELECT user_id FROM chats") == [("user_9",)]
    assert rows("SELECT user_id, key, value FROM user_prefs ORDER BY user_id, key") == [
        ("local_user", "memory", "{}"), ("user_9", "agents", "{}"), ("user_9", "memory", '{"mine": 1}')]  # theirs is kept


async def _all(db, sql):
    return [tuple(r) for r in await (await db.execute(sql)).fetchall()]


def test_off_means_open(client, monkeypatch):
    monkeypatch.setenv("DAXAGENT_AUTH", "")
    assert client.get("/chats/conversations").status_code == 200 and client.get("/auth/me").json()["auth"] is False
