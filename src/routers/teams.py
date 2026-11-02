"""Microsoft Teams bot: every Teams chat or channel thread with the bot is one DAXAGENT task.

Azure Bot Service posts each Teams message to ``POST /teams/messages`` (signed with a Bot Framework
token); the thread runs through ``services.chat_bridge`` like the web app's task mode, and replies go
out through the Bot Connector with the bot's credentials: DAXAGENT_TEAMS_APP_ID,
DAXAGENT_TEAMS_APP_PASSWORD and, for a single-tenant bot, DAXAGENT_TEAMS_TENANT_ID.
"""

import asyncio
import os
import re
import time
from typing import Any

import httpx
import jwt
from fastapi import APIRouter, HTTPException, Request
from loguru import logger

from src.services.chat_bridge import open_thread

router = APIRouter()
_jwks = jwt.PyJWKClient("https://login.botframework.com/v1/.well-known/keys", cache_keys=True)
_token: dict[str, Any] = {}


def _cfg(name: str) -> str:
    return os.getenv(f"DAXAGENT_TEAMS_{name}", "")


def verify(authorization: str, service_url: str) -> None:
    """Only Azure Bot Service may post here: a token for our app that names the activity's serviceUrl."""
    token = authorization.removeprefix("Bearer ").strip()
    try:
        key = _jwks.get_signing_key_from_jwt(token).key
        claims = jwt.decode(token, key, algorithms=["RS256"], audience=_cfg("APP_ID"), issuer="https://api.botframework.com")
    except jwt.PyJWTError as e:
        raise HTTPException(401, f"Bot Framework token rejected: {e}") from e
    if str(claims.get("serviceurl", "")).rstrip("/") != service_url.rstrip("/"):
        raise HTTPException(401, "Bot Framework token is for another service URL")


async def _bearer() -> str:
    if _token.get("expires", 0) > time.time() + 60:
        return _token["value"]
    tenant = _cfg("TENANT_ID") or "botframework.com"
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
            data={"grant_type": "client_credentials", "client_id": _cfg("APP_ID"),
                  "client_secret": _cfg("APP_PASSWORD"), "scope": "https://api.botframework.com/.default"},
        )
    response.raise_for_status()
    body = response.json()
    _token.update(value=body["access_token"], expires=time.time() + body["expires_in"])
    return _token["value"]


async def reply(activity: dict, text: str, kind: str = "message") -> None:
    """Post to the Teams conversation the activity came from (a message, or a typing indicator).

    Never raises: a failed delivery must not stop the agents' run.
    """
    conversation = activity["conversation"]["id"]
    body = {"type": kind, "text": text, "textFormat": "markdown", "from": activity["recipient"],
            "recipient": activity["from"], "conversation": {"id": conversation}, "replyToId": activity.get("id")}
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                f"{activity['serviceUrl'].rstrip('/')}/v3/conversations/{conversation}/activities",
                json=body, headers={"Authorization": f"Bearer {await _bearer()}"},
            )
        response.raise_for_status()
    except Exception as e:
        logger.warning(f"[teams] reply to {conversation} failed: {e}")


@router.post("/messages")
async def messages(request: Request) -> dict:
    """Azure Bot Service delivers every Teams activity here; the agents' answers follow through reply()."""
    if not _cfg("APP_ID"):
        raise HTTPException(503, "Teams bot is not configured (DAXAGENT_TEAMS_APP_ID)")
    activity = await request.json()
    await asyncio.to_thread(verify, request.headers.get("authorization", ""), str(activity.get("serviceUrl", "")))
    text = re.sub(r"<at>.*?</at>", "", activity.get("text") or "").strip()  # the @mention in a channel
    if activity.get("type") != "message" or not text:
        return {}

    async def say(reply_text: str) -> None:
        await reply(activity, reply_text)

    (await open_thread("teams", activity["conversation"]["id"], say)).send(text)
    await reply(activity, "", "typing")
    return {}
