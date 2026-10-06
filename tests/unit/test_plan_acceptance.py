from src.omni.manager import Omni


def test_only_a_plain_yes_approves_the_plan():
    for text in ["yes, looks good.", "ok", "okay go ahead", "Proceed", "LGTM"]:
        assert Omni._is_approval(text), text
    for text in ["Change the plan: drop outreach", "yes but skip enrichment", "no", "TERMINATE", ""]:
        assert not Omni._is_approval(text), text


def test_a_plan_the_user_asked_to_change_is_not_pending():
    plan = {"name": "planner_agent", "content": '{"overall_status": "in_progress"}'}
    assert not Omni._has_pending_plan([plan, {"name": "get_user_acceptance", "content": "Change the plan: drop outreach"}])
    assert Omni._has_pending_plan([plan, {"name": "get_user_acceptance", "content": "yes, looks good."}])
