"""LLM as judge, as in the "Eval as Product" deck: bundle, score, classify, suggest, gate.

Bundle: one turn's interaction record (routers.admin.turns: request, every step, tool calls with inputs and results, cards
and answers, the answer, the person's feedback) plus its expected answer when Data Axle curated one. Score: the judge model
fills a fixed shape (Judgement) at temperature 0. Classify: severity comes from the ladder in severity(), never from the
model; the root cause is one of a closed set, each naming the artifact to change. Suggest: one concrete fix to that artifact.
Every verdict is stored per judge version and never overwritten, so old conversations can be judged again and versions
compared. Gate: run_suite() replays the planner on every expected answer with a person's prompts and cards; a version
passes when it scores at least as well as the one before and breaks no case that passed.
"""

import asyncio
import hashlib
import json
import re
import uuid
from datetime import date, timedelta
from typing import Literal

from loguru import logger
from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from src.configs.llm_configs_manager import LLMConfigManager

JUDGE_VERSION = "judge-1"  # bump when JUDGE_PROMPT or severity() changes: old verdicts stay under their version

# Closed set of root causes: what each means, and the DAXAGENT artifact an engineer changes for it.
ROOT_CAUSES = {
    "prompt": ("An instruction was ambiguous or missing a rule", "A step's or an agent's prompt, in Settings, Orchestrator"),
    "routing": ("The plan gave work to the wrong agent, or skipped or added one", "An agent card, in Settings, Orchestrator"),
    "tool_call": ("A wrong tool was called, or its parameters were filled wrongly", "The tool's description, or the agent's prompt"),
    "kb_gap": ("The agents lacked knowledge they needed", "Memory, or the agent's prompt"),
    "tool_bug": ("A tool failed or returned an error", "The MCP server or tool"),
    "data_quality": ("The tools worked, but the data itself was wrong or missing", "The source data, e.g. Data Axle"),
    "system": ("The run broke or stopped outside any agent: the orchestrator, a timeout or a lost connection", "DAXAGENT's server, in its logs"),
    "none": ("Nothing failed", ""),
}
SEVERITIES = ["critical", "high", "medium", "low"]  # the ladder, worst first

JUDGE_PROMPT = """You are DAXAGENT's evaluation judge. DAXAGENT is an outbound-sales assistant: an orchestrator plans a task and \
hands parts to agents (Lead Finder, Buyer Finder, Contact Enricher, Campaign Builder, Outreach and others), which call tools \
such as Data Axle search. You read one turn: what the person asked, every numbered step (plans, agent runs, tool calls with \
their inputs and results, approval cards and the person's answers), the final answer, the person's feedback and, when there \
is one, the expected answer curated by Data Axle.

Score from 0 to 4, where 4 is fully right:
- relevancy: the answer addresses what was asked.
- completeness: everything asked for was done, or clearly explained as not possible.
- tool_selection: the right agents and tools were used with the right parameters, none missing and none needless.

State as true or false:
- unsupported_fact: the answer states a number or fact as true that the tool results in the record do not support.
- wrong_tool: a wrong agent or tool was used for a part of the request, or a needed one was not used.
- materially_incomplete: a clear, well-formed request was largely left undone.

Then say where it went wrong:
- root_cause: exactly one of prompt, routing, tool_call, kb_gap, tool_bug, data_quality, system, none.
  prompt = an instruction was ambiguous or missing a rule; routing = the plan gave work to the wrong agent, or skipped or
  added one; tool_call = a wrong tool or wrongly filled parameters; kb_gap = knowledge the agents needed was missing;
  tool_bug = a tool failed or errored; data_quality = tools worked but the data was wrong or missing; system = the run broke
  or stopped outside any agent (the record just ends with no question waiting for the person); none = nothing failed.
- failing_step: the [number] of the first step where it went wrong, or -1 when nothing did.
- rationale: at most two sentences, citing step numbers.
- suggested_fix: one concrete change to the artifact behind the root cause (for example "Buyer Finder's card, Call when: \
also when a request names a job title"), or "" when nothing failed.

Rules:
- Judge only from the record; never assume something happened that is not in it.
- The person declining an approval, skipping a question or choosing a smaller scope is not a failure.
- Masked Data Axle previews before enrichment are expected, not a data problem.
- When an expected answer is given, compare against it; wording differences do not matter, missing or different substance does.
- A turn that stopped while waiting for the person is judged on what was done so far.
- Negative feedback from the person is a strong signal; say in the rationale whether the record explains it."""


