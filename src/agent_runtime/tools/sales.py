"""Tools for the sales personas: SIC lookup, the approval gates, questions to
the user, and Gmail through Composio."""

import json
import re
import uuid
from typing import Any

from loguru import logger

from src.agent_runtime import clicks, crm, leads, prefs, sender, sic
from src.agent_runtime.tools import artifacts
from src.agent_runtime.tools.context import ToolContext
from src.agent_runtime.tools.context import server_of as _server_of
from src.database import list_suppressed


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
    return await composio_call(user_id, "gmail", slug, arguments, "Gmail")


async def composio_upload(path: str, slug: str, toolkit: str) -> dict:
    """Stage a local file for a Composio action's file field (e.g. a Gmail attachment): {name, mimetype, s3key}."""
    import asyncio

    from composio import Composio
    from composio.core.models._files import FileUploadable

    from src.configs.llm_configs_manager import LLMConfigManager

    key = LLMConfigManager.get_config("composio_api_key").get("config_list", [{}])[0].get("api_key")
    if not key:
        raise RuntimeError("Composio API key not set. Add it in Settings.")
    client = Composio(api_key=key)
    staged = await asyncio.to_thread(FileUploadable.from_path, client._client, path, slug, toolkit, file_upload_allowlist=None)
    return staged.model_dump()


async def composio_call(user_id: str, toolkit: str, slug: str, arguments: dict, label: str = "") -> Any:
    """Run one Composio action of a connected app (gmail, slack, googlecalendar) for the user."""
    import asyncio

    from composio import Composio

    from src.configs.llm_configs_manager import LLMConfigManager

    key = LLMConfigManager.get_config("composio_api_key").get("config_list", [{}])[0].get("api_key")
    if not key:
        raise RuntimeError("Composio API key not set. Add it in Settings.")
    client = Composio(api_key=key)
    connections = await asyncio.to_thread(client.connected_accounts.list, user_ids=[user_id])
    if not any(c.toolkit and c.toolkit.slug.lower() == toolkit and c.status == "ACTIVE" for c in connections.items):
        label = label or toolkit.title()
        raise RuntimeError(f"{label} is not connected. Ask the user to connect {label} in Settings, then try again.")
    return await asyncio.to_thread(
        client.tools.execute, slug=slug, user_id=user_id, arguments=arguments, dangerously_skip_version_check=True
    )




