"""Tools that run things: the interactive PTY terminal and Python."""

import os
import uuid

from src.agent_runtime.tools.context import ToolContext


def _text(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}]}


def build(ctx: ToolContext):
    from claude_agent_sdk import tool

    @tool(
        "execute_command",
        "Run a shell command in an interactive terminal the user can see and type into. "
        "Streams output live. Use for installs, builds, tests and scripts.",
        {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "working_dir": {"type": "string", "description": "Defaults to the working directory"},
                "timeout": {"type": "integer", "description": "Seconds; default 120"},
            },
            "required": ["command"],
        },
    )
    async def execute_command(args: dict) -> dict:
        if ctx.tool_registry is None:
            return {"content": [{"type": "text", "text": "No terminal available in this session"}], "is_error": True}
        out = await ctx.tool_registry.execute_command(
            command=args["command"], working_dir=args.get("working_dir"), timeout=int(args.get("timeout") or 120)
        )
        return _text(out if isinstance(out, str) else str(out))

    @tool(
        "run_python",
        "Run Python code in the project environment and return its output. The code is saved to a file "
        "under the working directory first, so it can be re-run or edited.",
        {
            "type": "object",
            "properties": {
                "code": {"type": "string"},
                "filename": {"type": "string", "description": "Optional name for the script, e.g. profile_leads.py"},
                "timeout": {"type": "integer", "description": "Seconds; default 300"},
            },
            "required": ["code"],
        },
    )
    async def run_python(args: dict) -> dict:
        if ctx.tool_registry is None:
            return {"content": [{"type": "text", "text": "No terminal available in this session"}], "is_error": True}
        scripts = os.path.join(ctx.working_directory, "scripts")
        os.makedirs(scripts, exist_ok=True)
        name = args.get("filename") or f"snippet_{uuid.uuid4().hex[:6]}.py"
        if not name.endswith(".py"):
            name += ".py"
        path = os.path.join(scripts, os.path.basename(name))
        with open(path, "w") as f:
            f.write(args["code"])
        out = await ctx.tool_registry.execute_command(
            command=f'"{ctx.python_executable}" "{path}"',
            working_dir=ctx.working_directory,
            timeout=int(args.get("timeout") or 300),
        )
        return _text(f"[script: {path}]\n{out}")

    return [execute_command, run_python]
