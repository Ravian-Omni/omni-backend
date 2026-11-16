"""The MCP's view of a task: where it is from the stored history, and each question typed with how to answer it."""

import json

from src.routers.hands_mcp import simplify
from tests.unit.test_leads import temp_db  # noqa: F401 - a temp database for the queue
from src.services.task_status import question_of, status_of


def entry(name, raw, at="2026-11-03T10:00:00+00:00"):
    return {"name": name, "raw_message": raw if isinstance(raw, str) else json.dumps(raw), "timestamp": at}


def plan(*statuses):
    return entry("planner_agent", {"breakdown": [
        {"task_id": 1, "task": "[ ] Find 50 retail companies", "capability": "lead_finder", "status": statuses[0]},
        {"task_id": 2, "task": "[ ] Find buyers at each", "capability": "buyer_finder", "status": statuses[1]},
    ]})


OLD = [entry("chat_manager", "an earlier task"), entry("process_completion_agent", json.dumps("old summary"))]
RUN = [
    *OLD,
    entry("chat_manager", "{'task': \"Find Acme's buyers\", 'files': []}", "2026-11-03T10:00:00+00:00"),
    entry("clarifier", {"intro": "Which region?", "questions": [{"id": "region", "label": "Region"}]}),
    plan("pending", "pending"),
    entry("lead_finder", {"type": "agent_status", "status": "started", "persona": "lead_finder", "display_name": "Lead Finder"}),
    entry("lead_finder", {"type": "tool_use", "tool_name": "business_search"}),
    entry("lead_finder", {"type": "decision_card", "card": "confirm_spend", "credits": 50, "message": "Reveal 50 records?", "answered": True, "answer": "yes"}),
    entry("lead_finder", {"type": "decision_card", "card": "confirm_spend", "credits": 20, "message": "Reveal 20 more?", "answered": True, "answer": "no"}),
    entry("lead_finder", {"type": "artifact", "artifact": {"id": "lead_list-1", "title": "Retail leads", "kind": "lead_list", "row_count": 50}}, "2026-11-03T10:02:00+00:00"),
]


def test_a_running_task_names_the_agent_at_work_and_its_step():
    s = status_of(RUN, running=True, now="2026-11-03T10:05:00+00:00")
    assert s["request"] == "Find Acme's buyers"  # only the latest task, its Python-text request cleaned
    assert (s["stage"], s["note"]) == ("running", "Lead Finder is working: business search")
    assert [p["status"] for p in s["plan"]] == ["in_progress", "pending"]
    assert s["plan"][0]["task"] == "Find 50 retail companies"
    assert s["working"][0]["steps_done"] == 1 and s["progress"] == {"total": 2, "completed": 0, "failed": 0, "remaining": 2, "percent": 0}
    assert s["credits"]["approved"] == 50 and s["credits"]["declined"] == 20
    assert s["saved"] == [{"agent": "lead_finder", "id": "lead_list-1", "title": "Retail leads", "kind": "lead_list", "rows": 50}]
    assert s["elapsed_seconds"] == 300


def test_a_credit_spend_waiting_on_approval_is_a_typed_question():
    pending = {"type": "input_request", "data": {"source": "lead_finder", "content": {
        "card": "confirm_spend", "id": 7, "title": "Confirm credit spend", "message": "Enriching 10 records will consume 10 credits",
        "credits": 10, "count": 10, "unit": "records", "balance_before": 500, "balance_after": 490}}}
    s = status_of(RUN, running=True, pending=pending)
    assert s["stage"] == "waiting_for_answer"
    q = s["question"]
    assert (q["kind"], q["asked_by"], q["credits"], q["balance_after"]) == ("credit_request", "lead_finder", 10, 490)
    assert q["answer_with"].startswith('"yes" to approve')


def test_a_finished_task_reports_each_result_and_the_summary():
    done = [*RUN[:-1],
            entry("lead_finder", {"type": "agent_status", "status": "finished", "persona": "lead_finder"}),
            entry("lead_finder", {"role": "assistant", "content": "Found 50 companies.", "final": True}),
            plan("completed", "failed"),
            entry("process_completion_agent", json.dumps("## Done\nHere are the buyers."), "2026-11-03T10:10:00+00:00")]
    s = status_of(done, running=False)
    assert (s["stage"], s["summary"]) == ("done", "## Done\nHere are the buyers.")
    assert s["plan"][0]["result"] == "Found 50 companies."
    assert s["progress"]["percent"] == 100 and s["progress"]["failed"] == 1
    assert s["working"] == [] and s["elapsed_seconds"] == 600
    assert status_of(RUN, running=False)["stage"] == "stopped"


