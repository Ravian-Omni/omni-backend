"""The send tool refuses an email that has a placeholder left in it, or a recipient that is a shared inbox or suppressed:
the check is in the tool, so no prompt and no approval overrides it."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src import database
from src.agent_runtime import leads, sender
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
    monkeypatch.setattr(sender, "mailbox", AsyncMock(return_value="me@mine.com"))  # the account's own address, not a Gmail call
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


def test_a_shared_inbox_the_lead_gate_passed_in_this_chat_is_written_to(send, monkeypatch):
    """The user, 18 Nov 2026: a shared inbox is used when it is the only address a company has. The send gate lets through
    exactly the ones the lead gate passed, so the two cannot disagree."""
    run, gmail, _ = send
    monkeypatch.setattr(leads, "passed_shared", AsyncMock(return_value={"newbiz@solo.com"}))
    assert not run(to="newbiz@solo.com").get("is_error")
    gmail.assert_called_once()
    assert "info@acme.com is a shared or role inbox" in refused(run(to="info@acme.com"))  # one the gate did not pass


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


# --- what the email says ([20] item 2): links and addresses stay on the user's, or the recipient's, domains; no payment asks
def test_a_link_or_address_off_the_users_and_the_recipients_domains_is_refused():
    own = {"mine.com"}
    ok = "See https://cal.mine.com/ana, www.acme.com/pricing, or write to ana@acme.com and me@mine.com."
    assert leads.send_problems(["ana@acme.com"], "Hello", ok, set(), own) == []
    [problem] = leads.send_problems(["ana@acme.com"], "Hello", "Pay at https://evil.io/x or ask bob@other.org; www.www-evil.net", set(), own)
    assert problem.startswith("it links to or names an address at a domain that is not yours or the recipient's: evil.io, other.org, www-evil.net")
    assert leads.send_problems(["ana@acme.com"], "Hello", "https://evil.io", set()) == []  # own None: the check is not asked for


@pytest.mark.parametrize("body, asks", [
    ("Please wire the funds by Friday.", True),
    ("Send me your bank details and the routing number.", True),
    ("You can pay the invoice in BTC.", True),
    ("Could you buy three gift cards and send me the codes?", True),
    ("Thanks for your time: we'll send you a $50 gift card after the call.", False),
    ("We help banks cut fraud on wire payments.", False),
])
def test_a_request_for_money_by_wire_bank_crypto_or_gift_card_is_refused(body, asks):
    problems = leads.send_problems(["ana@acme.com"], "Hello", body, set(), set())
    assert (problems == ["it asks for money by wire, bank details, crypto or gift cards"]) is asks and (problems == []) is not asks


def test_a_domain_the_user_listed_may_be_linked_and_any_other_is_not_sent(send):
    from src.agent_runtime import prefs

    run, gmail, _ = send
    assert "calendly.com" in refused(run(body="Book here: https://calendly.com/me"))
    gmail.assert_not_called()
    asyncio.run(prefs.put("u", "sending", {"domains": ["calendly.com"]}))
    assert not run(body="Book here: https://calendly.com/me").get("is_error")


# --- the bounce stop ([20] item 3)
def _sends(tmp_path, sent: int, bounced: int, at="2026-11-16T10:00:00+00:00"):
    async def write():
        from src.database import get_chat_repository, save_artifact

        await (await get_chat_repository()).create_chat({"user_id": "u", "chat_id": "chat-0"}, "omni")
        rows = [{"plan_id": "p0", "to": f"p{n}@acme.com", "status": "sent", "at": f"{at[:-9]}{n:02d}+00:00"} for n in range(sent)]
        rows += [{"plan_id": "p0", "to": f"p{n}@acme.com", "status": "bounced", "at": at} for n in range(bounced)]
        (path := tmp_path / "send_log-p0.json").write_text(json.dumps({"rows": rows}))
        await save_artifact({"id": "send_log-p0", "chat_id": "chat-0", "persona": "outreach", "kind": "send_log", "title": "log",
                             "path": str(path), "row_count": len(rows), "source": "", "created_at": at})
    asyncio.run(write())


def test_too_many_bounces_stop_new_first_emails_until_the_user_clears_it(send, tmp_path):
    from src.agent_runtime import prefs

    run, gmail, _ = send
    _sends(tmp_path, sent=40, bounced=3)  # 3 of 40 is 7.5%: over 5%, and at least 3
    assert "3 of your last 40 sends bounced (8%, over the 5% limit)" in refused(run())
    assert not run(thread_id="t1").get("is_error")  # a follow-up or a reply still goes
    assert not run(step=2).get("is_error")
    asyncio.run(prefs.put("u", "sending", {"bounces_cleared_at": "2026-11-17T00:00:00+00:00"}))  # sends before it stop counting
    assert not run().get("is_error")


@pytest.mark.parametrize("sent, bounced, stops", [(100, 5, False), (100, 6, True), (20, 2, False)])
def test_the_stop_needs_more_than_5_percent_and_at_least_3(temp_db, tmp_path, sent, bounced, stops):
    _sends(tmp_path, sent, bounced)
    assert bool(asyncio.run(leads.bounce_stop("u"))) is stops
