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
import time
import uuid
from datetime import datetime, timezone
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from loguru import logger
from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations

from src.agent_runtime import leads, site
from src.agent_runtime.personas import persona_names
from src.configs.datetime_utils import dt
from src.agent_runtime.tools import campaign
from src.agent_runtime.tools.artifacts import load_owned, load_record, save_payload
from src.database import answer_decision, run_started
from src.database import (budget_left, chat_of_agenda, enqueue_run, find_artifacts, get_chat_repository, get_chat_title, list_conversations, list_handoffs,
                          count_resume, list_marked_runs, list_queued_runs, load_pref, pop_queued_run, queued_run, save_pref, set_budget,
                          unmark_run, find_task, list_task_rows, save_task)
from src.database import list_artifacts as db_list_artifacts
from src.dependencies import get_websocket_manager
from src.services import brain_hands, chat_bridge, needs, run_result, task_status as status
from src.services.chat_bridge import USER_ID, ChatThread, Thread
from src.services.chat_service import ChatService
from src.omni import signal_play
from src.utilities.async_errors import AsyncErrorCode

INSTRUCTIONS = (
    "DAXAGENT runs multi-step tasks for the user with a team of agents: find leads and buyers, enrich contacts, research "
    "the market, build a campaign, write and send outreach as the user, answer replies, or anything a connected app can do. "
    "Chat or task: use chat(message) for a quick job one assistant does in a turn and answers at once: check the inbox or "
    "the calendar, search the web, look up a company or person, read or sum up a saved list, a question about earlier work. "
    "Use start_run for work with several steps or agents, or that saves lists, spends credits or sends a campaign: lead "
    "lists, buyers, enrichment, campaigns, outreach, a goal's research. When unsure, chat first: it says when a task is "
    "needed. "
    "chat_id is the conversation: start_run returns it, every question and next_event carries it, and next_event, answer "
    "and task_status take it. Start one with start_run(task, files), then call next_event(chat_id) in a loop; to continue "
    "the same conversation (its agents see what was done there before) pass its chat_id to start_run instead of starting "
    "a new one. Events: plan (the agents lined up, "
    "each step's status), agent (an agent started or finished), saved (a list or document it saved), input_request, "
    "summary, completion, error. Every input_request carries a `question` with its kind and `answer_with`: clarify (a "
    "few details before planning), plan_approval, choose, credit_request (credits to spend: approve or decline), "
    "send_approval, review, provide_data, text. Reply with answer(key, response, request_id) exactly as answer_with says "
    "(request_id is in the input_request: a question already answered, in the web app or by you, is refused with reason not_open); the run "
    "waits until you do. task_status(key or chat_id) tells where any task is (also ones started in the web app): stage, "
    "each plan step's status, percent finished, the agents at work and their current step, the open question, credits "
    "approved, saved work and the final summary; list_tasks lists recent tasks. list_artifacts(chat_id) lists the files a task saved (lead lists, buyer maps, enriched contacts, campaign plans) with their ids; without chat_id it lists the files of every task (search and kind narrow it), so earlier work can be reused. read_artifact(artifact_id, offset, limit) reads one's rows a page at a time, whichever task saved it. A campaign plan's steps are drafts until approved: approve_plan_steps(chat_id, plan_id) approves them, as the user does on the campaign page, so Outreach can draft or send them; call it only when you are allowed to approve the copy for the user. A run's completion event and task_status carry campaigns: per campaign plan, newest first, the email steps approved, drafted, sent, replied and bounced, and `next`, what it waits on: approve_steps, create_drafts, send (the drafts are in Gmail) or watch_replies; next.start_run is the task to pass to start_run with the same chat_id, as the campaign page's buttons do. Sending still asks send_approval first. answer also takes a chat_id, to answer a "
    "web-app task's open question. handoffs lists replies that need a person, with Jev's reading and a drafted answer; "
    "send_handoff sends that answer in the contact's thread; sweep checks Gmail for new replies now."
)

mcp = FastMCP("daxagent", instructions=INSTRUCTIONS, streamable_http_path="/mcp",
              host="0.0.0.0")  # no localhost-only Host check: it is mounted behind the bearer gate and may be reached by domain
