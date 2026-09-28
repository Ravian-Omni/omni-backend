"""Tools for the sales personas: SIC lookup, the approval gates, questions to
the user, and Gmail through Composio."""

import json
import re
from typing import Any

from loguru import logger

from src.agent_runtime import sic
from src.agent_runtime.tools import artifacts
from src.agent_runtime.tools.context import ToolContext
from src.agent_runtime.tools.context import server_of as _server_of


def _text(payload: Any) -> dict:
    return {"content": [{"type": "text", "text": payload if isinstance(payload, str) else json.dumps(payload, default=str)}]}


def _error(msg: str) -> dict:
    return {"content": [{"type": "text", "text": msg}], "is_error": True}


async def _credit_balance(server: str) -> int | None:
    """Ask a server for its credit balance when it exposes one."""
    from src.mcp_client import call_tool, is_connected, list_tools

    try:
        if not await is_connected(server):
            return None
        names = {t["name"] for t in await list_tools(server)}
        if "fetch_available_credits" not in names:
            return None
        raw = await call_tool(server, "fetch_available_credits", {})
        m = re.search(r'"availableCredits"\s*:\s*(\d+)', raw) or re.search(r"(\d+)", raw)
        return int(m.group(1)) if m else None
    except Exception as e:
        logger.warning(f"Could not read credit balance from {server}: {e}")
        return None


async def gmail_call(user_id: str, slug: str, arguments: dict) -> Any:
    """Run one Composio Gmail action for the user; raises when Gmail is not connected."""
    import asyncio

    from composio import Composio

    from src.configs.llm_configs_manager import LLMConfigManager

    key = LLMConfigManager.get_config("composio_api_key").get("config_list", [{}])[0].get("api_key")
    if not key:
        raise RuntimeError("Composio API key not set. Add it in Settings.")
    client = Composio(api_key=key)
    connections = await asyncio.to_thread(client.connected_accounts.list, user_ids=[user_id])
    if not any(c.toolkit and c.toolkit.slug.lower() == "gmail" and c.status == "ACTIVE" for c in connections.items):
        raise RuntimeError("Gmail is not connected. Ask the user to connect Gmail in Settings, then try again.")
    return await asyncio.to_thread(
        client.tools.execute, slug=slug, user_id=user_id, arguments=arguments, dangerously_skip_version_check=True
    )




