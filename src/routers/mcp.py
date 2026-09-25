"""Endpoints for MCP servers: sign-in, runtime add/remove, tool classes."""

import re
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from loguru import logger
from pydantic import BaseModel, Field

from src.database import load_mcp_tool_classes, save_mcp_tool_class
from src.mcp_client import auth_type, call_tool, is_connected, list_tools, options, server_names, server_url
from src.mcp_client.classify import TOOL_CLASSES, classify_tool
from src.mcp_client.config import add_server, is_bundled, is_enabled, is_reserved, remove_server, set_enabled, specialist_eligible
from src.agent_runtime import specialists
from src.agent_runtime.specialists import specialist_name
from src.mcp_client.discovery import discover
from src.mcp_client.oauth import (
    build_login_url,
    exchange_code,
    forget_tokens,
    store_static_token,
)

router = APIRouter()


def _redirect_uri(request: Request, server: str) -> str:
    """The callback URL this server is registered with."""
    return str(request.base_url).rstrip("/") + f"/mcp/callback/{server}"


def _require(server: str) -> None:
    if server not in server_names():
        raise HTTPException(status_code=404, detail=f"Unknown MCP server: {server}")


async def _describe(name: str) -> dict[str, Any]:
    opts = options(name)
    return {
        "name": name,
        "url": server_url(name),
        "display_name": opts.get("display_name", name),
        "description": opts.get("description", ""),
        "icon": opts.get("icon", ""),
        "auth": auth_type(name),
        "personas": opts.get("personas"),
        "bundled": is_bundled(name),
        "connected": await is_connected(name),
        "enabled": is_enabled(name),
        "reserved": is_reserved(name),
        "specialist": specialist_name(name) if specialist_eligible(name) else None,
    }


async def _tools_with_classes(server: str) -> list[dict[str, Any]]:
    overrides = await load_mcp_tool_classes(server)
    tools = await list_tools(server)
    for t in tools:
        t["class"] = classify_tool(t["name"], t["description"], t.get("annotations"), overrides.get(t["name"]))
        t["class_overridden"] = t["name"] in overrides
    return tools


@router.get("/servers")
async def list_servers():
    """List every MCP server (bundled and user-added) with its connection state."""
    return {"servers": [await _describe(name) for name in server_names()]}


class NewServer(BaseModel):
    """A server the user adds from the UI by pasting its URL."""

    url: str
    name: str | None = None
    display_name: str | None = None
    description: str | None = None
    auth: str | None = Field(default=None, description="none | oauth | bearer | api_key; discovered when omitted")
    token: str | None = Field(default=None, description="Token when auth is 'bearer' or 'api_key'")
    header_name: str | None = Field(default=None, description="Header for api_key auth, default x-api-key")
    authorize_url: str | None = None
    token_url: str | None = None
    register_url: str | None = None
    personas: list[str] | None = None
    planner_note: str | None = None
    system_prompt_append: str | None = None


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "server"


@router.post("/servers")
async def create_server(body: NewServer):
    """Add an MCP server at runtime.

    Discovers how the server authenticates unless the caller says. Servers
    that answer without credentials are usable at once; OAuth servers show up
    as disconnected until the user signs in; bearer servers store the token.
    """
    url = body.url.strip()
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="URL must start with http:// or https://")
    name = _slug(body.name or body.display_name or re.sub(r"^https?://", "", url).split("/")[0])
    if name in server_names():
        raise HTTPException(status_code=409, detail=f"An MCP server named '{name}' already exists")

    daxagent: dict[str, Any] = {
        "display_name": body.display_name or body.name or name,
        "description": body.description or "",
        "icon": "",
    }
    for key in ("personas", "planner_note", "system_prompt_append"):
        value = getattr(body, key)
        if value:
            daxagent[key] = value

    auth = body.auth
    discovered_tools: list[dict] = []
    if auth == "oauth" or (auth is None and body.authorize_url and body.token_url):
        daxagent["auth"] = "oauth"
        daxagent["oauth"] = {"authorize_url": body.authorize_url, "token_url": body.token_url}
        if body.register_url:
            daxagent["oauth"]["register_url"] = body.register_url
        if not (body.authorize_url and body.token_url):
            raise HTTPException(status_code=400, detail="OAuth servers need authorize_url and token_url")
    elif auth in ("bearer", "api_key"):
        if not body.token:
            raise HTTPException(status_code=400, detail=f"{auth} auth needs a token")
        daxagent["auth"] = auth
        if auth == "api_key":
            daxagent["header"] = body.header_name or "x-api-key"
    elif auth == "none":
        daxagent["auth"] = "none"
    else:
        try:
            found = await discover(url)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        daxagent["auth"] = found["auth"]
        if found["auth"] == "oauth":
            daxagent["oauth"] = found["oauth"]
        else:
            discovered_tools = found.get("tools", [])

    await add_server(name, {"url": url, "daxagent": daxagent})
    if auth in ("bearer", "api_key"):
        await store_static_token(name, body.token)
    logger.info(f"MCP server '{name}' added ({daxagent['auth']} auth)")
    await specialists.refresh()
    described = await _describe(name)
    described["tools"] = [t["name"] for t in discovered_tools]
    return described


