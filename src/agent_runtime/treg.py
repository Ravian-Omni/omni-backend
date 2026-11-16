"""treg (treg.to), the outside data layer of the signals contract [9] and [10]: the people at a company by title, and a
work email found and checked in one call.

Every paid call goes through `_call`, which holds the rules in code: only the endpoints the server's config names, a
ceiling on each call, and a dollar cap per run that no agent can raise. The server's own tools are never offered to an
agent (`guarded` in its config); agents get `treg__find_contacts` (tools/treg.py), which ends here.
"""

import json
import os
import uuid
from urllib.parse import urlparse

from src.agent_runtime import leads
from src.database import data_spent, record_data_spend, run_started
from src.mcp_client import call_tool, options
from src.mcp_client.config import in_mode, is_enabled, personas_for

SERVER = "treg"
RUN_USD = 0.50  # dollars one run may spend; DAXAGENT_TREG_RUN_USD overrides it
SEARCH_ROWS = 5  # people asked for per title search: it is billed per row
MAX_TITLES = 3
MAX_CONTACTS = 3  # paid email lookups in one call to find_contacts
CHECK_WORDS = {"valid", "invalid", "catch_all", "risky", "unknown"}  # the words treg's check gives (contract people.email.verify)

# the planner's ability line for an agent that has the tool (omni/orchestrator.py adds it only while treg is connected)
ABILITY = ("treg__find_contacts (real money per call, capped per run): the people at a company's website by title, or a named person, "
           "each with a work email treg found and checked; says who passes the lead gate and why the others do not.")
runs: dict[str, str] = {}  # chat -> when its run began; set by hands_mcp, since a run spans sourcing rounds that each mark the chat anew


def configured() -> bool:
    """treg has a token in the environment and is switched on for tasks (Settings > Connections)."""
    return bool(os.getenv(options(SERVER).get("token_env", ""))) and is_enabled(SERVER) and in_mode(SERVER, "task")


def offered(persona: str) -> bool:
    return configured() and persona in (personas_for(SERVER) or [])


def run_cap() -> float:
    return float(os.getenv("DAXAGENT_TREG_RUN_USD") or RUN_USD)


def ceiling() -> float:
    """The most one call may cost: sent as X-Treg-Route-Max-Cost, and the least a run must have left to make another."""
    return float(options(SERVER).get("max_call_usd", 0.05))


def begin_run(chat_id: str, started_at: str) -> None:
    runs[chat_id] = started_at


def end_run(chat_id: str) -> None:
    runs.pop(chat_id, None)


async def _since(chat_id: str) -> str:
    return runs.get(chat_id) or await run_started(chat_id)


async def spent(chat_id: str, since: str) -> float:
    """Dollars paid at treg by the chat since `since`; none without treg connected (nothing could have been called)."""
    return round(await data_spent(chat_id, since), 6) if configured() else 0.0


async def out(chat_id: str, since: str) -> bool:
    """treg is on and the run's dollars no longer cover one more call."""
    return configured() and round(run_cap() - await spent(chat_id, since), 6) < ceiling()


def email_status(answer: dict) -> str:
    """The contact's email_status from a routed find's answer: treg's own check (`_treg.verification`), never the finder's
    claim (`output.verified`). Only `valid` passes the lead gate; catch_all, risky, unknown, invalid, an address at another
    domain than the one asked for, and a check that did not run all fail it."""
    meta = answer.get("_treg") or {}
    check = meta.get("verification") or {}
    if not check.get("checked"):
        return "unchecked"
    if meta.get("domain_match") is False:
        return "other_domain"  # a former employer's address
    word = str(check.get("verdict") or "").lower()
    return word if word in CHECK_WORDS else "unknown"


