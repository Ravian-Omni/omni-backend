"""State the in-process tools need: where files go, how to talk to the user,
what the user has approved so far."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from src.agent_runtime.decisions import DecisionCards


@dataclass
class ToolContext:
    chat_id: str
    user_id: str
    persona: str
    chat_dir: str
    working_directory: str
    file_location: str
    artifacts_dir: str
    python_executable: str
    decisions: DecisionCards
    emit: Callable[[dict[str, Any]], Awaitable[None]]
    tool_registry: Any = None  # AsyncToolRegistry with the PTY command executor
    task_id: str | None = None
    call_id: str | None = None
    capability_id: str | None = None
    # Full tool name (mcp__server__tool) -> read | spend | send, for remote servers.
    remote_tool_classes: dict[str, str] = field(default_factory=dict)
    # Approved call counts, keyed by full tool name, consumed by the permission gate.
    spend_allowance: dict[str, int] = field(default_factory=dict)
    send_allowance: dict[str, int] = field(default_factory=dict)

    def resolve_tool(self, short_or_full: str) -> str | None:
        """Find the full name of a known remote tool from its short name."""
        if short_or_full in self.remote_tool_classes:
            return short_or_full
        for full in self.remote_tool_classes:
            if full.endswith("__" + short_or_full):
                return full
        return None
