"""The agents get a finished run as its result, not its whole transcript; the run in progress stays word for word."""

from autogen import ConversableAgent, GroupChat, GroupChatManager

from src.omni.memory import LEDGER, REQUEST_CHARS, compact


def m(name, content):
    return {"role": "user", "name": name, "content": content}


LONG = "GOAL: three clients. LIMITS: Bay Area only, research only, no sends. " + "x" * 5000
HISTORY = [
    m("chat_manager", LONG), m("planner_agent", "{plan 1}"), m("agent_executor", "tool output " * 900),
    m("process_completion_agent", "Saved analysis-a913883a (five-row matrix). Failed: no named people. Pending: final consolidation."),
    m("chat_manager", "second request"), m("planner_agent", "{plan 2}"),
    m("process_completion_agent", "Saved analysis-f7a57847 in chat 7af4e9a0."),
    m("chat_manager", "the run in progress, every word kept " + "y" * 3000), m("planner_agent", "{plan 3}"), m("get_user_acceptance", "yes"),
]


def test_finished_runs_keep_their_results_and_the_run_in_progress_is_whole():
    out = compact(HISTORY, "Files saved in this chat: analysis-a913883a, analysis-f7a57847")
    assert [x["name"] for x in out] == ["chat_manager", "process_completion_agent", "chat_manager", "process_completion_agent",
                                        LEDGER, "chat_manager", "planner_agent", "get_user_acceptance"]
    assert out[0]["content"] == LONG[:REQUEST_CHARS] and "LIMITS: Bay Area only" in out[0]["content"]  # an earlier request keeps its head
    assert out[1] == HISTORY[3] and out[3] == HISTORY[6]  # what was saved, what failed, what is pending: word for word
    assert out[-3:] == HISTORY[-3:]  # the current run untouched, its last speaker last
    assert HISTORY[0]["content"] == LONG  # the stored history is not changed


def test_a_chat_with_no_finished_run_and_a_second_trim_change_nothing():
    assert compact(HISTORY[:3]) == HISTORY[:3]
    once = compact(HISTORY, "ledger")
    assert compact(once, "ledger") == once


def test_autogen_resumes_a_trimmed_history_with_the_ledger_in_it():
    names = {x["name"] for x in HISTORY} - {"chat_manager"}
    chat = GroupChat(agents=[ConversableAgent(n, llm_config=False) for n in names], messages=[])
    manager = GroupChatManager(chat, name="chat_manager", llm_config=False)
    manager.resume(messages=compact(HISTORY, "Files saved in this chat: analysis-a913883a"))  # raised on an unknown name
