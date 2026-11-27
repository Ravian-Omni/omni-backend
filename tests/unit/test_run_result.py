"""The update envelope of contract [15]: one `result` on every run that ends for Brain_Hands, set by code."""

import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from src.routers import hands_mcp as hm
from src.services import run_result
from tests.unit.test_leads import thread

GOAL = 'SIGNAL PLAY: {"company": "Osaic", "date": "2026-11-14", "url": "https://x.co/a", "website": "osaic.com"}'
PLAN = [{"step": 1, "agent": "signal_play", "agent_name": "Signal Play", "task": "Find the buyer at Osaic and draft the opener",
         "details": "a first email that cites the signal", "status": "completed"}]
SAVED = [{"agent": "signal_play", "id": "campaign_plan-1", "title": "Osaic opener", "kind": "campaign_plan", "rows": 3}]
CAMPAIGN = [{"plan_id": "campaign_plan-1", "next": {"action": "approve_steps"}}]


def ts(**kw):
    return {"chat_id": "chat-1", "request": GOAL, "stage": "done", "plan": PLAN, "saved": SAVED, "campaigns": CAMPAIGN,
            "summary": "Drafted a 3-step sequence for Jane Doe at Osaic. The opener cites the appointment. Approve it on the campaign page. Extra.",
            "started_at": "2026-11-16T10:00:00+00:00", "updated_at": "2026-11-16T10:05:00+00:00", **kw}


def test_a_finished_play_is_completed_and_says_the_user_approves_the_plan_next():
    r = run_result.envelope(ts(), key="run-7", agenda_id="agd_1", numbers={"credits_spent": 3, "leads": {"passed": 1}})
    assert {k: r[k] for k in ("v", "in_reply_to", "type", "app", "agent", "task_id", "agenda_id", "status", "retryable")} == {
        "v": 1, "in_reply_to": "run-7", "type": "result", "app": "daxagent", "agent": "Signal Play", "task_id": "chat-1",
        "agenda_id": "agd_1", "status": "completed", "retryable": False}
    assert "reason" not in r and r["about"] == {"company": "Osaic", "website": "osaic.com"}
    assert r["summary"].endswith("Approve it on the campaign page.")  # three sentences
    assert r["steps"] == [{"n": 1, "agent": "Signal Play", "did": "Find the buyer at Osaic and draft the opener",
                           "to_achieve": "a first email that cites the signal", "status": "completed"}]
    assert r["outputs"] == [{"kind": "campaign_plan", "id": "campaign_plan-1", "title": "Osaic opener"}]
    assert r["numbers"] == {"leads": {"passed": 1}, "credits_spent": 3}
    assert r["next"] == {"who": "user", "action": "approve the steps of the campaign plan", "ref": "campaign_plan-1"}
    assert (r["started_at"], r["ended_at"]) == ("2026-11-16T10:00:00+00:00", "2026-11-16T10:05:00+00:00")


@pytest.mark.parametrize("state, numbers, error, cancelled, expect", [
    (ts(summary="SIGNAL PLAY rejected: no contact passed (2 email not verified: catch_all)"), {}, "", False,
     ("rejected", "no contact passed (2 email not verified: catch_all)", False, "none")),
    (ts(summary="RECOVERY NOTE ready: no note, they asked not to be contacted."), {}, "", False,
     ("rejected", "they asked not to be contacted.", False, "none")),
    (ts(), {"leads": {"stopped_because": "budget_used_up"}}, "", False, ("partial", "lead sourcing stopped: budget used up", False, "user")),
    (ts(plan=[*PLAN, {**PLAN[0], "step": 2, "status": "failed"}]), {}, "", False, ("partial", "1 of 2 plan steps did not complete", False, "user")),
    (ts(), {}, "Request timed out", False, ("failed", "Request timed out", True, "brain_hands")),
    (ts(), {}, "KeyError: 'rows'", False, ("failed", "KeyError: 'rows'", False, "user")),
    (ts(), {}, "", True, ("stopped", "stopped before it finished", False, "none")),
    (ts(stage="stopped", summary=None), {}, "", False, ("stopped", "the run ended without an answer (lost, e.g. on a restart)", True, "brain_hands")),
])
def test_each_status_with_its_reason_retry_and_who_acts(state, numbers, error, cancelled, expect):
    r = run_result.envelope(state, numbers=numbers, error=error, cancelled=cancelled)
    assert (r["status"], r.get("reason"), r["retryable"], r["next"]["who"]) == expect


