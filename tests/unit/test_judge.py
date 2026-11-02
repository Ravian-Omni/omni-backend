"""LLM as judge: severity by rule, the case the judge reads, expected answers matched to turns, and the gate."""

import asyncio

import pytest

from src import judge
from src.database import add_truth_version, connection, current_truths


def j(**kw):
    base = dict(relevancy=4, completeness=4, tool_selection=4, unsupported_fact=False, wrong_tool=False, materially_incomplete=False,
                root_cause="none", failing_step=-1, rationale="", suggested_fix="")
    return judge.Judgement(**{**base, **kw})


@pytest.mark.parametrize("kw, expected", [
    ({}, "low"),
    ({"completeness": 3}, "medium"),  # correct but partial
    ({"wrong_tool": True, "tool_selection": 1}, "high"),
    ({"materially_incomplete": True}, "high"),
    ({"unsupported_fact": True, "wrong_tool": True}, "critical"),  # a wrong figure as fact outranks everything
])
def test_severity_is_a_rule(kw, expected):
    assert judge.severity(j(**kw)) == expected


def test_the_case_keeps_step_numbers_and_the_ends_of_long_turns():
    turn = {"turn": "t1", "request": "Find dentists", "status": "answered", "feedback": [{"rating": 1, "description": "wrong city"}],
            "steps": [{"kind": "step", "who": "planner_agent", "text": "plan"}] + [{"kind": "tool", "server": "data-axle", "tool": f"search{i}", "input": {}, "result": "ok"} for i in range(200)]
            + [{"kind": "answer", "text": "Here are 20 dentists"}]}
    text = judge.bundle(turn, {"case_id": "c", "version": 2, "expected_agents": ["lead_finder"], "expected_answer": "20 dentists in Austin"})
    assert "[0] planner_agent: plan" in text and "[201] answer to the person: Here are 20 dentists" in text  # numbered as the trace
    assert "steps omitted" in text and "rated 1 of 5: wrong city" in text and "EXPECTED (curated by Data Axle, version 2): agents lead_finder" in text


def test_a_verdict_never_points_outside_the_turn():
    v = judge.verdict("chat", "u", {"turn": "t", "steps": [{}, {}]}, None, j(failing_step=7, completeness=2), "luna")
    assert v["failing_step"] == -1 and v["severity"] == "medium" and v["final_score"] == round(10 / 3, 2) and v["ground_truth"] == ""


def test_expected_answers_match_their_turn_first_then_the_same_request():
    truths = [{"case_id": "a", "request": "find  Dentists", "source_chat_id": "", "source_task_id": ""},
              {"case_id": "b", "request": "other", "source_chat_id": "c1", "source_task_id": "t1"}]
    assert judge.truth_for("c1", {"turn": "t1", "request": "find dentists"}, truths)["case_id"] == "b"
    assert judge.truth_for("c2", {"turn": "t9", "request": "Find dentists "}, truths)["case_id"] == "a"
    assert judge.truth_for("c2", {"turn": "t9", "request": "something new"}, truths) is None


def test_the_gate_blocks_a_lower_score_or_a_broken_case():
    prev = {"score": 0.5, "config_version": "aaa", "results": [{"case_id": "x", "passed": True}, {"case_id": "y", "passed": False}]}
    better = {"score": 1.0, "results": [{"case_id": "x", "passed": True, "request": "X"}, {"case_id": "y", "passed": True, "request": "Y"}]}
    swapped = {"score": 0.5, "results": [{"case_id": "x", "passed": False, "request": "X"}, {"case_id": "y", "passed": True, "request": "Y"}]}
    assert judge.gate(better, prev)["passes"] and judge.gate(better, None)["first"]
    assert not judge.gate(swapped, prev)["passes"] and judge.gate(swapped, prev)["regressions"] == ["X"]  # same score, but X broke


def test_expected_answers_are_versioned_never_overwritten(tmp_path, monkeypatch):
    monkeypatch.setattr(connection.settings, "ROOT_DIR", str(tmp_path))
    monkeypatch.setattr(connection, "_db", None)

    async def scenario():
        await connection.init_db()
        case = {"case_id": "case-1", "request": "Find dentists", "expected_agents": ["lead_finder"], "expected_answer": "",
                "query_class": "lookup", "source_chat_id": "", "source_task_id": "", "author": "admin", "retired": 0}
        await add_truth_version(case)
        second = await add_truth_version({**case, "expected_agents": ["lead_finder", "buyer_finder"]})
        live = await current_truths()
        await add_truth_version({**case, "retired": 1})
        gone, kept = await current_truths(), await current_truths(include_retired=True)
        await connection.close_db()
        return second, live, gone, kept

    second, live, gone, kept = asyncio.run(scenario())
    assert second["version"] == 2 and live[0]["expected_agents"] == ["lead_finder", "buyer_finder"]
    assert gone == [] and kept[0]["version"] == 3 and kept[0]["retired"] == 1