_threads: dict[str, "HandsThread"] = {}
_watching: set[asyncio.Task] = set()  # needs waiting to be pushed, queue dispatches
_tender: asyncio.Task | None = None  # the loop that expires unanswered questions and starts queued runs (recover starts it)
_active: set[str] = set()  # chats with a run begun here and not ended
_lock = asyncio.Lock()  # one decision at a time on who starts and who waits
FAILED_RUN = AsyncErrorCode.TASK_EXECUTION_FAILED.value  # the error that ends a run
RESULT_S = 20  # the most a run's result may take to build (task status, learnings); past it the result goes out without learnings
QUIET_S = 30  # a run that sent nothing for this long and that the manager no longer runs has ended
TEND_S = 30  # how often questions nobody answers are given up on and queued runs are started
QUESTION_WAIT_S = 60 * float(os.getenv("DAXAGENT_QUESTION_WAIT_MIN", "30"))  # an unanswered question of a run driven from here
MAX_PARALLEL = int(os.getenv("DAXAGENT_MAX_PARALLEL_RUNS", "3"))  # chats whose runs go at the same time
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

    task_id = ""  # its row in tasks (contract [26]), set when a run begins
    noted = 0.0  # when last_progress_at was last written

    def __init__(self, key: str, chat_id: str) -> None:
        self.queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.ask_text = ""  # Omni's last verification text, or the message a stopped plan waits on
        self.plan: list[dict[str, Any]] = []  # the latest plan's steps
        self.agenda_id = ""  # Brain_Hands' agenda this run serves, echoed in every event
        self.started_at = dt.now_iso()  # when the run began: its credits are the ones approved since
        self.lead_target, self.rounds, self.seen = 0, 0, 0  # leads wanted, sourcing rounds since the first, contacts seen when the round began
        self.request = ""  # what start_run asked, for the result's `task` and `about`
        self.last_event = time.monotonic()  # when the run last showed it is alive: a run quiet past QUIET_S may have ended
        self.asked_at: float | None = None  # when the open question was asked, for QUESTION_WAIT_S
        self.stop_reason = ""  # why this side stopped the run, when it did
        self.polling = 0  # next_event calls waiting right now
        self.last_poll = time.monotonic()  # when the last one ended

        async def say(_: str) -> None:
            pass

        super().__init__("hands", key, chat_id, say)

    async def send_json(self, event: dict[str, Any]) -> None:
        await super().send_json(event)  # keeps the ready and pending flags
        content = (event.get("data") or {}).get("content")
        if isinstance(content, dict) and content.get("name") in ("clarifier", "manual_verification", "conversation_agent"):
            form = status.loads(content.get("content"))
            self.ask_text = str(form.get("intro") or "") if isinstance(form, dict) else str(form or "")
        self.last_event = time.monotonic()
        if self.task_id and self.last_event - self.noted > PROGRESS_WRITE_S:  # every event is progress; written at most this often
            self.noted = self.last_event
            await _track(self.task_id, last_progress_at=dt.now_iso())
        if not (simple := simplify(event, self.ask_text, self.plan)):
            return
        ended = simple["type"] == "completion" or (simple["type"] == "error" and event.get("error_code") == FAILED_RUN)
        going_on = False  # a lead round handed on: not the run's end
        try:
            if simple["type"] == "plan":
                self._progress(simple["steps"])
                self.plan = simple["steps"]
                if current := next((s for s in simple["steps"] if s.get("status") == "running"), None):
                    await _track(self.task_id, step=str(current.get("task") or current.get("agent") or "")[:300])
            if simple["type"] == "input_request":
                simple["chat_id"] = self.chat_id  # the conversation to answer in, and to continue later
                self.asked_at = time.monotonic()
                await self._announce(simple, event)
                q = simple.get("question") or {}
                await _track(self.task_id, state="waiting", waiting_on={"who": "user", "what": str(q.get("title") or q.get("message") or q.get("kind") or "")[:300],
                                                                       "since": dt.now_iso()})
            if simple["type"] == "completion" and await self._close_round(simple):
                going_on = True  # another sourcing round is starting: this is not the run's end
                return
            if self.agenda_id:
                simple["agenda_id"] = self.agenda_id
            if title := await get_chat_title(self.chat_id):
                simple["task_title"] = title  # the name the chat has now: it follows the work
            if ended:
                simple["result"] = await self._safe_result(simple)
        except Exception as e:  # the event still goes out, and an ended run still frees its chat
            logger.warning(f"[hands] {self.chat_id}: {simple['type']} sent without its extras: {e}")
        finally:
            if not going_on:
                self.queue.put_nowait(simple)  # before the chat is freed: its next run clears this queue when it begins
                if ended:
                    await _track(self.task_id, state=_end_state(simple), ended_at=dt.now_iso(), waiting_on="", result=simple.get("result") or "")
                    _run_ended(self.chat_id)

    async def _safe_result(self, end: dict[str, Any]) -> dict[str, Any]:
        """The result within RESULT_S; past it, or when building it fails, the result from what the run itself knows."""
        try:
            return await asyncio.wait_for(self._result(end), RESULT_S)
        except Exception as e:  # TimeoutError included
            logger.warning(f"[hands] {self.chat_id}: result built without task status or learnings: {e}")
            return run_result.envelope({"chat_id": self.chat_id, "request": self.request}, key=self.key, agenda_id=self.agenda_id,
                                       error=end.get("message", "") if end["type"] == "error" else "", cancelled=end.get("status") == "cancelled",
                                       stop_reason=self.stop_reason, started_at=self.started_at, ended_at=dt.now_iso())

    def lost(self, why: str) -> None:
        """The run ended without saying so: its poller gets a stopped, retryable result, and its chat is freed."""
        result = run_result.envelope({"chat_id": self.chat_id, "request": self.request, "stage": "stopped"}, key=self.key, agenda_id=self.agenda_id,
                                     started_at=self.started_at, ended_at=dt.now_iso(), stop_reason=why)
        self.queue.put_nowait({"type": "completion", "status": "lost", "chat_id": self.chat_id,
                               **({"agenda_id": self.agenda_id} if self.agenda_id else {}), "result": result})
        _active.discard(self.chat_id)
        site.end_run(self.chat_id)
        if self.task_id:
            _watch(_track(self.task_id, state="failed", ended_at=dt.now_iso(), waiting_on="", result=result))

    def _base(self) -> dict[str, Any]:
        return run_result.envelope({"chat_id": self.chat_id, "request": self.request}, key=self.key, agenda_id=self.agenda_id)

    def _progress(self, steps: list[dict[str, Any]]) -> None:
        """A progress update (contract [15]) for each plan step that has just ended."""
        before = {s["step"]: s["status"] for s in self.plan}
        for s in steps:
            if s["status"] in ("completed", "failed") and before.get(s["step"]) != s["status"]:
                self.queue.put_nowait({"type": "progress", "chat_id": self.chat_id, **({"agenda_id": self.agenda_id} if self.agenda_id else {}),
                                       "result": run_result.progress(self._base(), s)})

    async def _result(self, end: dict[str, Any]) -> dict[str, Any]:
        """The run's result (contract [15]): its state as task_status reads it, the numbers on its completion, and learnings."""
        try:
            ts = await status.task_status(USER_ID, self.chat_id)
        except Exception as e:  # the result never holds up the end of a run: it goes out with what the run itself knows
            logger.warning(f"[hands] no task status for {self.chat_id}'s result: {e}")
            ts = {"chat_id": self.chat_id, "request": self.request}
        ts["request"] = ts.get("request") or self.request
        learned = await run_result.learnings(ts) if ts.get("summary") else []
        if learned:
            await save_pref(USER_ID, f"learnings:{self.chat_id}", learned)  # task_status shows them too
        return run_result.envelope(ts, key=self.key, agenda_id=self.agenda_id, error=end.get("message", "") if end["type"] == "error" else "",
                                   cancelled=end.get("status") == "cancelled", stop_reason=self.stop_reason, learnings=learned, started_at=self.started_at, ended_at=dt.now_iso(),
                                   numbers={k: end[k] for k in ("leads", "credits_spent") if k in end})

    async def _close_round(self, done: dict[str, Any]) -> bool:
        """Put the lead counts on a completion. True when the lead target is not met and sourcing goes on instead: the next
        round is queued as a note, which the manager starts as the next task, and this completion is not shown."""
        tally = await leads.tally(self.chat_id, self.started_at)  # this run's contacts, not every list the chat ever saved
        done["credits_spent"] = await needs.credits_approved(self.chat_id, self.started_at)  # across every sourcing round of the run
        done["leads"] = {"target": self.lead_target or None, "passed": tally["passed"], "failed": tally["failed"]}
        if not self.lead_target:
            return False
        why = "stopped" if done.get("status") != "complete" else leads.stop_reason(self.lead_target, tally, self.seen, await budget_left(self.chat_id), self.rounds)
        if why:
            done["leads"]["stopped_because"] = why
            return False
        self.rounds, self.seen = self.rounds + 1, tally["seen"]
        (await get_websocket_manager()).add_note(self.chat_id, leads.next_round(self.lead_target, tally))
        return True

    async def _announce(self, simple: dict[str, Any], event: dict[str, Any]) -> None:
        """Give the question the fields of a need (contract [7]) and push it if nobody polls for it."""
        need = await needs.build(self.chat_id, str(event.get("request_id") or ""), simple["question"], simple["card"], str(event.get("timestamp") or ""))
        simple.update({k: v for k, v in need["data"].items() if k != "card"})  # `card` is already there, raw
        if need["id"]:
            task = asyncio.create_task(self._push_unattended(need))
            _watching.add(task)
            task.add_done_callback(_watching.discard)

    async def _push_unattended(self, need: dict[str, Any]) -> None:
        """Push the need once, when nobody has polled this run for UNATTENDED_S since it was asked and it is still open."""
        opened = time.monotonic()
        while True:
            await asyncio.sleep(1 if self.polling else max(0.05, needs.UNATTENDED_S - (time.monotonic() - max(opened, self.last_poll))))
            open_ = (await get_websocket_manager()).pending_request(self.chat_id)
            if not open_ or open_.get("request_id") != need["id"] or open_.get("answered") or self.task.done():
                return
            if not self.polling and time.monotonic() - max(opened, self.last_poll) >= needs.UNATTENDED_S:
                need["data"]["task_title"] = await get_chat_title(self.chat_id) or need["data"].get("task_title", "")  # renamed since it was asked
                await needs.push(need)
                return


