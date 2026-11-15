"""Bearer keys for outside agents calling DAXAGENT's own MCP (/hands/mcp): made in Settings > Connections > DAX MCP."""

import hashlib
import hmac
import os
import secrets

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from src import auth
from src.database import delete_hands_key, list_hands_keys, save_hands_key, touch_hands_key

router = APIRouter()


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()  # keys are random, so a plain hash is enough


async def accepted(bearer: str) -> dict | None:
    """The key a bearer token is ({id, name}) if it may use /hands/mcp: the DAXAGENT_HANDS_TOKEN variable or a key made in the app."""
    if not bearer:
        return None
    env = os.environ.get("DAXAGENT_HANDS_TOKEN", "")
    if env and hmac.compare_digest(bearer, env):
        return {"id": "", "name": "server token"}
    return await touch_hands_key(_hash(bearer))


class NewKey(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)


@router.get("")
async def keys(request: Request) -> dict:
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    return {"url": f"{proto}://{request.headers.get('host', request.url.netloc)}/hands/mcp", "keys": await list_hands_keys()}


@router.post("", status_code=201)
async def create(body: NewKey, request: Request) -> dict:
    """Make a key; its value is returned this once."""
    user = await auth.SessionGate.user(request.scope)
    key = "dax_" + secrets.token_urlsafe(32)
    key_id = secrets.token_hex(6)
    await save_hands_key(key_id, body.name.strip(), _hash(key), (user or {}).get("email") or "local")
    return {"id": key_id, "name": body.name.strip(), "key": key}


@router.delete("/{key_id}")
async def revoke(key_id: str) -> dict:
    if not await delete_hands_key(key_id):
        raise HTTPException(status_code=404, detail="No such key")
    return {"revoked": key_id}
