"""The lead gate (signals contract [8]): whether a contact counts as a lead is decided here, in code, never by a prompt.

A lead is a named person with a business email of their own that the source checked, who is not suppressed and was not
written to before. Every enriched_contacts row is marked `gate` pass or fail with its `gate_reason` when it is saved,
and a campaign sends only to rows that pass when it is rendered.
"""

import asyncio
import json
import re
from collections import Counter
from typing import Any

from src.agent_runtime import creatives, crm
from src.database import checked_emails, find_artifacts, list_artifacts, list_suppressed, note_source_emails, source_emails

# the local part of a shared or role inbox: it reaches a team, not the person
ROLE_INBOXES = {
    "info", "hello", "hi", "contact", "sales", "marketing", "support", "admin", "office", "team", "newbiz", "enquiries", "inquiries",
    "hr", "careers", "jobs", "help", "service", "billing", "accounts", "mail", "press", "media", "webmaster", "postmaster",
    "noreply", "no-reply", "reception", "orders", "general", "hola", "business", "enquiry",
}
# shortcut: a short list of the common free-mail domains; add more as they turn up
FREE_MAIL = {"gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "aol.com", "icloud.com", "live.com", "msn.com", "proton.me", "protonmail.com", "gmx.com"}
VERIFIED = {"verified", "valid", "deliverable", "safe", "domain_ok"}  # what a finder says of an email it checked; domain_ok: DAXAGENT's own check
IN_HOUSE = {"domain_ok", "no_mail_domain", "bad_syntax"}  # words only DAXAGENT's own check gives: an agent's are dropped
STATUS_KEYS = ("email_status", "email_verification", "verification_status")
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
SENT = ("sent", "replied", "bounced", "auto_reply")  # send_log statuses that mean we wrote to the address
MAX_ROUNDS = 10  # a safety stop: sourcing rounds after the first, when the target, the budget and the source never end it


def email_of(row: dict[str, Any]) -> str:
    return creatives.field(row, "email").lower()


def is_shared(email: str) -> bool:
    return email.split("@")[0].split("+")[0].replace(".", "") in {r.replace(".", "") for r in ROLE_INBOXES}


def _named(row: dict[str, Any]) -> str:
    first, last = creatives.field(row, "first_name"), creatives.field(row, "last_name")
    return f"{first} {last}" if first and last else creatives.field(row, "full_name")


def _status(row: dict[str, Any]) -> str:
    return str(next((row[k] for k in STATUS_KEYS if row.get(k)), "")).lower()


def _checked(row: dict[str, Any]) -> bool:
    return str(row.get("email_verified")).lower() in ("true", "yes", "1") or _status(row) in VERIFIED


def gate(row: dict[str, Any], suppressed: set[str], contacted: set[str], proven: set[str] = frozenset()) -> tuple[str, str]:
    """("pass", "") or ("fail", why): the first check the row fails. proven: addresses this chat already wrote to without a
    bounce: the send showed they work, so they count as checked; every other check still applies."""
    name, email = _named(row), email_of(row)
    for fails, why in (
        (len(name.split()) < 2, "no full name"),
        ("*" in name or "*" in email, "masked by the source"),
        (not email, "no email"),
        (is_shared(email), "shared or role inbox"),
        (email.split("@")[-1] in FREE_MAIL, "free-mail address, not a business email"),
        (not _checked(row) and email not in proven, f"email not verified: {_status(row)}" if _status(row) else "email not checked by the source"),
        (email in suppressed or email.split("@")[-1] in suppressed, "suppressed"),  # an address, or its whole domain
        (email in contacted, "already written to"),
    ):
        if fails:
            return "fail", why
    return "pass", ""


def prospect(row: dict[str, Any], domain: str, suppressed: set[str], contacted: set[str]) -> str:
    """"" when a contact whose email is not found yet could still become a lead, else the gate's reason: the checks no finder
    can change (name, masked, a shared or free-mail address, suppressed, written to), so nothing is paid for a contact that
    would fail anyway. An email the row already has is held to them; none yet stands in as a business address at `domain`."""
    stand_in = {"email": f"prospect@{domain}", "email_status": "valid"}
    return gate({**stand_in, **{k: v for k, v in row.items() if v}}, suppressed, contacted)[1]


def _rows(path: str) -> list[dict[str, Any]]:
    try:
        with open(path) as f:
            return json.load(f).get("rows", [])
    except (OSError, ValueError):
        return []


async def proven(chat_id: str) -> set[str]:
    """Addresses this chat sent to that have not bounced."""
    sent, bounced = set(), set()
    for record in await list_artifacts(chat_id):
        if record["kind"] == "send_log":
            for r in _rows(record["path"]):
                (sent if r.get("status") == "sent" else bounced if r.get("status") == "bounced" else set()).add(str(r.get("to") or "").lower())
    return sent - bounced


async def contacted(user_id: str, exclude_chat: str | None = None) -> set[str]:
    """Addresses the user's campaigns have written to, from every send log but this chat's own: its own follow-ups are not duplicates."""
    out: set[str] = set()
    for record in await find_artifacts(user_id, "", "send_log", 2000):
        if record["chat_id"] == exclude_chat:
            continue
        out.update(str(r.get("to") or r.get("recipient_email") or "").lower() for r in _rows(record["path"]) if r.get("status") in SENT)
    out.discard("")
    return out


async def written_chats(user_id: str) -> dict[str, str]:
    """Each address the user's campaigns have written to, with the chat that wrote to it last."""
    out: dict[str, str] = {}
    for record in reversed(await find_artifacts(user_id, "", "send_log", 2000)):  # oldest first: a later chat wins
        for r in _rows(record["path"]):
            if r.get("status") in SENT and (email := str(r.get("to") or r.get("recipient_email") or "").lower()):
                out[email] = record["chat_id"]
    return out


async def sets(user_id: str, exclude_chat: str | None = None) -> tuple[set[str], set[str]]:
    """(suppressed addresses, addresses already written to) for gate()."""
    return await list_suppressed(user_id), await contacted(user_id, exclude_chat)


async def note_source(chat_id: str, server: str, text: str) -> None:
    """Remember the addresses a reserved data source's answer (Data Axle) held in this chat: only those get the in-house
    check, so an address an agent guessed never passes on its domain alone."""
    from src.mcp_client.config import is_reserved

    if is_reserved(server) and (found := {e.lower() for e in EMAIL.findall(text)}):
        await note_source_emails(chat_id, server, found)


async def _in_house(emails: set[str]) -> dict[str, str]:
    """DAXAGENT's own check of each address: domain_ok (valid syntax and a domain that takes mail), no_mail_domain,
    bad_syntax, or unchecked when the lookup failed. It does not prove the mailbox exists; a bounce suppresses it later."""
    from src.agent_runtime import sender  # not at the top: sender imports this module

    domains = sorted({e.rsplit("@", 1)[1] for e in emails if EMAIL.fullmatch(e)})
    takes = dict(zip(domains, await asyncio.gather(*(sender.accepts_mail(d) for d in domains))))
    words = {True: "domain_ok", False: "no_mail_domain", None: "unchecked"}
    return {e: words[takes[e.rsplit("@", 1)[1]]] if EMAIL.fullmatch(e) else "bad_syntax" for e in emails}


async def settle(chat_id: str, rows: list[dict[str, Any]]) -> None:
    """Put on each row the email status code decides, whatever an agent wrote: treg's word for an address it checked; for an
    address Data Axle returned in this chat with no finder's word on it, the in-house check. A word only the in-house check
    gives is dropped from any other row."""
    treg_words, sourced, todo = await checked_emails(chat_id), await source_emails(chat_id), []
    for row in rows:
        email = email_of(row)
        if (word := treg_words.get(email)) is not None:
            row["email_status"], row["email_verified"] = word, word in VERIFIED
        elif email in sourced and _status(row) in ("unchecked", *IN_HOUSE, ""):
            todo.append(row)
        else:
            for k in STATUS_KEYS:
                if str(row.get(k) or "").lower() in IN_HOUSE:
                    row[k] = ""
    words = await _in_house({email_of(r) for r in todo}) if todo else {}
    for row in todo:
        row["email_status"] = words[email_of(row)]


async def mark(user_id: str, chat_id: str, rows: list[dict[str, Any]]) -> None:
    """Stamp each row with its gate and the reason, on the email statuses settle() decides."""
    from src.services import needs  # not at the top: services imports the agent runtime

    suppressed, written = await sets(user_id, chat_id)
    await settle(chat_id, rows)
    agenda = None
    for row in rows:
        row["gate"], row["gate_reason"] = gate(row, suppressed, written)
        if row["gate"] == "pass" and crm.configured():  # the CRM gets every lead, in the background
            agenda = agenda if agenda is not None else await needs.agenda_of(chat_id)
            crm.later(lambda row=row: crm.lead(row, chat_id, agenda))


async def tally(chat_id: str, since: str = "") -> dict[str, Any]:
    """The chat's contacts by the marks saved with them (a later save of a contact replaces an earlier one):
    how many there are, how many are leads, and why the others are not. since: only lists saved at or after this ISO time."""
    by_contact: dict[str, dict[str, Any]] = {}
    for record in reversed(await list_artifacts(chat_id)):  # oldest first
        if record["kind"] != "enriched_contacts" or record["created_at"] < since:
            continue
        for row in _rows(record["path"]):
            by_contact[email_of(row) or f"{_named(row)}|{creatives.field(row, 'company')}".lower()] = row
    failed = Counter(r.get("gate_reason") or "not checked" for r in by_contact.values() if r.get("gate") != "pass")
    return {"seen": len(by_contact), "passed": sum(r.get("gate") == "pass" for r in by_contact.values()), "failed": dict(failed)}


def stop_reason(target: int, tally: dict[str, Any], seen_before: int, left: float | None, rounds: int, data_out: bool = False) -> str | None:
    """Why sourcing ends after a round, or None to go on: the target is met, the budget is used up (credits, or the run's
    dollars at an outside data source), the round found no new contact (the source is dry), or the safety stop."""
    if tally["passed"] >= target:
        return "target_met"
    if data_out or (left is not None and left < 1):  # not enough for one more credit or one more paid call
        return "budget_used_up"
    if tally["seen"] <= seen_before:
        return "source_dry"
    return "round_limit" if rounds >= MAX_ROUNDS else None


def next_round(target: int, tally: dict[str, Any]) -> str:
    """The task for the next sourcing round."""
    failed = ", ".join(f"{n} {why}" for why, n in tally["failed"].items()) or "none"
    return (f"Lead target: {target} leads, {tally['passed']} so far; the others failed the gate ({failed}). Find more: new companies and "
            "buyers not already in this chat's lead lists, enrich only the buyers, and save them as enriched_contacts with the finder's "
            "email_status. A lead is a named person with a business email of their own that the finder verified.")


# a token the renderer left, or the sender placeholders agents write when they do not know a name
PLACEHOLDER = re.compile(r"\{\{.*?\}\}|\{[a-z_]+\}|\[(?:your|company|first|last|full|sender|recipient|insert)[^\]]*\]", re.I)


def send_problems(recipients: list[str], subject: str, body: str, suppressed: set[str]) -> list[str]:
    """Why an email must not go out, one line per problem: a placeholder left in it, or a recipient that is a shared
    inbox or suppressed. The send tool refuses on any; no approval overrides it."""
    problems = []
    if found := sorted({m.group(0) for m in PLACEHOLDER.finditer(f"{subject}\n{body}")}):
        problems.append("it has an unfilled placeholder: " + ", ".join(found))
    for to in recipients:
        if is_shared(to.strip().lower()):
            problems.append(f"{to} is a shared or role inbox")
        if to.strip().lower() in suppressed or to.strip().lower().split("@")[-1] in suppressed:
            problems.append(f"{to} is suppressed")
    return problems
