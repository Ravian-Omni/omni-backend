"""Contract [29]: a task's end is pushed to Brain_Hands as task.ended; a row no run holds is closed failed, a quiet live one is
pushed stalled once per quiet stretch."""

import asyncio
from types import SimpleNamespace

import pytest

from src.database import find_task, save_task
from src.routers import hands_mcp as hm
from tests.unit.test_leads import temp_db  # noqa: F401 - the temp_db fixture

OLD, NOW = "2026-11-22T06:11:00+00:00", None


def row(id, state="running", progress=OLD):
    return {"id": id, "run_key": f"k-{id}", "chat_id": f"c-{id}", "agenda_id": "agd_1", "title": f"goal {id}", "state": state,
            "step": "sourcing", "waiting_on": "", "started_at": OLD, "last_progress_at": progress}


@pytest.fixture
def pushed(temp_db, monkeypatch):
    sent = []
    monkeypatch.setattr(hm.brain_hands, "push_in_background", lambda kind, id, title, text, **data: sent.append((kind, id, data)))
    monkeypatch.setattr(hm, "_threads", {})
    monkeypatch.setattr(hm, "_stall_told", set())
    return sent


def test_an_end_state_is_pushed_once_with_the_rows_own_fields(pushed):
    async def go():
        await save_task(row("dt_a"))
        await hm._track("dt_a", state="done", ended_at="2026-11-22T07:00:00+00:00", result={"v": 1, "summary": "3 leads"})
        await hm._track("dt_a", step="report")  # not an end: nothing pushed
    asyncio.run(go())
    assert pushed == [("task.ended", "dt_a:done", {"v": 1, "task_id": "dt_a", "chat_id": "c-dt_a", "agenda_id": "agd_1", "run_key": "k-dt_a",
                                                   "state": "done", "step": "sourcing", "ended_at": "2026-11-22T07:00:00+00:00"})]


def test_a_row_no_run_holds_is_closed_failed_and_a_quiet_live_one_is_stalled_once(pushed):
    hm._threads["k-dt_live"] = SimpleNamespace(task_id="dt_live", task=SimpleNamespace(done=lambda: False))

    async def go():
        for r in (row("dt_dead"), row("dt_live"), row("dt_q", state="queued")):
            await save_task(r)
        await hm._settle()
        await hm._settle()  # a second tick tells nothing new
        return await find_task("dt_dead"), await find_task("dt_live"), await find_task("dt_q")
    dead, live, queued = asyncio.run(go())
    assert dead["state"] == "failed" and "lost" in str(dead["result"]) and live["state"] == "running" and queued["state"] == "queued"
    assert [(k, i, d["state"]) for k, i, d in pushed] == [("task.ended", "dt_dead:failed", "failed"), ("task.ended", f"dt_live:stalled:{OLD}", "stalled")]


def test_a_run_still_starting_is_not_closed_before_its_task_id_is_set(pushed):
    hm._threads["k-dt_new"] = SimpleNamespace(task_id="", task=SimpleNamespace(done=lambda: False))  # _begin, before find_task returns

    async def go():
        await save_task(row("dt_new", progress="2999-01-01T00:00:00+00:00"))
        await hm._settle()
        return await find_task("dt_new")
    assert asyncio.run(go())["state"] == "running" and pushed == []
