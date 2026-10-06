"""The owner works a handoff from its card: reassign, claim, send in the thread (the click is the approval)."""

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.agent_runtime.tools import sales
from src.database import connection, save_handoff
from src.routers import handoffs


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setattr(connection.settings, "ROOT_DIR", str(tmp_path))
    monkeypatch.setattr(connection, "_db", None)
    asyncio.run(connection.init_db())
    asyncio.run(save_handoff({"id": "handoff-1", "user_id": "u", "chat_id": "c", "contact": "x@bigco.com", "thread_id": "t1",
                              "route": "answer", "reply": "What does it cost?", "draft": "It starts at..."}))
    sent = []

    async def fake_gmail(user_id, slug, arguments):
        sent.append((slug, arguments))
        return {"successful": True}

    monkeypatch.setattr(sales, "gmail_call", fake_gmail)
    app = FastAPI()
    app.include_router(handoffs.router, prefix="/handoffs")
    yield TestClient(app), sent
    asyncio.run(connection.close_db())


def test_owner_reassigns_claims_and_sends_in_the_thread(api):
    client, sent = api
    assert client.patch("/handoffs/handoff-1", json={"owner": "Ana"}).json()["owner"] == "Ana"
    assert client.patch("/handoffs/handoff-1", json={"status": "claimed"}).json()["status"] == "claimed"
    done = client.post("/handoffs/handoff-1/send", json={"body": "Plans start at $99/month."}).json()
    assert done["status"] == "sent" and done["draft"] == "Plans start at $99/month."
    assert sent == [("GMAIL_REPLY_TO_THREAD", {"thread_id": "t1", "recipient_email": "x@bigco.com",
                                               "message_body": "Plans start at $99/month.", "user_id": "me", "is_html": False})]
    assert client.post("/handoffs/handoff-1/send", json={"body": "again"}).status_code == 409  # never twice
    assert [h["id"] for h in client.get("/handoffs", params={"user_id": "u", "status": "active"}).json()["handoffs"]] == []


def test_unknown_handoff_and_empty_answer_are_refused(api):
    client, _ = api
    assert client.get("/handoffs/nope").status_code == 404
    assert client.post("/handoffs/handoff-1/send", json={"body": ""}).status_code == 422
