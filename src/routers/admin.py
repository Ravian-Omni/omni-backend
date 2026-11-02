"""Admin dashboard (#/admin): who asked what, every turn traced step by step, feedback, models and tokens.

Admins only (auth.is_admin). Everything comes from the conversations' own history (chats.raw_messages), which keeps the
whole interaction rather than the final answer: the request, the orchestrator's steps, each agent run, every tool call
with its input and result, the answer and the tokens. One turn (task_id) is one interaction record: request, steps,
tool calls, answer and the person's feedback. An LLM judge can later score these same records, old ones included.
"""

import ast
import asyncio
import json
from collections import Counter, defaultdict
from datetime import date, timedelta

from fastapi import APIRouter, HTTPException

from src import auth
from src.agent_runtime.tools.context import server_of
from src.database import admin_rows, list_decisions

router = APIRouter()

HUMAN = {"chat_manager", "get_user_acceptance", "user_form", "user_input"}  # what the person typed or answered in a task
ANSWERS = {"process_completion_agent", "conversation_agent", "chat_agent"}  # a turn's reply to the person
ORCHESTRATOR = {"judge_question", "clarifier", "planner_agent", "agent_aligner", "agent_router", "agent_caller",
                "agent_executor", "manual_verification", "user"}  # in a task, "user" is the orchestrator's brief to an agent


def _text(raw) -> str:
    """Readable text of one stored message: a string, a chat message, a model's tool calls or the tools' replies."""
    if isinstance(raw, str):
        return raw
    if not isinstance(raw, dict):
        return ""
    if content := raw.get("content"):
        return content if isinstance(content, str) else json.dumps(content, default=str)
    if calls := raw.get("tool_calls"):
        return "\n".join(f"{(c.get('function') or {}).get('name')}({(c.get('function') or {}).get('arguments', '')})" for c in calls)
    return "\n".join(str(r.get("content", "")) for r in raw.get("tool_responses") or [])


def _request(text: str) -> str:
    """A task's opening message is stored as "{'task': ..., 'files': [...]}"."""
    if text.startswith("{'task'"):
        try:
            return str(ast.literal_eval(text).get("task", text))
        except Exception:  # not a literal after all: show it as stored
            pass
    return text


def merged(main: list[dict], runs: list[list[dict]]) -> list[dict]:
    """A task's history plus any agent run kept only in its own row (runs from before they were mirrored into the
    task), in time order."""
    if not runs:
        return main
    sig = lambda m: json.dumps(m.get("raw_message"), sort_keys=True, default=str)  # noqa: E731
    seen = {sig(m) for m in main}
    extra = [m for run in runs if run and not any(sig(m) in seen for m in run) for m in run]
    return sorted(main + extra, key=lambda m: m.get("timestamp") or "") if extra else main