def test_plan_approval_and_a_waiting_plan_stage():
    s = status_of(RUN[:5], running=True, pending={"data": {"content": json.dumps({"agent": "get_user_acceptance", "prompt": "Proceed?"})}})
    assert s["stage"] == "awaiting_plan_approval" and s["question"]["kind"] == "plan_approval"
    assert s["question"]["plan"][1] == {"step": 2, "agent": "buyer_finder", "agent_name": "Buyer Finder", "task": "Find buyers at each", "status": "pending"}
    assert status_of(RUN[:4], running=True)["stage"] == "understanding"


def test_questions_say_how_to_answer_them():
    form = question_of({"card": "form", "title": "A few details before I plan", "questions": [{"id": "region", "options": [{"value": "us"}]}],
                        "assumptions": ["US only"], "asked_by": "clarifier"})
    assert form["kind"] == "clarify" and form["questions"][0]["id"] == "region" and '"values"' in form["answer_with"]
    choose = question_of({"card": "choose", "question": "Which segment?", "options": [{"value": "a", "label": "A"}], "rows": None}, "buyer_finder")
    assert choose["kind"] == "choose" and choose["asked_by"] == "buyer_finder" and "selected" in choose["answer_with"]
    # Omni's plain prompt asks the verification text it sent just before
    assert question_of({"agent": "user_input", "prompt": "Awaiting"}, context="Which account?")["message"] == "Which account?"


def test_progress_events_for_mcp_callers():
    started = {"type": "message", "data": {"source": "lead_finder", "content": {"name": "lead_finder", "content": {
        "type": "agent_status", "status": "started", "persona": "lead_finder", "display_name": "Lead Finder", "task": "Find leads"}}}}
    assert simplify(started) == {"type": "agent", "agent": "lead_finder", "agent_name": "Lead Finder", "status": "started", "task": "Find leads"}
    saved = {"type": "message", "data": {"source": "lead_finder", "content": {"content": {"type": "artifact", "artifact": {"title": "Leads", "kind": "lead_list", "row_count": 5}}}}}
    assert simplify(saved)["type"] == "saved"
    planned = {"type": "message", "data": {"source": "OMNI", "content": {"name": "planner_agent", "content": json.dumps(
        {"breakdown": [{"capability": "lead_finder", "task": "Find", "status": "pending"}]})}}}
    assert simplify(planned)["steps"] == [{"step": 1, "agent": "lead_finder", "agent_name": "Lead Finder", "task": "Find", "status": "pending"}]
    asked = simplify({"type": "input_request", "data": {"source": "user_verification", "content": json.dumps({"card": "form", "questions": []})}})
    assert asked["question"]["kind"] == "clarify" and asked["card"]["card"] == "form"
    # a run the conversation agent ends (the caller answered in text: blocked, nothing to run) still says why
    blocked = {"type": "message", "data": {"source": "OMNI", "content": {"name": "conversation_agent", "content": "Blocked: no sender email."}}}
    assert simplify(blocked) == {"type": "summary", "text": "Blocked: no sender email."}
    assert status_of([entry("chat_manager", "outreach"), entry("conversation_agent", json.dumps("Blocked: no sender email."))], False)["stage"] == "done"
    # a plan stopped mid-way waits on the user: the question is what it said
    stopped = [entry("chat_manager", "outreach"), entry("conversation_agent", json.dumps("Still pending: confirm the four recipients."))]
    s = status_of(stopped, True, pending={"data": {"content": json.dumps({"agent": "user_input", "prompt": "Awaiting"})}})
    assert (s["stage"], s["question"]["message"]) == ("waiting_for_answer", "Still pending: confirm the four recipients.")


def test_the_sidebar_list_says_which_tasks_an_ai_started(tmp_path, monkeypatch):
    import asyncio

    import src.database as database
    from src.database import connection, get_chat_repository, list_conversations, save_pref

    monkeypatch.setattr(connection.settings, "ROOT_DIR", str(tmp_path))
    monkeypatch.setattr(connection, "_db", None)
    monkeypatch.setattr(database, "_chat_repository", None)  # a cached one holds an earlier test's closed connection

    async def go():
        await connection.init_db()
        repo = await get_chat_repository()
        for chat_id in ("by-ai", "by-me"):
            await repo.create_chat({"user_id": "u", "chat_id": chat_id, "chat_dir": str(tmp_path), "messages": [],
                                    "raw_messages": [entry("chat_manager", "a task")], "created_at": "2026-11-04T08:00:00",
                                    "updated_at": "2026-11-04T08:00:00"}, "omni")
        await save_pref("u", "run_by:by-ai", "brain-hands")  # what hands_mcp.start_run saves
        rows = {c["chat_id"]: c["run_by"] for c in await list_conversations("u")}
        await connection.close_db()
        return rows

    assert asyncio.run(go()) == {"by-ai": "brain-hands", "by-me": None}


