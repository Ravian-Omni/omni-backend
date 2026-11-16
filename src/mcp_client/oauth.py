"""OAuth 2.0 (authorization code + PKCE) for remote MCP servers.

The Data Axle MCP server only supports the authorization_code grant, so a user
signs in once through the provider's hosted page and the resulting tokens are
persisted. Tokens are stored as JSON in the existing api_keys table under the
provider name "mcp:<server>", so no schema change is required.
"""

import base64
import hashlib
import json
import os
import time

import httpx
from loguru import logger

from src.database import delete_api_key, load_all_api_keys, save_api_key
from src.mcp_client.config import oauth_endpoints, options

# Endpoints come from configs/mcp_servers.json, per server: each provider has
# its own, discovered from /.well-known/oauth-authorization-server.

_STORE_PREFIX = "mcp:"
# code_verifier per in-flight login, keyed by state
_pending: dict[str, str] = {}


def _b64url(raw: bytes) -> str:
    """Base64url-encode without padding, as required by PKCE."""
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


async def _store(server: str, tokens: dict) -> None:
    """Persist tokens, recording when the access token expires."""
    tokens["expires_at"] = time.time() + int(tokens.get("expires_in", 3600))
    await save_api_key(f"{_STORE_PREFIX}{server}", json.dumps(tokens))


async def _load(server: str) -> dict | None:
    """Read stored tokens for a server, or None when it has never signed in."""
    raw = (await load_all_api_keys()).get(f"{_STORE_PREFIX}{server}")
    return json.loads(raw) if raw else None


async def store_static_token(server: str, token: str) -> None:
    """Persist a bearer token the user pasted, as a token that never expires."""
    await _store(server, {"access_token": token, "expires_in": 10**9})
    logger.info(f"Stored static bearer token for {server}")


async def forget_tokens(server: str) -> None:
    """Drop a server's tokens so it counts as disconnected.

    The registered client_id is kept, so reconnecting only needs a fresh sign-in.
    """
    await delete_api_key(f"{_STORE_PREFIX}{server}")
    logger.info(f"Cleared MCP tokens for {server}")


async def register_client(server: str, redirect_uri: str) -> str:
    """Register a client with the server and return its client_id."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            oauth_endpoints(server)["register_url"],
            json={
                "client_name": "daxagent-backend",
                "redirect_uris": [redirect_uri],
                "grant_types": ["authorization_code"],
                "response_types": ["code"],
                "token_endpoint_auth_method": "none",
            },
        )
        resp.raise_for_status()
        return resp.json()["client_id"]


async def build_login_url(server: str, redirect_uri: str) -> str:
    """Register a client, remember its PKCE verifier, and return the login URL."""
    client_id = await register_client(server, redirect_uri)
    verifier = _b64url(os.urandom(32))
    challenge = _b64url(hashlib.sha256(verifier.encode()).digest())
    state = _b64url(os.urandom(16))
    _pending[state] = verifier
    await save_api_key(f"{_STORE_PREFIX}{server}:client_id", client_id)

    params = httpx.QueryParams(
        response_type="code",
        client_id=client_id,
        redirect_uri=redirect_uri,
        code_challenge=challenge,
        code_challenge_method="S256",
        state=state,
    )
    return f"{oauth_endpoints(server)['authorize_url']}?{params}"


async def exchange_code(server: str, code: str, state: str, redirect_uri: str) -> dict:
    """Exchange an authorization code for tokens and persist them."""
    verifier = _pending.pop(state, None)
    if not verifier:
        raise ValueError("Unknown or expired login state; start the login again.")

    client_id = (await load_all_api_keys()).get(f"{_STORE_PREFIX}{server}:client_id")
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            oauth_endpoints(server)["token_url"],
            data={
                "grant_type": "authorization_code",
                "client_id": client_id,
                "code": code,
                "redirect_uri": redirect_uri,
                "code_verifier": verifier,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp.raise_for_status()
        tokens = resp.json()

    await _store(server, tokens)
    logger.info(f"MCP OAuth tokens stored for {server}")
    return tokens


async def get_access_token(server: str) -> str | None:
    """Return a valid access token, refreshing it when it has expired. A server may keep its token in the environment
    (`token_env` in its config block) instead of the database."""
    if token := os.getenv(options(server).get("token_env", "")):
        return token
    tokens = await _load(server)
    if not tokens:
        return None
    if time.time() < tokens.get("expires_at", 0) - 60:
        return tokens.get("access_token")

    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        return None

    client_id = (await load_all_api_keys()).get(f"{_STORE_PREFIX}{server}:client_id")
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            oauth_endpoints(server)["token_url"],
            data={
                "grant_type": "refresh_token",
                "client_id": client_id,
                "refresh_token": refresh_token,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    if resp.status_code != 200:
        logger.warning(f"MCP token refresh failed for {server}: {resp.text[:200]}")
        return None

    refreshed = resp.json()
    refreshed.setdefault("refresh_token", refresh_token)
    await _store(server, refreshed)
    return refreshed.get("access_token")
