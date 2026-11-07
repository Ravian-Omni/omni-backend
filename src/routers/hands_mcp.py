"""DAXAGENT's MCP server for outside agents and apps (Brain_Hands first), mounted at /hands/mcp (bearer
DAXAGENT_HANDS_TOKEN). It acts in chat_bridge.USER_ID's workspace: the hosted app's owner.

A run is driven the way the Slack and Teams bots drive one, through chat_bridge.Thread, except that the
events go to a queue the caller drains with next_event and answers with answer. Every question a run asks
(the clarifier's form, plan approval, an agent's choice, a credit spend or a send to approve) comes as one
input_request with a typed `question` saying how to answer it. task_status reads any task's state from its
history (services/task_status.py). Replies, sweeps and handoff sends reuse the functions the web app calls.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations

from src.agent_runtime.tools.artifacts import load_record, save_payload
from src.database import get_chat_repository, list_conversations, list_handoffs, save_pref
from src.database import list_artifacts as db_list_artifacts
from src.dependencies import get_websocket_manager
from src.services import chat_bridge, task_status as status
from src.services.chat_bridge import USER_ID, Thread
from src.services.chat_service import ChatService

INSTRUCTIONS = (
    "DAXAGENT runs multi-step tasks for the user with a team of agents: find leads and buyers, enrich contacts, research "
    "the market, build a campaign, write and send outreach as the user, answer replies, or anything a connected app can do. "
    "chat_id is the conversation: start_run returns it, every question and next_event carries it, and next_event, answer "
    "and task_status take it. Start one with start_run(task, files), then call next_event(chat_id) in a loop; to continue "
    "the same conversation (its agents see what was done there before) pass its chat_id to start_run instead of starting "
    "a new one. Events: plan (the agents lined up, "
    "each step's status), agent (an agent started or finished), saved (a list or document it saved), input_request, "
    "summary, completion, error. Every input_request carries a `question` with its kind and `answer_with`: clarify (a "
    "few details before planning), plan_approval, choose, credit_request (credits to spend: approve or decline), "
    "send_approval, review, provide_data, text. Reply with answer(key, response) exactly as answer_with says; the run "
    "waits until you do. task_status(key or chat_id) tells where any task is (also ones started in the web app): stage, "
    "each plan step's status, percent finished, the agents at work and their current step, the open question, credits "
    "approved, saved work and the final summary; list_tasks lists recent tasks. list_artifacts(chat_id) lists the files a task saved (lead lists, buyer maps, enriched contacts, campaign plans) with their ids, and read_artifact(chat_id, id, offset, limit) reads one's rows a page at a time. A campaign plan's steps are drafts until approved: approve_plan_steps(chat_id, plan_id) approves them, as the user does on the campaign page, so Outreach can draft or send them; call it only when you are allowed to approve the copy for the user. A run's completion event and task_status carry campaigns: per campaign plan, newest first, the email steps approved, drafted, sent, replied and bounced, and `next`, what it waits on: approve_steps, create_drafts, send (the drafts are in Gmail) or watch_replies; next.start_run is the task to pass to start_run with the same chat_id, as the campaign page's buttons do. Sending still asks send_approval first. answer also takes a chat_id, to answer a "
    "web-app task's open question. handoffs lists replies that need a person, with Jev's reading and a drafted answer; "
    "send_handoff sends that answer in the contact's thread; sweep checks Gmail for new replies now."
)

mcp = FastMCP("daxagent", instructions=INSTRUCTIONS, streamable_http_path="/mcp",
              host="0.0.0.0")  # no localhost-only Host check: it is mounted behind the bearer gate and may be reached by domain
_threads: dict[str, "HandsThread"] = {}
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False)
READ = ToolAnnotations(readOnlyHint=True)


def simplify(event: dict[str, Any], context: str = "", plan: list[dict] | None = None) -> dict[str, Any] | None:
    """One WebSocket event as the caller needs it, or None for the stream of partial messages.
    context: Omni's last verification text, the question its plain user_input prompt asks; plan: the latest plan's steps."""
    kind, data = event.get("type"), event.get("data") or {}
    if kind == "input_request":
        card, asked_by = status.card_of(event)
        return {"type": "input_request", "question": status.question_of(card, asked_by, context, plan), "card": card,
                "input_type": event.get("input_type")}
    if kind == "completion":
        return {"type": "completion", "status": event.get("status")}
    if kind == "error":
        return {"type": "error", "message": str(event.get("message") or event.get("error") or "unknown error")}
    if kind == "message" and data.get("source") == "OMNI" and isinstance(data.get("content"), dict):
        name, text = data["content"].get("name"), data["content"].get("content") or ""
        if name in ("process_completion_agent", "conversation_agent"):  # either one ends a run with the answer
            return {"type": "summary", "text": text}
        if name == "planner_agent":
            plan = status.loads(text)
            steps = [status.plan_step(i, s) for i, s in enumerate(plan.get("breakdown") or [], 1)] if isinstance(plan, dict) else []
            return {"type": "plan", "steps": steps, "text": text[:4000]}
        return None
    inner = data.get("content", {}).get("content") if kind == "message" and isinstance(data.get("content"), dict) else None
    if isinstance(inner, dict) and inner.get("type") == "agent_status":
        return {"type": "agent", "agent": inner.get("persona"), "agent_name": inner.get("display_name"), "status": inner.get("status"),
                **({"task": inner["task"]} if inner.get("task") else {}),
                **({"seconds": round(inner["duration_ms"] / 1000)} if inner.get("duration_ms") else {})}
    if isinstance(inner, dict) and inner.get("type") == "artifact" and isinstance(inner.get("artifact"), dict):
        a = inner["artifact"]
        return {"type": "saved", "agent": data.get("source"), "id": a.get("id"), "title": a.get("title"), "kind": a.get("kind"), "rows": a.get("row_count")}
    return None


class HandsThread(Thread):
    """A Thread whose events go to a queue instead of to a chat app."""

    def __init__(self, key: str, chat_id: str) -> None:
        self.queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.ask_text = ""  # Omni's last verification text, or the message a stopped plan waits on
        self.plan: list[dict[str, Any]] = []  # the latest plan's steps

        async def say(_: str) -> None:
            pass

        super().__init__("hands", key, chat_id, say)

    async def send_json(self, event: dict[str, Any]) -> None:
        await super().send_json(event)  # keeps the ready and pending flags
        content = (event.get("data") or {}).get("content")
        if isinstance(content, dict) and content.get("name") in ("clarifier", "manual_verification", "conversation_agent"):
            form = status.loads(content.get("content"))
            self.ask_text = str(form.get("intro") or "") if isinstance(form, dict) else str(form or "")
        if simple := simplify(event, self.ask_text, self.plan):
            if simple["type"] == "plan":
                self.plan = simple["steps"]
            if simple["type"] == "input_request":
                simple["chat_id"] = self.chat_id  # the conversation to answer in, and to continue later
            self.queue.put_nowait(simple)


def _find(key: str) -> HandsThread | None:
    """The run started here with this key, or the latest one on this chat_id."""
    return _threads.get(key) or next((t for t in reversed(_threads.values()) if t.chat_id == key), None)


def _thread(key: str) -> HandsThread:
    t = _find(key)
    if not t:
        raise ValueError(f"no run with key {key}")
    return t


@mcp.tool(annotations=WRITE)
async def start_run(task: str, ctx: Context, key: str = "", files: list[str] | None = None, chat_id: str = "") -> dict[str, Any]:
    """Start a task run (a lead search, a campaign, outreach, a reply) and return its chat_id; drive it with next_event and answer.
    chat_id: the conversation to continue, so its agents see what was done there before; empty starts a new one.
    key: optionally your own id for the run (defaults to the chat_id). files: paths on this machine to attach (a deck, a list)."""
    if key and (t := _threads.get(key)) and not t.task.done():
        raise ValueError(f"run {key} is still going")
    if chat_id and not await (await get_chat_repository()).get_chat(USER_ID, chat_id, "omni"):
        raise ValueError(f"no task {chat_id}")
    if chat_id and (await get_websocket_manager()).is_running(chat_id):
        raise ValueError(f"task {chat_id} is still running")
    chat_id = chat_id or (await ChatService.create_omni_chat(USER_ID))["chat_id"]
    key = key or chat_id
    info = ctx.session.client_params.clientInfo if ctx.session.client_params else None
    # the web app marks the task as run by this AI; "mcp" is the Python SDK's default name, which says nothing
    await save_pref(USER_ID, f"run_by:{chat_id}", info.name if info and info.name not in ("", "mcp") else "AI agent")
    # a chat whose thread is still open takes the next task on it; a closed one reopens from its history
    t = next((o for o in _threads.values() if o.chat_id == chat_id and not o.task.done()), None) or HandsThread(key, chat_id)
    while not t.queue.empty():
        t.queue.get_nowait()  # the last run's leftovers are not this run's events
    t.ask_text, t.plan = "", []
    _threads[key] = t
    t.inbox.put_nowait(json.dumps({"type": "start", "task": task, "files": files or []}))
    return {"key": key, "chat_id": chat_id}


@mcp.tool(annotations=READ)
async def next_event(key: str, timeout: int = 25) -> dict[str, Any]:
    """The run's events since the last call: input_request (answer it with answer), plan, summary, completion (with
    campaigns: each campaign plan's counts and next step), error. key: the run's chat_id (or your key). Waits up to timeout seconds (at most 60) for the first one. closed is true when
    the run is over and drained."""
    t = _thread(key)
    events: list[dict[str, Any]] = []
    try:
        events.append(await asyncio.wait_for(t.queue.get(), min(max(timeout, 1), 60)))
    except asyncio.TimeoutError:
        pass
    while not t.queue.empty():
        events.append(t.queue.get_nowait())
    if done := next((e for e in events if e["type"] == "completion"), None):
        done["campaigns"] = await status.campaigns(t.chat_id)  # what each campaign plan waits on now, e.g. drafts ready to send
    pending = bool((await get_websocket_manager()).pending_request(t.chat_id))
    return {"chat_id": t.chat_id, "events": events, "closed": t.task.done() and t.queue.empty(), "pending": pending}


@mcp.tool(annotations=WRITE)
async def answer(key: str, response: str) -> dict[str, Any]:
    """Answer the open question of a task (its chat_id, or the key of a run started here), as the
    question's answer_with says: 'yes', 'no', free text, or a JSON object such as {"values": {...}} for a clarify
    form, {"action": "choose", "selected": [...]}, {"action": "revise", "text": "..."} or {"action": "skip"}."""
    reply: Any = response.strip()
    if reply.startswith("{"):
        try:
            reply = json.loads(reply)  # the form and card answers are objects
        except ValueError:
            pass
    manager = await get_websocket_manager()
    t = _find(key)
    if t:
        if t.task.done():
            raise ValueError(f"run {key} is over")
        if not manager.pending_request(t.chat_id):  # the live question, not t.pending: the web app may have answered it
            return {"ok": False, "note": "nothing is waiting for an answer (it may have been answered in the web app)"}
        t.pending = False
        t.inbox.put_nowait(json.dumps({"type": "input_response", "response": reply}))
        return {"ok": True, "chat_id": t.chat_id}
    if not await (await get_chat_repository()).get_chat(USER_ID, key, "omni"):
        raise ValueError(f"no run or task {key}")
    if not manager.pending_request(key):
        return {"ok": False, "note": "nothing is waiting for an answer"}
    await manager.handle_input_response(key, reply)
    return {"ok": True, "chat_id": key}


@mcp.tool(annotations=READ)
async def task_status(key: str = "", chat_id: str = "") -> dict[str, Any]:
    """Where a task is: stage (understanding, waiting_for_answer, awaiting_plan_approval, running, wrapping_up, done,
    stopped), a note, each plan step's agent, task, status and result, progress (percent of steps finished), the agents
    at work with their current step, the open question with how to answer it, credits approved and declined, saved
    work, the final summary, timings and campaigns (each campaign plan's steps approved, drafted, sent, replied and its
    next step). Give the key of a run started here or the chat_id of any task."""
    if key and (t := _find(key)):
        chat_id = t.chat_id
    chat_id = chat_id or key
    if not chat_id:
        raise ValueError("give the key of a run started here or a task's chat_id")
    return await status.task_status(USER_ID, chat_id)


@mcp.tool(annotations=READ)
async def list_tasks(limit: int = 10) -> dict[str, Any]:
    """The most recent tasks, newest first, with their chat_id, folder name, request, stage and percent finished."""
    keys = {t.chat_id: k for k, t in _threads.items()}
    tasks = []
    for c in [c for c in await list_conversations(USER_ID) if c["collection"] == "omni"][: min(max(limit, 1), 50)]:
        s = await status.task_status(USER_ID, c["chat_id"])
        tasks.append({"chat_id": c["chat_id"], "key": keys.get(c["chat_id"]), "name": os.path.basename(str(c["chat_dir"] or "").rstrip("/")),
                      "request": s["request"][:300], "stage": s["stage"], "percent": s["progress"]["percent"], "updated_at": s["updated_at"]})
    return {"tasks": tasks}


@mcp.tool(annotations=READ)
async def list_artifacts(chat_id: str) -> dict[str, Any]:
    """The files a task saved (lead lists, buyer maps, enriched contacts, campaign plans, …), newest first: id, kind,
    title, rows and the agent that saved it. Read one with read_artifact."""
    if not await (await get_chat_repository()).get_chat(USER_ID, chat_id, "omni"):
        raise ValueError(f"no task {chat_id}")
    return {"chat_id": chat_id, "artifacts": [
        {"id": a["id"], "kind": a["kind"], "title": a["title"], "rows": a["row_count"], "agent": a["persona"], "created_at": a["created_at"]}
        for a in await db_list_artifacts(chat_id)]}


@mcp.tool(annotations=READ)
async def read_artifact(chat_id: str, artifact_id: str, offset: int = 0, limit: int = 100) -> dict[str, Any]:
    """A saved file's rows, a page at a time (limit at most 500), with its columns, row_count and meta. Page on with
    offset until offset + len(rows) reaches row_count."""
    if not await (await get_chat_repository()).get_chat(USER_ID, chat_id, "omni"):
        raise ValueError(f"no task {chat_id}")
    try:
        record, payload = await load_record(chat_id, artifact_id)  # checks the file belongs to this chat
    except FileNotFoundError as e:
        raise ValueError(str(e)) from e
    rows, offset, limit = payload.get("rows", []), max(offset, 0), min(max(limit, 1), 500)
    return {"chat_id": chat_id, "id": artifact_id, "kind": record["kind"], "title": record["title"],
            "columns": payload.get("columns", []), "row_count": len(rows), "offset": offset,
            "rows": rows[offset : offset + limit], "meta": payload.get("meta", {})}


@mcp.tool(annotations=WRITE)
async def approve_plan_steps(chat_id: str, plan_id: str, steps: list[int] | None = None) -> dict[str, Any]:
    """Approve a campaign plan's steps, as the user does on its campaign page: Outreach drafts or sends only approved
    steps, and each batch still asks send_approval. steps: the step numbers to approve; empty approves them all.
    Call it only when you are allowed to approve the copy for the user."""
    if not await (await get_chat_repository()).get_chat(USER_ID, chat_id, "omni"):
        raise ValueError(f"no task {chat_id}")
    try:
        record, payload = await load_record(chat_id, plan_id)
    except FileNotFoundError as e:
        raise ValueError(str(e)) from e
    if record["kind"] != "campaign_plan":
        raise ValueError(f"{plan_id} is a {record['kind']}, not a campaign plan")
    rows = payload.get("rows", [])
    newly = [r for r in rows if r.get("status") != "approved" and (not steps or int(r.get("step") or 1) in steps)]
    for r in newly:
        r["status"] = "approved"
    if newly:
        meta = payload.setdefault("meta", {})
        meta["rev"] = int(meta.get("rev") or 0) + 1  # the page and agents holding the old rev reload before they edit
        await save_payload(record, payload)
    return {"chat_id": chat_id, "plan_id": plan_id, "approved_now": len(newly),
            "approved_steps": sum(1 for r in rows if r.get("status") == "approved"), "steps": len(rows)}


@mcp.tool(annotations=READ)
async def handoffs(status: str = "", chat_id: str | None = None, since: str | None = None) -> dict[str, Any]:
    """Replies from contacts that the Inbox Agent handed to a person: contact, route (handoff, propose_meeting, answer,
    suppress, snooze, auto_reply, or bounce: a delivery failure, contact the mailer-daemon, read.address the dead address), read (Jev's intent), the reply text, a drafted answer, status.
    status: '' all, 'active' open or claimed, or one of open, claimed, sent, done. since: ISO time, newer only."""
    rows = await list_handoffs(USER_ID, status or None, chat_id)
    if since:
        rows = [h for h in rows if h["created_at"] > since]
    return {"handoffs": rows}


@mcp.tool(annotations=WRITE)
async def sweep() -> dict[str, Any]:
    """Check every sent campaign thread in Gmail now and open handoffs for new replies (the reply watcher's sweep)."""
    from src.agent_runtime import watcher

    return await watcher.sweep(USER_ID)


@mcp.tool(annotations=WRITE)
async def send_handoff(handoff_id: str, body: str) -> dict[str, Any]:
    """Send body as the answer to a handoff, as a reply in the contact's Gmail thread, exactly as the app's Send does."""
    from src.routers.handoffs import HandoffSend
    from src.routers.handoffs import send_handoff as send

    return await send(handoff_id, HandoffSend(body=body))


_inner: Any = None  # the MCP ASGI app of the current app start


@asynccontextmanager
async def running() -> AsyncIterator[None]:
    """Serve the MCP for one app start. A session manager runs only once, so each start builds its own (tests start the app many times)."""
    global _inner
    mcp._session_manager = None
    inner = mcp.streamable_http_app()
    async with mcp.session_manager.run():
        _inner = inner
        try:
            yield
        finally:
            _inner = None


def app() -> Any:
    """The MCP ASGI app behind a bearer check. No token configured means no access."""

    async def gate(scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] == "http":
            headers = {k.decode().lower(): v.decode() for k, v in scope["headers"]}
            token = os.environ.get("DAXAGENT_HANDS_TOKEN", "")
            if not token or headers.get("authorization") != f"Bearer {token}":
                await send({"type": "http.response.start", "status": 401, "headers": [(b"content-type", b"text/plain")]})
                await send({"type": "http.response.body", "body": b"Brain_Hands token missing or wrong"})
                return
        if _inner is None:  # outside the app's lifespan
            await send({"type": "http.response.start", "status": 503, "headers": [(b"content-type", b"text/plain")]})
            await send({"type": "http.response.body", "body": b"DAXAGENT is not running"})
            return
        await _inner(scope, receive, send)

    return gate
