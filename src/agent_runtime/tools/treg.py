"""The agents' road to treg: people at a company with a work email treg found and checked. Everything paid, and every cap,
is in agent_runtime/treg.py; the tool is named `treg__...` so the connector strip shows the call under treg."""

import json

from src.agent_runtime import treg
from src.agent_runtime.tools.artifacts import _text
from src.agent_runtime.tools.context import ToolContext


def build(ctx: ToolContext):
    if not treg.offered(ctx.persona):
        return []
    from claude_agent_sdk import tool

    @tool(
        "treg__find_contacts",
        "Find the people to write to at a company, each with a work email treg found and checked in the same call. Use it when you "
        "need a person and a checked email that Data Axle did not give: the buyer for a signal, the people at an account listed "
        "under ACCOUNTS FROM SIGNALS, or an enriched person with no checked email. Costs real money per call, capped per run; "
        "people who could not pass the lead gate are left unpaid. Give the company's website and either `person` (a full name, "
        "when the signal, the account line or the record names one) or `titles` (up to 3 job titles, best first: the signal's "
        "target_titles when it has them, else the titles of whoever buys the user's offer). Returns `contacts` (full_name, title, "
        "email, email_status, email_source, gate, gate_reason): save them to enriched_contacts exactly as returned, email, "
        "email_status and email_source unchanged, since DAXAGENT decides who is a lead from them; a contact is a lead only when "
        "`gate` is pass. `skipped` are the people left unpaid and why. Stop calling it when `stopped_because` is set, and say how "
        "many people you could not check.",
        {"type": "object", "properties": {
            "website": {"type": "string", "description": "The company's website or domain, e.g. acme.com"},
            "person": {"type": "string", "description": "A person's full name, to find their email without searching"},
            "titles": {"type": "array", "items": {"type": "string"}, "description": "Job titles to search for at the company, best first"},
            "limit": {"type": "integer", "description": "How many people to find emails for (1 to 3, default 2)"},
        }, "required": ["website"]},
    )
    async def find_contacts(args: dict) -> dict:
        ctx.data_sources.add(treg.SERVER)
        titles = args.get("titles") or []
        result = await treg.find_contacts(ctx.user_id, ctx.chat_id, str(args.get("website") or ""), [titles] if isinstance(titles, str) else titles,
                                          str(args.get("person") or ""), int(args.get("limit") or 2))
        return _text(json.dumps(result, ensure_ascii=False))

    return [find_contacts]
