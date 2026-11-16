"""The Inbox Agent's handoff tool: give a reply to the person on the team who owns the contact."""

from src.agent_runtime import inbox, jev
from src.agent_runtime.tools.artifacts import _error, _text
from src.agent_runtime.tools.context import ToolContext


def build(ctx: ToolContext):
    from claude_agent_sdk import tool

    @tool(
        "hand_off",
        "Give a reply to the person on the team who owns the contact (Settings, Team): it appears as a handoff card "
        "they claim, edit and send. Use it for the routes handoff, propose_meeting and answer. Put your suggested "
        "reply in draft (for propose_meeting, the meeting times; for answer, the answer). Never send it yourself.",
        {
            "type": "object",
            "properties": {
                "contact": {"type": "string", "description": "Email of the person who replied"},
                "route": {"type": "string", "enum": ["handoff", "propose_meeting", "answer"]},
                "reply": {"type": "string", "description": "Their reply, as check_replies gave it"},
                "draft": {"type": "string", "description": "Your suggested answer, or empty"},
                "subject": {"type": "string"},
                "plan_id": {"type": "string"},
                "thread_id": {"type": "string"},
                "read": {"type": "object", "description": "Jev's reading from check_replies, as given"},
                "owner": {"type": "string", "description": "The contact's owner when the contact row names one"},
            },
            "required": ["contact", "route", "reply"],
        },
    )
    async def hand_off(args: dict) -> dict:
        h = await inbox.open_handoff(
            ctx, contact=args["contact"], route=args["route"], reply=args["reply"], read=args.get("read"),
            plan_id=args.get("plan_id", ""), thread_id=args.get("thread_id", ""), subject=args.get("subject", ""),
            draft=args.get("draft", ""), row_owner=args.get("owner", ""),
        )
        owner = h["owner_details"]
        return _text({"handoff_id": h["id"], "owner": owner["name"] if owner else None,
                      "assigned_to": owner["name"] if owner else "the shared inbox (no owner set in Settings, Team)",
                      "route": jev.ROUTES.get(h["route"], h["route"]), "notified": h["notified"] or "nobody (no Slack or email set in Settings, Team)"})

    @tool(
        "meeting_slots",
        "Up to three free 30-minute times in the user's Google Calendar over the next working days (09:00 to 17:00, "
        "their time, one per day), for a propose_meeting draft. If Calendar is not connected or nothing is free, "
        "write the draft without times and say the owner will suggest some.",
        {"type": "object", "properties": {"days": {"type": "integer", "minimum": 1, "maximum": 10},
                                          "minutes": {"type": "integer", "enum": [15, 30, 45, 60]}}},
    )
    async def meeting_slots(args: dict) -> dict:
        try:
            slots = await inbox.free_slots(ctx.user_id, int(args.get("days") or 5), int(args.get("minutes") or 30))
        except RuntimeError as e:
            return _error(str(e))
        return _text({"slots": slots, "note": "Times are in the user's timezone; name the timezone in the draft."})

    @tool(
        "calendar_events",
        "The user's Google Calendar events a person is invited to: within a day of `when`, else over the next 14 days. "
        "Returns each event's title, start, end, attendees, description and link. Reads only.",
        {"type": "object", "properties": {"email": {"type": "string", "description": "The person's email"},
                                          "when": {"type": "string", "description": "The meeting's date and time if known, e.g. 2026-11-20 15:00"}},
         "required": ["email"]},
    )
    async def calendar_events(args: dict) -> dict:
        try:
            return _text({"events": await inbox.events_with(ctx.user_id, str(args["email"]), str(args.get("when") or ""))})
        except RuntimeError as e:
            return _error(str(e))

    return [hand_off, meeting_slots, calendar_events]
