"""Work out how to talk to an MCP server the user just pasted a URL for.

Follows the MCP authorization flow: an unauthenticated request either succeeds
(no auth needed) or returns 401 with a ``WWW-Authenticate`` header pointing at
the protected-resource metadata, which names the authorization server, whose
``/.well-known/oauth-authorization-server`` document gives the authorize,
token and registration endpoints. Servers that skip the header are probed at
the well-known paths on their origin.
"""

import re
from typing import Any
from urllib.parse import urlparse

import httpx
from loguru import logger


async def _get_json(client: httpx.AsyncClient, url: str) -> dict | None:
    try:
        resp = await client.get(url, headers={"Accept": "application/json"})
        if resp.status_code == 200 and "json" in resp.headers.get("content-type", ""):
            return resp.json()
    except httpx.HTTPError as e:
        logger.debug(f"MCP discovery: {url} -> {e}")
    return None


async def _try_unauthenticated(url: str) -> tuple[bool, list[dict]]:
    """Return (works_without_auth, tools) by attempting a real MCP handshake."""
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    try:
        async with streamablehttp_client(url) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.list_tools()
                return True, [
                    {
                        "name": t.name,
                        "description": t.description or "",
                        "input_schema": t.inputSchema or {},
                        "annotations": t.annotations.model_dump() if t.annotations else {},
                    }
                    for t in result.tools
                ]
    except Exception as e:  # 401, connection errors, protocol errors
        logger.info(f"MCP discovery: {url} needs auth or is unreachable ({type(e).__name__}: {e})")
        return False, []


async def discover(url: str) -> dict[str, Any]:
    """Describe a server: whether it needs OAuth and, if so, its endpoints.

    Returns:
        ``{"auth": "none", "tools": [...]}`` when the server answers without
        credentials, or ``{"auth": "oauth", "oauth": {authorize_url, token_url,
        register_url?}}`` when it publishes OAuth metadata.

    Raises:
        ValueError: when the server needs auth but its OAuth metadata cannot be
            found, so the user has to supply endpoints or a token by hand.
    """
    open_access, tools = await _try_unauthenticated(url)
    if open_access:
        return {"auth": "none", "tools": tools}

    parsed = urlparse(url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        resource_meta = None
        # 1. WWW-Authenticate: Bearer resource_metadata="..."
        try:
            resp = await client.post(url, json={"jsonrpc": "2.0", "id": 1, "method": "initialize"})
            header = resp.headers.get("www-authenticate", "")
            m = re.search(r'resource_metadata="([^"]+)"', header)
            if m:
                resource_meta = await _get_json(client, m.group(1))
        except httpx.HTTPError:
            pass
        # 2. Well-known protected resource metadata on the origin (path-aware, then root).
        if resource_meta is None:
            for candidate in (
                f"{origin}/.well-known/oauth-protected-resource{parsed.path}",
                f"{origin}/.well-known/oauth-protected-resource",
            ):
                resource_meta = await _get_json(client, candidate)
                if resource_meta:
                    break
        auth_servers = (resource_meta or {}).get("authorization_servers") or [origin]

        for auth_server in auth_servers:
            as_origin = auth_server.rstrip("/")
            as_path = urlparse(as_origin).path
            as_root = f"{urlparse(as_origin).scheme}://{urlparse(as_origin).netloc}"
            for candidate in (
                f"{as_root}/.well-known/oauth-authorization-server{as_path}",
                f"{as_root}/.well-known/oauth-authorization-server",
                f"{as_root}/.well-known/openid-configuration",
            ):
                meta = await _get_json(client, candidate)
                if meta and meta.get("authorization_endpoint") and meta.get("token_endpoint"):
                    oauth = {
                        "authorize_url": meta["authorization_endpoint"],
                        "token_url": meta["token_endpoint"],
                    }
                    if meta.get("registration_endpoint"):
                        oauth["register_url"] = meta["registration_endpoint"]
                    return {"auth": "oauth", "oauth": oauth}

    raise ValueError(
        "The server requires authentication but does not publish OAuth metadata. "
        "Add it with explicit authorize/token URLs or a bearer token."
    )
