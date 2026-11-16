"""The send tool refuses an email that has a placeholder left in it, or a recipient that is a shared inbox or suppressed:
the check is in the tool, so no prompt and no approval overrides it."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src import database
from src.agent_runtime import leads
from src.agent_runtime.tools import sales
from src.database import connection, suppress_email


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(connection.settings, "ROOT_DIR", str(tmp_path))
    monkeypatch.setattr(connection, "_db", None)
    monkeypatch.setattr(database, "_chat_repository", None)
    asyncio.run(connection.init_db())
    yield
    asyncio.run(connection.close_db())


@pytest.fixture
def send(temp_db, tmp_path, monkeypatch):
    """The gmail_send_email handler, a Gmail that records what goes out, and the context (with every send already approved)."""
    gmail = AsyncMock(return_value={"successful": True, "data": {}})
    monkeypatch.setattr(sales, "gmail_call", gmail)
    ctx = SimpleNamespace(chat_id="chat-1", user_id="u", persona="outreach", task_id=None, artifacts_dir=str(tmp_path), data_sources=set(),
                          emit=AsyncMock(), decisions=None, send_allowance={"*": 99}, send_approved=set())
    handler = next(t for t in sales.build(ctx) if t.name == "gmail_send_email").handler
    return (lambda **args: asyncio.run(handler({"to": "ana@acme.com", "subject": "Hello", "body": "Hi Ana, a short note.", **args}))), gmail, ctx


def refused(result) -> str:
    assert result.get("is_error"), result
    return result["content"][0]["text"]


@pytest.mark.parametrize("fields, shown", [
    ({"body": "Hi {{first_name}}, a note."}, "{{first_name}}"),
    ({"subject": "For {{company}}"}, "{{company}}"),
    ({"body": "Hi {first_name}"}, "{first_name}"),
    ({"body": "Best,\n[Your Name]"}, "[Your Name]"),
])
def test_an_email_with_a_placeholder_left_in_it_is_not_sent(send, fields, shown):
    run, gmail, _ = send
    assert shown in refused(run(**fields))
    gmail.assert_not_called()  # the send tool never reached Gmail, whatever was approved (send_allowance is full)


@pytest.mark.parametrize("to", ["info@acme.com", "newbiz@acme.com", "Hello@acme.com"])
def test_a_shared_or_role_inbox_is_not_written_to(send, to):
    run, gmail, _ = send
    assert f"{to} is a shared or role inbox" in refused(run(to=to))
    gmail.assert_not_called()


def test_a_suppressed_address_is_not_written_to_and_cc_and_bcc_count(send):
    run, gmail, _ = send
    asyncio.run(suppress_email("u", "Gone@Acme.com", "unsubscribe"))
    assert "gone@acme.com is suppressed" in refused(run(to="gone@acme.com")).lower()
    assert "sales@acme.com is a shared or role inbox" in refused(run(cc=["sales@acme.com"]))
    gmail.assert_not_called()


def test_a_clean_email_to_a_person_goes_out(send):
    run, gmail, _ = send
    assert not run().get("is_error")
    assert gmail.await_args.args[1] == "GMAIL_SEND_EMAIL" and gmail.await_args.args[2]["recipient_email"] == "ana@acme.com"
    # follow-ups in a thread go through the same check
    assert "shared" in refused(run(to="info@acme.com", thread_id="t1"))


def test_a_blocked_send_is_logged_with_its_reason_when_it_belongs_to_a_plan(send, tmp_path):
    run, gmail, ctx = send
    (tmp_path / "campaign_plan-p1.json").write_text(json.dumps({"rows": [], "meta": {}}))
    refused(run(to="info@acme.com", plan_id="campaign_plan-p1", step=1))
    log = json.loads(next(tmp_path.glob("send_log-*.json")).read_text())
    assert [(r["to"], r["status"], r["reason"]) for r in log["rows"]] == [("info@acme.com", "blocked", "info@acme.com is a shared or role inbox")]
    gmail.assert_not_called()


def test_the_check_is_one_function_of_the_email_and_who_is_suppressed():
    assert leads.send_problems(["ana@acme.com"], "Hello", "Hi Ana", set()) == []
    assert leads.send_problems(["a@x.com", "info@x.com"], "Re {{x}}", "ok", {"a@x.com"}) == [
        "it has an unfilled placeholder: {{x}}", "a@x.com is suppressed", "info@x.com is a shared or role inbox"]
