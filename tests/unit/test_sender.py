"""Deliverability: the sender's domain is checked for SPF, DKIM and DMARC before a send and only warns; a configured mailbox
is the one mail goes out from; a bounce suppresses the address for every later run."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src import database
from src.agent_runtime import inbox, leads, prefs, sender
from src.agent_runtime.tools import campaign, sales
from src.database import connection, list_suppressed
from tests.unit.test_leads import temp_db  # noqa: F401 - the temp_db fixture

RECORDS = {
    "acme.com": ["v=spf1 include:_spf.google.com ~all"],
    "_dmarc.acme.com": ["v=DMARC1; p=none"],
    "google._domainkey.acme.com": ["v=DKIM1; k=rsa; p=MIGfMA0"],
}


@pytest.fixture(autouse=True)
def fresh_caches(monkeypatch):
    monkeypatch.setattr(sender, "_domains", {})
    monkeypatch.setattr(sender, "_mailboxes", {})


def dns(monkeypatch, records, fail=()):
    async def txt(name, client):
        return None if any(name.endswith(f) for f in fail) else records.get(name, [])

    monkeypatch.setattr(sender, "_txt", txt)


def test_a_domain_with_all_three_records_has_no_warnings(monkeypatch):
    dns(monkeypatch, RECORDS)
    assert asyncio.run(sender.domain_warnings("acme.com")) == []


@pytest.mark.parametrize("missing, shown", [("acme.com", "no SPF record"), ("_dmarc.acme.com", "no DMARC record"), ("google._domainkey.acme.com", "No DKIM record")])
def test_each_missing_record_is_named(monkeypatch, missing, shown):
    dns(monkeypatch, {k: v for k, v in RECORDS.items() if k != missing})
    [warning] = asyncio.run(sender.domain_warnings("acme.com"))
    assert shown in warning


def test_a_lookup_that_fails_says_so_instead_of_claiming_a_record_is_missing(monkeypatch):
    dns(monkeypatch, RECORDS, fail=("acme.com",))
    [warning] = asyncio.run(sender.domain_warnings("acme.com"))
    assert warning.startswith("Could not check acme.com")


def test_the_answer_is_read_from_dns_over_https(monkeypatch):
    class Client:
        async def get(self, url, params, headers):
            assert url == "https://dns.google/resolve" and params["type"] == "TXT"
            return SimpleNamespace(json=lambda: {"Status": 0, "Answer": [{"type": 16, "data": '"v=spf1 ip4:1.2.3.4 " "~all"'}, {"type": 5, "data": "x"}]})

    assert asyncio.run(sender._txt("acme.com", Client())) == ["v=spf1 ip4:1.2.3.4 ~all"]


def test_a_free_mail_sender_is_warned_and_the_connected_account_is_the_default(temp_db, monkeypatch):
    gmail = AsyncMock(return_value={"successful": True, "data": {"response_data": {"emailAddress": "ana@gmail.com"}}})
    monkeypatch.setattr(sales, "gmail_call", gmail)
    [warning] = asyncio.run(sender.warnings("u"))
    assert "free-mail" in warning and "ana@gmail.com" in warning
    gmail.assert_awaited_once()
    asyncio.run(sender.warnings("u"))
    gmail.assert_awaited_once()  # the account is looked up once, not on every approval


def test_a_mailbox_in_settings_is_the_sender_and_its_domain_is_the_one_checked(temp_db, monkeypatch):
    dns(monkeypatch, {k: v for k, v in RECORDS.items() if k != "_dmarc.acme.com"})
    monkeypatch.setattr(sales, "gmail_call", AsyncMock(side_effect=AssertionError("the configured mailbox needs no profile lookup")))
    asyncio.run(prefs.put("u", "sending", {"mailbox": "sales@acme.com"}))
    assert asyncio.run(sender.mailbox("u")) == "sales@acme.com"
    assert "no DMARC record" in asyncio.run(sender.warnings("u"))[0]
    with pytest.raises(Exception):
        asyncio.run(prefs.put("u", "sending", {"mailbox": "not an address"}))


@pytest.fixture
def ask(temp_db, monkeypatch):
    """request_send_approval with a user who approves, and a sender whose domain has no DMARC."""
    dns(monkeypatch, {k: v for k, v in RECORDS.items() if k != "_dmarc.acme.com"})
    cards = []

    class Cards:
        async def confirm_send(self, **kw):
            cards.append(kw)
            return SimpleNamespace(approved=True, suggestion="")

    asyncio.run(prefs.put("u", "sending", {"mailbox": "sales@acme.com"}))
    ctx = SimpleNamespace(chat_id="chat-1", artifacts_dir="/nowhere", decisions=Cards(), send_allowance={}, send_approved=set(), user_id="u", remote_tool_classes={})
    return next(t for t in sales.build(ctx) if t.name == "request_send_approval").handler, cards


def test_the_warning_is_on_the_send_card_and_does_not_block_the_send(ask):
    handler, cards = ask
    result = asyncio.run(handler({"channel": "email", "recipients": ["ana@x.com"], "subject": "Hi", "body_preview": "Hello"}))
    assert "no DMARC record" in cards[0]["warnings"][0]
    assert '"approved": true' in result["content"][0]["text"] and "warnings" in result["content"][0]["text"]  # approved all the same


def test_a_configured_mailbox_is_the_from_address_of_a_new_email(temp_db, tmp_path, monkeypatch):
    ctx = SimpleNamespace(chat_id="chat-1", user_id="u", persona="outreach", task_id=None, artifacts_dir=str(tmp_path), data_sources=set(), emit=AsyncMock(),
                          decisions=None, send_allowance={"*": 9}, send_approved=set())
    asyncio.run(prefs.put("u", "sending", {"mailbox": "sales@acme.com"}))
    send = next(t for t in sales.build(ctx) if t.name == "gmail_send_email").handler
    gmail = AsyncMock(return_value={"successful": True, "data": {}})
    monkeypatch.setattr(sales, "gmail_call", gmail)
    asyncio.run(send({"to": "ana@x.com", "subject": "Hi", "body": "Hello"}))
    asyncio.run(send({"to": "ana@x.com", "subject": "Re", "body": "Hello again", "thread_id": "t1"}))
    assert gmail.await_args_list[0].args[2]["from_email"] == "sales@acme.com"
    assert "from_email" not in gmail.await_args_list[1].args[2]  # a reply keeps its thread's sender


def test_a_bounce_suppresses_the_address_for_every_later_run(temp_db, tmp_path, monkeypatch):
    ctx = SimpleNamespace(chat_id="chat-1", user_id="u", persona="outreach", task_id=None, artifacts_dir=str(tmp_path), data_sources=set(), emit=AsyncMock())
    bounce = {"to": "Gone@Acme.com", "from": "mailer-daemon@x.com", "message_id": "m1", "subject": "Undeliverable", "text": "failed", "thread_id": "t1"}
    monkeypatch.setattr(inbox, "open_handoff", AsyncMock(return_value={}))

    async def scenario():
        await campaign.settle_bounces(ctx, "campaign_plan-p1", [bounce])
        return await list_suppressed("u")

    suppressed = asyncio.run(scenario())
    assert suppressed == {"gone@acme.com"}
    assert leads.gate({"first_name": "Gil", "last_name": "One", "email": "gone@acme.com", "email_status": "verified"}, suppressed, set()) == ("fail", "suppressed")
