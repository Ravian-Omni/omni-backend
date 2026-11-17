"""Minimal client for remote (streamable HTTP) MCP servers."""

import asyncio
import re
import time
from typing import Any

from loguru import logger
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from src.mcp_client.config import auth_header_name, auth_type, options, server_url
from src.mcp_client.oauth import get_access_token


async def is_connected(server: str) -> bool:
    """True when the server can be called: it needs no login, or the user signed in."""
    if auth_type(server) == "none":
        return True
    return await get_access_token(server) is not None


async def auth_headers(server: str) -> dict[str, str]:
    """Headers to send to the server, or an empty dict when it needs none.

    Raises:
        PermissionError: when the server needs a login the user has not done.
    """
    if auth_type(server) == "none":
        return {}
    token = await get_access_token(server)
    if not token:
        raise PermissionError(f"{server} is not connected. Visit /mcp/auth/{server} to sign in.")
    # A pasted key may carry quotes, spaces or its own "Bearer " (sent as "Bearer Bearer kw_...", MarketWatch says Invalid token)
    token = re.sub(r"^bearer\s+", "", token.strip().strip("\"'").strip(), flags=re.I)
    if auth_type(server) == "api_key":
        return {auth_header_name(server): token}
    return {"Authorization": f"Bearer {token}"}


async def _session(server: str):
    """Open a session, or raise when the server needs a login."""
    headers = await auth_headers(server)
    return streamablehttp_client(server_url(server), headers=headers or None)


_TOOLS_TTL_S = 300  # a tool list rarely changes; listing a remote server costs 2-3 s
_tools_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}


_refreshing: set[str] = set()


async def _refresh_tools(server: str) -> list[dict[str, Any]]:
    try:
        tools = await _fetch_tools(server)
        _tools_cache[server] = (time.monotonic(), tools)
        return tools
    finally:
        _refreshing.discard(server)


async def refresh_tools(server: str) -> list[dict[str, Any]]:
    """Re-list the server now and replace the cached entry: for when its tools changed."""
    _tools_cache.pop(server, None)
    return await _refresh_tools(server)


def listed_tool_names(server: str) -> set[str]:
    """The server's tool names as last listed (at start-up, then on use); empty before any listing. Never waits."""
    return {t["name"] for t in (_tools_cache.get(server) or (0, []))[1]}


async def list_tools(server: str) -> list[dict[str, Any]]:
    """Return the server's tools as {name, description, input_schema, annotations} dicts.

    Served from a cache; an entry older than 5 minutes is still returned at once and
    refreshed in the background, so nobody waits for a listing after the first one.
    """
    hit = _tools_cache.get(server)
    if hit:
        if time.monotonic() - hit[0] > _TOOLS_TTL_S and server not in _refreshing:
            _refreshing.add(server)
            asyncio.create_task(_refresh_tools(server))
        return hit[1]
    return await _refresh_tools(server)


# What each server says about itself on initialize(): its instructions are the agents' guidance
# on when to call it, published by the server rather than written into our config.
_instructions: dict[str, str] = {}
_server_info: dict[str, dict[str, str]] = {}


def server_instructions(server: str) -> str:
    """The server's initialize() instructions, once it has been listed; empty when it publishes none."""
    return _instructions.get(server, "").strip()


def server_notes(server: str) -> str:
    """The server's own guidance for agents, as a prompt section; empty when it publishes none."""
    text = server_instructions(server)
    if not text:
        return ""
    display = options(server).get("display_name", server)
    return f"\n\n## {display} (from its MCP server)\n{text}\n"


def server_info(server: str) -> dict[str, str]:
    """The server's published name and version, once it has been listed."""
    return _server_info.get(server, {})


async def _fetch_tools(server: str) -> list[dict[str, Any]]:
    async with await _session(server) as (read, write, _):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            _instructions[server] = init.instructions or ""
            _server_info[server] = {"name": init.serverInfo.name, "version": init.serverInfo.version or ""}
            result = await session.list_tools()
            return [
                {
                    "name": tool.name,
                    "description": tool.description or "",
                    "input_schema": tool.inputSchema or {},
                    "annotations": tool.annotations.model_dump(exclude_none=True) if tool.annotations else {},
                }
                for tool in result.tools
            ]


class _Connection:
    """One open session to a server, owned by one background task that runs calls from a queue.

    The streamable-HTTP client must be entered and exited in the same task, so a single
    owner task keeps it open; opening a session per call costs ~3 s, a reused one ~0.5 s.
    """

    IDLE_S = 600

    def __init__(self, server: str):
        self.server = server
        self.queue: asyncio.Queue = asyncio.Queue()
        self.task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        try:
            async with await _session(self.server) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    while True:
                        try:
                            tool, arguments, future = await asyncio.wait_for(self.queue.get(), self.IDLE_S)
                        except asyncio.TimeoutError:
                            return  # idle: close; the next call reopens
                        try:
                            future.set_result(await session.call_tool(tool, arguments))
                        except Exception as e:
                            future.set_exception(e)
        except Exception as e:
            logger.warning(f"MCP connection to {self.server} closed: {e}")
        finally:
            while not self.queue.empty():  # fail waiting calls so callers can retry on a new connection
                *_, future = self.queue.get_nowait()
                if not future.done():
                    future.set_exception(ConnectionError(f"MCP connection to {self.server} closed"))

    async def call(self, tool: str, arguments: dict[str, Any]):
        future = asyncio.get_running_loop().create_future()
        await self.queue.put((tool, arguments, future))
        return await future


_connections: dict[str, _Connection] = {}


def _connection(server: str) -> _Connection:
    conn = _connections.get(server)
    if conn is None or conn.task.done():
        conn = _connections[server] = _Connection(server)
    return conn


def warm(server: str) -> None:
    """Open the server's connection ahead of the first tool call."""
    _connection(server)


async def call_tool(server: str, tool: str, arguments: dict[str, Any]) -> str:
    """Call one tool over the server's open connection and return its output as text."""
    try:
        result = await _connection(server).call(tool, arguments)
    except ConnectionError:
        result = await _connection(server).call(tool, arguments)  # the old connection died: one retry on a new one
    texts = [block.text for block in result.content if getattr(block, "type", None) == "text"]
    logger.info(f"MCP {server}.{tool} returned {len(texts)} text block(s)")
    return "\n".join(texts) if texts else str(result.content)
