"""A user's artifacts follow them: any of their chats reads one by id, another person's stay closed, and a change made
away from the artifact's own chat is saved as a copy. A campaign plan is sent only from its own chat."""

import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.agent_runtime.tools import artifacts, campaign, sales
from src.agent_runtime.tools.context import ToolContext
from src.database import connection, get_artifact
from src.routers import agents

ROWS = [{"company": "Acme", "status": "approved"}, {"company": "Bolt", "status": "draft"}]


@pytest.fixture
def chat(tmp_path, monkeypatch):
    """Ann owns chats a1 and a2, Bob owns b1. Returns a maker of tool contexts: chat(user, chat_id, task folder)."""
    monkeypatch.setattr(connection.settings, "ROOT_DIR", str(tmp_path))
    monkeypatch.setattr(connection, "_db", None)

    async def setup():
        await connection.init_db()
        db = await connection.get_db()
        for user, chat_id in (("ann", "a1"), ("ann", "a2"), ("bob", "b1")):
            await db.execute("INSERT INTO chats (user_id, chat_id, collection, created_at, updated_at) VALUES (?, ?, 'omni', '', '')", (user, chat_id))
        await db.commit()

    asyncio.run(setup())

    async def emit(event):
        pass

    def make(user, chat_id, folder, decisions=None):
        home = tmp_path / "tasks" / folder
        return ToolContext(chat_id=chat_id, user_id=user, persona="lead_finder", chat_dir=str(home), working_directory=str(home),
                           file_location=str(home), artifacts_dir=str(home / "artifacts"), python_executable="", decisions=decisions, emit=emit)

    return make


def call(ctx, name, args, module=artifacts):
    """(failed, result) of one tool call."""
    out = asyncio.run(next(t for t in module.build(ctx) if t.name == name).handler(args))
    text = out["content"][0]["text"]
    return out.get("is_error", False), json.loads(text) if text[:1] in "[{" else text


def save(ctx, kind="lead_list", title="Dental leads Austin", rows=ROWS, **more):
    return call(ctx, "save_artifact", {"kind": kind, "title": title, "rows": [dict(r) for r in rows], **more})[1]


def test_any_of_the_users_chats_reads_it(chat):
    alpha, beta = chat("ann", "a1", "Alpha"), chat("ann", "a2", "Beta")
    leads = save(alpha)["artifact_id"]
    here = call(beta, "list_artifacts", {})[1]
    assert here["artifacts"] == [] and "everywhere" in here["elsewhere"]  # the list says there is more than this chat
    found = call(beta, "list_artifacts", {"everywhere": True, "search": "dental AUSTIN"})[1]
    assert [(f["id"], f["from"]) for f in found] == [(leads, "the task 'Alpha'")]
    assert call(beta, "list_artifacts", {"everywhere": True, "kind": "buyer_map"})[1] == []
    assert call(alpha, "list_artifacts", {"kind": "lead_list"})[1]["artifacts"][0]["id"] == leads  # kind alone stays in this chat
    read = call(beta, "read_artifact", {"artifact_id": leads})[1]
    assert read["row_count"] == 2 and read["from"] == "the task 'Alpha'" and read["created_at"]
    assert "from" not in call(alpha, "read_artifact", {"artifact_id": leads})[1]


def test_another_persons_artifact_stays_closed(chat):
    ann, bob = chat("ann", "a1", "Alpha"), chat("bob", "b1", "Alpha")  # two people's same-named tasks share a folder
    leads = save(ann)["artifact_id"]
    assert call(bob, "read_artifact", {"artifact_id": leads})[0] and call(bob, "update_artifact", {"artifact_id": leads})[0]
    assert call(bob, "list_artifacts", {"everywhere": True})[1] == []
    app = FastAPI()
    app.include_router(agents.router, prefix="/agents")
    web = TestClient(app)
    assert web.get(f"/agents/download/{leads}?format=json&user_id=bob").status_code == 404
    assert web.get(f"/agents/download/{leads}?format=json&user_id=ann").status_code == 200
    assert web.get(f"/agents/download/{leads}?format=json").status_code == 200  # no sign-in gate: a local, single-user run
    # the composer's picker lists a person's own library only
    mine = web.get("/agents/library?user_id=ann&search=dental").json()["artifacts"]
    assert [(a["id"], a["chat_id"], a["from"]) for a in mine] == [(leads, "a1", "the task 'Alpha'")] and "path" not in mine[0]
    assert web.get("/agents/library?user_id=ann&search=nothing").json() == web.get("/agents/library?user_id=bob").json() == {"artifacts": []}