class Judgement(BaseModel):
    """What the judge model fills in; severity and the final score are derived from it by rule."""

    relevancy: int = Field(ge=0, le=4)
    completeness: int = Field(ge=0, le=4)
    tool_selection: int = Field(ge=0, le=4)
    unsupported_fact: bool
    wrong_tool: bool
    materially_incomplete: bool
    root_cause: Literal["prompt", "routing", "tool_call", "kb_gap", "tool_bug", "data_quality", "system", "none"]
    failing_step: int
    rationale: str
    suggested_fix: str


def severity(j: Judgement) -> str:
    """The ladder, by rule (deck: severity is assigned by rule, not the judge's discretion)."""
    if j.unsupported_fact:
        return "critical"  # a wrong figure delivered as fact
    if j.wrong_tool or j.materially_incomplete:
        return "high"  # wrong tool called, or a materially incomplete answer to a well-formed question
    if min(j.relevancy, j.completeness, j.tool_selection) < 4:
        return "medium"  # correct but partial
    return "low"  # correct and complete


def _short(value, n: int) -> str:
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[: n - 1] + "…"


def _line(s: dict) -> str:
    kind = s["kind"]
    if kind == "tool":
        return f"tool {s.get('server') or 'built-in'}.{s.get('tool')} input {_short(s.get('input'), 300)} -> {s.get('status') or 'done'}: {_short(s.get('result', ''), 500)}"
    if kind == "run":
        return f"agent {s.get('agent')} {s.get('status')}: {_short(s.get('text', ''), 300)}"
    if kind == "card":
        answer = s.get("answer", "(not answered)")
        return f"card {s.get('card')} '{_short(s.get('text', ''), 200)}', person answered: {_short(answer, 200)}"
    if kind == "step":
        return f"{s.get('who')}: {_short(s.get('text', ''), 1500 if s.get('who') == 'planner_agent' else 400)}"
    if kind == "agent":
        return f"{s.get('who')} says: {_short(s.get('text', ''), 600)}"
    if kind == "user":
        return f"person: {_short(s.get('text', ''), 1000)}"
    if kind == "answer":
        return f"answer to the person: {_short(s.get('text', ''), 3000)}"
    if kind == "artifact":
        return f"saved artifact {s.get('id')}: {_short(s.get('text', ''), 200)} ({s.get('rows') or 0} rows)"
    return f"event: {_short(s.get('text', ''), 200)}"


def bundle(turn: dict, truth: dict | None, keep_head: int = 40, keep_tail: int = 80) -> str:
    """One case for the judge: the turn's record with its steps numbered as the trace numbers them, and its expected answer."""
    lines = [f"[{i}] {_line(s)}" for i, s in enumerate(turn["steps"])]
    if len(lines) > keep_head + keep_tail:  # long tasks: the start (plan) and the end (results, answer) carry the verdict
        lines = lines[:keep_head] + [f"[... {len(lines) - keep_head - keep_tail} steps omitted ...]"] + lines[-keep_tail:]
    parts = [f"REQUEST: {turn.get('request') or '(none)'}", f"STATUS: {turn.get('status')}", "STEPS:", *lines]
    for f in turn.get("feedback") or []:
        parts.append(f"PERSON'S FEEDBACK: rated {f['rating']} of 5{': ' + f['description'] if f.get('description') else ''}")
    if truth:
        parts.append(f"EXPECTED (curated by Data Axle, version {truth['version']}): agents {' > '.join(truth['expected_agents']) or '(any)'}; "
                     f"answer: {truth['expected_answer'] or '(not given)'}")
    return "\n".join(parts)


def _client() -> tuple[AsyncOpenAI, dict]:
    cfg = (LLMConfigManager.get_config("default").get("config_list") or [{}])[0]
    return AsyncOpenAI(api_key=cfg.get("api_key"), base_url=cfg.get("base_url")), cfg