def build(ctx: ToolContext):
    from claude_agent_sdk import tool

    @tool(
        "sic_lookup",
        "Find SIC industry codes for an industry described in words (e.g. 'dental offices', 'SaaS companies'). "
        "Returns the best matching 4-digit codes with descriptions; pass a code to Data Axle as primary_sic_code_id.",
        {"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 20}}, "required": ["query"]},
    )
    async def sic_lookup(args: dict) -> dict:
        return _text(sic.lookup(args["query"], int(args.get("limit") or 8)))

    @tool(
        "request_spend_approval",
        "Ask the user to approve spending credits BEFORE calling a tool that costs credits (e.g. business_enrichment). "
        "Shows the count, the credit cost and the balance. If approved, that many calls of the tool are allowed; "
        "declined means do not call it.",
        {
            "type": "object",
            "properties": {
                "tool": {"type": "string", "description": "The credit-consuming tool, e.g. contact_enrichment"},
                "count": {"type": "integer", "minimum": 1, "description": "How many records you will enrich"},
                "reason": {"type": "string", "description": "One line on why, e.g. 'resolve the 40 buyer contacts in buyer_map-1a2b'"},
                "credits_per_call": {"type": "integer", "minimum": 1, "description": "Default 1"},
            },
            "required": ["tool", "count", "reason"],
        },
    )
    async def request_spend_approval(args: dict) -> dict:
        full = ctx.resolve_tool(args["tool"])
        if not full:
            return _error(f"Unknown tool '{args['tool']}'. Known credit tools: "
                          + ", ".join(k.split('__')[-1] for k, c in ctx.remote_tool_classes.items() if c == 'spend'))
        server = _server_of(full)
        count = int(args["count"])
        per_call = int(args.get("credits_per_call") or 1)
        balance = await _credit_balance(server)
        decision = await ctx.decisions.confirm_spend(
            tool=full.split("__")[-1], server=server, count=count, credits=count * per_call,
            balance_before=balance, detail=args.get("reason", ""),
        )
        if decision.approved:
            ctx.spend_allowance[full] = ctx.spend_allowance.get(full, 0) + count  # approvals add up
            return _text({"approved": True, "tool": full.split("__")[-1], "calls_allowed": count, "balance_before": balance})
        return _text({"approved": False, "message": "The user declined the credit spend. Do not call the tool; report and offer a smaller batch."})

    @tool(
        "request_send_approval",
        "Ask the user to approve sending a batch of messages BEFORE sending. Shows the recipients, subject and body. "
        "If approved, that many sends are allowed; declined means send nothing.",
        {
            "type": "object",
            "properties": {
                "channel": {"type": "string", "description": "email"},
                "recipients": {"type": "array", "items": {"type": "string"}, "description": "Email addresses"},
                "subject": {"type": "string"},
                "body_preview": {"type": "string", "description": "The exact body for the first recipient"},
                "reason": {"type": "string", "description": "Which campaign step and segment this is"},
                "draft_only": {"type": "boolean", "description": "True when creating drafts instead of sending"},
            },
            "required": ["channel", "recipients", "subject", "body_preview"],
        },
    )
    async def request_send_approval(args: dict) -> dict:
        recipients = [r for r in (args.get("recipients") or []) if isinstance(r, str) and r.strip()]
        if not recipients:
            return _error("No recipients given")
        tool_name = "gmail_create_draft" if args.get("draft_only") else "gmail_send_email"
        decision = await ctx.decisions.confirm_send(
            tool=tool_name, server="composio", channel=args.get("channel", "email"), recipients=recipients,
            subject=args.get("subject", ""), body_preview=args.get("body_preview", ""), detail=args.get("reason", ""),
        )
        if decision.approved:
            # Any send tool may deliver the approved batch (Outreach's Gmail tool or Gmail's own).
            ctx.send_allowance["*"] = ctx.send_allowance.get("*", 0) + len(recipients)
            return _text({"approved": True, "sends_allowed": len(recipients), "tool": tool_name})
        return _text({"approved": False, "message": "The user declined this batch. Send nothing; report and ask what to change."})

    @tool(
        "ask_user",
        "Ask the user a free-form question and wait for the answer. Use it whenever you need information you cannot look up.",
        {"type": "object", "properties": {"question": {"type": "string"}, "title": {"type": "string"}}, "required": ["question"]},
    )
    async def ask_user(args: dict) -> dict:
        d = await ctx.decisions.text(args["question"], title=args.get("title") or "Question")
        return _text({"answer": d.text})

    @tool(
        "ask_user_choice",
        "Offer the user options and wait for their pick. Each option has a label, a value and an optional description. "
        "Set multi to true to allow several.",
        {
            "type": "object",
            "properties": {
                "question": {"type": "string"},
                "options": {"type": "array", "items": {"type": "object", "properties": {"label": {"type": "string"}, "value": {"type": "string"}, "description": {"type": "string"}}, "required": ["label", "value"]}},
                "multi": {"type": "boolean"},
                "title": {"type": "string"},
            },
            "required": ["question", "options"],
        },
    )
    async def ask_user_choice(args: dict) -> dict:
        d = await ctx.decisions.choose(args["question"], args["options"], bool(args.get("multi")), title=args.get("title") or "Your call")
        if not d.approved and not d.selected and not d.text:
            return _text({"answered": False, "message": "The user did not choose. Ask differently or proceed with the safest option and say so."})
        return _text({"answered": True, "selected": d.selected or ([d.value] if d.value is not None else []), "note": d.text})

    @tool(
        "ask_user_for_data",
        "Ask the user for a dataset: a file path or pasted rows. Returns the path or text they provided.",
        {"type": "object", "properties": {"prompt": {"type": "string"}, "accept": {"type": "array", "items": {"type": "string"}}}, "required": ["prompt"]},
    )
    async def ask_user_for_data(args: dict) -> dict:
        d = await ctx.decisions.provide_data(args["prompt"], args.get("accept"))
        if not d.approved:
            return _text({"provided": False, "message": "The user did not provide data. Explain what you need and stop."})
        return _text({"provided": True, "value": d.value or d.text})

    @tool(
        "review_with_user",
        "Show an artifact to the user for review before you continue. The user can drop rows; "
        "the tool returns the ids they excluded and updates the artifact accordingly.",
        {"type": "object", "properties": {"artifact_id": {"type": "string"}, "message": {"type": "string"}}, "required": ["artifact_id"]},
    )
    async def review_with_user(args: dict) -> dict:
        try:
            payload = artifacts.load(ctx, args["artifact_id"])
        except FileNotFoundError as e:
            return _error(str(e))
        d = await ctx.decisions.review_artifact(
            payload["id"], payload["kind"], payload["title"], payload["columns"], payload["rows"], payload["row_count"],
            message=args.get("message") or "Review this list before I continue. Untick anything you want left out.",
        )
        excluded = []
        if isinstance(d.raw, dict):
            excluded = [int(x) for x in (d.raw.get("excluded_ids") or d.raw.get("excluded") or []) if str(x).isdigit()]
        if excluded:
            rows = [r for r in payload["rows"] if r.get("_id") not in set(excluded)]
            await artifacts.write(ctx, payload["kind"], payload["title"], rows, payload.get("columns"), payload.get("source", ""), artifact_id=payload["id"], meta=payload.get("meta"))
        return _text({"approved": d.approved, "excluded_ids": excluded, "remaining_rows": payload["row_count"] - len(excluded), "note": d.text})

    # ---- Gmail through Composio -------------------------------------------------
    async def _gmail_execute(slug: str, arguments: dict) -> dict:
        try:
            result = await gmail_call(ctx.user_id, slug, arguments)
        except RuntimeError as e:
            return _error(str(e))
        return _text(result if isinstance(result, dict | list | str) else str(result))

    async def _send(slug: str, arguments: dict, args: dict, status: str) -> dict:
        """Run a send or draft; with plan_id, log it to the campaign's send log as it happens."""
        try:
            result = await gmail_call(ctx.user_id, slug, arguments)
        except RuntimeError as e:
            return _error(str(e))
        if args.get("plan_id") and isinstance(result, dict) and result.get("successful"):
            from src.agent_runtime.tools.campaign import record

            data = result.get("data") or {}
            thread = (data.get("response_data") or data).get("threadId") or args.get("thread_id")
            await record(ctx, args["plan_id"], {"to": args["to"].lower(), "step": args.get("step"), "status": status, "thread_id": thread})
        return _text(result if isinstance(result, dict | list | str) else str(result))

    CAMPAIGN_FIELDS = {
        "plan_id": {"type": "string", "description": "From render_campaign; logs the send to the campaign's send log"},
        "step": {"type": "integer", "description": "From render_campaign"},
    }

    @tool(
        "gmail_send_email",
        "Send one email through the user's connected Gmail. Requires request_send_approval first. "
        "Pass thread_id (from render_campaign) to send a follow-up as a reply in the same thread.",
        {
            "type": "object",
            "properties": {
                "to": {"type": "string"}, "subject": {"type": "string"}, "body": {"type": "string"},
                "cc": {"type": "array", "items": {"type": "string"}}, "bcc": {"type": "array", "items": {"type": "string"}},
                "is_html": {"type": "boolean"},
                "thread_id": {"type": "string", "description": "Reply in this thread (follow-up steps)"},
                **CAMPAIGN_FIELDS,
            },
            "required": ["to", "subject", "body"],
        },
    )
    async def gmail_send_email(args: dict) -> dict:
        if args.get("thread_id"):
            return await _send("GMAIL_REPLY_TO_THREAD", {
                "thread_id": args["thread_id"], "recipient_email": args["to"], "message_body": args["body"],
                "user_id": "me", "is_html": bool(args.get("is_html")),
            }, args, "sent")
        arguments = {"recipient_email": args["to"], "subject": args["subject"], "body": args["body"], "user_id": "me",
                     "is_html": bool(args.get("is_html"))}
        if args.get("cc"):
            arguments["cc"] = args["cc"]
        if args.get("bcc"):
            arguments["bcc"] = args["bcc"]
        return await _send("GMAIL_SEND_EMAIL", arguments, args, "sent")

    @tool(
        "gmail_create_draft",
        "Create a Gmail draft (not sent) in the user's connected Gmail. Requires request_send_approval with draft_only.",
        {"type": "object", "properties": {"to": {"type": "string"}, "subject": {"type": "string"}, "body": {"type": "string"}, "is_html": {"type": "boolean"}, **CAMPAIGN_FIELDS}, "required": ["to", "subject", "body"]},
    )
    async def gmail_create_draft(args: dict) -> dict:
        return await _send("GMAIL_CREATE_EMAIL_DRAFT", {"recipient_email": args["to"], "subject": args["subject"], "body": args["body"], "user_id": "me", "is_html": bool(args.get("is_html"))}, args, "drafted")

    @tool(
        "gmail_search_emails",
        "Search the user's Gmail (e.g. 'from:someone@x.com newer_than:30d') to check prior contact.",
        {"type": "object", "properties": {"query": {"type": "string"}, "max_results": {"type": "integer", "minimum": 1, "maximum": 50}}, "required": ["query"]},
    )
    async def gmail_search_emails(args: dict) -> dict:
        return await _gmail_execute("GMAIL_FETCH_EMAILS", {"query": args["query"], "max_results": int(args.get("max_results") or 10), "user_id": "me"})

    return [
        sic_lookup, request_spend_approval, request_send_approval, ask_user, ask_user_choice,
        ask_user_for_data, review_with_user, gmail_send_email, gmail_create_draft, gmail_search_emails,
    ]
