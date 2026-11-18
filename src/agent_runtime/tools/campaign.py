"""The tools Outreach sends from: rendered approved steps, the send log, and the replies that stop follow-ups."""

import asyncio
import json
import os
import re
from collections import Counter
from datetime import datetime, timedelta
from email.utils import parseaddr
from types import SimpleNamespace
from typing import Any

from src.agent_runtime import creatives, crm, jev, leads, prefs
from src.agent_runtime.tools import artifacts
from src.agent_runtime.tools.context import ToolContext
from src.configs.datetime_utils import dt
from src.database import find_artifacts, list_artifacts, list_creatives, suppress_email

# Replies DAX settles itself, with no handoff: Brain_Hands is told of them from record_reply
SETTLED_ROUTES = ("suppress", "snooze", "auto_reply")

# A delivery failure in a sent thread (a "Delay" notice is not one: the mail still goes out)
BOUNCE = re.compile(r"mailer-daemon|postmaster|delivery status|undeliver|returned to sender|delivery (has )?failed|address not found|failure notice", re.I)


def log_id(plan_id: str) -> str:
    """One send log per plan, id shaped like every artifact id (kind-8 chars)."""
    return f"send_log-{plan_id[-8:]}"


async def record(ctx: ToolContext, plan_id: str, row: dict[str, Any]) -> None:
    """Append one outcome (sent, drafted, replied) to the plan's send log, quietly."""
    try:
        rows = artifacts.load(ctx, log_id(plan_id))["rows"]
    except FileNotFoundError:
        rows = []
    rows.append({"plan_id": plan_id, "at": dt.now_iso(), **row})
    await artifacts.write(ctx, "send_log", f"Send log for {plan_id}", rows, source="send tools", artifact_id=log_id(plan_id), announce=False)


async def _history(ctx: ToolContext, plan_id: str) -> dict[str, dict[str, Any]]:
    """Per recipient email: when each step was sent, the thread of the first email, and whether they replied."""
    seen: dict[str, dict[str, Any]] = {}
    for rec in await list_artifacts(ctx.chat_id):
        if rec["kind"] != "send_log":
            continue
        for row in artifacts.load(ctx, rec["id"]).get("rows", []):
            to = str(row.get("to") or "").lower()
            unsubscribed = row.get("status") == "replied" and str(row.get("intent") or "").lower() == "unsubscribe"
            if not to or (row.get("plan_id") not in (None, plan_id) and not unsubscribed):
                continue  # an unsubscribe holds the contact in every campaign
            h = seen.setdefault(to, {"thread_id": None, "sent_at": {}, "replied": False, "handled": set()})
            if row.get("status") == "sent":
                h["sent_at"].setdefault(row.get("step"), row.get("at"))
                h["thread_id"] = h["thread_id"] or row.get("thread_id")
            h["replied"] |= row.get("status") in ("replied", "bounced")  # an auto_reply (out of office) does not hold follow-ups
            if row.get("message_id"):
                h["handled"].add(row["message_id"])
    return seen


def _due(sent_at: str | None, days: int) -> bool:
    try:
        return datetime.fromisoformat(str(sent_at)) + timedelta(days=days) <= dt.now()
    except (ValueError, TypeError):
        return True  # an unreadable timestamp never blocks a follow-up the user approved


