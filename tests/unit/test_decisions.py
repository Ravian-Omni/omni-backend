"""Card answers: skip leaves the call to the agent; revise carries the user's own words."""

from src.agent_runtime.decisions import parse_response


def test_skip_and_revise_answers():
    skip = parse_response("choose", {"action": "skip"})
    assert skip.skipped and not skip.approved and skip.suggestion == ""
    revise = parse_response("confirm_spend", {"action": "revise", "text": "only enrich 5"})
    assert not revise.approved and revise.suggestion == "only enrich 5" and "only enrich 5" in revise.summary()
    assert parse_response("confirm_spend", {"action": "approve"}).approved


def test_free_text_never_approves_a_spend_or_a_send():
    # an MCP caller's "draft only" to a send card was read as yes, and the batch went out
    for card in ("confirm_send", "confirm_spend"):
        d = parse_response(card, "draft only")
        assert not d.approved and d.suggestion == "draft only"
        assert parse_response(card, "yes").approved and not parse_response(card, "no").approved
    assert parse_response("choose", "the second one").approved  # elsewhere free text is still the answer
