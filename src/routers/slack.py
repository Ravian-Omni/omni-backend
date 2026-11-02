"""Slack bot: a DM with the bot, or a channel thread where it is @mentioned, is one DAXAGENT task.

Slack's Events API posts each message to ``POST /slack/events`` (signed with the app's signing
secret); the thread runs through ``services.chat_bridge`` like the web app's task mode, and replies
go out with chat.postMessage. Variables: DAXAGENT_SLACK_SIGNING_SECRET, DAXAGENT_SLACK_BOT_TOKEN.
Event subscriptions: app_mention and message.im; scopes: app_mentions:read, chat:write, im:history,
reactions:write.
"""

import hashlib
import hmac
import json
import os
import re
import time

import httpx
from fastapi import APIRouter, HTTPException, Request
from loguru import logger

from src.services.chat_bridge import open_thread

router = APIRouter()


def _cfg(name: str) -> str:
    return os.getenv(f"DAXAGENT_SLACK_{name}", "")


def verify(headers, body: bytes) -> None:
    """Only Slack may post here: the request is signed with the app's signing secret and is fresh."""
    timestamp = headers.get("x-slack-request-timestamp", "")
    if not timestamp.isdigit() or abs(time.time() - int(timestamp)) > 300:
        raise HTTPException(401, "Slack request is stale")
    digest = "v0=" + hmac.new(_cfg("SIGNING_SECRET").encode(), f"v0:{timestamp}:".encode() + body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(digest, headers.get("x-slack-signature", "")):
        raise HTTPException(401, "Slack signature mismatch")


def mrkdwn(text: str) -> str:
    """Slack's own markup: *bold* and <url|label> links."""
    text = re.sub(r"\*\*(.+?)\*\*", r"*\1*", text)
    return re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"<\2|\1>", text)


async def api(method: str, **payload) -> dict:
    """One Slack Web API call. Never raises: a failed delivery must not stop the agents' run."""
    payload = {k: v for k, v in payload.items() if v is not None}
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(f"https://slack.com/api/{method}", json=payload,
                                         headers={"Authorization": f"Bearer {_cfg('BOT_TOKEN')}"})
        body = response.json()
        if not body.get("ok"):
            logger.warning(f"[slack] {method} failed: {body.get('error')}")
        return body
    except Exception as e:
        logger.warning(f"[slack] {method} failed: {e}")
        return {}


@router.post("/events")
async def events(request: Request) -> dict:
    """Slack delivers every subscribed event here; the agents' answers follow through chat.postMessage."""
    if not (_cfg("SIGNING_SECRET") and _cfg("BOT_TOKEN")):
        raise HTTPException(503, "Slack bot is not configured (DAXAGENT_SLACK_SIGNING_SECRET, DAXAGENT_SLACK_BOT_TOKEN)")
    body = await request.body()
    verify(request.headers, body)
    payload = json.loads(body)
    if payload.get("type") == "url_verification":
        return {"challenge": payload.get("challenge")}
    event = payload.get("event") or {}
    # Slack re-sends an event when the reply was slow (the first delivery is handled), and echoes the
    # bot's own posts and edits (subtype) back as messages.
    if request.headers.get("x-slack-retry-num") or event.get("bot_id") or event.get("subtype"):
        return {}
    if event.get("type") not in ("message", "app_mention"):
        return {}
    text = re.sub(r"<@[A-Z0-9]+>", "", event.get("text") or "").strip()  # the @mention
    channel, root = event.get("channel"), event.get("thread_ts") or event.get("ts")
    if not text or not channel:
        return {}
    # shortcut: a channel thread continues only through @mentions (no message.channels subscription),
    # dedupe app_mention/message pairs by ts when subscribing to it.
    direct = event.get("channel_type") == "im"
    key, thread_ts = (channel, None) if direct else (f"{channel}:{root}", root)

    async def say(reply_text: str) -> None:
        await api("chat.postMessage", channel=channel, thread_ts=thread_ts, text=mrkdwn(reply_text))

    (await open_thread("slack", key, say)).send(text)
    await api("reactions.add", channel=channel, timestamp=event.get("ts"), name="eyes")
    return {}