async def fetch_replies(ctx, plan_id: str) -> dict[str, Any]:
    """New replies on a plan's sent threads, each read by Jev (with a route) when Jev is connected.
    Raises RuntimeError when Gmail is not connected. Used by check_replies and the reply watcher."""
    from src.agent_runtime.tools.sales import gmail_call

    history = await _history(ctx, plan_id)
    threads = {to: h for to, h in history.items() if h["thread_id"] and not h["replied"]}
    replies, bounces, errors = [], [], []
    for to, h in threads.items():
        result = await gmail_call(ctx.user_id, "GMAIL_FETCH_MESSAGE_BY_THREAD_ID", {"thread_id": h["thread_id"], "user_id": "me"})
        messages = ((result or {}).get("data") or {}).get("messages") or []
        theirs = [m for m in messages if to in str(m.get("sender") or "").lower()]
        dsn = [m for m in messages if m not in theirs and m.get("messageId") not in h["handled"] and "delay" not in str(m.get("subject") or "").lower()
               and BOUNCE.search(f"{m.get('sender') or ''} {m.get('subject') or ''}")]
        if dsn:  # the address does not take mail: no reply will come
            m = dsn[-1]
            bounces.append({"to": to, "thread_id": h["thread_id"], "message_id": m.get("messageId"),
                            "from": parseaddr(str(m.get("sender") or ""))[1] or str(m.get("sender") or ""),
                            "subject": m.get("subject") or "", "text": str(m.get("messageText") or m.get("preview") or "")[:1500]})
        elif theirs and theirs[-1].get("messageId") not in h["handled"]:
            last = theirs[-1]
            replies.append({"to": to, "thread_id": h["thread_id"], "message_id": last.get("messageId"),
                            "received": last.get("messageTimestamp"), "subject": last.get("subject") or "",
                            "text": str(last.get("messageText") or last.get("preview") or "")[:1500]})
        elif not theirs and not (result or {}).get("successful", True):
            errors.append({"to": to, "error": (result or {}).get("error")})
    if replies and jev.configured():
        rules = await prefs.get(ctx.user_id, "inbox")
        for r in replies:
            try:
                r["read"] = await jev.read_reply(r["text"], {"subject": r["subject"], "from": r["to"]})
                r["route"] = jev.route(r["read"], rules)
            except jev.JevError as e:
                r["read_error"] = str(e)  # this one is classified by the agent (or handed to a person) instead
    return {"threads_checked": len(threads), "replies": replies, "bounces": bounces, "errors": errors,
            "decided_by": "jev" if jev.configured() else "you"}