def steps(messages: list[dict], chat_mode: bool) -> list[dict]:
    """One readable step per stored message, in order: a tool's result is folded into its call, and each model call's
    tokens and model are put on its step."""
    out: list[dict] = []
    calls: dict[str, dict] = {}
    model_of: dict[str, str] = {}  # agent -> model, from its run's finish line (the OpenAI runner names it)
    running: dict[str, tuple[int, int]] = {}  # chat mode, old records: agent -> its connection's running total
    for m in messages:
        who, raw, usage = m.get("name") or "", m.get("raw_message"), m.get("usage") or {}
        kind = raw.get("type") if isinstance(raw, dict) else None
        if kind == "tool_result" and raw.get("tool_use_id") in calls:
            calls[raw["tool_use_id"]].update(status=raw.get("status"), result=raw.get("content", ""))
            continue
        step: dict = {"at": m.get("timestamp") or "", "turn": m.get("task_id") or "", "who": who}
        if kind in ("tool_use", "tool_result"):  # a result whose call was not kept still counts as a call
            name = raw.get("tool_full_name") or raw.get("tool_name") or ""
            server = server_of(name)
            step.update(kind="tool", tool=raw.get("tool_name") or name, server=None if server == "daxagent" else server,
                        input=raw.get("tool_input"), status=raw.get("status"), tool_class=raw.get("tool_class"))
            if kind == "tool_result":
                step["result"] = raw.get("content", "")
            calls[raw.get("tool_use_id") or f"#{len(out)}"] = step
        elif kind == "agent_status":
            model_of[who] = raw.get("model") or model_of.get(who, "")
            step.update(kind="run", status=raw.get("status"), agent=raw.get("display_name") or raw.get("persona") or who,
                        text=raw.get("task") or "", duration_ms=raw.get("duration_ms"), tools_called=raw.get("tools_called"))
        elif kind == "decision_card":
            step.update(kind="card", id=raw.get("id"), card=raw.get("card"), text=raw.get("title") or raw.get("message") or "")
        elif kind == "artifact":
            a = raw.get("artifact") or {}
            step.update(kind="artifact", id=a.get("id"), text=a.get("title") or "", rows=a.get("row_count"))
        elif kind == "user_note":
            step.update(kind="user", text=_text(raw))
        elif kind:  # handoff, task_suggestion, ...
            step.update(kind="event", text=kind.replace("_", " "))
        else:
            text = _text(raw)
            final = isinstance(raw, dict) and bool(raw.get("final"))
            plumbing = isinstance(raw, dict) and bool(raw.get("tool_calls") or raw.get("tool_responses"))
            if final:  # an agent's final message repeats the last thing it said: keep it once
                prev = next((x for x in reversed(out) if x["kind"] == "agent" and x["who"] == who), None)
                if prev is not None and prev["turn"] == step["turn"] and prev["text"].strip() == text.strip():
                    out.remove(prev)
            if who in HUMAN or (who == "user" and chat_mode):
                step.update(kind="user", text=_request(text) if who == "chat_manager" else text)
            elif not plumbing and (who in ANSWERS or (final and chat_mode)):
                step.update(kind="answer", text=text)
            elif plumbing or who in ORCHESTRATOR:
                step.update(kind="step", text=text)
            else:  # an agent's narration, or in a task its report back to the orchestrator
                step.update(kind="agent", text=text, final=final)
        delta = usage.get("message_delta") or {}
        if delta.get("total_tokens"):  # an orchestrator (AutoGen) model call
            step.update(model=(usage.get("current_total") or {}).get("model") or "unknown",
                        prompt_tokens=int(delta.get("prompt_tokens") or 0), completion_tokens=int(delta.get("completion_tokens") or 0))
        elif usage.get("total_tokens"):  # an agent run: on its finish line (per_run) since 2026-10-29, on its final message before
            p, c = int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0)
            if chat_mode and not usage.get("per_run"):
                # shortcut: old chat records hold the connection's running total, so a drop marks a new connection; a new
                # connection whose first turn outgrows the last total reads as a continuation (undercount). Exact once per_run.
                last_p, last_c = running.get(who, (0, 0))
                running[who] = (p, c)
                if p >= last_p and c >= last_c:
                    p, c = p - last_p, c - last_c
            step.update(model=usage.get("model") or model_of.get(who) or ("claude" if usage.get("cost_usd") else "unknown"),
                        prompt_tokens=p, completion_tokens=c)
        if "prompt_tokens" in step:
            step["tokens"] = step["prompt_tokens"] + step["completion_tokens"]
        out.append(step)
    return out


def counts(steps_: list[dict]) -> dict:
    """Tool calls, MCP calls, tokens and models over some steps."""
    tools = [s for s in steps_ if s["kind"] == "tool"]
    models: Counter = Counter()
    for s in steps_:
        if s.get("model"):
            models[s["model"]] += s.get("tokens", 0)
    return {
        "tool_calls": len(tools), "mcp_calls": sum(1 for s in tools if s["server"]),
        "servers": sorted({s["server"] for s in tools if s["server"]}),
        "agents": sorted({s["agent"] for s in steps_ if s["kind"] == "run"}),
        "tokens": sum(s.get("tokens", 0) for s in steps_), "models": dict(models),
    }


