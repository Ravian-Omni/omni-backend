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


def test_a_your_call_form_asked_again_after_a_skip_ends_the_task():
    from src.omni.manager import SKIPPED

    request = {"name": "chat_manager", "content": "Get 3 B2B clients"}
    ask = {"name": "manual_verification", "content": '{"questions": [{"id": "sender_name", "required": true}]}'}
    skip = {"name": "user_form", "content": SKIPPED}
    assert Omni._skipped_verification([request, ask, skip])
    assert not Omni._skipped_verification([request, ask, {"name": "user_form", "content": "User verification answers:\n- Name: Ada"}])
    assert not Omni._skipped_verification([request, {"name": "clarifier", "content": "{}"}, skip])  # an intake skip: defaults are fine
    assert not Omni._skipped_verification([request, ask, skip, {"name": "chat_manager", "content": "Here are the details"}])


def test_only_a_short_go_ahead_resumes_an_unfinished_plan():
    # the chat's request is str({"task": ..., "files": ...}); the routing resumes the plan only when its text is a go-ahead
    assert Omni._is_approval(Omni._request_text(str({"task": "ok", "files": []})))
    assert not Omni._is_approval(Omni._request_text(str({"task": "GOAL: get 3 B2B clients for MarketWatch", "files": []})))
    assert Omni._request_text("continue") == "continue"


def test_a_caller_that_stops_mid_plan_waits_for_the_users_reply():
    # chat 6e0faa26: steps 3 and 4 pending, the caller wrote "still pending" instead of calling Campaign Builder, and the
    # run ended; the MCP caller never got a question it could answer with the verified details
    plan = {"name": "planner_agent", "content": '{"overall_status": "pending", "breakdown": []}'}
    prose = {"name": "agent_caller", "content": "The correction is still pending."}
    said = {"name": "conversation_agent", "content": "The correction is still pending."}
    assert Omni._caller_stopped_mid_plan([plan, prose, said])
    done = {"name": "planner_agent", "content": '{"overall_status": "completed"}'}
    assert not Omni._caller_stopped_mid_plan([done, prose, said])  # nothing left to run: the answer ends the run
    assert not Omni._caller_stopped_mid_plan([{"name": "judge_question", "content": "conversation"}, said])  # small talk


def test_the_one_off_email_sender_runs_only_for_a_step_given_to_it():
    # chat 6e0faa26: the router gave Campaign Builder the step, the caller called email_sender (which sends at once)
    router = {"name": "agent_router", "content": '{"task_assignments": [{"capability": "campaign_builder", "task_id": 2}]}'}
    assert Omni._assigned([router, {"name": "agent_caller", "content": None}]) == {"campaign_builder"}
    mine = {"name": "agent_router", "content": '{"task_assignments": [{"capability": "email_sender"}]}'}
    assert "email_sender" in Omni._assigned([router, mine])  # the latest assignment counts
    assert Omni._assigned([{"name": "agent_router", "content": "not json"}]) == set()
    assert Omni._assigned([]) == set()


def test_the_caller_runs_the_agent_the_router_named_with_its_task():
    # chat 6e0faa26: given campaign_builder, the caller model called user_context, or wrote "did not complete" and no call
    import json

    def tool(name, *fields):
        return {"type": "function", "function": {"name": name, "parameters": {"type": "object", "properties": {f: {"type": "string"} for f in fields}}}}

    tools = [tool("campaign_builder", "query"), tool("user_context", "query"), tool("GMAIL_SEND_EMAIL", "recipient_email", "body")]
    router = {"name": "agent_router", "content": json.dumps({"task_assignments": [{"capability": "campaign_builder", "task": "Validate campaign_plan-36033709"}]})}
    [call] = Omni._direct_calls([router], tools)
    assert call["function"]["name"] == "campaign_builder" and json.loads(call["function"]["arguments"]) == {"query": "Validate campaign_plan-36033709"}
    assert call["id"].startswith("call_") and call["type"] == "function"
    app = {"name": "agent_router", "content": json.dumps({"task_assignments": [{"capability": "GMAIL_SEND_EMAIL", "task": "x"}]})}
    assert Omni._direct_calls([app], tools) is None  # an app tool's own fields: the model fills them
    unknown = {"name": "agent_router", "content": json.dumps({"task_assignments": [{"capability": "lead_finder", "task": "x"}]})}
    assert Omni._direct_calls([unknown], tools) is None
    assert Omni._direct_calls([router, {"name": "agent_executor", "content": "done"}], tools) is None  # only right after the router
    assert Omni._direct_calls([{"name": "agent_router", "content": "not json"}], tools) is None