def test_an_outside_agent_reads_the_files_a_task_saved(tmp_path, monkeypatch):
    import asyncio

    import src.database as database
    from src.database import connection, get_chat_repository, save_artifact
    from src.routers import hands_mcp as hm

    monkeypatch.setattr(connection.settings, "ROOT_DIR", str(tmp_path))
    monkeypatch.setattr(connection, "_db", None)
    monkeypatch.setattr(database, "_chat_repository", None)
    path = tmp_path / "lead_list-1.json"
    path.write_text(json.dumps({"columns": ["name"], "rows": [{"_id": i + 1, "name": f"Co {i}"} for i in range(5)], "meta": {"rev": 1}}))

    async def go():
        await connection.init_db()
        repo = await get_chat_repository()
        for user, chat_id in ((hm.USER_ID, "mine"), (hm.USER_ID, "other"), ("someone-else", "theirs")):
            await repo.create_chat({"user_id": user, "chat_id": chat_id, "chat_dir": str(tmp_path), "messages": [],
                                    "raw_messages": [], "created_at": "2026-11-06T08:00:00", "updated_at": "2026-11-06T08:00:00"}, "omni")
        for artifact_id, chat_id in (("lead_list-1", "mine"), ("lead_list-2", "theirs")):
            await save_artifact({"id": artifact_id, "chat_id": chat_id, "persona": "lead_finder", "kind": "lead_list",
                                 "title": "Retail leads", "path": str(path), "row_count": 5})
        listed = (await hm.list_artifacts("mine"))["artifacts"]
        page = await hm.read_artifact("lead_list-1", "mine", offset=3, limit=10)
        # the account's files open by id from any task, and list across tasks; another account's do neither
        assert (await hm.read_artifact("lead_list-1", "other"))["chat_id"] == (await hm.read_artifact("lead_list-1"))["chat_id"] == "mine"
        assert [(a["id"], a["chat_id"]) for a in (await hm.list_artifacts(search="retail"))["artifacts"]] == [("lead_list-1", "mine")]
        assert (await hm.list_artifacts(kind="buyer_map"))["artifacts"] == []
        errors = []
        for artifact_id in ("lead_list-9", "lead_list-2"):  # a file that is not there, another account's file
            try:
                await hm.read_artifact(artifact_id)
            except ValueError as e:
                errors.append(str(e))
        # a plan's steps are drafts until approved; over the MCP there is no campaign page to click
        plan = tmp_path / "campaign_plan-1.json"
        plan.write_text(json.dumps({"columns": ["step", "status"], "meta": {"rev": 2},
                                    "rows": [{"_id": i + 1, "step": n, "status": "draft"} for i, n in enumerate((1, 2, 1))]}))
        await save_artifact({"id": "campaign_plan-1", "chat_id": "mine", "persona": "campaign_builder", "kind": "campaign_plan",
                             "title": "Plan", "path": str(plan), "row_count": 3})
        nexts = [(await status.campaigns("mine"))[0]["next"]["action"]]
        first = await hm.approve_plan_steps("mine", "campaign_plan-1", steps=[1])
        rest = await hm.approve_plan_steps("mine", "campaign_plan-1")
        for args in (("mine", "lead_list-1"), ("other", "campaign_plan-1")):  # not a plan, another task's plan
            try:
                await hm.approve_plan_steps(*args)
            except ValueError as e:
                errors.append(str(e))
        # what the plan waits on after each stage, the way the completion event tells the caller
        nexts.append((await status.campaigns("mine"))[0]["next"])
        log = tmp_path / "send_log-1.json"
        for outcome in ("drafted", "sent"):
            log.write_text(json.dumps({"rows": [{"plan_id": "campaign_plan-1", "to": "a@x.com", "step": 1, "status": s}
                                                for s in ("drafted", "sent")[: ("drafted", "sent").index(outcome) + 1]]}))
            await save_artifact({"id": "send_log-1", "chat_id": "mine", "persona": "outreach", "kind": "send_log",
                                 "title": "Send log", "path": str(log), "row_count": 1})
            nexts.append((await status.campaigns("mine"))[0])
        await connection.close_db()
        return listed, page, errors, first, rest, json.loads(plan.read_text()), nexts

    from src.services import task_status as status

    listed, page, errors, first, rest, saved, nexts = asyncio.run(go())
    drafts, after_drafts, after_send = nexts[1], nexts[2], nexts[3]
    assert nexts[0] == "approve_steps"
    assert drafts["action"] == "create_drafts" and "`campaign_plan-1`" in drafts["start_run"]
    assert (after_drafts["emails_approved"], after_drafts["drafted"], after_drafts["sent"], after_drafts["next"]["action"]) == (3, 1, 0, "send")
    assert "send_approval" in after_drafts["next"]["note"]
    assert (after_send["sent"], after_send["next"]["action"]) == (1, "watch_replies")
    assert [(a["id"], a["rows"], a["agent"]) for a in listed] == [("lead_list-1", 5, "lead_finder")]
    assert (page["row_count"], page["offset"], [r["name"] for r in page["rows"]]) == (5, 3, ["Co 3", "Co 4"])
    assert len(errors) == 4
    assert (first["approved_now"], first["approved_steps"], rest["approved_now"], rest["approved_steps"]) == (2, 2, 1, 3)
    assert [r["status"] for r in saved["rows"]] == ["approved"] * 3 and saved["meta"]["rev"] == 4


