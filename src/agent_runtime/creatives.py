"""Render campaign copy for one recipient and flag what would embarrass the sender.

A campaign_plan artifact holds one row per segment x step with ``{{token}}``
placeholders; its ``meta`` holds the brief (sender, footer, fallbacks) and the
audience artifact the recipients come from. Pure functions, no I/O.
"""

import re
from typing import Any

TOKEN = re.compile(r"\{\{\s*([a-z_]+)\s*\}\}")
LINK = re.compile(r"https?://\S+")
LEGAL_SUFFIX = re.compile(r"[,\s]+(llc|l\.l\.c\.|inc\.?|incorporated|corp\.?|corporation|co\.?|ltd\.?|pllc|pc|p\.c\.)$", re.I)
MAX_WORDS = 150
FIRST_MAX_WORDS = 85  # the opener (step 1): short, and no link at all

# Token -> audience columns to try, in order (Data Axle and hand-made lists use different names).
ALIASES: dict[str, tuple[str, ...]] = {
    "first_name": ("first_name", "firstName", "contact_first_name"),
    "last_name": ("last_name", "lastName", "contact_last_name"),
    "full_name": ("full_name", "name", "contact_name", "buyer_name"),
    "title": ("title", "job_title", "contact_title", "buyer_title"),
    "company": ("company", "business_name", "company_name", "businessName", "masked_name"),
    "city": ("city",),
    "state": ("state",),
    "industry": ("industry", "sic_description", "primary_sic_description"),
    "employees": ("employees", "employee_count", "location_employee_count"),
    "email": ("email", "email_address", "work_email", "business_email", "contact_email"),
    "phone": ("phone", "phone_number"),
}
SENDER_TOKENS = ("sender_name", "sender_title", "sender_company")


def _tidy(token: str, value: str) -> str:
    """ALL-CAPS legal names read as spam; 'ACME PLUMBING LLC' becomes 'Acme Plumbing'."""
    if value.isupper() and len(value) > 3:
        value = re.sub(r"'S\b", "'s", value.title())  # "JOE'S" -> "Joe's", not "Joe'S"
    if token == "company":
        value = LEGAL_SUFFIX.sub("", value).strip()
    return value


def field(row: dict[str, Any], token: str) -> str:
    for key in ALIASES.get(token, (token,)):
        value = row.get(key)
        if value not in (None, ""):
            return str(value).strip()
    if token == "first_name":
        return field(row, "full_name").split(" ")[0]
    return ""


def render(text: str, row: dict[str, Any], brief: dict[str, Any]) -> tuple[str, list[str]]:
    """Fill ``{{tokens}}`` for one recipient; returns the text and what went wrong."""
    issues: list[str] = []
    fallbacks = brief.get("fallbacks") or {}

    def fill(match: re.Match) -> str:
        token = match.group(1)
        if token in SENDER_TOKENS:
            value = str(brief.get(token) or "")
        else:
            value = field(row, token)
            if "*" in value:  # Data Axle preview masking
                issues.append(f"masked {token}")
                value = ""
            value = _tidy(token, value) if value else ""
        if not value:
            value = str(fallbacks.get(token) or "")
            if not value:
                issues.append(f"empty {token}")
        return value

    if unknown := sorted({t for t in TOKEN.findall(text) if t not in ALIASES and t not in SENDER_TOKENS}):
        issues.append("unknown token " + ", ".join(unknown))
    return TOKEN.sub(fill, text or ""), issues


def footer(brief: dict[str, Any]) -> str:
    """Signature, postal address and opt-out line: the legal minimum for cold email."""
    lines = [brief.get("sender_name"), brief.get("sender_title"), brief.get("sender_company"),
             brief.get("postal_address"), brief.get("opt_out")]
    return "\n".join(str(v) for v in lines if v)


def message(step: dict[str, Any], row: dict[str, Any], brief: dict[str, Any], assets: dict[str, dict] | None = None) -> dict[str, Any]:
    """One finished message (subject, body with footer) plus lint issues. assets: the campaign's creatives by id,
    to check the step's attachments and inline image."""
    subject, subject_issues = render(step.get("subject") or "", row, brief)
    body, body_issues = render(step.get("body") or "", row, brief)
    issues = subject_issues + body_issues
    if assets is not None:
        from src.agent_runtime.assets import lint

        issues += lint(step, assets)
    channel = step.get("channel") or "email"
    # a step written for one recipient names them (Campaign Builder puts a public route there when the list has no email)
    to = str(step.get("recipient_email") or "").strip() or field(row, "email")
    if channel == "email" and int(step.get("step") or 1) == 1:  # the copy as written, before the footer (its opt-out may be a link)
        if len(body.split()) > FIRST_MAX_WORDS:
            issues.append(f"first email over {FIRST_MAX_WORDS} words")
        if LINK.search(body):
            issues.append("a link in the first email")
    if channel == "email":
        legal = [" ".join(str(brief[k]).split()) for k in ("postal_address", "opt_out") if brief.get(k)]
        if not (legal and all(v in " ".join(body.split()) for v in legal)):  # copy that signs off itself keeps its own
            body = f"{body.rstrip()}\n\n{footer(brief)}".rstrip()
        if not to:
            issues.append("no email")
        if not brief.get("opt_out") or not brief.get("postal_address"):
            issues.append("footer incomplete")
        if len(LINK.findall(body)) > 1:
            issues.append("more than one link")
    if len(body.split()) > MAX_WORDS:
        issues.append(f"over {MAX_WORDS} words")
    return {
        "step": step.get("step"), "role": step.get("role"), "channel": channel, "segment": step.get("segment"),
        "to": to, "phone": field(row, "phone"), "subject": subject, "body": body,
        "attachments": list(step.get("attachments") or []), "inline_image": step.get("inline_image") or "",
        "issues": sorted(set(issues)),
    }


def steps_for(plan: dict[str, Any], row: dict[str, Any]) -> list[dict[str, Any]]:
    """Plan rows that apply to one recipient: their segment's steps plus steps for 'all'.

    Without meta.segment_field a single named segment applies to everyone; with several,
    only the 'all' rows do (sending every segment's copy to everyone would duplicate steps).
    A row with `to` (add_touch) is that one recipient's own step and no one else's.
    """
    rows = plan.get("rows", [])
    seg_field = (plan.get("meta") or {}).get("segment_field")
    named = {str(s.get("segment") or "all") for s in rows if not s.get("to")} - {"all"}
    mine = str(row.get(seg_field, "")) if seg_field else (named.pop() if len(named) == 1 else "all")
    email = field(row, "email").lower()
    return [s for s in rows if (str(s["to"]).lower() == email if s.get("to") else str(s.get("segment") or "all") in ("all", mine))]


def blocking(issues: list[str]) -> list[str]:
    """Issues that must stop a send (style warnings such as length do not)."""
    return [i for i in issues if i.startswith(("no email", "masked", "empty", "unknown token", "footer incomplete", "missing attachment", "inline image"))]