async def settle_bounces(ctx, plan_id: str, bounces: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Hold the sequence for each bounced address and hand the delivery failure to a person (route "bounce", from the
    mailer-daemon, its text naming the address); returns the handoffs."""
    from src.agent_runtime import inbox

    opened = []
    for b in bounces:
        await record(ctx, plan_id, {"to": b["to"], "status": "bounced", "message_id": b["message_id"], "summary": b["subject"]})
        await suppress_email(ctx.user_id, b["to"], "bounce")  # not this campaign only: every later run
        crm.later(lambda to=b["to"]: crm.suppress(to, "bounce"))
        opened.append(await inbox.open_handoff(ctx, contact=b["from"], route="bounce", reply=b["text"], read={"intent": "bounce", "address": b["to"]},
                                               plan_id=plan_id, thread_id=b["thread_id"], subject=b["subject"]))
    return opened


async def record_reply(ctx, plan_id: str, to: str, intent: str, route: str = "", summary: str = "", message_id: str = "",
                       text: str = "", subject: str = "", thread_id: str = "") -> dict[str, Any]:
    """Log a reply: it holds further follow-ups, except an out-of-office; not_now gets its snooze date. A reply settled
    here (unsubscribe, not now, out of office) is also pushed to Brain_Hands, keyed on its Gmail message."""
    auto = intent == "out_of_office" or route == "auto_reply"
    row = {"to": to.lower(), "status": "auto_reply" if auto else "replied", "intent": intent, "route": route,
           "summary": summary, "message_id": message_id}
    if intent == "not_now" or route == "snooze":
        row["snooze_until"] = (dt.now() + timedelta(days=(await prefs.get(ctx.user_id, "inbox"))["snooze_days"])).date().isoformat()
    await record(ctx, plan_id, row)
    if route == "suppress" or intent == "unsubscribe":
        await suppress_email(ctx.user_id, to, "unsubscribe")  # every later run, not only this campaign
        crm.later(lambda: crm.suppress(to, "unsubscribe"))
    if message_id:  # the reply on the person's CRM record, keyed on the Gmail message
        crm.later(lambda: crm.activity(to, "reply", text or summary or intent, message_id))
    if route in SETTLED_ROUTES and message_id:
        from src.services import brain_hands

        brain_hands.push_in_background("reply", f"reply:{message_id}", subject, text or summary, email=to.lower(), thread_id=thread_id,
                                       intent=intent, route=route, campaign_id=plan_id)
    return row


async def own_plan(ctx: ToolContext, plan_id: str) -> dict[str, Any]:
    """The plan, which must be this chat's own: its approvals and its send log live with it.
    Raises FileNotFoundError for a plan made in another chat (saying what to do) and for one that is not the user's."""
    plan, origin = await artifacts.find(ctx, plan_id)
    if origin:
        raise FileNotFoundError(
            f"The plan '{plan_id}' belongs to {origin}, where its approvals and send log are. Send it from there, or copy it into "
            "this chat with update_artifact (pass only artifact_id): the copy's steps go back to draft for the user to approve")
    return plan


async def render_plan(ctx: ToolContext, plan_id: str, only_step: int | None = None, segment: str | None = None) -> dict[str, Any]:
    """The plan's approved email steps rendered per recipient: ready messages and why the rest are held.
    Raises FileNotFoundError when the plan is not this chat's own or its audience is missing."""
    plan = await own_plan(ctx, plan_id)
    audience = (await artifacts.find(ctx, (plan.get("meta") or {}).get("audience_artifact_id") or ""))[0]["rows"]
    brief = (plan.get("meta") or {}).get("brief") or {}
    assets = {c["id"]: c for c in await list_creatives(ctx.chat_id, plan_id)}
    history = await _history(ctx, plan_id)
    ready, skipped, seen = [], Counter(), set()
    suppressed, written = await leads.sets(ctx.user_id, ctx.chat_id)
    worked = await leads.proven(ctx.chat_id)
    await leads.settle(ctx.chat_id, audience)  # the statuses code decides, also on an audience that never went through save
    resort = leads.last_resorts(audience)
    for row in audience:
        verdict, why = leads.gate(row, suppressed, written, worked, resort)
        if verdict != "pass":
            skipped.update([f"not a lead: {why}"])  # once per contact, whatever the step says
            continue
        steps = creatives.steps_for(plan, row)
        emails = sorted({int(s.get("step") or 1) for s in steps if s.get("channel", "email") == "email"})
        for step in steps:
            n = int(step.get("step") or 1)
            if step.get("status") != "approved" or step.get("channel", "email") != "email":
                continue
            if only_step is not None and n != only_step:
                continue
            if segment and str(step.get("segment")) != segment:
                continue
            m = creatives.message(step, row, brief, assets)
            key = (m["to"].lower(), n)
            h = history.get(key[0], {"thread_id": None, "sent_at": {}, "replied": False, "handled": set()})
            prev = max((e for e in emails if e < n), default=None)
            first_sent = h["sent_at"].get(emails[0]) if emails else None
            held = creatives.blocking(m["issues"]) or [
                reason for reason, hit in (
                    ("replied", h["replied"]),
                    ("already sent", n in h["sent_at"]),
                    ("previous step not sent", prev is not None and prev not in h["sent_at"]),
                    ("not due yet", prev is not None and first_sent and not _due(first_sent, int(step.get("send_after_days") or 0))),
                    ("duplicate email", key in seen),
                ) if hit
            ]
            if held:
                skipped.update(held[:1])
                continue
            seen.add(key)
            ready.append({**{k: m[k] for k in ("to", "subject", "body", "segment", "attachments", "inline_image")}, "plan_id": plan_id,
                          "step": n, "thread_id": h["thread_id"] if prev is not None else None})
    return {"ready": ready, "skipped": dict(skipped), "approved_steps": sum(1 for s in plan.get("rows", []) if s.get("status") == "approved")}


_touching = asyncio.Lock()  # two touches added at once must not both rewrite the same plan file


async def add_touch(user_id: str, chat_id: str, to: str, subject: str, body: str, send_after_days: int = 0, plan_id: str = "",
                    sign_off: dict[str, str] | None = None) -> dict[str, Any]:
    """One email for one person, its copy stored exactly as given, as a draft step of the chat's plan (contract [21] item 4):
    {plan_id, step, status} or {refused: why}. The person must pass the lead gate in this chat now, from its saved contacts.
    The step is the person's highest step plus one; with no plan_id a plan is started, on the contacts list that holds them
    and with the sign-off given (sender_name, sender_title, sender_company, postal_address, opt_out), else that of the newest
    campaign brief that has one. The user approves it on the campaign page."""
    to = to.strip().lower()
    refused = lambda why: {"refused": why}  # noqa: E731
    if not subject.strip() or not body.strip():
        return refused("empty subject or body")
    saved = await list_artifacts(chat_id)  # newest first: a later save of a contact is the one that counts
    found = next(((rec, r) for rec in saved if rec["kind"] == "enriched_contacts" for r in leads._rows(rec["path"]) if leads.email_of(r) == to), None)
    if not found:
        return refused("not a contact saved in this chat")
    audience, row = found
    suppressed, written = await leads.sets(user_id, chat_id)
    await leads.settle(chat_id, [row])
    verdict, why = leads.gate(row, suppressed, written, await leads.proven(chat_id), leads.last_resorts(leads._rows(audience["path"])))
    if verdict != "pass":
        return refused(f"did not pass the lead gate: {why}")
    for rec in saved:
        if rec["kind"] == "send_log" and (hit := next((r["status"] for r in leads._rows(rec["path"]) if str(r.get("to") or "").lower() == to
                                                       and r.get("status") in ("replied", "bounced")), None)):
            return refused(hit)
    async with _touching:
        if plan_id:
            try:
                record, plan = await artifacts.load_record(chat_id, plan_id)
            except FileNotFoundError:
                return refused("not a campaign plan of this chat")
            if record["kind"] != "campaign_plan":
                return refused("not a campaign plan of this chat")
            try:
                people = (await artifacts.load_record(chat_id, (plan.get("meta") or {}).get("audience_artifact_id") or ""))[1].get("rows", [])
            except FileNotFoundError:
                people = []
            if not any(leads.email_of(r) == to for r in people):
                return refused("not in the plan's contacts list: add_touch with no plan_id starts a plan for them")
            brief = (plan.get("meta") or {}).get("brief") or {}
        else:
            if mine := next((rec["id"] for rec in saved if rec["kind"] == "campaign_plan"
                             and any(str(s.get("to") or "").lower() == to for s in leads._rows(rec["path"]))), None):
                return refused(f"already in plan {mine}: pass its plan_id")
            if given := {k: v.strip() for k, v in (sign_off or {}).items() if v and v.strip()}:
                brief = given if given.get("postal_address") and given.get("opt_out") else None
            else:
                plans = await find_artifacts(user_id, "", "campaign_plan", 200)  # the user's, newest first
                brief = next((b for rec in plans if (b := _brief(rec["path"])).get("postal_address") and b.get("opt_out")), None)
            if not brief:
                return refused("no sign-off: give postal_address and opt_out, or keep a campaign brief that has both")
            record, plan = None, {"rows": []}
        n = max((int(s.get("step") or 1) for s in plan["rows"] if str(s.get("to") or "").lower() == to), default=0) + 1
        links = len(creatives.LINK.findall(body))
        _, issues = creatives.render(f"{subject}\n{body}", row, brief)
        for fails, why in ((n == 1 and len(body.split()) > creatives.FIRST_MAX_WORDS, f"first email over {creatives.FIRST_MAX_WORDS} words"),
                           (n == 1 and links, "a link in the first email"), (links > 1, "more than one link"),
                           (bool(creatives.blocking(issues)), "; ".join(creatives.blocking(issues)))):
            if fails:
                return refused(why)
        step = {"segment": to, "to": to, "step": n, "role": "opener" if n == 1 else "follow_up", "send_after_days": 0 if n == 1 else max(0, int(send_after_days)),
                "channel": "email", "subject": subject, "body": body, "status": "draft"}
        if record:
            plan["rows"].append({**step, "_id": max((int(s.get("_id") or 0) for s in plan["rows"]), default=0) + 1})
            plan.setdefault("meta", {})["rev"] = int(plan["meta"].get("rev") or 0) + 1  # the page holding the old rev reloads before it edits
            await artifacts.save_payload(record, plan)
        else:
            ctx = SimpleNamespace(chat_id=chat_id, user_id=user_id, task_id=None, persona="brain_hands", artifacts_dir=os.path.dirname(audience["path"]), data_sources=set())
            record = await artifacts.write(ctx, "campaign_plan", f"Touches for {creatives.field(row, 'company') or to}", [step], source="add_touch: copy from Brain_Hands",
                                           meta={"audience_artifact_id": audience["id"], "brief": brief}, announce=False)
    return {"plan_id": record["id"], "step": n, "status": "draft"}


def _brief(path: str) -> dict[str, Any]:
    try:
        with open(path) as f:
            return (json.load(f).get("meta") or {}).get("brief") or {}
    except (OSError, ValueError):
        return {}


def build(ctx: ToolContext):
    from claude_agent_sdk import tool

    @tool(
        "render_campaign",
        "Finished messages of a campaign_plan for sending: each approved email step rendered for each recipient, "
        "footer included. Send 'ready' messages exactly as given, passing plan_id and step (and thread_id when "
        "present) to the send tool. 'skipped' counts why the rest are held: no email, masked or empty fields, "
        "incomplete footer, replied, previous step not sent, not due yet, already sent, duplicate email.",
        {
            "type": "object",
            "properties": {
                "plan_id": {"type": "string"},
                "step": {"type": "integer"},
                "segment": {"type": "string"},
            },
            "required": ["plan_id"],
        },
    )
    async def render_campaign(args: dict) -> dict:
        try:
            return artifacts._text(await render_plan(ctx, args["plan_id"], args.get("step"), args.get("segment")))
        except FileNotFoundError as e:
            # the hint is for a missing audience; an error that names the plan is about the plan itself
            hint = "" if args["plan_id"] in str(e) else " The plan needs meta.audience_artifact_id pointing at the contacts artifact."
            return artifacts._error(f"{e}.{hint}")

    @tool(
        "check_replies",
        "Check Gmail for replies to a campaign's sent emails. Each reply comes with its text and, when Jev is "
        "connected, Jev's reading (intent and probabilities) and a route to follow: suppress, auto_reply, snooze, "
        "handoff, propose_meeting or answer. Without Jev, classify the intent yourself. Store every reply with "
        "record_reply (it holds further follow-ups to that person; an unsubscribe stops every campaign).",
        {"type": "object", "properties": {"plan_id": {"type": "string"}}, "required": ["plan_id"]},
    )
    async def check_replies(args: dict) -> dict:
        try:
            await own_plan(ctx, args["plan_id"])
            found = await fetch_replies(ctx, args["plan_id"])
        except (RuntimeError, FileNotFoundError) as e:
            return artifacts._error(str(e))
        found["bounces"] = [{"to": b["to"], "subject": b["subject"], "handoff": h["id"]}
                            for b, h in zip(found["bounces"], await settle_bounces(ctx, args["plan_id"], found["bounces"]))]
        return artifacts._text({**found, "routes": jev.ROUTES, "bounces_note": "Bounced addresses are recorded already "
                                "(their follow-ups are held and a person has the handoff); do not record_reply them."})

    @tool(
        "record_reply",
        "Store a reply in the campaign's send log: Jev's intent and route when check_replies gave them. It holds "
        "further follow-ups to that person, except an out-of-office (the sequence goes on); not_now comes back "
        "after the snooze days set in Settings.",
        {
            "type": "object",
            "properties": {
                "plan_id": {"type": "string"},
                "to": {"type": "string"},
                "intent": {"type": "string", "enum": list(jev.INTENTS)},
                "route": {"type": "string", "enum": list(jev.ROUTES)},
                "summary": {"type": "string", "description": "One line on what they said"},
                "message_id": {"type": "string", "description": "From check_replies, so the same reply is never handled twice"},
            },
            "required": ["plan_id", "to", "intent"],
        },
    )
    async def record_reply_tool(args: dict) -> dict:
        try:
            await own_plan(ctx, args["plan_id"])  # a reply logged from another chat would take the plan's send log with it
        except FileNotFoundError as e:
            return artifacts._error(str(e))
        row = await record_reply(ctx, args["plan_id"], args["to"], args["intent"], args.get("route", ""),
                                 args.get("summary", ""), args.get("message_id", ""))
        return artifacts._text({"recorded": True, "send_log": log_id(args["plan_id"]), "status": row["status"],
                                "snooze_until": row.get("snooze_until")})

    @tool(
        "read_creatives",
        "The ad creatives the user uploaded for a campaign plan (campaign page, Creatives): id, name, type, public "
        "link and what each says (an image's words and look, a PDF's or text file's content). Match the copy to them, "
        "and set a step's attachments or inline_image to their ids when that step should carry one.",
        {"type": "object", "properties": {"plan_id": {"type": "string"}}, "required": ["plan_id"]},
    )
    async def read_creatives(args: dict) -> dict:
        found = await list_creatives(ctx.chat_id, args["plan_id"])
        return artifacts._text([{"id": c["id"], "name": c["name"], "type": c["mime"], "size_kb": c["size"] // 1024,
                                 "public_link": c["url"], "says": c["summary"] or "(could not be read)"} for c in found]
                               or "No creatives uploaded for this campaign.")

    return [render_campaign, check_replies, record_reply_tool, read_creatives]
