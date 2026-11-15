"""Replies a person must answer: who owns them (Settings, Team) and the handoffs waiting for them.

The Inbox Agent opens a handoff when Jev's route needs a person (handoff, propose_meeting, answer);
the owner claims it, edits the drafted reply and sends it from the handoff card.
"""

import uuid
from datetime import datetime, timedelta

from src.agent_runtime import prefs
from src.database import save_handoff

WORK_HOURS = (9, 17)  # meeting times are offered on weekdays inside these hours, the user's local time


def owner_for(team: dict, email: str, row_owner: str = "") -> dict | None:
    """The member who answers this contact: the contact's own owner, the owner of their email
    domain, then the default owner. None means the shared inbox (whoever claims it)."""
    members = {m["name"].lower(): m for m in team.get("members", [])}
    domain = email.rsplit("@", 1)[-1].lower()
    for name in (row_owner, (team.get("account_owners") or {}).get(domain, ""), team.get("default_owner", "")):
        if name and name.lower() in members:
            return members[name.lower()]
    return None


async def open_handoff(ctx, *, contact: str, route: str, reply: str, read: dict | None = None, plan_id: str = "",
                       thread_id: str = "", subject: str = "", draft: str = "", row_owner: str = "") -> dict:
    """Store the handoff, assign its owner and show it in the chat; returns it with the owner's details."""
    from src.services import brain_hands

    team = await prefs.get(ctx.user_id, "team")
    owner = owner_for(team, contact, row_owner)
    handoff = await save_handoff({
        "id": f"handoff-{uuid.uuid4().hex[:8]}", "user_id": ctx.user_id, "chat_id": ctx.chat_id, "plan_id": plan_id,
        "contact": contact.lower(), "thread_id": thread_id, "owner": owner["name"] if owner else "", "route": route,
        "subject": subject, "reply": reply, "read": read or {}, "draft": draft,
    })
    await ctx.emit({"type": "handoff", "handoff": handoff})
    notified = await notify(ctx.user_id, handoff, owner, team)
    await brain_hands.push_reply(
        handoff["id"], handoff["subject"], handoff["reply"], email=handoff["contact"], thread_id=handoff["thread_id"],
        intent=handoff["read"].get("intent", "other"), route=handoff["route"], draft=handoff["draft"],
        campaign_id=handoff["plan_id"], handoff_id=handoff["id"])
    return {**handoff, "owner_details": owner, "notified": notified}


def pick_slots(busy: list[tuple[datetime, datetime]], start: datetime, days: int = 5, minutes: int = 30, limit: int = 3) -> list[datetime]:
    """The first free time on each of the next working days (one per day, so the offer spreads out)."""
    picked, day = [], start.replace(minute=0, second=0, microsecond=0)
    while len(picked) < limit and day < start + timedelta(days=days + 4):
        if day.weekday() < 5:
            t = day.replace(hour=WORK_HOURS[0])
            while t + timedelta(minutes=minutes) <= day.replace(hour=WORK_HOURS[1]):
                end = t + timedelta(minutes=minutes)
                if t >= start + timedelta(hours=2) and not any(b0 < end and t < b1 for b0, b1 in busy):
                    picked.append(t)
                    break
                t += timedelta(minutes=30)
        day = (day + timedelta(days=1)).replace(hour=0)
    return picked


async def free_slots(user_id: str, days: int = 5, minutes: int = 30) -> list[str]:
    """Free meeting times from the user's Google Calendar (raises when Calendar is not connected)."""
    from src.agent_runtime.tools.sales import composio_call

    now = datetime.now().astimezone()
    result = await composio_call(user_id, "googlecalendar", "GOOGLECALENDAR_FIND_FREE_SLOTS", {
        "time_min": now.isoformat(timespec="seconds"), "time_max": (now + timedelta(days=days + 4)).isoformat(timespec="seconds"),
    }, "Google Calendar")
    if not (result or {}).get("successful", True):
        raise RuntimeError(f"Google Calendar: {(result or {}).get('error')}")
    calendars = ((result or {}).get("data") or {}).get("calendars") or {}
    busy = [(datetime.fromisoformat(b["start"]).astimezone(), datetime.fromisoformat(b["end"]).astimezone())
            for cal in calendars.values() for b in cal.get("busy", [])]
    return [t.isoformat(timespec="minutes") for t in pick_slots(busy, now, days, minutes)]


async def notify(user_id: str, handoff: dict, owner: dict | None, team: dict) -> list[str]:
    """Tell the owner (or the shared inbox) about a handoff on Slack and by email; returns what was sent or why not."""
    from src.agent_runtime.tools.sales import composio_call, gmail_call

    who = owner["name"] if owner else "the shared inbox"
    text = (f"Reply from {handoff['contact']} needs you ({handoff['route'].replace('_', ' ')}).\n"
            f"> {handoff['reply'][:400]}\n"
            f"Open DAXAGENT to read it and send the drafted answer." + ("" if owner else " Whoever takes it, claim it there."))
    slack_to = (owner or {}).get("slack") or ("" if owner else team.get("slack_channel", ""))
    emails = [owner["email"]] if owner and owner.get("email") else ([] if owner else [m["email"] for m in team.get("members", []) if m.get("email")])
    done = []
    if team.get("notify_slack", True) and slack_to:
        try:
            await composio_call(user_id, "slack", "SLACK_SEND_MESSAGE", {"channel": slack_to, "markdown_text": text}, "Slack")
            done.append(f"Slack {slack_to}")
        except Exception as e:
            done.append(f"Slack not sent: {e}")
    if team.get("notify_email", True):
        for email in emails:
            try:
                await gmail_call(user_id, "GMAIL_SEND_EMAIL", {"recipient_email": email, "subject": f"Reply from {handoff['contact']} for {who}",
                                                               "body": text, "user_id": "me", "is_html": False})
                done.append(f"email {email}")
            except Exception as e:
                done.append(f"email to {email} not sent: {e}")
    return done