def test_about_is_left_out_for_a_plain_request_and_kept_for_a_meeting_prep():
    assert "about" not in run_result.envelope(ts(request="Find 20 dentists in Austin"))
    r = run_result.envelope(ts(request='MEETING PREP: {"email": "ana@acme.com", "company": "Acme"}', saved=[{"kind": "meeting_brief", "id": "mb-1", "title": "Brief"}]))
    assert r["about"] == {"company": "Acme", "email": "ana@acme.com"}
    assert r["next"] == {"who": "user", "action": "read the meeting brief before the meeting", "ref": "mb-1"}


def run_thread(monkeypatch, events, state):
    monkeypatch.setattr(hm.status, "task_status", AsyncMock(return_value=state))
    monkeypatch.setattr(hm.run_result, "learnings", AsyncMock(return_value=["Data Axle had no buyer at Osaic."]))
    monkeypatch.setattr(hm, "save_pref", AsyncMock())
    monkeypatch.setattr(hm.leads, "tally", AsyncMock(return_value={"passed": 1, "seen": 1, "failed": {}}))
    monkeypatch.setattr(hm, "credits_spent", AsyncMock(return_value=2))
    ended = []
    monkeypatch.setattr(hm, "_run_ended", ended.append)
    t = thread(target=0)
    t.key, t.request = "run-7", GOAL

    async def go():
        for e in events:
            await t.send_json(e)

    asyncio.run(go())
    return [t.queue.get_nowait() for _ in range(t.queue.qsize())], ended


def test_the_completion_event_carries_the_result_beside_its_fields(monkeypatch):
    out, ended = run_thread(monkeypatch, [{"type": "completion", "status": "complete"}], ts())
    (done,) = out
    assert done["credits_spent"] == 2 and done["leads"]["passed"] == 1  # nothing removed
    assert done["result"]["status"] == "completed" and done["result"]["in_reply_to"] == "run-7"
    assert done["result"]["numbers"]["credits_spent"] == 2 and done["result"]["learnings"] == ["Data Axle had no buyer at Osaic."]
    assert ended == ["chat-1"]


def test_a_run_that_fails_ends_with_a_failed_result_and_frees_its_chat(monkeypatch):
    error = {"type": "error", "error_code": hm.FAILED_RUN, "message": "Connection reset by peer"}
    out, ended = run_thread(monkeypatch, [error], ts(summary=None))
    assert out[0]["result"]["status"] == "failed" and out[0]["result"]["retryable"] and ended == ["chat-1"]
    out, ended = run_thread(monkeypatch, [{"type": "error", "message": "a tool hiccup"}], ts())
    assert "result" not in out[0] and ended == []  # an error that does not end the run is passed on as before


def test_a_plan_step_that_ends_is_reported_as_progress(monkeypatch):
    def plan(*statuses):
        breakdown = [{"capability": "lead_finder", "task": "Find dentists", "details": "a list to enrich", "status": statuses[0]},
                     {"capability": "contact_enricher", "task": "Enrich them", "status": statuses[1]}]
        return {"type": "message", "data": {"source": "OMNI", "content": {"name": "planner_agent", "content": json.dumps({"breakdown": breakdown})}}}

    out, _ = run_thread(monkeypatch, [plan("pending", "pending"), plan("completed", "pending"), plan("completed", "failed")], ts())
    progress = [e["result"] for e in out if e["type"] == "progress"]
    assert [(p["status"], p["steps"][0]["n"], p["steps"][0]["to_achieve"]) for p in progress] == [("completed", 1, "a list to enrich"), ("failed", 2, "")]
    assert progress[1]["reason"].startswith("step 2") and progress[0]["next"] == {"who": "daxagent", "action": "continue the plan"}
    assert progress[0]["type"] == "progress" and progress[0]["in_reply_to"] == "run-7" and progress[0]["about"]["company"] == "Osaic"