class ServerUpdate(BaseModel):
    enabled: bool | None = Field(default=None, description="Switch the server on or off for chat, tasks and personas")
    display_name: str | None = None
    description: str | None = None
    personas: list[str] | None = None
    planner_note: str | None = None
    system_prompt_append: str | None = None


@router.put("/servers/{server}")
async def update_server(server: str, body: ServerUpdate):
    """Change a server's display fields, persona access or prompt notes."""
    _require(server)
    fields = body.model_dump(exclude_none=True)
    enabled = fields.pop("enabled", None)
    if enabled is not None:
        await set_enabled(server, enabled)
    if fields:
        if is_bundled(server):
            raise HTTPException(status_code=400, detail="Bundled servers are edited in configs/mcp_servers.json (only the on/off switch is stored)")
        from src.mcp_client.config import _config

        config = dict(_config()[server])
        daxagent = dict(config.get("daxagent", {}))
        daxagent.update(fields)
        config["daxagent"] = daxagent
        await add_server(server, config)
    await specialists.refresh()
    return await _describe(server)


@router.delete("/servers/{server}")
async def delete_server(server: str):
    """Forget a user-added server, its tokens and its tool settings."""
    _require(server)
    if is_bundled(server):
        raise HTTPException(status_code=400, detail="Bundled servers cannot be removed, only disconnected")
    composio_id = (options(server).get("composio") or {}).get("server_id")
    await forget_tokens(server)
    await remove_server(server)
    if composio_id:
        try:
            client, _ = _composio_client()
            result = client.mcp.delete(composio_id)
            logger.info(f"Composio MCP server {composio_id} deleted: {result}")
        except Exception as e:
            logger.warning(f"Composio MCP server {composio_id} not deleted: {e}")
    await specialists.refresh()
    return {"success": True, "server": server, "composio_server_deleted": bool(composio_id)}


@router.get("/status/{server}")
async def server_status(server: str):
    """Report whether one server is connected, and what it exposes."""
    _require(server)
    if not await is_connected(server):
        return {"server": server, "status": "INITIATED", "tool_count": 0}
    try:
        tools = await list_tools(server)
    except Exception as e:
        logger.warning(f"MCP server '{server}' connected but tools unavailable: {e}")
        return {"server": server, "status": "ACTIVE", "tool_count": 0, "error": str(e)}
    return {"server": server, "status": "ACTIVE", "tool_count": len(tools), "tools": [t["name"] for t in tools]}


@router.get("/auth/{server}")
async def start_auth(server: str, request: Request):
    """Redirect the browser to the provider's sign-in page."""
    _require(server)
    try:
        url = await build_login_url(server, _redirect_uri(request, server))
    except Exception as e:
        logger.error(f"MCP login could not start for {server}: {e}")
        raise HTTPException(status_code=502, detail=f"Could not start login: {e}")
    return RedirectResponse(url)


@router.post("/connect/{server}")
async def connect(server: str, request: Request):
    """Start a sign-in and return its URL (mirrors the Composio connect endpoint)."""
    _require(server)
    if await is_connected(server):
        return {"success": True, "server": server, "status": "ACTIVE", "message": f"{server} is already connected"}
    if auth_type(server) != "oauth":
        return {"success": False, "server": server, "error": f"{server} does not use OAuth; supply a token instead"}
    try:
        url = await build_login_url(server, _redirect_uri(request, server))
    except Exception as e:
        logger.error(f"MCP login could not start for {server}: {e}")
        return {"success": False, "server": server, "error": str(e)}
    return {"success": True, "server": server, "status": "INITIATED", "redirect_url": url}


@router.get("/callback/{server}", response_class=HTMLResponse)
async def auth_callback(server: str, request: Request, code: str = "", state: str = ""):
    """Exchange the authorization code for tokens and report the result."""
    if not code:
        return HTMLResponse("<h3>Sign-in failed: no authorization code.</h3>", status_code=400)
    try:
        await exchange_code(server, code, state, _redirect_uri(request, server))
        tools = await list_tools(server)
        await specialists.refresh()
        names = ", ".join(t["name"] for t in tools)
        return HTMLResponse(
            "<body style=\"font:15px -apple-system,sans-serif;text-align:center;padding:3rem\">"
            f"<h3>&#10003; {server} connected</h3>"
            f"<p>{len(tools)} tools are now available: {names}</p>"
            "<p style=\"color:#666\">Returning to DAXAGENT&hellip;</p>"
            "<script>setTimeout(function(){window.close()},2000)</script>"
            "</body>"
        )
    except Exception as e:
        logger.error(f"MCP callback failed for {server}: {e}")
        return HTMLResponse(f"<h3>Sign-in failed:</h3><pre>{e}</pre>", status_code=502)