async def judge(turn: dict, truth: dict | None) -> tuple[Judgement, str]:
    """The judge model's verdict on one case, and the model that gave it."""
    client, cfg = _client()
    r = await client.beta.chat.completions.parse(
        model=cfg.get("model"), extra_body=cfg.get("extra_body"), temperature=0, response_format=Judgement,
        messages=[{"role": "system", "content": JUDGE_PROMPT}, {"role": "user", "content": bundle(turn, truth)}])
    return r.choices[0].message.parsed, cfg.get("model") or ""


def verdict(chat_id: str, user_id: str, turn: dict, truth: dict | None, j: Judgement, model: str) -> dict:
    """The stored row: the judge's scores and facts plus what the rules derive from them."""
    return {
        "chat_id": chat_id, "task_id": turn["turn"], "user_id": user_id, "request": (turn.get("request") or "")[:2000],
        "turn_at": turn.get("at") or "", "judge_version": JUDGE_VERSION, "model": model,
        "ground_truth": f"{truth['case_id']}@{truth['version']}" if truth else "",
        "relevancy": j.relevancy, "completeness": j.completeness, "tool_selection": j.tool_selection,
        "final_score": round((j.relevancy + j.completeness + j.tool_selection) / 3, 2),
        "severity": severity(j), "root_cause": j.root_cause,
        "failing_step": j.failing_step if 0 <= j.failing_step < len(turn["steps"]) else -1,
        "rationale": j.rationale, "suggested_fix": j.suggested_fix,
        "facts": {"unsupported_fact": j.unsupported_fact, "wrong_tool": j.wrong_tool, "materially_incomplete": j.materially_incomplete},
    }


def normal(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def truth_for(chat_id: str, turn: dict, truths: list[dict]) -> dict | None:
    """The expected answer for a turn: one saved from this very turn, else one for the same request."""
    same_turn = [t for t in truths if t["source_chat_id"] == chat_id and t["source_task_id"] == turn["turn"]]
    return (same_turn or [t for t in truths if normal(t["request"]) == normal(turn.get("request", ""))] or [None])[0]


# --- the judging job: one at a time per server, progress read by the dashboard ---------------------------------------

job = {"running": False, "what": "", "done": 0, "failed": 0, "total": 0, "error": ""}


def pick_turns(data: dict, chat_id: str | None, days: int, judged: set[tuple[str, str]]) -> list[tuple[str, str, dict]]:
    """The turns to judge: every turn of one conversation, or each not yet judged turn of the last `days` days."""
    from src.routers.admin import conversations, steps, turns

    since = (date.today() - timedelta(days=days)).isoformat()
    feedback = data["feedback"]
    out = []
    for cid, main, messages, chat_mode in conversations(data["chats"]):
        if chat_id and cid != chat_id:
            continue
        for t in turns(steps(messages, chat_mode)):
            if not (t["request"] or t["answer"]):
                continue
            if not chat_id and (str(t["at"])[:10] < since or (cid, t["turn"]) in judged):
                continue
            t["feedback"] = [{"rating": f[3], "description": f[4]} for f in feedback if f[0] == cid and f[1] == t["turn"]]
            out.append((cid, main[1], t))
    return out


async def run_judging(chat_id: str | None = None, days: int = 7) -> None:
    """Judge a conversation, or the last days' unjudged turns; four at a time, each verdict saved as it comes."""
    from src.database import admin_rows, current_truths, latest_evals, list_decisions, save_eval

    job.update(running=True, what=f"conversation {chat_id}" if chat_id else f"last {days} days", done=0, failed=0, total=0, error="")
    try:
        data = await admin_rows(chat_id)
        judged = {(e["chat_id"], e["task_id"]) for e in await latest_evals(JUDGE_VERSION)}
        cases = await asyncio.to_thread(pick_turns, data, chat_id, days, judged)
        for cid in {c[0] for c in cases}:  # what the person answered on each card, as the trace shows it
            answers = {d["id"]: d.get("response") for d in await list_decisions(cid)}
            for c in cases:
                for s in c[2]["steps"] if c[0] == cid else ():
                    if s["kind"] == "card" and s.get("id") in answers:
                        s["answer"] = answers[s["id"]]
        truths = await current_truths()
        job["total"] = len(cases)
        gate = asyncio.Semaphore(4)

        async def one(cid: str, user_id: str, turn: dict) -> None:
            async with gate:
                try:
                    truth = truth_for(cid, turn, truths)
                    j, model = await judge(turn, truth)
                    await save_eval(verdict(cid, user_id, turn, truth, j, model))
                    job["done"] += 1
                except Exception as e:
                    job["failed"] += 1
                    logger.warning(f"[judge] {cid}/{turn['turn']} not judged: {e}")

        await asyncio.gather(*(one(*c) for c in cases))
    except Exception as e:
        job["error"] = str(e)
        logger.exception("[judge] run failed")
    finally:
        job["running"] = False


# --- the gate ---------------------------------------------------------------------------------------------------------

RUNS_PER_CASE = 3  # the same request must get the same plan every time, so each case is planned three times


async def config_of(user_id: str) -> tuple[str, dict]:
    """A short id for what the planner reads (its prompt and the agent cards) and the settings to restore that version."""
    from src.agent_runtime import prefs
    from src.omni import orchestrator

    stages = await orchestrator.stage_prompts(user_id)
    cards = orchestrator.render(await orchestrator.user_cards(user_id))
    version = hashlib.sha1(json.dumps([stages["planner"], cards]).encode()).hexdigest()[:8]
    return version, {k: await prefs.get(user_id, k) for k in ("orchestrator", "agents", "custom_agents")}


async def plan_of(system: str, request: str) -> str:
    """The planner's agent sequence for a request, the way a task starts (intake already done)."""
    from src.omni.response_format import PlannerResponse

    client, cfg = _client()
    r = await client.beta.chat.completions.parse(
        model=cfg.get("model"), extra_body=cfg.get("extra_body"), temperature=0, response_format=PlannerResponse,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": request},
                  {"role": "assistant", "name": "clarifier", "content": json.dumps({"needs_input": False, "intro": "Specific enough to plan.", "questions": []})}])
    return " > ".join(t.capability for t in r.choices[0].message.parsed.breakdown)


