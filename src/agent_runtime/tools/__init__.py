"""The in-process MCP server every persona session gets ("daxagent").

``build_server`` returns the SDK server config, the full names of its tools,
and each tool's confirmation class so the session's permission gate knows
which calls to stop for a card.
"""

from claude_agent_sdk import create_sdk_mcp_server

from src.agent_runtime.tools import artifacts, sales, viz, workspace
from src.agent_runtime.tools.context import ToolContext

SERVER_NAME = "daxagent"

# Tools that leave the system or spend money. Everything else is "read".
TOOL_CLASSES = {
    "gmail_send_email": "send",
    "gmail_create_draft": "send",
}


def full_name(short: str) -> str:
    return f"mcp__{SERVER_NAME}__{short}"


def build_server(ctx: ToolContext):
    tools = [*workspace.build(ctx), *artifacts.build(ctx), *viz.build(ctx), *sales.build(ctx)]
    server = create_sdk_mcp_server(name=SERVER_NAME, version="1.0.0", tools=tools)
    names = [t.name for t in tools]
    classes = {full_name(n): TOOL_CLASSES.get(n, "read") for n in names}
    return server, names, classes


__all__ = ["SERVER_NAME", "ToolContext", "build_server", "full_name"]