def _find(key: str) -> HandsThread | None:
    """The run started here with this key, or the latest one on this chat_id."""
    return _threads.get(key) or next((t for t in reversed(_threads.values()) if t.chat_id == key), None)


def _thread(key: str) -> HandsThread:
    t = _find(key)
    if not t:
        raise ValueError(f"no run with key {key}")
    return t


async def _source(ctx: Context) -> str:
    """Who is calling: the client's own name and version (self-reported) and the key it used (which the app made)."""
    info = ctx.session.client_params.clientInfo if ctx.session.client_params else None
    client = f"{info.name} {info.version}".strip() if info and info.name not in ("", "mcp") else "AI agent"  # "mcp" is the SDK default
    request = getattr(getattr(ctx, "request_context", None), "request", None)
    key = ((request.scope.get("state") or {}).get("dax_key") if request else None) or {}
    if key.get("id"):
        from src.database import note_hands_client

        await note_hands_client(key["id"], client)
    return f"{client} · {key['name']}" if key.get("name") else client


@mcp.tool(annotations=WRITE)
async def start_run(task: str, ctx: Context, key: str = "", files: list[str] | None = None, chat_id: str = "",
                    agenda_id: str = "", lead_target: int = 0, credit_budget: float | None = None, agent: str = "") -> dict[str, Any]:
    """Start a task run (a lead search, a campaign, outreach, a reply) and return its chat_id; drive it with next_event and answer.
    Tasks are for long, multi-step work: several agents, saved lists, credits, sends. A small request answered in one turn
    (check the inbox or calendar, one web search, look someone up, sum up a saved list) is not a task: use chat.
    chat_id: the conversation to continue, so its agents see what was done there before; empty starts a new one, or with an
    agenda_id continues that agenda's chat (a goal has one chat).
    A run on a chat that is running, or beyond the parallel limit, is queued: {queued: true, position}; a chat's runs go in order.
    key: optionally your own id for the run (defaults to the chat_id). files: paths on this machine to attach (a deck, a list).
    agenda_id: the agenda this run serves; kept on the chat and echoed in every event.
    lead_target: how many leads that pass the lead gate the run must produce; it keeps sourcing until they are found, the
    source runs dry or a round limit is hit, and its completion says which in `leads` (target, passed, failed, stopped_because).
    credit_budget: the credits this goal may still spend without asking (what is left of its cap). A credit spend that fits is
    approved by DAXAGENT itself and logged; one above it raises a card as before. Kept per agenda (per chat without one).
    agent: one agent to do the whole task (e.g. lead_finder, buyer_finder, contact_enricher, outreach): it takes the task
    straight away, with no questions form, plan, plan approval or router, and its answer is the run's result."""
    if agent and agent not in persona_names():
        raise ValueError(f"no agent {agent}; known: {', '.join(persona_names())}")
    if chat_id and not await (await get_chat_repository()).get_chat(USER_ID, chat_id, "omni"):
        raise ValueError(f"no task {chat_id}")
    chat_id = chat_id or (agenda_id and await chat_of_agenda(USER_ID, agenda_id)) or (await ChatService.create_omni_chat(USER_ID))["chat_id"]
    task_id = f"dt_{uuid.uuid4().hex[:12]}"
    key = key or task_id  # unique: a chat may hold many tasks, each told apart
    now = dt.now_iso()
    await save_task({"id": task_id, "run_key": key, "chat_id": chat_id, "agenda_id": agenda_id, "title": task.strip().split("\n")[0][:200],
                     "state": "queued", "started_at": now, "last_progress_at": now})
    await save_pref(USER_ID, f"run_by:{chat_id}", await _source(ctx))  # the web app marks the task as run by it
    if agenda_id:
        await save_pref(USER_ID, f"agenda:{chat_id}", agenda_id)
    place = await _admit({"key": key, "chat_id": chat_id, "task": f"{signal_play.DIRECT} {agent}\n{task}" if agent else task, "files": files or [], "lead_target": lead_target, "credit_budget": credit_budget})
    agenda = await needs.agenda_of(chat_id)
    return {"id": task_id, "key": key, "chat_id": chat_id, **({"queued": True, "position": place} if place else {}), **({"agenda_id": agenda} if agenda else {})}


STALL_MIN = 10  # a running task with no progress for this long is reported stalled
PROGRESS_WRITE_S = 10


async def _track(task_id: str, **fields: Any) -> None:
    """Write what happened to a task; a failure here never stops the run or its events."""
    if not task_id:
        return
    try:
        await save_task({"id": task_id, **fields})
    except Exception as e:
        logger.warning(f"[hands] task {task_id} not updated: {e}")
        return
    if fields.get("state") in ENDED and (row := await find_task(task_id)):
        _ended(row, fields["state"])