def gate(run: dict, previous: dict | None) -> dict:
    """Pass when this version scores at least as well as the one before and breaks no case that passed there."""
    if previous is None:
        return {"passes": True, "first": True, "regressions": []}
    before = {r["case_id"] for r in previous["results"] if r["passed"]}
    regressions = [r["request"] for r in run["results"] if r["case_id"] in before and not r["passed"]]
    return {"passes": run["score"] >= previous["score"] and not regressions, "first": False, "regressions": regressions,
            "previous_score": previous["score"], "previous_version": previous["config_version"]}


async def run_suite(user_id: str) -> None:
    """Replay the planner on every expected answer that names its agents, with this person's prompts and cards; save the run."""
    from src.database import current_truths, save_suite_run
    from src.omni import orchestrator

    job.update(running=True, what="the prompt check", done=0, failed=0, total=0, error="")
    try:
        cases = [t for t in await current_truths() if t["expected_agents"]]
        version, config = await config_of(user_id)
        system = await orchestrator.planner_prompt(user_id)
        job["total"] = len(cases) * RUNS_PER_CASE
        gate_ = asyncio.Semaphore(6)

        async def plan(request: str) -> str:
            async with gate_:
                try:
                    return await plan_of(system, request)
                except Exception as e:
                    job["failed"] += 1
                    return f"(planner failed: {e})"
                finally:
                    job["done"] += 1

        results = []
        for case, plans in zip(cases, await asyncio.gather(*(asyncio.gather(*(plan(c["request"]) for _ in range(RUNS_PER_CASE))) for c in cases))):
            expected = " > ".join(case["expected_agents"])
            results.append({"case_id": case["case_id"], "version": case["version"], "request": case["request"], "expected": expected,
                            "plans": list(plans), "passed": all(p == expected for p in plans)})
        passed = sum(r["passed"] for r in results)
        await save_suite_run({"user_id": user_id, "config_version": version, "config": config, "cases": len(results), "passed": passed,
                              "score": round(passed / len(results), 4) if results else 0.0, "results": results})
    except Exception as e:
        job["error"] = str(e)
        logger.exception("[judge] prompt check failed")
    finally:
        job["running"] = False


def new_case_id() -> str:
    return "case-" + uuid.uuid4().hex[:8]
