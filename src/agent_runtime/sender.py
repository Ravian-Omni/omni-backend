"""The address campaigns send from, and whether its domain is set up to be believed (SPF, DKIM, DMARC).

Everything here only warns: a send is never held back by it (the lead and send gates are the ones that block).
"""

import asyncio
import time

import httpx

from src.agent_runtime import prefs
from src.agent_runtime.leads import FREE_MAIL, bounce_stop

DKIM_SELECTORS = ("google", "selector1", "selector2", "default", "k1", "s1", "mail", "dkim")  # DKIM has no way to list a domain's selectors
CACHE_S = 3600
_domains: dict[str, tuple[float, list[str]]] = {}
_mailboxes: dict[str, tuple[float, str]] = {}
_mail_domains: dict[str, tuple[float, bool]] = {}
TYPES = {"TXT": 16, "MX": 15}


async def _records(name: str, kind: str, client: httpx.AsyncClient) -> list[str] | None:
    """A DNS name's records of one kind (through Google's DNS-over-HTTPS, which needs no extra package); [] when it has
    none, None when the lookup itself failed."""
    try:
        data = (await client.get("https://dns.google/resolve", params={"name": name, "type": kind}, headers={"accept": "application/dns-json"})).json()
    except (httpx.HTTPError, ValueError):
        return None
    if data.get("Status") not in (0, 3):  # 3: the name does not exist
        return None
    return [a["data"] for a in data.get("Answer", []) if a.get("type") == TYPES[kind]]


async def _txt(name: str, client: httpx.AsyncClient) -> list[str] | None:
    records = await _records(name, "TXT", client)
    return None if records is None else ["".join(r.split('" "')).strip('"') for r in records]


async def accepts_mail(domain: str) -> bool | None:
    """Whether the domain has an MX record that takes mail (a null MX, "0 .", says it takes none); None when the lookup
    failed. A domain is looked up once an hour, so once in a run."""
    if (hit := _mail_domains.get(domain)) and time.monotonic() - hit[0] < CACHE_S:
        return hit[1]
    async with httpx.AsyncClient(timeout=5) as client:
        mx = await _records(domain, "MX", client)
    if mx is None:
        return None  # not kept: the next run asks again
    takes = any(r.split()[-1] != "." for r in mx if r.split())
    _mail_domains[domain] = (time.monotonic(), takes)
    return takes


async def domain_warnings(domain: str) -> list[str]:
    """What is missing from the domain's SPF, DMARC and DKIM records (checked once an hour)."""
    if (hit := _domains.get(domain)) and time.monotonic() - hit[0] < CACHE_S:
        return hit[1]
    async with httpx.AsyncClient(timeout=5) as client:
        spf, dmarc, *dkim = await asyncio.gather(_txt(domain, client), _txt(f"_dmarc.{domain}", client),
                                                 *(_txt(f"{s}._domainkey.{domain}", client) for s in DKIM_SELECTORS))
    if spf is None or dmarc is None:
        found = [f"Could not check {domain}'s SPF, DKIM and DMARC records (the DNS lookup failed)."]
    else:
        found = []
        if not any(t.lower().startswith("v=spf1") for t in spf):
            found.append(f"{domain} has no SPF record: receivers cannot tell mail from it is really yours.")
        if not any(t.lower().startswith("v=dmarc1") for t in dmarc):
            found.append(f"{domain} has no DMARC record (_dmarc.{domain}).")
        if not any("v=dkim1" in t.lower() or "p=" in t.lower() for records in dkim for t in records or []):
            found.append(f"No DKIM record found for {domain} at the usual selectors ({', '.join(DKIM_SELECTORS)}); ignore this if yours uses another.")
    _domains[domain] = (time.monotonic(), found)
    return found


async def mailbox(user_id: str) -> str:
    """The address campaigns send from: the one set in Settings (prefs "sending"), else the connected Gmail account's own."""
    if configured := (await prefs.get(user_id, "sending")).get("mailbox", ""):
        return configured
    if (hit := _mailboxes.get(user_id)) and time.monotonic() - hit[0] < 600:
        return hit[1]
    from src.agent_runtime.tools.sales import gmail_call

    try:
        data = ((await gmail_call(user_id, "GMAIL_GET_PROFILE", {"user_id": "me"})) or {}).get("data") or {}
    except RuntimeError:  # Gmail is not connected: the send itself will say so
        return ""
    address = str((data.get("response_data") or data).get("emailAddress") or "")
    _mailboxes[user_id] = (time.monotonic(), address)
    return address


async def own_domains(user_id: str) -> set[str]:
    """The domains an email may link to as the user's own: the sending mailbox's and the ones listed in prefs "sending"."""
    listed = {d.strip().lower().removeprefix("www.") for d in (await prefs.get(user_id, "sending"))["domains"]}
    return {(await mailbox(user_id)).rsplit("@", 1)[-1].lower(), *listed} - {""}


async def warnings(user_id: str) -> list[str]:
    """What to tell the user about the address a send goes out from, before it does; empty when nothing is wrong."""
    stop = [line] if (line := await bounce_stop(user_id)) else []
    address = await mailbox(user_id)
    domain = address.rsplit("@", 1)[-1].lower()
    if not address:
        return stop
    if domain in FREE_MAIL:
        return [*stop, f"{address} is a free-mail address: cold email from it is likely to be filtered. Send from a mailbox on your own domain (prefs \"sending\")."]
    return [*stop, *await domain_warnings(domain)]