def test_start_run_continues_a_chat_without_the_last_runs_leftovers(monkeypatch, temp_db):
    import asyncio
    from types import SimpleNamespace

    from src.routers import hands_mcp as hm

    class Thread:  # a HandsThread without the omni WebSocket behind it
        def __init__(self, key, chat_id):
            self.chat_id, self.queue, self.inbox = chat_id, asyncio.Queue(), asyncio.Queue()
            self.task, self.ask_text, self.plan = SimpleNamespace(done=lambda: False), "", []
            self.agenda_id, self.polling, self.last_poll = "", 0, 0.0

    async def get_chat(_user, chat_id, _mode):
        return {"chat_id": chat_id} if chat_id in ("old", "busy") else None

    async def nothing(*_):
        return None

    async def repo():
        return SimpleNamespace(get_chat=get_chat)

    async def manager():
        return SimpleNamespace(is_running=lambda chat_id: chat_id == "busy", running_chats=lambda: ["busy"], pending_request=lambda _: None)

    async def create_omni_chat(_user):
        return {"chat_id": "new"}

    monkeypatch.setattr(hm, "_threads", {})
    monkeypatch.setattr(hm, "HandsThread", Thread)
    monkeypatch.setattr(hm, "get_chat_repository", repo)
    monkeypatch.setattr(hm, "get_websocket_manager", manager)
    monkeypatch.setattr(hm, "save_pref", nothing)
    monkeypatch.setattr(hm.needs, "agenda_of", lambda _chat_id: nothing())
    monkeypatch.setattr(hm, "ChatService", SimpleNamespace(create_omni_chat=create_omni_chat))
    ctx = SimpleNamespace(session=SimpleNamespace(client_params=None))

    async def go():
        assert (await hm.start_run("a", ctx, key="k0"))["chat_id"] == "new"
        assert (await hm.start_run("outreach", ctx, key="k1", chat_id="old"))["chat_id"] == "old"
        first = hm._threads["k1"]
        first.queue.put_nowait({"type": "completion", "status": "complete"})  # left over from the run that just ended
        hm._active.clear()  # that run has ended: its chat takes the next task
        await hm.start_run("follow up", ctx, key="k2", chat_id="old")
        assert hm._threads["k2"] is first and first.queue.empty()  # the open thread takes the next task
        assert [json.loads(first.inbox.get_nowait())["task"] for _ in range(2)] == ["outreach", "follow up"]
        # the chat_id is the conversation: a run started without a key is driven by it, and so is one with a key
        hm._threads.clear()
        assert (await hm.start_run("b", ctx))["chat_id"] == "new" and "new" in hm._threads
        await hm.start_run("c", ctx, key="mine", chat_id="old")
        assert hm._find("old") is hm._threads["mine"]
        assert (await hm.next_event("old", timeout=1))["chat_id"] == "old"
        try:
            await hm.start_run("x", ctx, key="k3", chat_id="missing")
            raise AssertionError("missing")
        except ValueError:
            pass
        queued = await hm.start_run("x", ctx, key="k4", chat_id="busy")  # a running chat queues the task instead of refusing it
        assert (queued["queued"], queued["position"]) == (True, 1)

    asyncio.run(go())
