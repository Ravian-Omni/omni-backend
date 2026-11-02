"""Only Slack gets in; a DM or an @mention becomes the thread's task and is acknowledged."""
import hashlib
import hmac
import json
import time
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from src.routers import slack

SECRET = "slack-secret"


def _signed(body: dict, secret=SECRET, timestamp=None):
    raw = json.dumps(body).encode()
    timestamp = str(timestamp or int(time.time()))
    signature = "v0=" + hmac.new(secret.encode(), f"v0:{timestamp}:".encode() + raw, hashlib.sha256).hexdigest()
    return raw, {"x-slack-request-timestamp": timestamp, "x-slack-signature": signature, "content-type": "application/json"}


def test_only_fresh_requests_signed_with_our_secret_pass(monkeypatch):
    monkeypatch.setenv("DAXAGENT_SLACK_SIGNING_SECRET", SECRET)
    raw, headers = _signed({"type": "event_callback"})
    slack.verify(headers, raw)
    with pytest.raises(HTTPException):
        slack.verify(_signed({"type": "event_callback"}, secret="other")[1], raw)
    with pytest.raises(HTTPException):
        slack.verify(_signed({"type": "event_callback"}, timestamp=int(time.time()) - 600)[1], raw)
    with pytest.raises(HTTPException):
        slack.verify(headers, raw + b" ")


def test_markdown_becomes_mrkdwn():
    assert slack.mrkdwn("Reply **yes** and see [the list](https://x.y/z)") == "Reply *yes* and see <https://x.y/z|the list>"


def _event(**fields):
    return {"type": "event_callback", "event": {"type": "message", "channel": "D1", "channel_type": "im", "ts": "1.2", "user": "U1", "text": "hi", **fields}}


@pytest.fixture
def bot(monkeypatch):
    monkeypatch.setenv("DAXAGENT_SLACK_SIGNING_SECRET", SECRET)
    monkeypatch.setenv("DAXAGENT_SLACK_BOT_TOKEN", "xoxb-1")
    opened, calls = [], []

    async def open_thread(app, key, say):
        opened.append((app, key, say))
        return SimpleNamespace(send=lambda text: opened.append(text))

    async def api(method, **payload):
        calls.append((method, payload))
        return {"ok": True}

    monkeypatch.setattr(slack, "open_thread", open_thread)
    monkeypatch.setattr(slack, "api", api)
    app = FastAPI()
    app.include_router(slack.router, prefix="/slack")
    client = TestClient(app)
    return lambda body, **headers: client.post("/slack/events", content=_signed(body)[0], headers={**_signed(body)[1], **headers}), opened, calls


def test_dms_and_mentions_become_tasks_in_their_thread(bot):
    post, opened, calls = bot
    assert post({"type": "url_verification", "challenge": "abc"}).json() == {"challenge": "abc"}
    assert post(_event(text="find dentists in Austin")).json() == {}
    assert opened[0][:2] == ("slack", "D1") and opened[1] == "find dentists in Austin"
    assert calls == [("reactions.add", {"channel": "D1", "timestamp": "1.2", "name": "eyes"})]
    mention = _event(type="app_mention", channel="C1", channel_type="channel", ts="9.9", thread_ts="5.5", text="<@UBOT> yes")
    post(mention)
    assert opened[2][:2] == ("slack", "C1:5.5") and opened[3] == "yes"
    # replies from a channel thread stay in it; DM replies are top level
    import asyncio
    asyncio.run(opened[2][2]("Done **now**"))
    assert calls[-1] == ("chat.postMessage", {"channel": "C1", "thread_ts": "5.5", "text": "Done *now*"})
    asyncio.run(opened[0][2]("Plan"))
    assert calls[-1] == ("chat.postMessage", {"channel": "D1", "thread_ts": None, "text": "Plan"})  # api() drops the None
    # the bot's own echo, edits, retries and unsigned posts never start a task
    for ignored in (_event(bot_id="B1"), _event(subtype="message_changed"), {"type": "event_callback", "event": {"type": "reaction_added"}}):
        assert post(ignored).json() == {}
    assert post(_event(), **{"x-slack-retry-num": "1"}).json() == {}
    assert len(opened) == 4
    assert post(_event(), **{"x-slack-signature": "v0=bad"}).status_code == 401
