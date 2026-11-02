"""Hands a data file to Newton, the Data Analyst's data-science engine, without the file passing through the model.

Newton's own upload tools take the file's content inside the call, which a model cannot write for a real
dataset; this tool reads the file here and sends it straight to the server.
"""

import base64
import os

from src.agent_runtime.tools.artifacts import _error, _text
from src.agent_runtime.tools.context import ToolContext
from src.agent_runtime.tools.files import _resolve

SERVER = "newton"  # the name Newton was added under in Settings > Connections
# shortcut: the whole file goes in one MCP request (base64), fine up to ~50 MB; stream it if bigger files matter
MAX_BYTES = 50_000_000


def build(ctx: ToolContext):
    from claude_agent_sdk import tool

    from src.mcp_client import call_tool

    @tool(
        "newton_upload",
        "Send a data file to Newton: into a new project (give title and problem) or an existing one (project_id). "
        "Pass only the file's path; DAXAGENT reads it. Returns Newton's reply with the project_id for ask, get_answer and the rest.",
        {"type": "object", "properties": {
            "path": {"type": "string", "description": "The file's path: an attached file or an exported artifact"},
            "project_id": {"type": "string", "description": "Add the file to this Newton project; omit to create one"},
            "title": {"type": "string", "description": "The new project's name"},
            "problem": {"type": "string", "description": "What the new project is for, e.g. 'What drives restaurant ratings'"},
        }, "required": ["path"]},
    )
    async def newton_upload(args: dict) -> dict:
        try:
            path = _resolve(ctx, str(args["path"]))
        except ValueError as e:
            return _error(str(e))
        if not os.path.isfile(path):
            return _error(f"No file at {args['path']}")
        if os.path.getsize(path) > MAX_BYTES:
            return _error(f"{os.path.basename(path)} is over {MAX_BYTES // 1_000_000} MB: upload it in Newton itself, then use its project_id")
        with open(path, "rb") as f:
            data = {"filename": os.path.basename(path), "content_base64": base64.b64encode(f.read()).decode()}
        if args.get("project_id"):
            name, payload = "upload_data", {"project_id": args["project_id"], **data}
        else:
            name, payload = "create_project", {"title": args.get("title") or "", "problem": args.get("problem") or "", **data}
        ctx.data_sources.add(SERVER)
        try:
            return _text(await call_tool(SERVER, name, payload))
        except Exception as e:
            return _error(f"Newton did not take the file: {e}")

    return [newton_upload]