ENDED = ("done", "failed", "cancelled")


def _ended(row: dict[str, Any], state: str, id: str = "") -> None:
    """Contract [29]'s task.ended push; stalled is not final, a later end of the same task wins."""
    brain_hands.push_in_background(
        "task.ended", id or f"{row['id']}:{state}", row["title"], "",  # the result itself: task_status
        v=1, task_id=row["id"], chat_id=row["chat_id"], agenda_id=row["agenda_id"], run_key=row["run_key"], state=state,
        step=row["step"], ended_at=row["ended_at"] or dt.now_iso())


async def _settle() -> None:
    """A task row left running or waiting by a run that no longer goes is closed failed; a live one quiet for STALL_MIN
    minutes is pushed stalled, once per quiet stretch."""
    going = {k: t for k, t in _threads.items() if not t.task.done()}
    live = {t.task_id for t in going.values()} | set(going)  # by key too: a starting run is in _threads before its task_id is set
    for row in await list_task_rows(True, None, 200):
        if row["state"] not in ("running", "waiting"):
            continue
        if row["id"] not in live and row["run_key"] not in live:
            ended = dt.now_iso()
            await _track(row["id"], state="failed", ended_at=ended, waiting_on="", result=run_result.envelope(
                {"chat_id": row["chat_id"], "request": row["title"], "stage": "stopped"}, key=row["run_key"], agenda_id=row["agenda_id"],
                started_at=row["started_at"], ended_at=ended, stop_reason="lost: the run that held this task is no longer going"))
        elif row["state"] == "running" and (await _view(row))["state"] == "stalled" and (told := f"{row['id']}:stalled:{row['last_progress_at']}") not in _stall_told:
            _stall_told.add(told)
            _ended(row, "stalled", told)


_stall_told: set[str] = set()


def _watch(coro) -> None:
    task = asyncio.create_task(coro)
    _watching.add(task)
    task.add_done_callback(_watching.discard)


def _end_state(completion: dict[str, Any]) -> str:
    """done, cancelled or failed, from a run's last event."""
    if completion.get("type") == "error":
        return "failed"
    return {"complete": "done", "cancelled": "cancelled", "stopped": "cancelled"}.get(str(completion.get("status")), "failed")


async def _view(task: dict[str, Any]) -> dict[str, Any]:
    """A task in contract [26]'s shape; running with no progress for STALL_MIN minutes reads stalled."""
    state = task["state"]
    if state == "running" and (datetime.now(timezone.utc) - datetime.fromisoformat(task["last_progress_at"])).total_seconds() > STALL_MIN * 60:
        state = "stalled"
    queued = await queued_run(task["run_key"]) if state == "queued" else None
    return {"v": 1, "id": task["id"], "app": "daxagent", "agenda_id": task["agenda_id"], "parent_id": task["run_key"], "chat_id": task["chat_id"],
            "title": task["title"], "state": state, "waiting_on": task["waiting_on"], "step": task["step"], "started_at": task["started_at"],
            "last_progress_at": task["last_progress_at"], "position": queued["position"] if queued else None, "result": task["result"]}


async def _busy() -> set[str]:
    """Chats with a run going: begun here and not ended, or running from the web app. A run begun here that the manager no
    longer runs and that has been quiet past QUIET_S ended without a word (it closed, failed in an
    unexpected way, or never started): it is reported as lost and its chat is freed."""
    manager = await get_websocket_manager()
    live = {t.chat_id: t for t in _threads.values() if not t.task.done()}
    _active.intersection_update(live)
    for chat in list(_active):
        t = live[chat]
        if not manager.is_running(chat) and time.monotonic() - t.last_event > QUIET_S:  # a run waiting on an answer is still running
            logger.warning(f"[hands] {chat}: the run ended without finishing; freeing its chat")
            t.lost("the run ended without finishing")
    return _active | set(manager.running_chats())


async def _begin(run: dict[str, Any]) -> None:
    """Start a run on its chat: its open thread takes the task, else a new one opens from the chat's history."""
    chat_id, key = run["chat_id"], run["key"]
    if run["credit_budget"] is not None:
        await set_budget(chat_id, max(0.0, float(run["credit_budget"])))
    t = next((o for o in _threads.values() if o.chat_id == chat_id and not o.task.done()), None) or HandsThread(key, chat_id)
    while not t.queue.empty():
        t.queue.get_nowait()  # the last run's leftovers are not this run's events
    t.key = key  # a reused thread's results answer this run, not the one that opened it
    t.ask_text, t.plan, t.stop_reason, t.asked_at, t.last_event = "", [], "", None, time.monotonic()
    t.agenda_id = await needs.agenda_of(chat_id)  # a continued chat keeps its agenda
    t.lead_target, t.rounds, t.started_at = max(0, int(run["lead_target"])), 0, dt.now_iso()
    site.begin_run(chat_id, t.started_at)  # the run's cap on site reads counts from here, across its sourcing rounds
    t.seen = (await leads.tally(chat_id, t.started_at))["seen"] if t.lead_target else 0
    _threads[key] = t
    _active.add(chat_id)
    t.task_id = (row["id"] if (row := await find_task(key)) and row["run_key"] == key else "")
    await _track(t.task_id, state="running", last_progress_at=dt.now_iso(), waiting_on="")
    await save_pref(USER_ID, f"run_params:{chat_id}", {"key": key, "lead_target": t.lead_target})  # what a resume after a restart needs
    t.request = run["task"]
    t.inbox.put_nowait(json.dumps({"type": "start", "task": run["task"], "files": run["files"]}))


async def _admit(run: dict[str, Any]) -> int | None:
    """Start the run, or queue it (returns its place) when its chat is running or MAX_PARALLEL chats already are."""
    async with _lock:
        busy = await _busy()
        behind = any(q["chat_id"] == run["chat_id"] for q in await list_queued_runs())  # a chat's runs keep their order
        if behind or run["chat_id"] in busy or len(busy) >= MAX_PARALLEL:
            return await enqueue_run(run)
        await _begin(run)
    return None


BEGIN_TRIES = 3  # a queued run that fails to start this many times is dropped with a failed result
_begin_failures: dict[int, int] = {}  # queued run id -> failed starts so far
_dropped: dict[str, dict[str, Any]] = {}  # run key -> the failed completion its poller gets next