def build(ctx: ToolContext):
    from claude_agent_sdk import tool

    @tool(
        "sic_lookup",
        "Find SIC industry codes for an industry described in words (e.g. 'dental offices', 'SaaS companies'). "
        "Returns the best matching 4-digit codes with descriptions; pass the codes to Data Axle as primary_sic_code (comma joined).",
        {"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 20}}, "required": ["query"]},
    )
    async def sic_lookup(args: dict) -> dict:
        return _text(sic.lookup(args["query"], int(args.get("limit") or 8)))

    @tool(
        "request_spend_approval",
        "Ask the user to approve spending credits BEFORE calling a tool that costs credits (e.g. salesgenie_business_enrichment). "
        "Shows the count, the credit cost and the balance. If approved, that many calls of the tool are allowed; "
        "declined means do not call it.",
        {
            "type": "object",
            "properties": {
                "tool": {"type": "string", "description": "The credit-consuming tool, e.g. salesgenie_business_enrichment"},
                "count": {"type": "integer", "minimum": 1, "description": "How many records you will enrich"},
                "reason": {"type": "string", "description": "One line on why, e.g. 'resolve the 40 buyer contacts in buyer_map-1a2b'"},
                "credits_per_call": {"type": "integer", "minimum": 1, "description": "Credits per record. Default 2 (a Data Axle enrichment with an email)"},
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
        per_call = int(args.get("credits_per_call") or 2)
        balance = await _credit_balance(server)
        decision = await ctx.decisions.confirm_spend(
            tool=full.split("__")[-1], server=server, count=count, credits=count * per_call,
            balance_before=balance, detail=args.get("reason", ""),
        )
        if decision.approved:
            ctx.spend_allowance[full] = ctx.spend_allowance.get(full, 0) + count  # approvals add up
            return _text({"approved": True, "tool": full.split("__")[-1], "calls_allowed": count, "balance_before": balance})
        if decision.suggestion:
            return _text({"approved": False, "user_said": decision.suggestion, "message": "The user answered with their own instruction instead of approving. Follow it (for example a smaller batch) and ask again; spend nothing yet."})
        return _text({"approved": False, "message": "The user declined the credit spend. Do not call the tool; report and offer a smaller batch."})

    @tool(
        "request_send_approval",
        "Ask the user to approve sending a batch of messages BEFORE sending. Shows the recipients, subject and body. "
        "If approved, that many sends are allowed; declined means send nothing. For a campaign batch pass plan_id and "
        "step (from render_campaign) and list the recipients in render order: the card shows the first one's exact email.",
        {
            "type": "object",
            "properties": {
                "channel": {"type": "string", "description": "email"},
                "recipients": {"type": "array", "items": {"type": "string"}, "description": "Email addresses"},
                "subject": {"type": "string"},
                "body_preview": {"type": "string", "description": "The exact body for the first recipient"},
                "reason": {"type": "string", "description": "Which campaign step and segment this is"},
                "draft_only": {"type": "boolean", "description": "True when creating drafts instead of sending"},
                "plan_id": {"type": "string", "description": "For a campaign batch: the card then shows the first recipient's exact rendered email"},
                "step": {"type": "integer", "description": "For a campaign batch: the step being sent"},
            },
            "required": ["channel", "recipients", "subject", "body_preview"],
        },
    )
    async def request_send_approval(args: dict) -> dict:
        recipients = [r for r in (args.get("recipients") or []) if isinstance(r, str) and r.strip()]
        if not recipients:
            return _error("No recipients given")
        recips = frozenset(r.strip().lower() for r in recipients)
        copy: Any = (args.get("subject", ""), args.get("body_preview", ""))
        if args.get("plan_id"):
            # The approver checks the card as the email itself: show the rendered one, not the agent's words about it
            from src.agent_runtime.tools.campaign import render_plan

            try:
                ready = (await render_plan(ctx, args["plan_id"], args.get("step")))["ready"]
            except FileNotFoundError:
                ready = []
            first = next((m for m in ready if m["to"].lower() == recipients[0].strip().lower()), None)
            if first:
                args = {**args, "subject": first["subject"], "body_preview": first["body"]}
            copy = frozenset((m["to"].lower(), m["subject"], m["body"]) for m in ready if m["to"].lower() in recips) or copy
        tool_name = "gmail_create_draft" if args.get("draft_only") else "gmail_send_email"
        batch = (tool_name, recips, copy)
        warnings = await sender.warnings(ctx.user_id)
        if batch in ctx.send_approved:
            # Asked again for the same batch (Outreach re-checked replies first): one card, and the approved count stays
            return _text({"approved": True, "already_approved": True, "sends_left": ctx.send_allowance.get("*", 0), "tool": tool_name})
        decision = await ctx.decisions.confirm_send(
            tool=tool_name, server="composio", channel=args.get("channel", "email"), recipients=recipients,
            subject=args.get("subject", ""), body_preview=args.get("body_preview", ""), detail=args.get("reason", ""),
            plan_id=args.get("plan_id", ""), step=args.get("step"), warnings=warnings,
        )
        if decision.approved:
            # Any send tool may deliver the approved batch (Outreach's Gmail tool or Gmail's own).
            ctx.send_allowance["*"] = ctx.send_allowance.get("*", 0) + len(recipients)
            ctx.send_approved.add(batch)
            return _text({"approved": True, "sends_allowed": len(recipients), "tool": tool_name, **({"warnings": warnings} if warnings else {})})
        if decision.suggestion:
            return _text({"approved": False, "user_said": decision.suggestion, "message": "The user answered with their own instruction instead of approving. Apply it and ask again; send nothing yet."})
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
                "why": {"type": "string", "description": "One line the user sees: what depends on this answer and what you do if they skip"},
            },
            "required": ["question", "options"],
        },
    )
    async def ask_user_choice(args: dict) -> dict:
        d = await ctx.decisions.choose(args["question"], args["options"], bool(args.get("multi")), title=args.get("title") or "Your call", why=args.get("why") or "")
        if d.skipped:
            return _text({"answered": False, "skipped": True, "message": "The user left this to you: go with your recommended option and say which one you used."})
        if not d.approved and not d.selected and not d.text:
            return _text({"answered": False, "message": "The user did not choose. Ask differently or proceed with the safest option and say so."})
        return _text({"answered": True, "selected": d.selected or ([d.value] if d.value is not None else []), "note": d.text})

    @tool(
        "ask_user_for_data",
        "Ask the user for a dataset: a file path or pasted rows. Returns the path or text they provided.",
        {"type": "object", "properties": {"prompt": {"type": "string"}, "accept": {"type": "array", "items": {"type": "string"}}, "why": {"type": "string", "description": "One line the user sees: what depends on this answer and what you do if they skip"}}, "required": ["prompt"]},
    )
    async def ask_user_for_data(args: dict) -> dict:
        d = await ctx.decisions.provide_data(args["prompt"], args.get("accept"), why=args.get("why") or "")
        if not d.approved:
            return _text({"provided": False, "message": "The user did not provide data. Explain what you need and stop."})
        return _text({"provided": True, "value": d.value or d.text})

    @tool(
        "suggest_task",
        "Offer to move this request to Task mode when it needs several steps or specialist agents (a full analysis "
        "of a file; a lead list with buyers, enrichment and a campaign). The user gets Create Task and Skip buttons; "
        "Create Task opens a new task with your title, request and files filled in, ready to send. Put what the "
        "task would do in outline (the user reads it on the card) and do not write it again; call it once.",
        {"type": "object", "properties": {
            "title": {"type": "string", "description": "Task name, 2-5 words"},
            "outline": {"type": "string", "description": "What the task would do, as a short markdown numbered list (one line each); shown above the buttons"},
            "request": {"type": "string", "description": "The task's first message, in the user's voice: the goal, the scope and every detail they gave"},
            "files": {"type": "array", "items": {"type": "string"}, "description": "Paths of the attached files the task needs"},
        }, "required": ["title", "request"]},
    )
    async def suggest_task(args: dict) -> dict:
        suggestion = {"id": uuid.uuid4().hex[:12], "title": str(args["title"])[:80], "request": str(args["request"]), "outline": str(args.get("outline") or ""),
                      "files": [str(f) for f in args.get("files") or []]}
        await ctx.emit({"type": "task_suggestion", "suggestion": suggestion})
        return _text({"shown": True, "message": "The user sees your outline with Create Task and Skip. End here: write nothing more."})

    @tool(
        "review_with_user",
        "Show an artifact to the user for review before you continue. The user can drop rows; "
        "the tool returns the ids they excluded and updates the artifact accordingly.",
        {"type": "object", "properties": {"artifact_id": {"type": "string"}, "message": {"type": "string"}, "why": {"type": "string", "description": "One line the user sees: what depends on this answer and what you do if they skip"}}, "required": ["artifact_id"]},
    )
    async def review_with_user(args: dict) -> dict:
        try:
            payload, origin = await artifacts.find(ctx, args["artifact_id"])
        except FileNotFoundError as e:
            return _error(str(e))
        d = await ctx.decisions.review_artifact(
            payload["id"], payload["kind"], payload["title"], payload["columns"], payload["rows"], payload["row_count"],
            message=args.get("message") or "Review this list before I continue. Untick anything you want left out.",
            why=args.get("why") or "",
        )
        if d.suggestion:
            return _text({"approved": False, "changes_requested": d.suggestion, "message": "The user asked for changes instead of approving. Apply them, update the artifact, and review again."})
        excluded = []
        if isinstance(d.raw, dict):
            excluded = [int(x) for x in (d.raw.get("excluded_ids") or d.raw.get("excluded") or []) if str(x).isdigit()]
        saved = {}
        if excluded:
            rows = [r for r in payload["rows"] if r.get("_id") not in set(excluded)]
            record = await artifacts.rewrite(ctx, payload, origin, rows)
            if origin:
                saved = {"saved_as": record["id"], "message": f"`{payload['id']}` is from {origin} and stays as it was. The reviewed list is `{record['id']}`, a copy in this chat: use it from now on."}
        return _text({"approved": d.approved, "excluded_ids": excluded, "remaining_rows": payload["row_count"] - len(excluded), "note": d.text, **saved})

    # ---- Gmail through Composio -------------------------------------------------
    async def _gmail_execute(slug: str, arguments: dict) -> dict:
        try:
            result = await gmail_call(ctx.user_id, slug, arguments)
        except RuntimeError as e:
            return _error(str(e))
        return _text(result if isinstance(result, dict | list | str) else str(result))

    async def _send(slug: str, arguments: dict, args: dict, status: str) -> dict:
        """Run a send or draft; with plan_id, log it to the campaign's send log as it happens."""
        if args.get("plan_id"):
            from src.agent_runtime.tools.campaign import own_plan

            try:
                await own_plan(ctx, args["plan_id"])  # before anything goes out: the send log lives with the plan
            except FileNotFoundError as e:
                return _error(str(e))
        problems = []
        if status == "sent":  # the email as written, before clicks.rewrite puts our redirect on its links
            text = f"{args.get('subject', '')}\n{args['body']}"
            own = await sender.own_domains(ctx.user_id) if leads.LINK.search(text) or leads.EMAIL.search(text) else None  # no link: nothing to look up
            to_all = [args["to"], *(args.get("cc") or []), *(args.get("bcc") or [])]
            # a shared inbox goes only where the lead gate passed it in this chat; the lookup is skipped when none is written to
            resort = await leads.passed_shared(ctx.chat_id) if any(leads.is_shared(t.strip().lower()) for t in to_all) else frozenset()
            problems = leads.send_problems(to_all, args.get("subject", ""), args["body"], await list_suppressed(ctx.user_id), own, resort)
            if not args.get("thread_id") and (args.get("step") or 1) <= 1 and (stop := await leads.bounce_stop(ctx.user_id)):
                problems.append(stop)  # first emails only: follow-ups and replies to people who wrote still go
        if problems:
            reason = "; ".join(problems)
            if args.get("plan_id"):
                from src.agent_runtime.tools.campaign import record

                await record(ctx, args["plan_id"], {"to": args["to"].lower(), "step": args.get("step"), "status": "blocked", "reason": reason})
            return _error(f"Not sent: {reason}. No approval overrides this: fix the plan or leave the recipient out.")
        if status == "sent" and (stop := await leads.daily_stop(ctx.user_id)):  # nothing wrong with the email: it waits
            return _error(f"Not sent: {stop}")
        if status == "sent":
            key = "message_body" if "message_body" in arguments else "body"
            arguments[key] = await clicks.rewrite(arguments[key], bool(arguments.get("is_html")), args["to"], args.get("plan_id", ""), args.get("step"), args.get("subject", ""))
        try:
            result = await gmail_call(ctx.user_id, slug, arguments)
        except RuntimeError as e:
            return _error(str(e))
        if args.get("plan_id") and isinstance(result, dict) and result.get("successful"):
            from src.agent_runtime.tools.campaign import record

            data = result.get("data") or {}
            thread = (data.get("response_data") or data).get("threadId") or args.get("thread_id")
            await record(ctx, args["plan_id"], {"to": args["to"].lower(), "step": args.get("step"), "status": status, "thread_id": thread})
            if status == "sent":  # the CRM's record of it, keyed on the Gmail message so a repeat adds nothing
                key = (data.get("response_data") or data).get("id") or f"{args['plan_id']}:{args.get('step')}:{args['to'].lower()}"
                crm.later(lambda: crm.activity(args["to"], "email_sent", f"{args.get('subject', '')}\n\n{arguments.get('body') or arguments.get('message_body') or ''}", str(key)))
        return _text(result if isinstance(result, dict | list | str) else str(result))

    CAMPAIGN_FIELDS = {
        "plan_id": {"type": "string", "description": "From render_campaign; logs the send to the campaign's send log"},
        "step": {"type": "integer", "description": "From render_campaign"},
        "attachments": {"type": "array", "items": {"type": "string"}, "description": "Creative ids from render_campaign, attached to the email"},
        "inline_image": {"type": "string", "description": "Creative id from render_campaign, shown inside the email"},
    }

    async def _with_creatives(args: dict, arguments: dict, slug: str, body_key: str) -> dict | str:
        """Attach the campaign's creatives and show its inline image; returns the arguments, or what is wrong."""
        import os

        from src.agent_runtime import assets
        from src.database import get_creative

        async def mine(creative_id: str) -> dict | None:
            c = await get_creative(creative_id)
            return c if c and c["chat_id"] == ctx.chat_id and os.path.exists(c["path"]) else None

        if args.get("inline_image"):
            c = await mine(args["inline_image"])
            problems = assets.lint({"inline_image": args["inline_image"]}, {c["id"]: c} if c else {})
            if problems:
                return problems[0]
            arguments[body_key] = assets.html_body(arguments[body_key], c["url"], c["name"])
            arguments["is_html"] = True
        files = []
        for creative_id in args.get("attachments") or []:
            c = await mine(creative_id)
            if not c:
                return f"missing attachment {creative_id}"
            files.append(await composio_upload(c["path"], slug, "gmail"))
        if files:
            arguments["attachment"] = files
        return arguments

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
            slug, body_key, arguments = "GMAIL_REPLY_TO_THREAD", "message_body", {
                "thread_id": args["thread_id"], "recipient_email": args["to"], "message_body": args["body"],
                "user_id": "me", "is_html": bool(args.get("is_html")),
            }
        else:
            slug, body_key, arguments = "GMAIL_SEND_EMAIL", "body", {
                "recipient_email": args["to"], "subject": args["subject"], "body": args["body"], "user_id": "me",
                "is_html": bool(args.get("is_html")),
            }
            if mailbox := (await prefs.get(ctx.user_id, "sending")).get("mailbox"):
                arguments["from_email"] = mailbox  # a send-as address on the user's own domain
            if args.get("cc"):
                arguments["cc"] = args["cc"]
            if args.get("bcc"):
                arguments["bcc"] = args["bcc"]
        arguments = await _with_creatives(args, arguments, slug, body_key)
        return _error(f"Not sent: {arguments}") if isinstance(arguments, str) else await _send(slug, arguments, args, "sent")

    @tool(
        "gmail_create_draft",
        "Create a Gmail draft (not sent) in the user's connected Gmail. Requires request_send_approval with draft_only.",
        {"type": "object", "properties": {"to": {"type": "string"}, "subject": {"type": "string"}, "body": {"type": "string"}, "is_html": {"type": "boolean"}, **CAMPAIGN_FIELDS}, "required": ["to", "subject", "body"]},
    )
    async def gmail_create_draft(args: dict) -> dict:
        arguments = {"recipient_email": args["to"], "subject": args["subject"], "body": args["body"], "user_id": "me", "is_html": bool(args.get("is_html"))}
        arguments = await _with_creatives(args, arguments, "GMAIL_CREATE_EMAIL_DRAFT", "body")
        return _error(f"Not drafted: {arguments}") if isinstance(arguments, str) else await _send("GMAIL_CREATE_EMAIL_DRAFT", arguments, args, "drafted")

    @tool(
        "gmail_search_emails",
        "Search the user's Gmail (e.g. 'from:someone@x.com newer_than:30d') to check prior contact.",
        {"type": "object", "properties": {"query": {"type": "string"}, "max_results": {"type": "integer", "minimum": 1, "maximum": 50}}, "required": ["query"]},
    )
    async def gmail_search_emails(args: dict) -> dict:
        return await _gmail_execute("GMAIL_FETCH_EMAILS", {"query": args["query"], "max_results": int(args.get("max_results") or 10), "user_id": "me"})

    return [
        sic_lookup, request_spend_approval, request_send_approval, ask_user, ask_user_choice,
        ask_user_for_data, suggest_task, review_with_user, gmail_send_email, gmail_create_draft, gmail_search_emails,
    ]