@router.post("/disconnect/{server}")
async def disconnect(server: str):
    """Forget a server's tokens. Its tools disappear from new sessions."""
    _require(server)
    await forget_tokens(server)
    await specialists.refresh()
    return {"success": True, "server": server, "message": f"{server} disconnected"}


@router.get("/tools/{server}")
async def server_tools(server: str):
    """List a connected server's tools with their confirmation class."""
    _require(server)
    try:
        return {"server": server, "tools": await _tools_with_classes(server)}
    except PermissionError as e:
        raise HTTPException(status_code=401, detail=str(e))


class ToolClassUpdate(BaseModel):
    tool_class: str | None = Field(default=None, description="read | spend | send, or null to reset")


@router.put("/servers/{server}/tools/{tool}")
async def set_tool_class(server: str, tool: str, body: ToolClassUpdate):
    """Override how a tool is classed for confirmations."""
    _require(server)
    if body.tool_class is not None and body.tool_class not in TOOL_CLASSES:
        raise HTTPException(status_code=400, detail=f"tool_class must be one of {TOOL_CLASSES}")
    await save_mcp_tool_class(server, tool, body.tool_class)
    return {"server": server, "tool": tool, "tool_class": body.tool_class}


@router.get("/credits/{server}")
async def credits(server: str):
    """Ask a server for its credit balance, when it has a balance tool."""
    _require(server)
    if not await is_connected(server):
        raise HTTPException(status_code=401, detail=f"{server} is not connected")
    tools = {t["name"] for t in await list_tools(server)}
    balance_tool = next((t for t in ("fetch_available_credits", "get_credits", "credit_balance") if t in tools), None)
    if not balance_tool:
        return {"server": server, "credits": None}
    raw = await call_tool(server, balance_tool, {})
    match = re.search(r'"availableCredits"\s*:\s*(\d+)', raw) or re.search(r"(\d+)", raw)
    return {"server": server, "credits": int(match.group(1)) if match else None, "raw": raw[:500]}


# ---------------------------------------------------------------------------
# Composio bridge: turn the user's Composio toolkits into MCP servers
# ---------------------------------------------------------------------------

COMPOSIO_MCP_USER = "local_user"


def _composio_client():
    from composio import Composio

    from src.configs.llm_configs_manager import LLMConfigManager

    key = LLMConfigManager.get_config("composio_api_key").get("config_list", [{}])[0].get("api_key")
    if not key:
        raise HTTPException(status_code=400, detail="Composio API key not set. Add it in Settings.")
    return Composio(api_key=key), key