def turns(steps_: list[dict]) -> list[dict]:
    """A conversation's steps grouped into turns, one per task_id in order of first appearance: the interaction records."""
    by: dict[str, dict] = {}
    for s in steps_:
        t = by.setdefault(s["turn"], {"turn": s["turn"], "at": s["at"], "request": "", "answer": "", "steps": []})
        t["steps"].append(s)
        if s["kind"] == "user" and not t["request"]:
            t["request"] = s["text"]
        elif s["kind"] == "answer":
            t["answer"] = s["text"]
    for t in by.values():
        failed = any(s["kind"] == "run" and s.get("status") == "failed" for s in t["steps"])
        t.update(ended=t["steps"][-1]["at"], status="failed" if failed else "answered" if t["answer"] else "unanswered", **counts(t["steps"]))
    return list(by.values())


def conversations(chat_rows: list[tuple]):
    """(chat_id, its task or chat row, its messages, chat mode?) for every conversation with something in it."""
    grouped: dict[str, list[tuple]] = defaultdict(list)
    for row in chat_rows:
        grouped[row[0]].append(row)
    for chat_id, rows in grouped.items():
        main = next((r for r in rows if r[2] in ("omni", "chats")), None)
        if main is None:  # an agent run started on its own (test harness), not a conversation
            continue
        try:
            messages = merged(json.loads(main[5] or "[]"), [json.loads(r[5] or "[]") for r in rows if r is not main])
        except ValueError:
            continue
        if messages:
            yield chat_id, main, messages, main[2] == "chats"


def _feedback(row: tuple) -> dict:
    chat_id, task_id, user_id, rating, description, created_at = row
    return {"chat_id": chat_id, "task_id": task_id, "user_id": user_id, "rating": rating, "description": description, "created_at": created_at}


def _summary(chat_id: str, main: tuple, chat_mode: bool, trs: list[dict], fb: list[dict], hidden: bool, artifacts: int) -> dict:
    all_steps = [s for t in trs for s in t["steps"]]
    ratings = [f["rating"] for f in fb]
    return {
        "chat_id": chat_id, "user_id": main[1], "mode": "chat" if chat_mode else "task",
        "title": next((t["request"] for t in trs if t["request"]), "")[:300],
        "created_at": main[3], "updated_at": main[4], "hidden": hidden,
        "turns": len(trs), "requests": sum(1 for s in all_steps if s["kind"] == "user"), "steps": len(all_steps),
        "failed": sum(1 for t in trs if t["status"] == "failed"), "unanswered": sum(1 for t in trs if t["status"] == "unanswered"),
        "artifacts": artifacts, "feedback": len(fb), "rating": round(sum(ratings) / len(ratings), 2) if ratings else None,
        **counts(all_steps),
    }


