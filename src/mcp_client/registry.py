"""Register remote MCP tools with an AutoGen chat agent."""

import inspect
from typing import Any

import autogen
from loguru import logger

from src.mcp_client.client import call_tool, is_connected, list_tools
from src.mcp_client.config import options, server_names

# JSON Schema types -> Python annotations for the generated signature
_JSON_TYPES: dict[str, type] = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "array": list,
    "object": dict,
}


def _py_type(spec: dict[str, Any]) -> type:
    """Python annotation for a JSON-schema property; handles ["string", "null"] style unions."""
    t = spec.get("type")
    if isinstance(t, list):
        t = next((x for x in t if x != "null"), None)
    return _JSON_TYPES.get(t, str) if isinstance(t, str) else str


def _registered_names(agent) -> set[str]:
    tools = (getattr(agent, "llm_config", None) or {}).get("tools") or []
    return {t.get("function", {}).get("name") for t in tools if isinstance(t, dict)}


def _make_caller(server: str, tool: str, input_schema: dict[str, Any]):
    """Build the async function AutoGen calls for one MCP tool.

    AutoGen derives the tool's JSON schema from this function's signature, so
    the MCP input schema is turned into real keyword parameters. With only
    **kwargs the model nests every argument under a single "arguments" object
    and the server rejects the call.
    """

    async def run(**arguments: Any) -> str:
        return await call_tool(server, tool, arguments)

    properties = input_schema.get("properties") or {}
    required = set(input_schema.get("required") or [])
    run.__signature__ = inspect.Signature(
        [
            inspect.Parameter(
                name,
                inspect.Parameter.KEYWORD_ONLY,
                default=inspect.Parameter.empty if name in required else None,
                annotation=_py_type(spec) | None,
            )
            for name, spec in properties.items()
        ],
        return_annotation=str,
    )
    run.__name__ = tool
    return run


async def register_mcp_tools(chat_agent, agent_executor, prompt_agent=None, only: list[str] | None = None, mode: str = "chat") -> int:
    """Register every connected MCP server's tools; return how many were added.

    Servers that have not been signed in are skipped, so chat works normally
    until the user completes the OAuth login.

    Args:
        chat_agent: Agent that may call the tools.
        agent_executor: Agent that runs them.
        prompt_agent: Agent receiving each server's `system_prompt_append`
            (guardrails such as the Data Axle credit gate). Defaults to
            chat_agent; Omni passes the agent that talks to the user, since
            there the caller is not user-facing.
        mode: "chat" or "task"; servers the user switched off for that mode are skipped.
    """
    prompt_agent = prompt_agent or chat_agent
    registered = 0
    # Composio-bridged MCP servers expose the same tools chat mode already has from the
    # Composio SDK; registering them twice doubles the tool list for nothing.
    existing = _registered_names(chat_agent)
    from src.mcp_client.config import in_mode, is_enabled

    for server in server_names():
        if not is_enabled(server) or not in_mode(server, mode) or (only is not None and server not in only):
            continue
        bridged = [t.upper() for t in ((options(server).get("composio") or {}).get("toolkits") or [])]
        have_apps = {n.split("_")[0] for n in existing if n and n[:1].isupper()}
        if bridged and all(t in have_apps for t in bridged):
            logger.info(f"MCP server '{server}' skipped: {', '.join(bridged)} tools are already registered from Composio")
            continue
        if not await is_connected(server):
            logger.info(f"MCP server '{server}' not connected; skipping its tools")
            continue
        try:
            tools = await list_tools(server)
        except Exception as e:
            logger.warning(f"Could not list tools for MCP server '{server}': {e}")
            continue

        skipped = 0
        for tool in tools:
            if tool["name"] in existing:
                skipped += 1
                continue
            existing.add(tool["name"])
            autogen.register_function(
                _make_caller(server, tool["name"], tool["input_schema"]),
                caller=chat_agent,
                executor=agent_executor,
                name=tool["name"],
                description=tool["description"],
            )
            registered += 1
        guardrail = options(server).get("system_prompt_append")
        if guardrail:
            prompt_agent.update_system_message(prompt_agent.system_message + guardrail)
        logger.info(f"Registered {len(tools) - skipped} MCP tools from '{server}'" + (f" ({skipped} already registered)" if skipped else ""))
    return registered