async def _dispatch() -> None:
    """Start queued runs, oldest first: a chat's runs go one at a time, and at most MAX_PARALLEL chats run together.
    A run leaves the queue only once it has begun; one that fails to start is tried again on later passes without
    holding up the runs behind it, and after BEGIN_TRIES failures it is dropped and reported (_drop)."""
    async with _lock:
        busy = await _busy()
        for run in await list_queued_runs():
            if len(busy) >= MAX_PARALLEL:
                break
            if run["chat_id"] in busy:
                continue
            busy.add(run["chat_id"])  # its chat's later runs wait, whether it starts or not
            try:
                await _begin(run)
            except Exception as e:
                tries = _begin_failures[run["id"]] = _begin_failures.get(run["id"], 0) + 1
                logger.warning(f"[hands] queued run {run['key']} on {run['chat_id']} did not start ({tries}/{BEGIN_TRIES}): {e}")
                if tries >= BEGIN_TRIES:
                    await pop_queued_run(run["id"])
                    _begin_failures.pop(run["id"], None)
                    await _drop(run, e)
                continue
            await pop_queued_run(run["id"])
            _begin_failures.pop(run["id"], None)


async def _drop(run: dict[str, Any], error: Exception) -> None:
    """A queued run that could not start: its poller gets a failed completion, and Brain_Hands a notice saying why and
    whether to send it again."""
    agenda = await needs.agenda_of(run["chat_id"])
    result = run_result.envelope({"chat_id": run["chat_id"], "request": run["task"]}, key=run["key"], agenda_id=agenda,
                                 error=f"the run could not start after {BEGIN_TRIES} tries: {error}", ended_at=dt.now_iso())
    if (row := await find_task(run["key"])) and row["run_key"] == run["key"]:
        await _track(row["id"], state="failed", ended_at=dt.now_iso(), result=result)
    _dropped[run["key"]] = {"type": "completion", "status": "failed", "chat_id": run["chat_id"], **({"agenda_id": agenda} if agenda else {}), "result": result}
    await brain_hands.push("dax.run_failed", f"{run['key']}:not_started", "A queued DAX run could not start", result["reason"],
                           chat_id=run["chat_id"], key=run["key"], agenda_id=agenda, reason=result["reason"], retryable=result["retryable"])


MAX_RESUMES = 2  # a run that keeps killing the process is given up on


async def resume_runs() -> set[str]:
    """At startup: each run its process left unfinished continues on its chat. An approved plan goes on from its first
    unfinished step (Omni's "continue"); a run cut short before its plan was approved starts again from its request.
    A step that was going starts over, and asks its question again. Returns the chats resumed."""
    from src.omni.manager import Omni

    resumed: set[str] = set()
    for row in await list_marked_runs():
        if needs.alive(row["owner_pid"]):
            continue  # another backend's run on the same database
        chat = await (await get_chat_repository()).get_chat(USER_ID, row["chat_id"], "omni")
        if not chat or row["resumes"] >= MAX_RESUMES:
            await unmark_run(row["chat_id"])
            continue
        params = await load_pref(USER_ID, f"run_params:{row['chat_id']}") or {}
        resuming = Omni._has_pending_plan(chat.get("messages") or [])
        try:
            await count_resume(row["chat_id"])
            await _begin({"key": params.get("key") or row["chat_id"], "chat_id": row["chat_id"], "task": "continue" if resuming else row["task"],
                          "files": [] if resuming else row["files"], "lead_target": params.get("lead_target", 0), "credit_budget": None})
            resumed.add(row["chat_id"])
        except Exception as e:  # one run that cannot be resumed must not hold up the rest
            logger.warning(f"[resume] {row['chat_id']} could not be resumed: {e}")
    return resumed


async def recover() -> None:
    """Start-up: resume the runs that were cut short, close the questions nobody can answer now, start what was queued."""
    resumed = await resume_runs()
    await needs.close_lost(resumed)
    await _dispatch()
    global _tender
    if _tender is None or _tender.done():  # its own handle: _watching is awaited to drain, and this never ends
        _tender = asyncio.create_task(_tend())


async def _tend() -> None:
    """For as long as the app runs: give up on questions nobody answers, and start queued runs (which frees lost ones)."""
    while True:
        await asyncio.sleep(TEND_S)
        try:
            await _expire_questions()
            await _tell_blocked()
            await _dispatch()
            await _settle()
        except Exception as e:  # the next turn tries again
            logger.warning(f"[hands] tend: {e}")


async def _expire_questions() -> None:
    """A run driven from here whose question has waited past QUESTION_WAIT_S is stopped: the question closes as no_answer
    (pushed as "<request_id>:no_answer"), and the run ends stopped with "no answer to: <question>". Runs started in the web
    app are not here: they wait for the person."""
    manager = await get_websocket_manager()
    for t in {id(t): t for t in _threads.values()}.values():
        open_ = manager.pending_request(t.chat_id)
        if (t.chat_id not in _active or t.task.done() or not open_ or open_.get("answered") or t.asked_at is None
                or time.monotonic() - t.asked_at < QUESTION_WAIT_S):
            continue
        card, asked_by = status.card_of(open_)
        question = status.question_of(card, asked_by, t.ask_text, t.plan)
        t.stop_reason = f"no answer to: {question.get('title') or question.get('message') or 'a question'}"[:300]
        if (rid := str(open_.get("request_id") or "")).isdigit():
            await answer_decision(int(rid), {"closed": "no_answer"})
            need = await needs.build(t.chat_id, rid, question, card, str(open_.get("timestamp") or ""))
            await needs.push({**need, "id": f"{rid}:no_answer"}, reason="no_answer")
        await manager.stop_session(t.chat_id, t.stop_reason)


_told_blocked: set[tuple[str, str]] = set()  # (request_id, queued key) already told; shortcut: in memory, a restart tells once more


async def _tell_blocked() -> None:
    """A queued run whose chat waits on a question asked in the web app (not a run of ours) is told to Brain_Hands once
    per question, as a need it shows and never answers (answerable False): only the person answers it, in the web app."""
    manager = await get_websocket_manager()
    for run in await list_queued_runs():
        chat, key = run["chat_id"], run["key"]
        open_ = manager.pending_request(chat)
        if chat in _active or not open_ or open_.get("answered") or not (rid := str(open_.get("request_id") or "")):
            continue
        if (rid, key) in _told_blocked:
            continue
        card, asked_by = status.card_of(open_)
        need = await needs.build(chat, rid, status.question_of(card, asked_by, "", []), card, str(open_.get("timestamp") or ""))
        await needs.push({**need, "id": f"{rid}:blocks:{key}"}, reason="blocks_queued", queued_key=key, answerable=False)
        _told_blocked.add((rid, key))


