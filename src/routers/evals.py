"""LLM as judge for the admin dashboard (Evaluation tab): judge turns, the triage queue, expected answers and the gate.

Admins only, like the rest of /admin. Judging and the prompt check run in the background, one at a time; the dashboard
reads their progress from /job. See src/judge.py for how a turn is judged and how the gate decides.
"""

import asyncio
import re
from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from src import judge
from src.agent_runtime import prefs
from src.database import add_truth_version, admin_rows, current_truths, latest_evals, suite_runs
from src.routers.admin import _admin

router = APIRouter()
QUERY_CLASSES = ("lookup", "enrichment", "campaign", "analysis", "other")


def _start(work) -> dict:
    if judge.job["running"]:
        raise HTTPException(status_code=409, detail=f"Already working on {judge.job['what']}; wait for it to finish")
    judge.job.update(running=True)  # taken before the task starts, so two clicks cannot both start one
    asyncio.create_task(work)
    return judge.job


class JudgeRequest(BaseModel):
    chat_id: str | None = None  # one conversation, every turn; otherwise the last `days` days' unjudged turns
    days: int = Field(7, ge=1, le=90)


@router.post("/judge")
async def start_judging(body: JudgeRequest, user_id: str = "local_user") -> dict:
    _admin(user_id)
    return _start(judge.run_judging(body.chat_id, body.days))


@router.get("/job")
async def job_status(user_id: str = "local_user") -> dict:
    _admin(user_id)
    return judge.job


def health(evals: list[dict], days: int = 7) -> dict:
    """The deck's home screen: high-severity count, accuracy, tool selection and completeness over the last days."""
    since = (date.today() - timedelta(days=days)).isoformat()
    recent = [e for e in evals if str(e["turn_at"])[:10] >= since]
    n = len(recent)
    avg = lambda key: round(sum(e[key] for e in recent) / n, 2) if n else None
    return {
        "days": days, "judged": n,
        "high_severity": sum(1 for e in recent if e["severity"] in ("critical", "high")),
        "accuracy": round(sum(1 for e in recent if e["severity"] == "low") / n, 4) if n else None,
        "tool_selection": avg("tool_selection"), "completeness": avg("completeness"), "relevancy": avg("relevancy"),
        "by_severity": {s: sum(1 for e in recent if e["severity"] == s) for s in judge.SEVERITIES},
        "by_root_cause": {r: sum(1 for e in recent if e["root_cause"] == r) for r in judge.ROOT_CAUSES if r != "none"},
    }


@router.get("")
async def evaluation(user_id: str = "local_user") -> dict:
    """Everything the Evaluation tab shows: health, the triage queue (worst first), expected answers and the gate."""
    _admin(user_id)
    evals = await latest_evals(judge.JUDGE_VERSION)
    rank = {s: i for i, s in enumerate(judge.SEVERITIES)}
    queue = sorted(evals, key=lambda e: str(e["turn_at"]), reverse=True)
    queue.sort(key=lambda e: rank.get(e["severity"], 9))
    runs = await suite_runs(user_id)
    latest = runs[0] if runs else None
    previous = next((r for r in runs[1:] if latest and r["config_version"] != latest["config_version"]), None)
    current, _ = await judge.config_of(user_id)
    data = await admin_rows()
    unjudged = len(await asyncio.to_thread(judge.pick_turns, data, None, 7, {(e["chat_id"], e["task_id"]) for e in evals}))
    return {
        "judge_version": judge.JUDGE_VERSION, "job": judge.job, "health": {**health(evals), "unjudged": unjudged},
        "root_causes": {k: {"means": v[0], "artifact": v[1]} for k, v in judge.ROOT_CAUSES.items()},
        "queue": queue[:500],
        "truths": await current_truths(),
        "suite": {"latest": latest, "previous": previous, "gate": judge.gate(latest, previous) if latest else None, "current_version": current,
                  "history": [{k: r[k] for k in ("id", "config_version", "cases", "passed", "score", "created_at")} for r in runs[:10]]},
    }


@router.get("/chat/{chat_id}")
async def chat_evaluation(chat_id: str, user_id: str = "local_user") -> dict:
    """One conversation's verdicts and expected answers, by turn, for its trace page."""
    _admin(user_id)
    from src.routers.admin import conversations, steps, turns

    truths = await current_truths()
    data = await admin_rows(chat_id)
    by_turn = {}
    for _, _, messages, chat_mode in conversations(data["chats"]):
        for t in turns(steps(messages, chat_mode)):
            if truth := judge.truth_for(chat_id, t, truths):
                by_turn[t["turn"]] = truth
    evals = await latest_evals(judge.JUDGE_VERSION, chat_id)
    return {"results": {e["task_id"]: e for e in evals}, "truths": by_turn,
            "root_causes": {k: {"means": v[0], "artifact": v[1]} for k, v in judge.ROOT_CAUSES.items()}}


class TruthIn(BaseModel):
    """An expected answer, curated by an admin; saving one that exists adds a version."""

    case_id: str | None = None
    request: str = Field(min_length=1, max_length=4000)
    expected_agents: list[str] = Field(default_factory=list, max_length=20)  # the plan, in order; empty = any
    expected_answer: str = Field(default="", max_length=8000)
    query_class: Literal[QUERY_CLASSES] = "other"  # type: ignore[valid-type]
    source_chat_id: str = Field(default="", max_length=100)
    source_task_id: str = Field(default="", max_length=100)

    @field_validator("expected_agents")
    @classmethod
    def _names(cls, agents: list[str]) -> list[str]:
        bad = [a for a in agents if not re.fullmatch(r"[a-z0-9_]{1,80}", a)]
        if bad:
            raise ValueError(f"Not agent names: {', '.join(bad)}")
        return agents


@router.post("/truths")
async def save_truth(body: TruthIn, user_id: str = "local_user") -> dict:
    _admin(user_id)
    if body.case_id and body.case_id not in {t["case_id"] for t in await current_truths(include_retired=True)}:
        raise HTTPException(status_code=404, detail="No such expected answer")
    return await add_truth_version({**body.model_dump(), "case_id": body.case_id or judge.new_case_id(), "author": user_id, "retired": 0})


@router.post("/truths/{case_id}/retire")
async def retire_truth(case_id: str, user_id: str = "local_user") -> dict:
    _admin(user_id)
    case = next((t for t in await current_truths() if t["case_id"] == case_id), None)
    if case is None:
        raise HTTPException(status_code=404, detail="No such expected answer")
    keep = ("case_id", "request", "expected_agents", "expected_answer", "query_class", "source_chat_id", "source_task_id")
    return await add_truth_version({**{k: case[k] for k in keep}, "author": user_id, "retired": 1})


@router.post("/suite")
async def start_suite(user_id: str = "local_user") -> dict:
    """The gate: replay the planner on every expected answer with this admin's own prompts and cards."""
    _admin(user_id)
    if not any(t["expected_agents"] for t in await current_truths()):
        raise HTTPException(status_code=400, detail="Save at least one expected answer with its agents first")
    return _start(judge.run_suite(user_id))


@router.post("/suite/{run_id}/restore")
async def restore_version(run_id: int, user_id: str = "local_user") -> dict:
    """Put back the prompts, cards and own agents a past check ran with."""
    _admin(user_id)
    run = next((r for r in await suite_runs(user_id, limit=200) if r["id"] == run_id), None)
    if run is None:
        raise HTTPException(status_code=404, detail="No such check")
    for key, value in run["config"].items():
        await prefs.put(user_id, key, value)
    return {"restored": run["config_version"]}
