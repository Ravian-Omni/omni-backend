"""The tools Outreach sends from: rendered approved steps, the send log, and the replies that stop follow-ups."""

from collections import Counter
from datetime import datetime, timedelta
from typing import Any

from src.agent_runtime import creatives
from src.agent_runtime.tools import artifacts
from src.agent_runtime.tools.context import ToolContext
from src.configs.datetime_utils import dt
from src.database import list_artifacts


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
            h = seen.setdefault(to, {"thread_id": None, "sent_at": {}, "replied": False})
            if row.get("status") == "sent":
                h["sent_at"].setdefault(row.get("step"), row.get("at"))
                h["thread_id"] = h["thread_id"] or row.get("thread_id")
            h["replied"] |= row.get("status") == "replied"
    return seen


def _due(sent_at: str | None, days: int) -> bool:
    try:
        return datetime.fromisoformat(str(sent_at)) + timedelta(days=days) <= dt.now()
    except (ValueError, TypeError):
        return True  # an unreadable timestamp never blocks a follow-up the user approved


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
            plan = artifacts.load(ctx, args["plan_id"])
            audience = artifacts.load(ctx, (plan.get("meta") or {}).get("audience_artifact_id") or "")["rows"]
        except FileNotFoundError as e:
            return artifacts._error(f"{e}. The plan needs meta.audience_artifact_id pointing at the contacts artifact.")
        brief = (plan.get("meta") or {}).get("brief") or {}
        history = await _history(ctx, args["plan_id"])
        ready, skipped, seen = [], Counter(), set()
        for row in audience:
            steps = creatives.steps_for(plan, row)
            emails = sorted({int(s.get("step") or 1) for s in steps if s.get("channel", "email") == "email"})
            for step in steps:
                n = int(step.get("step") or 1)
                if step.get("status") != "approved" or step.get("channel", "email") != "email":
                    continue
                if args.get("step") is not None and n != args["step"]:
                    continue
                if args.get("segment") and str(step.get("segment")) != args["segment"]:
                    continue
                m = creatives.message(step, row, brief)
                key = (m["to"].lower(), n)
                h = history.get(key[0], {"thread_id": None, "sent_at": {}, "replied": False})
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
                ready.append({**{k: m[k] for k in ("to", "subject", "body", "segment")}, "plan_id": args["plan_id"],
                              "step": n, "thread_id": h["thread_id"] if prev is not None else None})
        return artifacts._text({"ready": ready, "skipped": dict(skipped), "approved_steps": sum(
            1 for s in plan.get("rows", []) if s.get("status") == "approved")})

    @tool(
        "check_replies",
        "Check Gmail for replies to a campaign's sent emails. Returns each reply with its text; classify the intent "
        "(interested, not_now, unsubscribe, out_of_office, other) and store it with record_reply, which stops "
        "further follow-ups to that person (an unsubscribe stops every campaign).",
        {"type": "object", "properties": {"plan_id": {"type": "string"}}, "required": ["plan_id"]},
    )
    async def check_replies(args: dict) -> dict:
        from src.agent_runtime.tools.sales import gmail_call

        history = await _history(ctx, args["plan_id"])
        threads = {to: h["thread_id"] for to, h in history.items() if h["thread_id"] and not h["replied"]}
        replies, errors = [], []
        for to, thread_id in threads.items():
            try:
                result = await gmail_call(ctx.user_id, "GMAIL_FETCH_MESSAGE_BY_THREAD_ID", {"thread_id": thread_id, "user_id": "me"})
            except RuntimeError as e:
                return artifacts._error(str(e))
            messages = ((result or {}).get("data") or {}).get("messages") or []
            theirs = [m for m in messages if to in str(m.get("sender") or "").lower()]
            if theirs:
                last = theirs[-1]
                replies.append({"to": to, "thread_id": thread_id, "received": last.get("messageTimestamp"),
                                "text": str(last.get("messageText") or last.get("preview") or "")[:1500]})
            elif not (result or {}).get("successful", True):
                errors.append({"to": to, "error": (result or {}).get("error")})
        return artifacts._text({"threads_checked": len(threads), "replies": replies, "errors": errors})

    @tool(
        "record_reply",
        "Store a classified reply in the campaign's send log. intent is interested, not_now, unsubscribe, "
        "out_of_office or other.",
        {
            "type": "object",
            "properties": {
                "plan_id": {"type": "string"},
                "to": {"type": "string"},
                "intent": {"type": "string", "enum": ["interested", "not_now", "unsubscribe", "out_of_office", "other"]},
                "summary": {"type": "string", "description": "One line on what they said"},
            },
            "required": ["plan_id", "to", "intent"],
        },
    )
    async def record_reply(args: dict) -> dict:
        await record(ctx, args["plan_id"], {"to": args["to"].lower(), "status": "replied", "intent": args["intent"],
                                            "summary": args.get("summary", "")})
        return artifacts._text({"recorded": True, "send_log": log_id(args["plan_id"])})

    return [render_campaign, check_replies, record_reply]