def _run_ended(chat_id: str) -> None:
    """A run's last completion went out: its chat is free, so the next queued run may start."""
    _active.discard(chat_id)
    site.end_run(chat_id)
    task = asyncio.create_task(_dispatch())
    _watching.add(task)
    task.add_done_callback(_watching.discard)


@mcp.tool(annotations=READ)
async def next_event(key: str, timeout: int = 25) -> dict[str, Any]:
    """The run's events since the last call: input_request (answer it with answer), plan, summary, completion (with
    campaigns: each campaign plan's counts and next step), error. key: the run's chat_id (or your key). Waits up to timeout seconds (at most 60) for the first one. closed is true when
    the run is over and drained."""
    if key in _dropped:  # it never started: its poller is told once, and the run is over
        end = _dropped.pop(key)
        return {"chat_id": end["chat_id"], "events": [end], "closed": True, "pending": False}
    if not _find(key) and await queued_run(key):
        await _dispatch()  # its turn may have come without another run ending here
    if not _find(key) and (waiting := await queued_run(key)):  # behind another run: nothing yet
        return {"chat_id": waiting["chat_id"], "events": [], "closed": False, "pending": False, "queued": True, "position": waiting["position"]}
    if not (t := _find(key)):  # not running here (it ended before a restart, or never was): over, so the poller stops
        return {"chat_id": key, "events": [], "closed": True, "pending": False, "unknown": True}
    events: list[dict[str, Any]] = []
    t.polling += 1
    try:
        events.append(await asyncio.wait_for(t.queue.get(), min(max(timeout, 1), 60)))
    except asyncio.TimeoutError:
        pass
    finally:
        t.polling -= 1
        t.last_poll = time.monotonic()
    while not t.queue.empty():
        events.append(t.queue.get_nowait())
    if done := next((e for e in events if e["type"] == "completion"), None):
        done["campaigns"] = await status.campaigns(t.chat_id)  # what each campaign plan waits on now, e.g. drafts ready to send
    pending = bool((await get_websocket_manager()).pending_request(t.chat_id))
    return {"chat_id": t.chat_id, "events": events, "closed": t.task.done() and t.queue.empty(), "pending": pending}


@mcp.tool(annotations=WRITE)
async def answer(key: str, response: str, request_id: str = "") -> dict[str, Any]:
    """Answer the open question of a task (its chat_id, or the key of a run started here), as the
    question's answer_with says: 'yes', 'no', free text, or a JSON object such as {"values": {...}} for a clarify
    form, {"action": "choose", "selected": [...]}, {"action": "revise", "text": "..."} or {"action": "skip"}.
    request_id: the question the answer is for (from its input_request). A question already answered, here or in the
    web app, or a stale one is not applied: {ok: false, reason: "not_open"}."""
    reply: Any = response.strip()
    if reply.startswith("{"):
        try:
            reply = json.loads(reply)  # the form and card answers are objects
        except ValueError:
            pass
    manager = await get_websocket_manager()
    t = _find(key)
    if t and t.task.done():
        raise ValueError(f"run {key} is over")
    chat_id = t.chat_id if t else key
    if not t and not await (await get_chat_repository()).get_chat(USER_ID, key, "omni"):
        raise ValueError(f"no run or task {key}")
    open_id = (manager.pending_request(chat_id) or {}).get("request_id")  # the live question: the web app may have answered it
    if not t and any(rid == str(request_id or open_id) for rid, _ in _told_blocked):  # a web-app run's question: the person answers it there
        return {"ok": False, "reason": "web_app_question", "note": "that question belongs to a run started in DAX's app; the user answers it there"}
    if not await manager.handle_input_response(chat_id, reply, request_id or None):
        return {"ok": False, "reason": "not_open", "note": "that question is not open (nothing waits, or it was answered in the web app, or request_id is stale)"}
    if t:
        t.pending = False
        await _track(t.task_id, state="running", waiting_on="", last_progress_at=dt.now_iso())
    return {"ok": True, "chat_id": chat_id, "task_id": chat_id, "request_id": open_id}


async def _waiting_on(chat_id: str) -> dict[str, Any] | None:
    """The run a queued run waits behind: when it began, who started it, and where it is; None when none runs the chat."""
    if chat_id not in _active and chat_id not in (await get_websocket_manager()).running_chats():
        return None
    return {"started_at": await run_started(chat_id), "source": "brain_hands" if chat_id in _active else "web_app",
            "state": (await status.task_status(USER_ID, chat_id))["stage"]}


@mcp.tool(annotations=READ)
async def task_status(key: str = "", chat_id: str = "") -> dict[str, Any]:
    """Where a task is: stage (understanding, waiting_for_answer, awaiting_plan_approval, running, wrapping_up, done,
    stopped), a note, each plan step's agent, task, status and result, progress (percent of steps finished), the agents
    at work with their current step, the open question with how to answer it, credits approved and declined, saved
    work, the final summary, timings and campaigns (each campaign plan's steps approved, drafted, sent, replied and its
    next step). Give the task's id, the key of a run started here or the chat_id of any task. A task started here also
    carries contract [26]'s fields: id, state (queued, running, waiting, stalled, done, failed, cancelled), waiting_on,
    step, started_at, last_progress_at, position, result."""
    task = await find_task(key or chat_id) if (key or chat_id) else None
    if task and task["state"] == "queued":
        return {**await _view(task), "queued": True, "chat_id": task["chat_id"], "waiting_on": await _waiting_on(task["chat_id"])}
    if task and key == task["id"]:
        key = task["run_key"]
    if key and (t := _find(key)):
        chat_id = t.chat_id
    elif key and not chat_id and (waiting := await queued_run(key)):  # not started yet: say what it waits behind
        return {"queued": True, "position": waiting["position"], "chat_id": waiting["chat_id"], "waiting_on": await _waiting_on(waiting["chat_id"])}
    chat_id = chat_id or key
    if not chat_id:
        raise ValueError("give the key of a run started here or a task's chat_id")
    if task:
        return {**await status.task_status(USER_ID, chat_id), **await _view(task)}
    if await _is_chat(chat_id):  # a chat (the chat tool) has no plan or steps: whether it is answering, and what it saved
        saved = [{"id": a["id"], "kind": a["kind"], "title": a["title"], "rows": a["row_count"]} for a in await db_list_artifacts(chat_id)]
        return {"chat_id": chat_id, "request": "chat", "stage": "running" if (await get_websocket_manager()).is_running(chat_id) else "done", "saved": saved}
    return await status.task_status(USER_ID, chat_id)


