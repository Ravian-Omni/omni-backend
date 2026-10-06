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


class TeamMember(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    email: str = Field(default="", max_length=200)
    slack: str = Field(default="", max_length=120)  # Slack member id or @handle


class Team(BaseModel):
    """Who answers the replies the agents hand off (Settings, Team)."""

    members: list[TeamMember] = Field(default_factory=list, max_length=100)
    default_owner: str = ""  # a member's name; "" = the shared inbox (whoever claims it)
    account_owners: dict[str, str] = Field(default_factory=dict)  # email domain -> member name
    slack_channel: str = Field(default="", max_length=120)  # where shared-inbox handoffs are posted, e.g. #sales-replies
    notify_slack: bool = True  # tell the owner on Slack (needs Slack connected in Settings, Connections)
    notify_email: bool = True  # and by email, from the user's connected Gmail


class InboxRules(BaseModel):
    """How Jev's reading of a reply becomes a route (Settings, Inbox). Probabilities are 0..1."""

    handoff: float = Field(0.7, ge=0, le=1)  # needs_human at or above this: a person answers
    suppress: float = Field(0.9, ge=0, le=1)  # unsubscribe / out of office this sure: handled without anyone
    meeting: float = Field(0.8, ge=0, le=1)  # interested and asking to meet: draft meeting times
    urgent: float = Field(0.75, ge=0, le=1)  # urgency at or above this: a person answers now
    confident: float = Field(0.5, ge=0, le=1)  # Jev less sure of the intent than this: a person reads it
    snooze_days: int = Field(90, ge=1, le=365)  # "not now" comes back after this many days
    # The reply watcher: checks every sent campaign thread on its own, no task needed.
    watch: bool = False
    every_minutes: int = Field(5, ge=1, le=120)
    work_start: int = Field(8, ge=0, le=23)  # local hours it runs in
    work_end: int = Field(19, ge=1, le=24)
    weekends: bool = False
    dry_run: bool = False  # read and route, but record nothing, open no handoffs and tell no one


SCHEMAS: dict[str, TypeAdapter] = {
    "memory": TypeAdapter(Memory),
    "agents": TypeAdapter(dict[str, AgentPref]),
    "team": TypeAdapter(Team),
    "inbox": TypeAdapter(InboxRules),
}
DEFAULTS: dict[str, Any] = {"memory": {}, "agents": {}, "team": {}, "inbox": {}}
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
