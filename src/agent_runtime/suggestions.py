"""Starter prompts for the home screen: fill-in-the-blank templates written from the user's own work.

A template is {"text": "Find 10 {business} in {area}", "slots": {"business": {"label": "type of business",
"options": ["dental offices", ...]}}}. Each user and mode keeps its last good set; when the user's lists or
apps change, a rewrite runs in the background and the new set shows on the next visit.
"""

import asyncio
import json
import re
from typing import Any

from loguru import logger

from src.agent_runtime import prefs
from src.agent_runtime.llm import complete
from src.database import recent_artifacts
from src.mcp_client import options, server_names
from src.mcp_client.config import in_mode, is_enabled

SLOT = re.compile(r"\{([^{}]+)\}")

_BUSINESS = {"label": "type of business", "options": ["dental offices", "HVAC contractors", "law firms", "auto repair shops"]}
_AREA = {"label": "area", "options": ["Austin, TX", "Denver, CO", "Miami, FL", "Chicago, IL"]}
_STATE = {"label": "state", "options": ["Texas", "Florida", "California", "Ohio"]}

FALLBACK = {
    "chat": [
        {"text": "Find 10 {business} in {area}", "slots": {"business": _BUSINESS, "area": _AREA}},
        {"text": "Show {business} in {area} on a map", "slots": {"business": _BUSINESS, "area": _AREA}},
        {"text": "Which {business} in {state} have the most employees?", "slots": {"business": _BUSINESS, "state": _STATE}},
        {"text": "How many Data Axle credits do I have left?", "slots": {}},
    ],
    "task": [
        {"text": "Build a list of 50 {business} in {state} with {size} employees",
         "slots": {"business": _BUSINESS, "state": _STATE,
                   "size": {"label": "company size", "options": ["1 to 10", "10 to 50", "50 to 200"]}}},
        {"text": "Find the decision makers at {business} in {area}", "slots": {"business": _BUSINESS, "area": _AREA}},
        {"text": "Draft a {length} email campaign for {business} in {area}",
         "slots": {"length": {"label": "length", "options": ["2-step", "3-step", "4-step"]}, "business": _BUSINESS, "area": _AREA}},
        {"text": "Enrich my latest lead list and show it on a map", "slots": {}},
    ],
}

MODES = {
    "chat": "Chat mode: one assistant answers in a single reply, so each prompt is one lookup or question: find or count "
            "businesses or contacts in Data Axle, compare places or industries, put results on a chart or map, check "
            "credits, or ask about a connected app (inbox, calendar).",
    "task": "Task mode: agents deliver a multi-step outcome, so each prompt is one job: Lead Finder builds a lead list, "
            "Buyer Finder maps the buyers inside target companies, Contact Enricher finds decision makers and their "
            "contact details (spends credits), Campaign Builder drafts an email and call sequence, Outreach sends it.",
}

SYSTEM = """You write four starter prompts for DAXAGENT, an outbound sales assistant on Data Axle's database of US businesses and consumers.
MODE
Each prompt is a fill-in-the-blank template: one short sentence (under 80 characters) that asks for one thing, with one or two blanks written as {name} (name is one lowercase word, like {business}). Each blank has a lowercase label of two or three words and three to five distinct, specific example options.
A blank stands for a whole noun phrase, so every option reads correctly in the sentence: "Find 10 {business} in {area}" with options "dental offices", "HVAC contractors".
The four prompts are four different jobs: no two share the same sentence shape or the same blanks.
Draw the options from what you know about the user (about_user) and their recent work (industries, places, list and plan names) when there is any; otherwise use common B2B examples. Mention an app only if it is connected. Plain words, no emoji.
Return JSON: {"templates": [{"text": "...", "slots": {"name": {"label": "...", "options": ["..."]}}}]}"""

_cache: dict[tuple[str, str], tuple[str, list[dict]]] = {}
_jobs: dict[tuple[str, str], asyncio.Task] = {}


def _key(name: str) -> str:
    """A blank's name as one snake_case word ("contact group" -> "contact_group")."""
    return re.sub(r"\W+", "_", name.strip().lower()).strip("_")


def clean(templates: Any) -> list[dict]:
    """The templates the UI can render: at most three distinct blanks, each defined with short options."""
    kept = []
    for t in templates if isinstance(templates, list) else []:
        text, slots = (t.get("text"), t.get("slots") or {}) if isinstance(t, dict) else (None, None)
        if not isinstance(text, str) or not isinstance(slots, dict):
            continue
        text = SLOT.sub(lambda m: "{%s}" % _key(m.group(1)), text)
        slots = {_key(str(k)): v for k, v in slots.items()}
        names = SLOT.findall(text)
        if not text or len(text) > 120 or len(names) > 3 or len(set(names)) < len(names) or "" in names \
                or re.search(r"[{}]", SLOT.sub("", text)):
            continue
        defined = {}
        for name in names:
            slot = slots.get(name) if isinstance(slots.get(name), dict) else {}
            opts = [o.strip() for o in slot.get("options") or [] if isinstance(o, str) and 0 < len(o.strip()) <= 60]
            if opts:
                defined[name] = {"label": str(slot.get("label") or name.replace("_", " "))[:30], "options": opts[:5]}
        if len(defined) == len(names):
            kept.append({"text": text, "slots": defined})
    return kept[:4]


async def _context(user_id: str, mode: str) -> dict[str, Any]:
    work, seen = [], set()
    for a in await recent_artifacts(user_id):
        if a["title"] not in seen and len(work) < 10:
            seen.add(a["title"])
            work.append(a)
    apps = sorted(options(n).get("display_name", n) for n in server_names() if is_enabled(n) and in_mode(n, mode))
    memory = await prefs.get(user_id, "memory")
    about = [m["text"] for m in memory["items"]][-10:] if memory["enabled"] else []
    return {"about_user": about, "recent_work": work, "connected_apps": apps}


async def _write(key: tuple[str, str], context: dict[str, Any], fingerprint: str) -> list[dict]:
    reply = await complete(SYSTEM.replace("MODE", MODES[key[1]]), json.dumps(context), max_tokens=1500, json_mode=True)
    templates = clean(json.loads(reply).get("templates"))
    if len(templates) < 2:
        raise ValueError(f"{len(templates)} usable templates")
    _cache[key] = (fingerprint, templates)
    return templates


def _rewrite(key: tuple[str, str], context: dict[str, Any], fingerprint: str) -> asyncio.Task:
    """One rewrite per user and mode at a time."""
    if key not in _jobs:
        def done(job: asyncio.Task) -> None:
            _jobs.pop(key, None)
            if not job.cancelled() and job.exception():
                logger.warning(f"Starter prompts not rewritten: {job.exception()}")

        _jobs[key] = asyncio.create_task(_write(key, context, fingerprint))
        _jobs[key].add_done_callback(done)
    return _jobs[key]


async def suggestions(user_id: str, mode: str) -> list[dict]:
    """The user's starter prompts: cached at once, or written now on a first visit (fallback set on failure)."""
    key = (user_id, mode if mode in MODES else "chat")
    context = await _context(user_id, key[1])
    fingerprint = json.dumps(context, sort_keys=True)
    cached = _cache.get(key)
    if cached and cached[0] == fingerprint:
        return cached[1]
    job = _rewrite(key, context, fingerprint)
    if cached:
        return cached[1]
    try:
        return await asyncio.wait_for(asyncio.shield(job), 8)
    except Exception:
        _cache.setdefault(key, ("", FALLBACK[key[1]]))  # later visits answer at once while the rewrite retries
        return FALLBACK[key[1]]
