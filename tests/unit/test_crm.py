"""The CRM over MCP (contract [16]): off without both settings, every write keyed so a repeat adds nothing, its
do-not-contact list copied into DAX's own, and a CRM that is down never holding anything up. The CRM is faked."""

import asyncio
import json
from types import SimpleNamespace

import pytest

from src.agent_runtime import crm, leads
from src.agent_runtime.tools import crm as crm_tools
from src.database import list_suppressed, note_source_emails
from tests.unit.test_leads import temp_db  # noqa: F401 - the temp_db fixture


class FakeCRM:
    def __init__(self, answers=None):
        self.calls, self.answers = [], answers or {}

    async def __call__(self, server, tool, args):
        assert server == "crm"
        self.calls.append((tool, args))
        return json.dumps(self.answers.get(tool, {"id": 0, "url": "https://crm/x", "created": True}))


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setenv("CRM_MCP_URL", "https://crm.example/mcp")
    monkeypatch.setenv("CRM_API_KEY", "k")
    f = FakeCRM()
    monkeypatch.setattr(crm, "call_tool", f)
    return f


def settle():
    async def go():
        await asyncio.gather(*list(crm._tasks))
    return go()


def test_without_both_settings_nothing_is_called_and_no_agent_gets_crm_tools(monkeypatch):
    calls = FakeCRM()
    monkeypatch.setattr(crm, "call_tool", calls)
    monkeypatch.delenv("CRM_MCP_URL", raising=False)
    monkeypatch.setenv("CRM_API_KEY", "k")
    assert asyncio.run(crm.call("find_contact", email="a@b.com")) is None and calls.calls == []
    assert crm_tools.build(SimpleNamespace(persona="meeting_prep")) == []


def test_only_meeting_prep_and_recovery_note_get_the_read_tools(fake):
    names = lambda persona: [t.name for t in crm_tools.build(SimpleNamespace(persona=persona, data_sources=set()))]  # noqa: E731
    assert names("meeting_prep") == names("recovery_note") == ["crm__find_contact", "crm__get_record"]
    assert names("outreach") == names("contact_enricher") == []


def test_a_lead_that_passes_goes_to_the_crm_as_company_then_person(temp_db, fake):
    async def go():
        await note_source_emails("chat-1", "data-axle", {"jo@acme.com"})
        rows = [{"email": "jo@acme.com", "full_name": "Jo Park", "company": "Acme", "website": "https://www.acme.com", "title": "CTO",
                 "first_name": "", "last_name": "", "contact_infogroupId": "889", "email_status": "verified"},
                {"email": "info@acme.com", "first_name": "No", "last_name": "Lead"}]  # a shared inbox: fails, never sent
        await leads.mark("u", "chat-1", rows)
        await settle()
    asyncio.run(go())
    assert [t for t, _ in fake.calls] == ["upsert_company", "upsert_contact"]
    assert fake.calls[0][1] == {"website": "acme.com", "name": "Acme"}
    contact = fake.calls[1][1]
    assert contact["email"] == "jo@acme.com" and contact["first_name"] == "Jo" and contact["website"] == "acme.com"
    assert contact["source"] == "dax" and contact["external"] == {"dax_chat_id": "chat-1", "data_axle_id": "889"}


def test_a_lead_with_no_first_name_uses_the_email_s_local_part(fake):
    asyncio.run(crm.lead({"email": "jdoe@acme.com"}, "chat-1"))
    assert fake.calls == [("upsert_contact", {"email": "jdoe@acme.com", "first_name": "jdoe", "source": "dax",
                                              "external": {"dax_chat_id": "chat-1"}})]  # no website: no company, and no link


def test_an_email_or_reply_is_logged_on_contact_0_keyed_on_its_gmail_message(fake):
    fake.answers["find_contact"] = {"id": 0, "email": "jo@acme.com"}
    asyncio.run(crm.activity("Jo@Acme.com", "reply", "Sounds good, call me", "msg-1"))
    assert fake.calls[-1] == ("log_activity", {"about": {"kind": "contact", "id": 0}, "kind": "reply", "text": "Sounds good, call me", "key": "msg-1"})
    fake.answers["find_contact"] = None
    asyncio.run(crm.activity("ghost@acme.com", "email_sent", "hi", "msg-2"))
    assert fake.calls[-1][0] == "find_contact"  # unknown to the CRM: nothing logged


def test_suppressions_from_the_crm_join_dax_s_own_list_and_a_domain_stops_its_addresses(temp_db, fake):
    fake.answers["list_suppressed"] = {"suppressed": [
        {"id": 0, "value": "ana@acme.com", "kind": "email", "reason": "asked to stop", "source": "web", "created_at": "2026-11-16T10:00:00Z"},
        {"id": 1, "value": "rival.com", "kind": "domain", "reason": "competitor", "source": "web", "created_at": "2026-11-16T11:00:00Z"}]}
    assert asyncio.run(crm.pull_suppressed("u")) == 2
    suppressed = asyncio.run(list_suppressed("u"))
    assert suppressed == {"ana@acme.com", "rival.com"}
    assert leads.gate({"full_name": "Bo Diaz", "email": "bo@rival.com", "email_status": "valid"}, suppressed, set()) == ("fail", "suppressed")
    assert leads.send_problems(["bo@rival.com"], "Hi", "Hello", suppressed) == ["bo@rival.com is suppressed"]
    asyncio.run(crm.pull_suppressed("u"))
    assert fake.calls[-1] == ("list_suppressed", {"since": "2026-11-16T11:00:00Z"})  # the next pull asks only for what is new


def test_a_crm_that_refuses_is_down_or_hangs_never_raises_or_holds_up(fake, monkeypatch):
    async def refuse(server, tool, args):
        return "Unknown stage: nope"  # an error answer is plain text

    async def down(server, tool, args):
        raise ConnectionError("CRM unreachable")

    async def hang(server, tool, args):
        await asyncio.sleep(3600)

    monkeypatch.setattr(crm, "TIMEOUT_S", 0.05)
    for answer in (refuse, down, hang):
        monkeypatch.setattr(crm, "call_tool", answer)
        assert asyncio.run(crm.call("find_contact", email="a@b.com")) is None
        asyncio.run(crm.activity("a@b.com", "reply", "x", "m"))  # nothing raised