def test_a_change_from_another_chat_is_saved_as_a_copy(chat):
    alpha, beta = chat("ann", "a1", "Alpha"), chat("ann", "a2", "Beta")
    alpha.data_sources.add("data-axle")
    plan = save(alpha, kind="campaign_plan", title="Spring plan")["artifact_id"]
    out = call(beta, "update_artifact", {"artifact_id": plan, "remove_ids": [2]})[1]
    assert out["copied_from"] == plan and out["artifact_id"] != plan and out["row_count"] == 1
    original = asyncio.run(get_artifact(plan))
    assert (original["chat_id"], original["row_count"]) == ("a1", 2)  # untouched, and still Alpha's
    copy = call(beta, "read_artifact", {"artifact_id": out["artifact_id"]})[1]
    assert copy["rows"][0]["status"] == "draft" and copy["meta"]["copied_from"] == plan and "from" not in copy  # the approval stayed behind
    assert copy["meta"]["data_sources"] == ["data-axle"]  # and it still credits where the rows came from
    assert call(alpha, "update_artifact", {"artifact_id": plan, "remove_ids": [2]})[1] == {"artifact_id": plan, "row_count": 1}  # at home: in place


def test_a_campaign_keeps_its_audience_in_its_own_chat_and_a_review_saves_a_copy(chat):
    async def review_artifact(*args, **kwargs):
        return SimpleNamespace(suggestion="", raw={"excluded_ids": [2]}, approved=True, text="")

    alpha, beta = chat("ann", "a1", "Alpha"), chat("ann", "a2", "Beta", SimpleNamespace(review_artifact=review_artifact))
    leads = save(alpha)["artifact_id"]
    plan = save(beta, kind="campaign_plan", title="Plan", rows=[], meta={"audience_artifact_id": leads})
    audience = plan["audience_artifact_id"]
    assert audience != leads and asyncio.run(get_artifact(audience))["chat_id"] == "a2"
    assert call(beta, "read_artifact", {"artifact_id": plan["artifact_id"]})[1]["meta"]["audience_artifact_id"] == audience
    reviewed = call(beta, "review_with_user", {"artifact_id": leads}, sales)[1]
    assert reviewed["saved_as"] not in (leads, audience) and asyncio.run(get_artifact(reviewed["saved_as"]))["row_count"] == 1
    assert asyncio.run(get_artifact(leads))["row_count"] == 2
    # a plan copied from another chat brings its audience along, and is this chat's own to send once its steps are approved again
    theirs = save(alpha, kind="campaign_plan", title="Alpha plan", rows=[{"step": 1, "status": "approved"}], meta={"audience_artifact_id": leads})
    copied = call(beta, "update_artifact", {"artifact_id": theirs["artifact_id"]})[1]["artifact_id"]
    brought = call(beta, "read_artifact", {"artifact_id": copied})[1]["meta"]["audience_artifact_id"]
    assert brought != leads and asyncio.run(get_artifact(brought))["chat_id"] == "a2"
    assert call(beta, "render_campaign", {"plan_id": copied}, campaign)[1]["approved_steps"] == 0


def test_a_campaign_plan_is_sent_only_from_its_own_chat(chat, monkeypatch):
    sent = []

    async def gmail_call(user_id, slug, arguments):
        sent.append(arguments["recipient_email"])
        return {"successful": True, "data": {"threadId": "t1"}}

    monkeypatch.setattr(sales, "gmail_call", gmail_call)
    # one folder for all three, as for runs started over MCP (they share the default folder) and two people's same-named tasks
    home, other, bob = chat("ann", "a1", "Shared"), chat("ann", "a2", "Shared"), chat("bob", "b1", "Shared")
    leads = save(home, rows=[{"company": "Acme", "email": "a@acme.com"}])["artifact_id"]
    plan = save(home, kind="campaign_plan", title="Plan", rows=[{"step": 1, "status": "approved", "subject": "Hi", "body": "Hello"}],
                meta={"audience_artifact_id": leads})["artifact_id"]
    mail = {"to": "a@acme.com", "subject": "Hi", "body": "Hello", "plan_id": plan, "step": 1}
    assert call(home, "render_campaign", {"plan_id": plan}, campaign)[1]["approved_steps"] == 1
    for ctx, why in ((other, "belongs to the task 'Shared'"), (bob, "No artifact")):
        for name, args, module in (("render_campaign", {"plan_id": plan}, campaign), ("check_replies", {"plan_id": plan}, campaign),
                                   ("record_reply", {"plan_id": plan, "to": "a@acme.com", "intent": "interested"}, campaign),
                                   ("gmail_send_email", mail, sales), ("gmail_create_draft", mail, sales)):
            failed, said = call(ctx, name, args, module)
            assert failed and why in said and "audience_artifact_id" not in said, (name, said)
    assert sent == [] and asyncio.run(get_artifact(campaign.log_id(plan))) is None  # nothing went out and nothing was logged
    assert not call(home, "gmail_send_email", mail, sales)[0] and sent == ["a@acme.com"]
    assert asyncio.run(get_artifact(campaign.log_id(plan)))["chat_id"] == "a1"  # the send log stays with the plan
