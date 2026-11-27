"""Where a task is, for callers outside the web app (the DAXAGENT MCP).

It is read from the chat's stored history (the request, every plan update, each agent's start, steps, saves and
finish, the questions and their answers, the final summary) plus two live facts from the WebSocket manager: whether
the run is going and the question it waits on. So it works for any task, started over MCP or in the web app, and
after a restart.
"""

import json
import re
from collections import Counter
from datetime import datetime
from typing import Any

from src.agent_runtime.decisions import parse_response

FINISHED = ("completed", "failed")
KINDS = {"form": "clarify", "confirm_spend": "credit_request", "confirm_send": "send_approval", "choose": "choose",
         "provide_data": "provide_data", "review_artifact": "review"}
ANSWER = {
    "plan_approval": '"yes" to run the plan, or say what to change',
    "clarify": '{"values": {"<question id>": "<option value, or your own text>"}, "text": "<optional note>"}; or free '
               'text; or {"action": "skip"} to go with the assumptions',
    "credit_request": '"yes" to approve spending the credits, "no" to decline, or {"action": "revise", "text": "<what to do instead>"}',
    "send_approval": '"yes" to send, "no" to hold it, or {"action": "revise", "text": "<what to change>"}',
    "choose": '{"action": "choose", "selected": ["<option value>"]}, or the option label as text; {"action": "skip"} lets the agent decide',
    "provide_data": 'the data as text, or {"action": "submit", "value": "<the data>"}',
    "review": '"yes" to keep it, "no" to drop it, or {"action": "revise", "text": "<what to change>"}',
    "text": "your answer as text",
}
# card fields worth passing on, per kind (see agent_runtime/decisions.py for each card's fields).
# Brain_Hands builds its own user questions from title, message, questions and options: keep those keys.
KEEP = ("questions", "assumptions", "question", "options", "multi", "why", "credits", "count", "unit", "tool", "server",
        "balance_before", "balance_after", "detail", "channel", "recipients", "recipient_count", "subject",
        "body_preview", "prompt", "accept", "allow_text", "artifact_id", "columns", "row_count")
# a request with an apostrophe is stored as Python text: {'task': "it's ...", 'files': []}
PY_REQUEST = re.compile(r"^\{\s*'task':\s*([\"'])(.*?)\1\s*,\s*'files'", re.S)