async def _call(chat_id: str, kind: str, body: dict, verify: bool = False) -> tuple[dict, str]:
    """One paid call: (treg's answer, "") or ({}, why not). What treg reports it charged is recorded, and with it the
    email it checked and the word it gave."""
    since = await _since(chat_id)
    if await out(chat_id, since):
        return {}, "this run's treg budget is used up"
    endpoint = options(SERVER)["endpoints"][kind]
    headers = {"X-Treg-Route-Max-Cost": f"{ceiling():g}", **({"X-Treg-Route-Verify": "true"} if verify else {})}
    try:
        # a fresh key per call: call_tool repeats a call once when its connection died, and treg bills a repeat unless the key is the same
        text = await call_tool(SERVER, "call", {"endpoint_id": endpoint, "body": body, "headers": headers, "idempotency_key": uuid.uuid4().hex})
    except Exception as e:  # a dropped connection may still have been charged: count the most one call can cost
        await record_data_spend(chat_id, endpoint, ceiling())
        return {}, f"treg call failed: {e}"
    try:
        reply = json.loads(text)
    except ValueError:
        return {}, f"treg said: {text[:200]}"
    answer = reply.get("body") if isinstance(reply.get("body"), dict) else {}
    usd = reply.get("cost_usd")
    if usd is None:
        usd = int((answer.get("_treg") or {}).get("charged_micro") or 0) / 1e6
    email = str((answer.get("output") or {}).get("email") or "") if verify else ""
    await record_data_spend(chat_id, endpoint, float(usd), str(reply.get("call_id") or ""), email, email_status(answer) if email else "")
    status = reply.get("status")
    if reply.get("error") or not (isinstance(status, int) and 200 <= status < 300):
        return {}, f"treg {status or 'error'}: {str(reply.get('error') or answer or reply.get('body'))[:200]}"
    return answer, ""


def _domain(site: str) -> str:
    host = urlparse(site if "//" in site else f"//{site}").hostname or ""
    return host.removeprefix("www.")


async def _candidates(chat_id: str, domain: str, titles: list[str], person: str, limit: int, suppressed: set[str], written: set[str],
                      skipped: list[dict], problems: list[str]) -> list[dict]:
    """The people worth a paid email call, best first: the named person, else the rows of a title search at the domain
    (one search per title until there are `limit`). A person who would fail the lead gate whatever the email says, or
    who no longer holds the title, is skipped before anything is paid for them."""
    found: dict[str, dict] = {}

    def consider(row: dict) -> None:
        name = str(row.get("name") or "").strip()
        if name.lower() in found or any(s["name"] == name for s in skipped):
            return
        gone = row.get("title_match") == "past" or row.get("title_until")
        if why := "no longer holds the title" if gone else leads.prospect({"full_name": name, "email": row.get("email")}, domain, suppressed, written):
            skipped.append({"name": name, "why": why})
        else:
            found[name.lower()] = row

    if person:
        consider({"name": person})
    for title in titles[:MAX_TITLES]:
        if len(found) >= limit:
            break
        answer, why = await _call(chat_id, "people_search", {"title": title, "company_domain": domain, "limit": SEARCH_ROWS})
        if why:
            problems.append(why)
            break
        for row in (answer.get("output") or {}).get("people") or []:
            consider(row)
    return list(found.values())[:limit]


async def find_contacts(user_id: str, chat_id: str, site: str, titles: list[str] | None = None, person: str = "", limit: int = 2) -> dict:
    """People at a company, each with an email treg found and checked, and the lead gate's verdict on each.
    A named `person` skips the search; otherwise the titles are searched at the domain."""
    domain, limit = _domain(site), max(1, min(limit, MAX_CONTACTS))
    since = await _since(chat_id)
    before = await spent(chat_id, since)
    suppressed, written = await leads.sets(user_id, chat_id)
    contacts, skipped, problems = [], [], []
    titles = list(dict.fromkeys(t.strip() for t in titles or [] if t.strip()))
    if not domain:
        problems.append("no company domain: give the company's website")
    elif not (person or titles):
        problems.append("give the person's name or the titles to search for")
    else:
        for row in await _candidates(chat_id, domain, titles, person.strip(), limit, suppressed, written, skipped, problems):
            name = str(row["name"]).strip()
            answer, why = await _call(chat_id, "email_find", {"full_name": name, "domain": domain}, verify=True)
            if why:
                problems.append(why)
                break
            output = answer.get("output") or {}
            email = str(output.get("email") or "").strip().lower()
            contact = {"full_name": name, "first_name": output.get("first_name") or name.split()[0], "last_name": output.get("last_name") or name.split()[-1],
                       "title": row.get("title") or "", "company": row.get("company") or "", "company_domain": domain, "linkedin_url": row.get("profile_url") or "",
                       "email": email, "email_status": email_status(answer) if email else "",
                       "email_source": f"treg:{(answer.get('_treg') or {}).get('served_by') or ''}"}
            contact["gate"], contact["gate_reason"] = leads.gate(contact, suppressed, written)
            contacts.append(contact)
    after = await spent(chat_id, since)
    return {"contacts": contacts, "skipped": skipped, "problems": list(dict.fromkeys(problems)), "spent_usd": round(after - before, 6),
            "run_spent_usd": after, "run_left_usd": max(0.0, round(run_cap() - after, 6)),
            **({"stopped_because": "budget_used_up"} if await out(chat_id, since) else {})}
