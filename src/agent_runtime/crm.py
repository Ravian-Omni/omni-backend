"""The CRM (Atomic CRM over MCP, signals contract [16]): DAX's writes to the system of record, and its do-not-contact list.

Off unless CRM_MCP_URL and CRM_API_KEY are both set (and the connector is on in Settings): then nothing is called. Every
write is keyed so a repeat adds nothing (upserts by domain and email; log_activity by the Gmail message id), so two DAXes
with the same key are safe. A CRM that is down, slow or refusing never blocks or fails a run, a send or the watcher:
each call has TIMEOUT_S, a miss is logged and skipped, and the writes run in the background.
"""

import asyncio
import json
import os
from typing import Any
from urllib.parse import urlparse

from loguru import logger

from src.agent_runtime import creatives
from src.mcp_client import call_tool
from src.mcp_client.config import is_enabled, personas_for

SERVER = "crm"
TIMEOUT_S = 8
_tasks: set[asyncio.Task] = set()


def configured() -> bool:
    return bool(os.getenv("CRM_MCP_URL", "").strip()) and bool(os.getenv("CRM_API_KEY", "").strip()) and is_enabled(SERVER)


def offered(persona: str) -> bool:
    return configured() and persona in (personas_for(SERVER) or [])


async def call(tool: str, **args: Any) -> Any:
    """One CRM tool call: its answer, or None when the CRM is off, slow, down or refuses (logged)."""
    if not configured():
        return None
    try:
        text = await asyncio.wait_for(call_tool(SERVER, tool, {k: v for k, v in args.items() if v not in (None, "", {})}), TIMEOUT_S)
        return json.loads(text)
    except Exception as e:  # a refusal comes back as plain text, which is not JSON
        logger.info(f"[crm] {tool} skipped: {str(e)[:200]}")
        return None


def later(make) -> None:
    """Run a CRM write in the background, so nothing waits on the CRM; nothing at all when it is off."""
    if configured():
        task = asyncio.create_task(make())
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)


def _domain(site: str) -> str:
    return (urlparse(site if "//" in site else f"//{site}").hostname or "").removeprefix("www.")


async def lead(row: dict, chat_id: str, agenda_id: str = "") -> None:
    """A contact that passed the lead gate: its company (when a website is known), then the person, linked to it."""
    email = creatives.field(row, "email").lower()
    website = _domain(str(row.get("website") or row.get("company_domain") or row.get("domain") or ""))
    if website:
        await call("upsert_company", website=website, name=creatives.field(row, "company") or website)
    data_axle_id = str(row.get("contact_infogroupId") or row.get("infogroupId") or row.get("infogroup_id") or "")
    await call("upsert_contact", email=email, first_name=creatives.field(row, "first_name") or email.split("@")[0],  # never empty
               last_name=creatives.field(row, "last_name"), title=creatives.field(row, "title"), website=website,
               email_status=str(row.get("email_status") or ""), source="dax",
               external={k: v for k, v in {"dax_chat_id": chat_id, "data_axle_id": data_axle_id, "agenda_id": agenda_id}.items() if v})


async def activity(email: str, kind: str, text: str, key: str) -> None:
    """A dated entry on the person's record, keyed so a repeat adds nothing; skipped when the CRM does not know them."""
    found = await call("find_contact", email=email.lower())
    if isinstance(found, dict) and found.get("id") is not None:  # an id can be 0
        await call("log_activity", about={"kind": "contact", "id": found["id"]}, kind=kind, text=(text or kind)[:20000], key=key)


async def suppress(email: str, reason: str) -> None:
    await call("suppress", value=email.lower(), reason=reason, source="dax")


async def pull_suppressed(user_id: str) -> int:
    """The CRM's do-not-contact entries since the last pull, copied into DAX's own table (the send gate's source, so a
    CRM that is down never opens it). Returns how many were copied."""
    from src.database import load_pref, save_pref, suppress_email

    since = await load_pref(user_id, "crm_suppressed_since") or None
    found = await call("list_suppressed", since=since)
    rows = (found or {}).get("suppressed") if isinstance(found, dict) else None
    for s in rows or []:
        await suppress_email(user_id, str(s["value"]), f"crm: {s.get('reason') or ''}"[:200])
    if rows:
        await save_pref(user_id, "crm_suppressed_since", rows[-1]["created_at"])  # oldest first: the last is the newest
    return len(rows or [])
