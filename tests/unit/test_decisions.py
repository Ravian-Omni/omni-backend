"""Card answers: skip leaves the call to the agent; revise carries the user's own words."""

from src.agent_runtime.decisions import parse_response


def test_skip_and_revise_answers():
    skip = parse_response("choose", {"action": "skip"})
    assert skip.skipped and not skip.approved and skip.suggestion == ""
    revise = parse_response("confirm_spend", {"action": "revise", "text": "only enrich 5"})
    assert not revise.approved and revise.suggestion == "only enrich 5" and "only enrich 5" in revise.summary()
    assert parse_response("confirm_spend", {"action": "approve"}).approved