def loads(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


def card_of(request: dict) -> tuple[dict, str]:
    """The card an input_request carries, and who asked it."""
    data = request.get("data") or {}
    card = loads(data.get("content"))
    if not isinstance(card, dict) or not card:
        card = {"card": "text", "message": str(data.get("content") or request.get("prompt") or "")}
    if card.get("agent") == "get_user_acceptance":
        card = {"card": "plan_approval", **card}  # a copy: the event is not changed; the orchestrator's prompt has no card name; callers read it to answer
    return card, str(data.get("source") or "")


def question_of(card: dict, asked_by: str = "", context: str = "", plan: list[dict] | None = None) -> dict:
    """An open question as an outside caller needs it: its kind, what it asks, and how to answer it.
    context: the verification text Omni sent just before, which is the question of its plain user_input prompt.
    plan: the steps a plan approval is about."""
    if "agent" in card:  # the orchestrator's own prompts: {"agent", "prompt"}; their prompt text is AutoGen's own
        if card["agent"] == "get_user_acceptance":
            q: dict[str, Any] = {"kind": "plan_approval", "asked_by": "omni", "title": "Approve the plan?",
                                 "message": "Omni lined up the agents below for this task. Run the plan?", "plan": plan or []}
        else:
            q = {"kind": "text", "asked_by": "omni", "title": "Omni asks", "message": context or str(card.get("prompt") or "")}
        kind = q["kind"]
    else:
        kind = KINDS.get(str(card.get("card")), "text")
        q = {"kind": kind, "id": card.get("id"), "asked_by": card.get("asked_by") or asked_by,
             "title": card.get("title") or "", "message": card.get("message") or card.get("prompt") or ""}
        q.update({k: card[k] for k in KEEP if card.get(k) not in (None, "", [])})
        if isinstance(card.get("rows"), list):
            q["rows"] = card["rows"][:5]
    q["answer_with"] = ANSWER[kind]
    return q


def agent_name(agent: str) -> str:
    try:
        from src.agent_runtime.personas import get_persona

        return get_persona(agent).display_name
    except Exception:
        return agent.removeprefix("mcp_").replace("_", " ").title()


def plan_step(i: int, s: dict) -> dict:
    """One step of the planner's breakdown, the same everywhere the MCP shows a plan."""
    agent = str(s.get("capability") or "")
    return {"step": i, "agent": agent, "agent_name": agent_name(agent),
            "task": re.sub(r"^\s*\[[ xX]\]\s*", "", str(s.get("task") or "")), "status": str(s.get("status") or "pending"),
            **({"details": str(s["details"])} if s.get("details") else {})}  # why the step is in the plan: a result's to_achieve


def _seconds(start: str | None, end: str | None) -> int | None:
    try:
        return max(0, round((datetime.fromisoformat(str(end)) - datetime.fromisoformat(str(start))).total_seconds()))
    except (TypeError, ValueError):
        return None


def status_of(entries: list[dict], running: bool, pending: dict | None = None, now: str | None = None) -> dict:
    """The chat's latest task (everything since its last request) as stage, plan progress, agents at work, open
    question, credits, saved work and summary. pending: the input_request the live run waits on."""
    start = max((i for i, e in enumerate(entries) if e.get("name") == "chat_manager"), default=0)
    task = entries[start:]
    request, plan, ask_text, summary = "", [], "", None
    names: dict[str, str] = {}
    runs: dict[str, dict] = {}  # each agent's latest run
    results: dict[str, str] = {}
    saved: list[dict] = []
    spends: list[dict] = []
    for e in task:
        name, raw = str(e.get("name") or ""), loads(e.get("raw_message"))
        if name == "chat_manager":
            m = PY_REQUEST.match(raw) if isinstance(raw, str) else None
            request = str(raw.get("task") if isinstance(raw, dict) else m.group(2) if m else raw or "")
        elif name == "planner_agent" and isinstance(raw, dict) and raw.get("breakdown"):
            plan = raw["breakdown"]
        elif name in ("clarifier", "manual_verification") and isinstance(raw, dict):
            ask_text = str(raw.get("intro") or "")
        elif name in ("process_completion_agent", "conversation_agent"):  # either one ends a run with the answer
            summary = raw if isinstance(raw, str) else json.dumps(raw)
            ask_text = summary if name == "conversation_agent" else ask_text  # what a plan stopped mid-way waits on
        elif isinstance(raw, dict):
            kind = raw.get("type")
            if kind == "agent_status":
                names[name] = raw.get("display_name") or names.get(name) or ""
                if raw.get("status") == "started":
                    runs[name] = {"agent": name, "status": "working", "since": e.get("timestamp"), "steps_done": 0, "current_step": ""}
                elif name in runs:
                    runs[name]["status"] = raw.get("status")
            elif kind == "tool_use" and name in runs:
                runs[name]["steps_done"] += 1
                runs[name]["current_step"] = str(raw.get("tool_name") or "").replace("_", " ")
            elif kind == "artifact" and isinstance(raw.get("artifact"), dict):
                a = raw["artifact"]
                saved.append({"agent": name, "id": a.get("id"), "title": a.get("title"), "kind": a.get("kind"), "rows": a.get("row_count")})
            elif kind == "decision_card" and raw.get("card") == "confirm_spend" and raw.get("answered"):
                spends.append({"credits": raw.get("credits") or 0, "for": raw.get("message") or "", "agent": name,
                               "approved": parse_response("confirm_spend", raw.get("answer")).approved})
            elif raw.get("final") and isinstance(raw.get("content"), str):
                results[name] = raw["content"]

    steps = []
    for i, s in enumerate(plan, 1):
        step = plan_step(i, s)
        agent, status, run = step["agent"], step["status"], runs.get(step["agent"])
        # an agent's own finish counts before the planner's next update catches up
        if run and status not in FINISHED:
            step["status"] = status = {"finished": "completed", "failed": "failed", "working": "in_progress" if running else status}.get(run["status"], status)
        step["agent_name"] = names.get(agent) or step["agent_name"]
        if status in FINISHED and agent in results:
            step["result"] = results[agent][:800]
        steps.append(step)

    working = [{**r, "agent_name": names.get(r["agent"]) or agent_name(r["agent"])} for r in runs.values() if running and r["status"] == "working"]
    for w in working:
        w.pop("status")
    question = question_of(*card_of(pending), context=ask_text, plan=[{k: v for k, v in s.items() if k != "result"} for s in steps]) if pending else None
    completed = sum(s["status"] == "completed" for s in steps)
    failed = sum(s["status"] == "failed" for s in steps)
    upcoming = next((s for s in steps if s["status"] == "pending"), None)
    if not running:
        stage, note = ("done", "Finished") if summary is not None else ("stopped", "Not running: the run ended before a final summary") if task else ("not_started", "")
    elif question:
        stage, note = ("awaiting_plan_approval" if question["kind"] == "plan_approval" else "waiting_for_answer"), question["title"] or question["message"]
    elif working:
        stage, note = "running", "; ".join(f"{w['agent_name']} is working" + (f": {w['current_step']}" if w["current_step"] else "") for w in working)
    elif not steps:
        stage, note = "understanding", "Reading the request and planning which agents to use"
    elif summary is not None or completed + failed == len(steps):
        stage, note = "wrapping_up", "Putting the answer together"
    else:
        stage, note = "running", f"Handing over to {upcoming['agent_name']}" if upcoming else "Working"
    stamps = [e.get("timestamp") for e in task if e.get("timestamp")]
    return {
        "request": request,
        "stage": stage,
        "note": note,
        "running": running,
        "progress": {"total": len(steps), "completed": completed, "failed": failed, "remaining": len(steps) - completed - failed,
                     # finished steps, failed ones included
                     "percent": round(100 * (completed + failed) / len(steps)) if steps else 0},
        "plan": steps,
        "working": working,
        "question": question,
        "credits": {"approved": sum(c["credits"] for c in spends if c["approved"]),
                    "declined": sum(c["credits"] for c in spends if not c["approved"]), "requests": spends},
        "saved": saved,
        "summary": summary,
        "started_at": stamps[0] if stamps else None,
        "updated_at": stamps[-1] if stamps else None,
        "elapsed_seconds": _seconds(stamps[0], now if running else stamps[-1]) if stamps else None,
    }


def next_step(plan_id: str, approved: int, done: Counter) -> dict:
    """What a campaign plan waits on, as the campaign page's buttons would continue it."""
    if done["sent"]:
        return {"action": "watch_replies", "do": "sweep, then handoffs: the replies that need a person, with a drafted answer"}
    if done["drafted"]:
        return {"action": "send", "start_run": f"Use Outreach to send the approved email steps of `{plan_id}`.",
                "note": "The drafts are in Gmail for the user to check. Outreach asks send_approval for the batch before "
                        "anything goes out: answer yes only when the user approved sending."}
    if approved:
        return {"action": "create_drafts", "start_run": f"Use Outreach to create Gmail drafts (do not send) for the approved email steps of `{plan_id}`."}
    return {"action": "approve_steps", "do": f"approve_plan_steps(chat_id, '{plan_id}') if you may approve the copy for "
                                            "the user; otherwise the user approves it on the campaign page"}


async def campaigns(chat_id: str) -> list[dict]:
    """Each campaign plan of a chat: email steps approved, drafted, sent, replied, bounced, and its next step."""
    from src.agent_runtime.tools.artifacts import load_record
    from src.database import list_artifacts

    records, logged = await list_artifacts(chat_id), {}
    payloads = {}
    for r in records:
        if r["kind"] in ("campaign_plan", "send_log"):
            try:
                payloads[r["id"]] = (await load_record(chat_id, r["id"]))[1]
            except FileNotFoundError:
                continue
        if r["kind"] == "send_log" and r["id"] in payloads:
            for row in payloads[r["id"]].get("rows", []):
                logged.setdefault(str(row.get("plan_id")), Counter())[str(row.get("status"))] += 1
    out = []
    for r in records:
        if r["kind"] != "campaign_plan" or r["id"] not in payloads:
            continue
        rows = payloads[r["id"]].get("rows", [])
        approved = sum(x.get("status") == "approved" and x.get("channel") != "call" for x in rows)
        done = logged.get(r["id"], Counter())
        out.append({"plan_id": r["id"], "title": r["title"], "steps": len(rows), "emails_approved": approved,
                    **{k: done[k] for k in ("drafted", "sent", "replied", "bounced")}, "next": next_step(r["id"], approved, done)})
    return out


async def task_status(user_id: str, chat_id: str) -> dict:
    """status_of for one of the user's task chats; ValueError when the user has no such task."""
    from src.configs.datetime_utils import dt
    from src.database import get_chat_repository
    from src.dependencies import get_websocket_manager

    doc = await (await get_chat_repository()).get_chat(user_id, chat_id, "omni")
    if not doc:
        raise ValueError(f"no task {chat_id}")
    manager = await get_websocket_manager()
    ts = {"chat_id": chat_id, **status_of(doc.get("raw_messages") or [], manager.is_running(chat_id),
                                          manager.pending_request(chat_id), dt.now_iso()), "campaigns": await campaigns(chat_id)}
    if ts["stage"] in ("done", "stopped"):  # an ended run's result (contract [15]); the learnings are the ones its end found
        from src.database import load_pref
        from src.services import needs, run_result

        ts["result"] = run_result.envelope(ts, agenda_id=await needs.agenda_of(chat_id), learnings=await load_pref(user_id, f"learnings:{chat_id}") or [],
                                           numbers={"credits_spent": ts["credits"]["approved"]})
    return ts
