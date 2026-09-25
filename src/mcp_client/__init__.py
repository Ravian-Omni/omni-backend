"""Client for remote MCP servers: bundled and runtime-added definitions,
OAuth sign-in, discovery, tool classification and AutoGen registration."""

from src.mcp_client.client import auth_headers, call_tool, is_connected, list_tools
from src.mcp_client.config import auth_type, options, server_names, server_url

__all__ = [
    "auth_headers", "auth_type", "call_tool", "is_connected", "list_tools",
    "options", "server_names", "server_url",
]
