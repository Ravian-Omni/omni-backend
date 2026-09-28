"""What each user tells the agents to know and do (Settings > Memory and Agents).

Stored per user in ``user_prefs`` as JSON, validated by the models below on every read and write.
Memory and the per-agent instructions are appended to each agent's system prompt.
"""

import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field, TypeAdapter

from src.configs.datetime_utils import dt
from src.database import load_pref, save_pref


class MemoryItem(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    text: str = Field(min_length=1, max_length=500)
    source: Literal["user", "agent"] = "user"
    created_at: str = Field(default_factory=dt.now_iso)


class Memory(BaseModel):
    enabled: bool = True
    items: list[MemoryItem] = Field(default_factory=list, max_length=200)


class AgentPref(BaseModel):
    instructions: str = Field(default="", max_length=2000)


SCHEMAS: dict[str, TypeAdapter] = {
    "memory": TypeAdapter(Memory),
    "agents": TypeAdapter(dict[str, AgentPref]),
}
DEFAULTS: dict[str, Any] = {"memory": {}, "agents": {}}
_version = 0  # bumped on every save, so open sessions know to pick the change up


def version() -> int:
    return _version


async def get(user_id: str, key: str) -> Any:
    schema = SCHEMAS[key]
    return schema.dump_python(schema.validate_python(await load_pref(user_id, key, DEFAULTS[key])))


async def put(user_id: str, key: str, value: Any) -> Any:
    """Validate and store; raises pydantic.ValidationError on a bad value."""
    global _version
    schema = SCHEMAS[key]
    clean = schema.dump_python(schema.validate_python(value))
    await save_pref(user_id, key, clean)
    _version += 1
    return clean


async def memory_notes(user_id: str) -> str:
    """Saved memory as a system prompt section ("" when off or empty)."""
    memory = await get(user_id, "memory")
    if not (memory["enabled"] and memory["items"]):
        return ""
    return ("\n\n## What you know about the user (saved memory)\nUse it, and do not ask the user for anything it already answers.\n"
            + "\n".join(f"- {m['text']}" for m in memory["items"]))


async def prompt_notes(user_id: str, persona: str) -> str:
    """Saved memory and the user's instructions for this agent, as system prompt sections."""
    instructions = ((await get(user_id, "agents")).get(persona) or {}).get("instructions", "").strip()
    return await memory_notes(user_id) + (f"\n\n## The user's standing instructions for you\n{instructions}" if instructions else "")


async def remember(user_id: str, text: str) -> str:
    """Add a fact an agent learned about the user; the reply tells the agent what happened."""
    memory = await get(user_id, "memory")
    if not memory["enabled"]:
        return "Memory is switched off in Settings, so nothing was saved."
    if any(m["text"].lower() == text.lower() for m in memory["items"]):
        return "Already in memory."
    if len(memory["items"]) >= 200:
        return "Memory is full; the user can remove old items in Settings > Memory."
    memory["items"].append({"text": text, "source": "agent"})
    await put(user_id, "memory", memory)
    return f"Saved to memory: {text}"