async def _is_chat(chat_id: str) -> bool:
    """A chat-mode chat (made by chat, or the web app's chat mode), not a task chat."""
    repo = await get_chat_repository()
    return not await repo.get_chat(USER_ID, chat_id, "omni") and bool(await repo.get_chat(USER_ID, chat_id, "chats"))


@mcp.tool(annotations=READ)
async def company_facts(website: str, name: str = "") -> dict[str, Any] | None:
    """A company's facts from one free Data Axle search (no agent, no credits): name, website, industry, employees (Data
    Axle's size range, e.g. "50-99"), city and state, leaving out what its free sample does not give; null when no single
    headquarters matches. Data Axle cannot search by domain, so the company is matched by `name` when you pass it, else
    by the domain's first label, and `website` is echoed back, not confirmed."""
    from src.services import company_facts as cf

    return await cf.facts(website, name)


@mcp.tool(annotations=READ)
async def list_tasks(limit: int = 10, active: bool = False, agenda_id: str = "") -> dict[str, Any]:
    """The most recent tasks, newest first, with their chat_id, folder name, request, stage and percent finished. With
    active or agenda_id: the tasks started here, in contract [26]'s shape (active: queued, running, waiting or stalled), each
    with its own id, any number on one chat."""
    if active or agenda_id:
        return {"tasks": [await _view(r) for r in await list_task_rows(active, agenda_id, min(max(limit, 1), 200))]}
    keys = {t.chat_id: k for k, t in _threads.items()}
    tasks = []
    for c in [c for c in await list_conversations(USER_ID) if c["collection"] == "omni"][: min(max(limit, 1), 50)]:
        s = await status.task_status(USER_ID, c["chat_id"])
        tasks.append({"chat_id": c["chat_id"], "key": keys.get(c["chat_id"]), "name": os.path.basename(str(c["chat_dir"] or "").rstrip("/")),
                      "request": s["request"][:300], "stage": s["stage"], "percent": s["progress"]["percent"], "updated_at": s["updated_at"]})
    return {"tasks": tasks}


@mcp.tool(annotations=READ)
async def list_artifacts(chat_id: str = "", search: str = "", kind: str = "") -> dict[str, Any]:
    """The files a task saved (lead lists, buyer maps, enriched contacts, campaign plans, …), newest first: id, kind,
    title, rows, the agent that saved it and its task's chat_id. Without chat_id: the newest 50 files of every task,
    narrowed by search (words in the title, source or id) and kind. Read one with read_artifact."""
    if chat_id and not await (await get_chat_repository()).get_chat(USER_ID, chat_id, "omni") and not await _is_chat(chat_id):
        raise ValueError(f"no task or chat {chat_id}")
    found = await db_list_artifacts(chat_id) if chat_id else await find_artifacts(USER_ID, search, kind, 50)
    return {"chat_id": chat_id, "artifacts": [
        {"id": a["id"], "kind": a["kind"], "title": a["title"], "rows": a["row_count"], "agent": a["persona"],
         "created_at": a["created_at"], "chat_id": a.get("chat_id", chat_id)}
        for a in found]}