@router.get("/composio/toolkits")
async def composio_toolkits():
    """Toolkits the user's Composio account can expose as MCP servers.

    One entry per toolkit with an auth config; ``connected`` says whether the
    local user has an active account on it (tools of unconnected toolkits
    ask for a sign-in the first time they run).
    """
    import asyncio

    client, _ = _composio_client()
    try:
        auth_configs, connections = await asyncio.gather(
            asyncio.to_thread(client.auth_configs.list),
            asyncio.to_thread(client.connected_accounts.list, user_ids=[COMPOSIO_MCP_USER]),
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Composio error: {e}")
    active = {c.auth_config.id for c in connections.items if c.status == "ACTIVE" and getattr(c, "auth_config", None)}
    by_toolkit: dict[str, dict[str, Any]] = {}
    for ac in auth_configs.items:
        slug = getattr(getattr(ac, "toolkit", None), "slug", None) or str(getattr(ac, "toolkit", ""))
        if not slug:
            continue
        entry = by_toolkit.setdefault(slug, {"toolkit": slug, "auth_config": None, "connected": False, "candidates": []})
        # Rank: connected first, then Composio-managed and enabled, then the rest.
        rank = (
            0 if ac.id in active else
            1 if getattr(ac, "is_composio_managed", False) and str(getattr(ac, "status", "ENABLED")).upper() == "ENABLED" else
            2
        )
        entry["candidates"].append((rank, ac.id))
    for entry in by_toolkit.values():
        entry["candidates"].sort()
        entry["connected"] = entry["candidates"][0][0] == 0
        entry["auth_config"] = entry["candidates"][0][1]
        entry["candidates"] = [c[1] for c in entry["candidates"]]
    return {"toolkits": sorted(by_toolkit.values(), key=lambda t: (not t["connected"], t["toolkit"]))}


class ComposioServer(BaseModel):
    toolkits: list[str] = Field(..., min_length=1, description="Composio toolkit slugs, e.g. ['hubspot', 'apollo']")
    name: str | None = None
    allowed_tools: list[str] | None = Field(default=None, description="Restrict to these tool slugs")
    personas: list[str] | None = None


@router.post("/composio")
async def create_composio_server(body: ComposioServer):
    """Create a Composio MCP server for the given toolkits and register it here.

    Composio hosts the server; it authenticates with the Composio API key in
    the x-api-key header and binds the user's connected accounts through the
    user_id in the URL. Deleting the server here deletes it in Composio too.
    """
    import asyncio

    client, api_key = _composio_client()
    listing = await composio_toolkits()
    known = {t["toolkit"]: t for t in listing["toolkits"]}
    metas: dict[str, Any] = {}
    for slug in body.toolkits:
        try:
            tk = await asyncio.to_thread(client.toolkits.get, slug)
            meta = getattr(tk, "meta", None)
            metas[slug] = {
                "name": getattr(tk, "name", None) or slug,
                "description": getattr(meta, "description", "") or "",
                "logo": getattr(meta, "logo", "") or "",
            }
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Composio has no toolkit '{slug}': {str(e)[:120]}")
        if slug not in known:
            # No auth config yet: create a Composio-managed one so the user can sign in on first use.
            try:
                created_ac = await asyncio.to_thread(
                    client.auth_configs.create, toolkit=slug, options={"type": "use_composio_managed_auth"}
                )
                known[slug] = {"toolkit": slug, "auth_config": created_ac.id, "connected": False}
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Could not create a Composio auth config for '{slug}': {str(e)[:160]}")
    slug = _slug(body.name or "composio-" + "-".join(body.toolkits))
    if slug in server_names():
        raise HTTPException(status_code=409, detail=f"An MCP server named '{slug}' already exists")
    # Composio rejects server names longer than 30 characters; keep them short and unique.
    import hashlib

    composio_name = ("dax-" + re.sub(r"[^a-z0-9]+", "-", "-".join(body.toolkits)))[:20].rstrip("-") + "-" + hashlib.sha1(slug.encode()).hexdigest()[:5]
    try:
        created, last_error = None, None
        # Try each toolkit's auth-config candidates in rank order until Composio accepts.
        import itertools

        candidate_lists = [known[t].get("candidates") or [known[t]["auth_config"]] for t in body.toolkits]
        for combo in itertools.islice(itertools.product(*candidate_lists), 6):
            try:
                created = await asyncio.to_thread(
                    client.mcp.create,
                    name=composio_name,
                    toolkits=[{"toolkit": t, "auth_config_id": ac} for t, ac in zip(body.toolkits, combo)],
                    allowed_tools=body.allowed_tools,
                )
                break
            except Exception as e:
                last_error = e
                logger.warning(f"Composio MCP create failed with auth configs {combo}: {e}")
        if created is None:
            raise last_error or RuntimeError("no auth config accepted")
        server_id = getattr(created, "id", None) or created["id"]
        instance = await asyncio.to_thread(client.mcp.generate, user_id=COMPOSIO_MCP_USER, mcp_config_id=server_id)
        url = getattr(instance, "url", None) or (instance.get("url") if isinstance(instance, dict) else None)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Composio could not create the MCP server: {e}")
    if not url:
        url = f"https://backend.composio.dev/v3/mcp/{server_id}?user_id={COMPOSIO_MCP_USER}"
    names = [metas[t]["name"] for t in body.toolkits]
    daxagent: dict[str, Any] = {
        "display_name": body.name or ", ".join(names),
        "description": "Composio-hosted MCP server for " + ", ".join(names) + ". "
        + " ".join(metas[t]["description"] for t in body.toolkits if metas[t]["description"]),
        "icon": next((metas[t]["logo"] for t in body.toolkits if metas[t]["logo"]), ""),
        "auth": "api_key",
        "header": "x-api-key",
        "composio": {"server_id": server_id, "toolkits": body.toolkits, "user_id": COMPOSIO_MCP_USER},
    }
    if body.personas:
        daxagent["personas"] = body.personas
    await add_server(slug, {"url": url, "daxagent": daxagent})
    await store_static_token(slug, api_key)
    logger.info(f"Composio MCP server '{slug}' registered ({server_id}) for {body.toolkits}")
    await specialists.refresh()
    described = await _describe(slug)
    try:
        described["tools"] = [t["name"] for t in await list_tools(slug)]
    except Exception as e:
        described["tools_error"] = str(e)
    return described
