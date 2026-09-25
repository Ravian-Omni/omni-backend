"""One sub-agent per MCP server ("specialists").

Every enabled, connected MCP server that is not reserved for the sales
personas gets its own persona, generated from the server's tool list: the
planner can delegate to it like any other capability, only that agent loads
that server's tools, and the read/spend/send classes gate its calls. Data Axle
is reserved, so the lead, buyer and enrichment personas keep using it directly.
"""

import re
from typing import Any

from loguru import logger

from src.agent_runtime import prompts
from src.agent_runtime.personas import COMMON_TOOLS, Persona
from src.database import load_mcp_tool_classes
from src.mcp_client import is_connected, list_tools, options, server_names
from src.mcp_client.classify import classify_tool
from src.mcp_client.config import specialist_eligible

_cache: dict[str, Persona] = {}
_by_server: dict[str, str] = {}

SPECIALIST_PROMPT = """You are DAXAGENT's {display_name} specialist: the one agent that works with {display_name} on the user's behalf.

## What {display_name} is
{description}
{notes}
## Your tools (all from the {display_name} MCP server)
{tool_lines}

## Rules
- Read-only tools run without asking. Tools marked (spend) consume credits or money and tools marked (send) change or send something: a confirmation card appears before they run; never argue past a decline.
- Work from what the user or the orchestrator gave you (ids, artifact ids, dates); read artifacts with read_artifact when a task names one. Do not invent identifiers or content.
- If {display_name} is not connected, a tool returns a sign-in link: hand the link to the user in your summary and stop; do not retry.
- Save lists you produce as artifacts (kind "other" unless a better kind fits) so the user can download them and other agents can use them.
"""


def specialist_name(server: str) -> str:
    return "mcp_" + re.sub(r"[^a-z0-9]+", "_", server.lower()).strip("_")


def server_for(persona_name: str) -> str | None:
    return _by_server_inverse().get(persona_name)


def _by_server_inverse() -> dict[str, str]:
    return {v: k for k, v in _by_server.items()}


def _escape(text: str) -> str:
    return (text or "").replace("{", "{{").replace("}", "}}")


def _short(text: str, n: int = 110) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


async def build(server: str) -> Persona | None:
    """Build the specialist for one server, or None when it is not eligible or reachable."""
    if not specialist_eligible(server) or not await is_connected(server):
        return None
    try:
        tools = await list_tools(server)
    except Exception as e:
        logger.warning(f"Specialist for '{server}' skipped: tools unavailable ({e})")
        return None
    if not tools:
        return None
    opts = options(server)
    overrides = await load_mcp_tool_classes(server)
    display = opts.get("display_name") or server
    lines, summary = [], []
    for t in tools:
        cls = classify_tool(t["name"], t.get("description", ""), t.get("annotations"), overrides.get(t["name"]))
        tag = "" if cls == "read" else f" ({cls})"
        lines.append(f"- {t['name']}{tag}: {_escape(_short(t.get('description', '')))}")
        summary.append(t["name"].split("__")[-1].replace("_", " ").lower())
    notes = ""
    if opts.get("system_prompt_append"):
        notes += "\n" + _escape(opts["system_prompt_append"].strip()) + "\n"
    if opts.get("planner_note"):
        notes += "\n" + _escape(opts["planner_note"].strip()) + "\n"
    description = (
        f"{display} specialist: works with {display} on the user's behalf through its MCP server. "
        f"{_short(opts.get('description', ''), 160)} "
        f"Can: {', '.join(summary[:14])}{', …' if len(summary) > 14 else ''}. "
        "Parameters: query (required): the complete task, with any ids, dates, names or artifact ids it needs. "
        f"Use this function for anything that should happen in {display}."
    )
    prompt = SPECIALIST_PROMPT.format(
        display_name=_escape(display), description=_escape(opts.get("description") or f"The {display} service."),
        notes=notes, tool_lines="\n".join(lines),
    ) + prompts._COMMON_RULES
    return Persona(
        name=specialist_name(server), display_name=display,
        tagline=f"Works with {display} for you", description=description, system_prompt=prompt,
        builtin_tools=["Read"], daxagent_tools=["review_with_user", *COMMON_TOOLS], remote_mcp=True,
        mcp_servers=[server], kind="specialist", server=server, icon=opts.get("icon", ""), max_turns=30,
    )


async def refresh() -> dict[str, Persona]:
    """Rebuild every specialist; call after servers are added, removed, switched or connected."""
    global _cache, _by_server
    fresh, by_server = {}, {}
    for server in server_names():
        try:
            persona = await build(server)
        except Exception as e:
            logger.warning(f"Specialist build failed for '{server}': {e}")
            persona = None
        if persona is not None:
            fresh[persona.name] = persona
            by_server[server] = persona.name
    _cache, _by_server = fresh, by_server
    if fresh:
        logger.info(f"MCP specialists ready: {', '.join(fresh)}")
    return dict(fresh)


def get(name: str) -> Persona | None:
    return _cache.get(name)


def all() -> dict[str, Persona]:
    return dict(_cache)
