"""Minimal client for remote (streamable HTTP) MCP servers."""

from typing import Any

from loguru import logger
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from src.mcp_client.config import auth_header_name, auth_type, server_url
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
    if auth_type(server) == "api_key":
        return {auth_header_name(server): token}
    return {"Authorization": f"Bearer {token}"}


async def _session(server: str):
    """Open a session, or raise when the server needs a login."""
    headers = await auth_headers(server)
    return streamablehttp_client(server_url(server), headers=headers or None)


async def list_tools(server: str) -> list[dict[str, Any]]:
    """Return the server's tools as {name, description, input_schema, annotations} dicts."""
    async with await _session(server) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
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


async def call_tool(server: str, tool: str, arguments: dict[str, Any]) -> str:
    """Call one tool and return its output as text."""
    async with await _session(server) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool, arguments)
            texts = [
                block.text
                for block in result.content
                if getattr(block, "type", None) == "text"
            ]
            logger.info(f"MCP {server}.{tool} returned {len(texts)} text block(s)")
            return "\n".join(texts) if texts else str(result.content)