def overview(data: dict, today: date) -> dict:
    """Totals, people, daily activity, agents, MCP servers, tools, models, every conversation and all feedback."""
    labels = {r[0]: {"email": r[1], "name": r[2], "first_seen": r[3], "last_seen": r[4]} for r in data["accounts"]}
    hidden = {r[0] for r in data["hidden"]}
    artifacts = Counter(r[0] for r in data["artifacts"])
    feedback = [_feedback(r) for r in data["feedback"]]
    fb_of: dict[str, list[dict]] = defaultdict(list)
    for f in feedback:
        fb_of[f["chat_id"]].append(f)
    days = {(today - timedelta(days=i)).isoformat(): {"conversations": 0, "requests": 0, "tokens": 0} for i in range(29, -1, -1)}
    day_tools: dict[str, Counter] = defaultdict(Counter)  # day -> MCP server ("" = built-in tools) -> calls
    users: dict[str, Counter] = defaultdict(Counter)
    seen_at: dict[str, list[str]] = defaultdict(list)
    agents: dict[str, Counter] = defaultdict(Counter)
    agent_names: dict[str, str] = {}
    servers: dict[str, Counter] = defaultdict(Counter)
    tools: Counter = Counter()
    models: dict[str, Counter] = defaultdict(Counter)
    requests_of: dict[tuple, str] = {}
    convs = []
    for chat_id, main, messages, chat_mode in conversations(data["chats"]):
        trs = turns(steps(messages, chat_mode))
        c = _summary(chat_id, main, chat_mode, trs, fb_of[chat_id], chat_id in hidden, artifacts[chat_id])
        convs.append(c)
        u = users[c["user_id"]]
        u.update(conversations=1, tasks=int(c["mode"] == "task"), chats=int(c["mode"] == "chat"), requests=c["requests"], turns=c["turns"],
                 tool_calls=c["tool_calls"], mcp_calls=c["mcp_calls"], tokens=c["tokens"], failed=c["failed"])
        seen_at[c["user_id"]] += [str(main[3]).replace(" ", "T"), str(main[4]).replace(" ", "T")]
        if (day := str(main[3])[:10]) in days:
            days[day]["conversations"] += 1
        for t in trs:
            requests_of[(chat_id, t["turn"])] = t["request"]
            if (day := str(t["at"])[:10]) in days:
                days[day]["requests"] += sum(1 for s in t["steps"] if s["kind"] == "user")
                days[day]["tokens"] += t["tokens"]
            for s in t["steps"]:
                if s["kind"] == "run" and s.get("status") != "started":
                    agent_names[s["who"]] = s["agent"]
                    agents[s["who"]].update(runs=1, failed=int(s.get("status") == "failed"), ms=s.get("duration_ms") or 0)
                elif s["kind"] == "tool":
                    tools[f"{s['server'] or 'built-in'} · {s['tool']}"] += 1
                    if (day := str(s["at"] or t["at"])[:10]) in days:
                        day_tools[day][s["server"] or ""] += 1
                    if s["server"]:
                        servers[s["server"]].update(calls=1, failed=int(s.get("status") == "failed"))
                if s.get("tokens"):
                    agents[s["who"]].update(tokens=s["tokens"], model_calls=1)
                    models[s["model"]].update(prompt=s["prompt_tokens"], completion=s["completion_tokens"], calls=1)
    for f in feedback:
        f["request"] = requests_of.get((f["chat_id"], f["task_id"]), "")
        users[f["user_id"]].update(feedback=1, rating_sum=f["rating"])
    for uid in labels:
        users[uid].update()  # people who signed in but never asked anything are users too
    week_ago = (today - timedelta(days=7)).isoformat()
    people = []
    for uid, u in users.items():
        label = labels.get(uid, {})
        seen = seen_at[uid] + [v for v in (label.get("first_seen"), label.get("last_seen")) if v]
        people.append({"user_id": uid, "email": label.get("email") or (uid if "@" in uid else ""), "name": label.get("name", ""),
                       "first_seen": min(seen, default=""), "last_active": max(seen, default=""),
                       **{k: v for k, v in u.items() if k != "rating_sum"},
                       "rating": round(u["rating_sum"] / u["feedback"], 2) if u["feedback"] else None})
    ratings = [f["rating"] for f in feedback]
    tool_rows = [{"tool": k, "calls": v} for k, v in tools.most_common(25)]
    return {
        "totals": {
            "users": len(people), "active_7d": sum(1 for p in people if p["last_active"] >= week_ago),
            "conversations": len(convs), "tasks": sum(1 for c in convs if c["mode"] == "task"), "chats": sum(1 for c in convs if c["mode"] == "chat"),
            "requests": sum(c["requests"] for c in convs), "turns": sum(c["turns"] for c in convs), "steps": sum(c["steps"] for c in convs),
            "agent_runs": sum(a["runs"] for a in agents.values()), "failed_runs": sum(a["failed"] for a in agents.values()),
            "tool_calls": sum(c["tool_calls"] for c in convs), "mcp_calls": sum(c["mcp_calls"] for c in convs), "mcp_servers": len(servers),
            "tokens": sum(c["tokens"] for c in convs), "artifacts": len(data["artifacts"]),
            "feedback": len(feedback), "rating": round(sum(ratings) / len(ratings), 2) if ratings else None,
            "positive": sum(1 for r in ratings if r >= 4), "negative": sum(1 for r in ratings if r <= 2),
        },
        **tool_days(days, day_tools),
        "users": sorted(people, key=lambda p: p["last_active"], reverse=True),
        "agents": sorted(({"agent": agent_names.get(k, k), "name": k, **v} for k, v in agents.items()), key=lambda a: -a["tokens"]),
        "servers": sorted(({"server": k, **v} for k, v in servers.items()), key=lambda s: -s["calls"]),
        "tools": tool_rows,
        "models": sorted(({"model": k, **v, "tokens": v["prompt"] + v["completion"]} for k, v in models.items()), key=lambda m: -m["tokens"]),
        "conversations": sorted(convs, key=lambda c: str(c["updated_at"]).replace(" ", "T"), reverse=True),
        "feedback": sorted(feedback, key=lambda f: f["created_at"], reverse=True),
    }