@mcp.tool(annotations=READ)
async def read_artifact(artifact_id: str, chat_id: str = "", offset: int = 0, limit: int = 100) -> dict[str, Any]:
    """A saved file's rows, a page at a time (limit at most 500), with its columns, row_count and meta. Page on with
    offset until offset + len(rows) reaches row_count. Any task's file opens by its id; chat_id in the result is the
    task that saved it."""
    # chat_id is taken for callers that still pass it; the id alone finds the file
    try:
        record, payload = await load_owned(USER_ID, artifact_id)
    except FileNotFoundError as e:
        raise ValueError(str(e)) from e
    rows, offset, limit = payload.get("rows", []), max(offset, 0), min(max(limit, 1), 500)
    return {"chat_id": record["chat_id"], "id": artifact_id, "kind": record["kind"], "title": record["title"],
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


@mcp.tool(annotations=WRITE)
async def add_touch(chat_id: str, to: str, subject: str, body: str, send_after_days: int = 0, plan_id: str | None = None,
                    sender_name: str = "", sender_title: str = "", sender_company: str = "", postal_address: str = "",
                    opt_out: str = "") -> dict[str, Any]:
    """Store one email for one person in that task's campaign plan as a draft, its copy exactly as you give it: no DAX agent
    rewrites it. Returns {plan_id, step, status} or {refused: why}. The person must have passed the lead gate in that task
    (a contact it saved). The step is the person's highest step plus one; with no plan_id it starts a plan (the first touch).
    body: plain text; it may use {{first_name}}, {{company}}, {{title}} and {{sender_name}}-style tokens, filled per
    recipient; the sign-off is added when sending, so end the body without a name. sender_name, sender_title,
    sender_company, postal_address, opt_out: the sign-off of a plan this call starts (postal_address and opt_out both needed);
    without them it copies the newest campaign brief that has both. Ignored with plan_id: the plan keeps its own. Step 1: at most 85 words and no link;
    a later step: at most one link. A later step goes in the first email's thread, after the step before it was sent and
    send_after_days after the first email. Nothing is sent: the step is a draft until it is approved (on the campaign page,
    or by approve_plan_steps), then a send asks send_approval as usual. Refusals: empty subject or body; not a contact saved in this chat; did not pass the lead
    gate: <why>; replied; bounced; not a campaign plan of this chat; not in the plan's contacts list; already in plan <id>;
    no sign-off; first email over 85 words; a link in the first email; more than one link; masked, empty or unknown tokens."""
    if not await (await get_chat_repository()).get_chat(USER_ID, chat_id, "omni"):
        raise ValueError(f"no task {chat_id}")
    sign_off = {"sender_name": sender_name, "sender_title": sender_title, "sender_company": sender_company,
                "postal_address": postal_address, "opt_out": opt_out}
    return await campaign.add_touch(USER_ID, chat_id, to, subject, body, send_after_days, plan_id or "", sign_off)


@mcp.tool(annotations=WRITE)
async def cancel(id: str) -> dict[str, Any]:
    """End a task (its id, key or chat_id): a queued one leaves the queue, a running or waiting one is stopped as the web
    app's Stop does, and what it held (its chat, its slot) is freed. Returns the task as task_status gives it."""
    task = await find_task(id)
    if not task:
        raise ValueError(f"no task {id}")
    if task["state"] == "queued":
        if waiting := await queued_run(task["run_key"]):
            await pop_queued_run(waiting["id"])
        await _track(task["id"], state="cancelled", ended_at=dt.now_iso())
    elif task["state"] in ("running", "waiting"):
        await (await get_websocket_manager()).stop_session(task["chat_id"], reason=f"cancelled by the caller ({id})")
        await _track(task["id"], state="cancelled", ended_at=dt.now_iso(), waiting_on="")
    return await _view(await find_task(task["id"]))


@mcp.tool(annotations=READ)
async def handoffs(status: str = "", chat_id: str | None = None, since: str | None = None) -> dict[str, Any]:
    """Replies from contacts that the Inbox Agent handed to a person: contact, route (handoff, propose_meeting, answer,
    suppress, snooze, auto_reply, or bounce: a delivery failure, contact the mailer-daemon, read.address the dead address), read (Jev's intent), the reply text, a drafted answer, status.
    status: '' all, 'active' open or claimed, or one of open, claimed, sent, done. since: ISO time, newer only."""
    rows = await list_handoffs(USER_ID, status or None, chat_id)
    if since:
        rows = [h for h in rows if h["created_at"] > since]
    return {"handoffs": rows}


_chats: dict[str, ChatThread] = {}  # chat-mode chats driven from here, by chat_id


@mcp.tool(annotations=WRITE)
async def chat(message: str, chat_id: str = "", timeout: int = 180) -> dict[str, Any]:
    """Ask DAX's chat assistant something quick and get its reply in this call: check the inbox, search the web, look
    something up in a connected app, read or sum up a saved list, draft one short note. One assistant, no plan, no team of
    agents. Never for long-running or multi-step work (lead lists, buyers, enrichment, campaigns, outreach, a goal's
    research): that goes to start_run; chat says when a request needs a task. chat_id: continue that chat (empty starts a new one; the answer gives it).
    Returns {chat_id, reply, done}; done false with `question` when the assistant waits on an answer (an approval to send,
    a choice): call chat again with the same chat_id and your answer as the message, as the question's answer_with says.
    Waits up to timeout seconds (at most 600); done false with no question means it is still working: call again with
    message "" to collect the rest."""
    if not chat_id:
        chat_id = (await ChatService.create_chat_mode_session(USER_ID))["chat_id"]
    elif not await (await get_chat_repository()).get_chat(USER_ID, chat_id, "chats"):
        raise ValueError(f"no chat {chat_id}: chat_id is one this tool or the web app's chat mode made")
    t = _chats.get(chat_id)
    if not t or t.task.done():
        t = _chats[chat_id] = ChatThread(chat_id)
    while not t.turn.empty():
        t.turn.get_nowait()  # what a turn left unread is not this turn's
    if message.strip():
        t.send(message.strip())
    texts: list[str] = []
    try:
        async with asyncio.timeout(min(max(timeout, 1), 600)):
            while (text := await t.turn.get()) is not None:
                texts.append(text)
    except TimeoutError:
        return {"chat_id": chat_id, "reply": "\n\n".join(texts), "done": False}
    if t.task.done() and not texts:  # the chat closed without a word: say so, never a silent "done"
        why = t.task.exception() if not t.task.cancelled() else None
        raise RuntimeError(f"the chat could not run: {why}" if why else "the chat closed without answering")
    if t.pending and texts and texts[-1] == t.asked:
        texts.pop()  # the question is given apart from the reply
    return {"chat_id": chat_id, "reply": "\n\n".join(texts), "done": not t.pending, **({"question": t.asked} if t.pending else {})}


@mcp.tool(annotations=WRITE)
async def request(request: str, query: str, ctx: Context, request_id: str = "", files: list[str] | None = None, agenda_id: str = "",
                  lead_target: int = 0, credit_budget: float | None = None, timeout: int = 180, agent: str = "") -> dict[str, Any]:
    """One door for both kinds of work. request: "chat" for a small request answered in one turn (check the inbox or
    calendar, one web search, look someone up, sum up a saved list); "task" for long, multi-step work (lead lists,
    buyers, enrichment, campaigns, outreach, a goal's research). query: what to do, in plain words. request_id: the
    chat's or task's id to continue (empty starts a new one); every answer gives it back. A chat answers in this call,
    as chat does ({reply, done, question}); a task starts, as start_run does, and is followed with next_event,
    answer and task_status, each taking request_id. files, agenda_id, lead_target, credit_budget and agent are for a task;
    timeout for a chat."""
    if request == "chat":
        return {"request": "chat", "request_id": (out := await chat(query, request_id, timeout))["chat_id"], **out}
    if request == "task":
        out = await start_run(query, ctx, key="", files=files, chat_id=request_id, agenda_id=agenda_id, lead_target=lead_target, credit_budget=credit_budget, agent=agent)
        return {"request": "task", "request_id": out["chat_id"], **out}
    raise ValueError('request is "chat" or "task"')


@mcp.tool(annotations=WRITE)
async def sweep() -> dict[str, Any]:
    """Check every sent campaign thread in Gmail now and open handoffs for new replies (the reply watcher's sweep). The
    handoffs opened here carry the facts and no drafted answer (draft ""): you write the answer and send it with
    send_handoff. For propose_meeting, read.free_times holds the free times found in the calendar."""
    from src.agent_runtime import watcher

    return await watcher.sweep(USER_ID, draft=False)


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
            from src.routers.hands_keys import accepted  # the env token, or a key made in Settings > Connections > DAX MCP

            key = await accepted(headers.get("authorization", "").removeprefix("Bearer ").strip())
            scope.setdefault("state", {})["dax_key"] = key  # start_run names the task's source by it
            if not key:
                await send({"type": "http.response.start", "status": 401, "headers": [(b"content-type", b"text/plain")]})
                await send({"type": "http.response.body", "body": b"Brain_Hands token missing or wrong"})
                return
        if _inner is None:  # outside the app's lifespan
            await send({"type": "http.response.start", "status": 503, "headers": [(b"content-type", b"text/plain")]})
            await send({"type": "http.response.body", "body": b"DAXAGENT is not running"})
            return
        await _inner(scope, receive, send)

    return gate
