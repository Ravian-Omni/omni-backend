"""Saved memory: lasting facts about the user that every agent reads (managed in Settings > Memory)."""

from src.agent_runtime import prefs
from src.agent_runtime.tools.artifacts import _error, _text
from src.agent_runtime.tools.context import ToolContext


def build(ctx: ToolContext):
    from claude_agent_sdk import tool

    @tool(
        "remember",
        "Save one lasting fact or preference the user told you about themselves, their company or how they want "
        "work done (e.g. 'Sells dental supplies in Texas', 'Signs emails as Sam Lee'). One short sentence. Not for "
        "one-off task details, contact data or secrets. Every agent reads saved memory in later chats and tasks.",
        {"type": "object", "properties": {"text": {"type": "string", "description": "One short sentence about the user"}}, "required": ["text"]},
    )
    async def remember(args: dict) -> dict:
        text = " ".join(str(args.get("text") or "").split())[:500]
        return _text(await prefs.remember(ctx.user_id, text)) if text else _error("text is empty")

    return [remember]