def tool_days(days: dict, day_tools: dict[str, Counter], most: int = 7) -> dict:
    """Each day's tool calls by MCP server, for the stacked chart: the busiest servers by name, the rest together,
    and built-in tools last. `tool_series` orders the groups so each keeps its colour."""
    from src.mcp_client import options

    totals = Counter()
    for counts_ in day_tools.values():
        totals.update({k: v for k, v in counts_.items() if k})
    top = [k for k, _ in totals.most_common(most)]
    # a server since removed has no display name left: "knightwatch" reads "Knightwatch"
    label = lambda server: options(server).get("display_name") or server.replace("-", " ").title() if server in top else "Other MCP servers"
    series = [label(k) for k in top] + (["Other MCP servers"] if len(totals) > most else []) + (["Built-in tools"] if any(c[""] for c in day_tools.values()) else [])
    out = []
    for d, v in days.items():
        by = Counter()
        for server, n in day_tools.get(d, {}).items():
            by["Built-in tools" if not server else label(server)] += n
        out.append({"day": d, **v, "tool_calls": sum(by.values()), "tools": dict(by)})
    return {"days": out, "tool_series": series}


def detail(data: dict, decisions: list[dict]) -> dict | None:
    """One conversation turn by turn, each with its steps, card answers and feedback."""
    for chat_id, main, messages, chat_mode in conversations(data["chats"]):
        trs = turns(steps(messages, chat_mode))
        answers = {d["id"]: d.get("response") for d in decisions}
        feedback = [_feedback(r) for r in data["feedback"]]
        for t in trs:
            t["feedback"] = [f for f in feedback if f["task_id"] == t["turn"]]
            for s in t["steps"]:
                if s["kind"] == "card" and s.get("id") in answers:
                    s["answer"] = answers[s["id"]]
        labels = {r[0]: {"email": r[1], "name": r[2]} for r in data["accounts"]}
        return {
            "conversation": _summary(chat_id, main, chat_mode, trs, feedback, chat_id in {r[0] for r in data["hidden"]}, len(data["artifacts"])),
            "user": labels.get(main[1], {"email": main[1] if "@" in main[1] else "", "name": ""}),
            "turns": trs, "feedback": feedback,
            "artifacts": [{"task_id": r[1], "kind": r[2], "title": r[3], "rows": r[4]} for r in data["artifacts"]],
        }
    return None


def _admin(user_id: str) -> None:
    if not auth.is_admin(user_id):
        raise HTTPException(status_code=403, detail="Admins only")


@router.get("/me")
async def am_i_admin(user_id: str = "local_user") -> dict:
    return {"admin": auth.is_admin(user_id)}


@router.get("/overview")
async def get_overview(user_id: str = "local_user") -> dict:
    _admin(user_id)
    data = await admin_rows()
    return await asyncio.to_thread(overview, data, date.today())  # parsing every history is CPU work: off the event loop


@router.get("/chats/{chat_id}")
async def get_chat(chat_id: str, user_id: str = "local_user") -> dict:
    _admin(user_id)
    data = await admin_rows(chat_id)
    result = await asyncio.to_thread(detail, data, await list_decisions(chat_id))
    if result is None:
        raise HTTPException(status_code=404, detail="No such conversation")
    return result
