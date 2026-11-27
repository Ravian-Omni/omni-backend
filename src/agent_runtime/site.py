"""People from a company's own site (signals contract [20] item 1), read through MarketWatch's read_site ([19]).

Off until the MarketWatch connection lists read_site. Every read goes through `find_contacts`, which holds the rules in
code: a cap on reads per run (each read spends MarketWatch credits, which the run's credit budget does not count), at most
MAX_CONTACTS people, and nobody kept who could not pass the lead gate. An address the site prints for a person is noted as
a source's, so it gets DAXAGENT's own check (leads.settle); with none printed the person has no email. No address is
guessed. What the site says is an outside page's words: only the fields are kept, never its free text.
"""

import asyncio
import json
import re
from urllib.parse import urlparse

from src.agent_runtime import leads
from src.database import note_source_emails, run_started
from src.mcp_client import call_tool
from src.mcp_client.client import listed_tool_names
from src.mcp_client.config import is_enabled

SERVER = "marketwatch"
TOOL = "read_site"
PERSONAS = ("signal_play", "contact_enricher")  # the person step of a signal play ([10])
MAX_READS = 3  # site reads per run
ENRICHER_READS = 10  # the Contact Enricher's fallback: one read per matched row with no email, about a Brain Hands batch
MAX_CONTACTS = 3
TIMEOUT_S = 120  # read_site answers within 100 s ([19])
FIELDS = {"name": "the person's full name", "title": "their job title as the page states it", "email": "their own email address if the page prints it, else null",
          "company_email": "the company's general inbox if the page prints one (e.g. info@), else null"}
# words that say a title's level, not its job: "VP Marketing" fits "Head of Marketing"
LEVEL = {"of", "the", "and", "for", "head", "vp", "svp", "evp", "vice", "president", "director", "chief", "officer", "senior", "sr", "lead", "manager", "global"}
WORD = re.compile(r"[a-z]+")
runs: dict[str, str] = {}  # chat -> when its run began; set by hands_mcp, since a run spans sourcing rounds
_reads: dict[tuple[str, str], int] = {}  # (chat, run start) -> reads; shortcut: in memory, so a restart resets the count
_failed: dict[tuple[str, str], str] = {}  # (chat, run start) -> why read_site failed: no more reads that run


def configured() -> bool:
    """MarketWatch is switched on and its connection lists read_site."""
    return is_enabled(SERVER) and TOOL in listed_tool_names(SERVER)


def offered(persona: str) -> bool:
    return persona in PERSONAS and configured()


def begin_run(chat_id: str, started_at: str) -> None:
    runs[chat_id] = started_at


def end_run(chat_id: str) -> None:
    runs.pop(chat_id, None)


def _domain(site: str) -> str:
    return (urlparse(site if "//" in site else f"//{site}").hostname or "").removeprefix("www.")


def fits(title: str, wanted: list[str]) -> bool:
    """The title holds every job word (not level word) of one of the wanted titles; any title when none is wanted."""
    have = set(WORD.findall(title.lower()))
    return not wanted or any(set(WORD.findall(w.lower())) - LEVEL <= have for w in wanted)


async def _read(domain: str, titles: list[str], person: str) -> tuple[list[dict], str]:
    """read_site's rows, or ([], why not)."""
    who = f"{person}, and their job title" if person else f"the people in these roles: {', '.join(titles)}"
    question = f"Who works at this company in a named work role? Find {who}. Only people the pages name."
    try:
        text = await asyncio.wait_for(call_tool(SERVER, TOOL, {"url": f"https://{domain}", "question": question[:500], "fields": FIELDS}), TIMEOUT_S)
        answer = json.loads(text)
    except Exception as e:  # a refusal comes back as plain text, which is not JSON
        return [], f"the site read failed: {str(e)[:200]}"
    if not answer.get("found"):
        return [], f"the site names nobody: {str(answer.get('reason') or 'not found')[:200]}"
    return [r for r in answer.get("rows") or [] if isinstance(r, dict)], ""


def _text(v, limit: int) -> str:
    return re.sub(r"\s+", " ", v).strip()[:limit] if isinstance(v, str) else ""


async def find_contacts(user_id: str, chat_id: str, site: str, titles: list[str] | None = None, person: str = "",
                        max_reads: int = MAX_READS) -> dict:
    """The people the company's own site names for the titles (or the named person), with the email it prints for each,
    and the lead gate's verdict on each."""
    domain, person = _domain(site), person.strip()
    titles = list(dict.fromkeys(t.strip() for t in titles or [] if t.strip()))
    run = (chat_id, runs.get(chat_id) or await run_started(chat_id))
    contacts, skipped, problems = [], [], []
    if not domain:
        problems.append("no company domain: give the company's website")
    elif not (person or titles):
        problems.append("give the person's name or the titles to look for")
    elif run in _failed:
        problems.append(f"the site reader is off for this run: {_failed[run]}")
    elif _reads.get(run, 0) >= max_reads:
        problems.append(f"this run has used its {max_reads} site reads")
    else:
        _reads[run] = _reads.get(run, 0) + 1
        rows, why = await _read(domain, titles, person)
        if why:
            problems.append(why)
            if why.startswith("the site read failed"):  # a MarketWatch limit or error: no retry this run
                _failed[run] = why
        suppressed, written = await leads.sets(user_id, chat_id)
        kept: list[dict] = []
        inboxes = [e for r in rows if leads.is_shared(e := _text(r.get("company_email"), 200).lower()) and e.endswith("@" + domain)]
        for row in rows:
            name, title, email = _text(row.get("name"), 100), _text(row.get("title"), 150), _text(row.get("email"), 200).lower()
            if not name or any(k["full_name"].lower() == name.lower() for k in kept):
                continue
            if not (name.lower() == person.lower() if person else fits(title, titles)):
                continue
            if why := leads.prospect({"full_name": name, "email": email}, domain, suppressed, written):
                skipped.append({"name": name, "why": why})
            elif len(kept) < MAX_CONTACTS:
                email = email if leads.EMAIL.fullmatch(email) else ""
                kept.append({"full_name": name, "first_name": name.split()[0], "last_name": name.split()[-1], "title": title, "company_domain": domain,
                             "email": email, "email_status": "", "email_source": f"website:{_text(row.get('source_url'), 300)}"})
        for contact in kept:  # a person whose own address the site does not print: the company's inbox, the lead gate decides
            if not contact["email"] and inboxes:
                contact["email"] = inboxes[0]
        if printed := {k["email"] for k in kept if k["email"]}:
            await note_source_emails(chat_id, SERVER, printed)  # so settle gives them the in-house check, as a Data Axle address gets
        await leads.settle(chat_id, kept)
        for contact in kept:
            contact["gate"], contact["gate_reason"] = leads.gate(contact, suppressed, written)
            contacts.append(contact)
    return {"contacts": contacts, "skipped": skipped, "problems": problems, "site_reads_left": 0 if run in _failed else max(0, max_reads - _reads.get(run, 0))}
