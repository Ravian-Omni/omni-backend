"""treg, the outside data layer (contracts [9] and [10]): a person found at a company by title, a work email found and
checked in one call. No live call: treg's MCP `call` tool is faked with answers shaped as its docs describe them."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.agent_runtime import leads, treg
from src.agent_runtime.tools import treg as treg_tool
from src.database import data_spent, record_data_spend, suppress_email
from src.mcp_client.client import is_connected
from src.omni import signal_play
from src.routers import hands_mcp as hm
from tests.unit.test_leads import run_completions, tally, temp_db  # noqa: F401 - the temp_db fixture

SEARCH, FIND = "treg.people.search", "treg.people.email.find"


@pytest.fixture(autouse=True)
def token(monkeypatch):
    monkeypatch.setenv("TREG_TOKEN", "t-123")
    monkeypatch.delenv("DAXAGENT_TREG_RUN_USD", raising=False)
    treg.runs.clear()


def reply(body, cost=0.0123, status=200):
    """What treg's MCP `call` tool returns: the upstream status, the routed answer as `body`, and the charge as `cost_usd`."""
    return json.dumps({"status": status, "endpoint_id": "x", "call_id": "call-1", "body": body, **({"cost_usd": cost} if cost is not None else {})})


def found(email="jane@acme.com", verdict="valid", checked=True, verified=True, **meta):
    """A routed email find answered with its check (X-Treg-Route-Verify: true)."""
    check = {"verdict": verdict, "checked": checked, "served_by": "bounceban", "cost_micro": 4000}
    return {"output": {"email": email, "confidence": 0.9, "verified": verified}, "raw": {},
            "_treg": {"served_by": "hunter.email.finder", "outcome": "hit", "charged_micro": 21000, "verification": check, **meta}}


def people(*rows):
    return {"output": {"people": list(rows), "count": len(rows)}, "raw": {}, "_treg": {"served_by": "icypeas", "outcome": "hit", "charged_micro": 380}}


class FakeTreg:
    """treg.call_tool: search answers one fixed list, a find answers by the name asked for."""

    def __init__(self, rows=(), finds=None, search_cost=0.002, find_cost=0.02):
        self.rows, self.finds, self.search_cost, self.find_cost, self.calls = rows, finds or {}, search_cost, find_cost, []

    async def __call__(self, server, tool, arguments):
        assert (server, tool) == ("treg", "call")
        self.calls.append(arguments)
        if arguments["endpoint_id"] == SEARCH:
            return reply(people(*self.rows), self.search_cost)
        answer = self.finds[arguments["body"]["full_name"]]
        return answer if isinstance(answer, str) else reply(answer, self.find_cost)

    def of(self, endpoint):
        return [c for c in self.calls if c["endpoint_id"] == endpoint]


def run(*args, **kw):
    return asyncio.run(treg.find_contacts("u", "chat-1", *args, **kw))


@pytest.mark.parametrize("verdict, status", [("valid", "valid"), ("catch_all", "catch_all"), ("risky", "risky"), ("unknown", "unknown"),
                                             ("invalid", "invalid"), ("deliverable", "unknown")])  # a word treg does not use fails closed
def test_the_checks_verdict_is_the_email_status_not_the_finders_claim(verdict, status):
    answer = found(verdict=verdict, verified=True)  # the finder says verified; treg's check wins
    assert treg.email_status(answer) == status
    gate = leads.gate({"full_name": "Jane Doe", "email": "jane@acme.com", "email_status": treg.email_status(answer)}, set(), set())
    assert (gate[0] == "pass") == (status == "valid")
    if status != "valid":
        assert gate == ("fail", f"email not verified: {status}")


def test_a_check_that_did_not_run_or_an_address_at_another_domain_fails_the_gate():
    assert treg.email_status(found(checked=False)) == "unchecked"
    assert treg.email_status(found(domain_match=False)) == "other_domain"  # a former employer's address, however valid
    assert treg.email_status({"output": {"email": "a@b.com"}, "_treg": {}}) == "unchecked"  # no check asked for
    assert leads.gate({"full_name": "Jane Doe", "email": "jane@acme.com", "email_status": "unchecked"}, set(), set()) == ("fail", "email not verified: unchecked")


def test_a_named_person_skips_the_search_and_every_call_carries_the_ceiling(temp_db, monkeypatch):
    fake = FakeTreg(finds={"Jane Doe": found()})
    monkeypatch.setattr(treg, "call_tool", fake)
    result = run("https://www.acme.com/about", person="Jane Doe")
    assert fake.of(SEARCH) == [] and len(fake.of(FIND)) == 1
    call = fake.of(FIND)[0]
    assert call["body"] == {"full_name": "Jane Doe", "domain": "acme.com"}
    assert call["headers"] == {"X-Treg-Route-Max-Cost": "0.05", "X-Treg-Route-Verify": "true"}  # the check rides on the find
    (contact,) = result["contacts"]
    assert (contact["email"], contact["email_status"], contact["gate"]) == ("jane@acme.com", "valid", "pass")
    assert contact["email_source"] == "treg:hunter.email.finder" and contact["company_domain"] == "acme.com"


def test_a_search_asks_for_one_title_at_the_domain_and_carries_no_verify_header(temp_db, monkeypatch):
    fake = FakeTreg(rows=[{"name": "Jane Doe", "title": "VP Sales", "company": "Acme", "profile_url": "https://linkedin.com/in/jd", "title_match": "current"}],
                    finds={"Jane Doe": found()})
    monkeypatch.setattr(treg, "call_tool", fake)
    result = run("acme.com", titles=["VP Sales", "CRO"], limit=1)
    (search,) = fake.of(SEARCH)  # one person wanted, found by the first title: no second search
    assert {k: v for k, v in search.items() if k != "idempotency_key"} == {
        "endpoint_id": SEARCH, "body": {"title": "VP Sales", "company_domain": "acme.com", "limit": treg.SEARCH_ROWS}, "headers": {"X-Treg-Route-Max-Cost": "0.05"}}
    assert search["idempotency_key"] != fake.of(FIND)[0]["idempotency_key"]  # a key per call, so a repeat of one call is free and a new call is new
    assert result["contacts"][0]["title"] == "VP Sales" and result["contacts"][0]["linkedin_url"] == "https://linkedin.com/in/jd"


def test_nobody_is_paid_for_who_would_fail_the_gate_anyway(temp_db, monkeypatch):
    asyncio.run(suppress_email("u", "zed@acme.com", "unsubscribed"))
    rows = [{"name": "Jane Doe", "title_match": "current"},
            {"name": "Bob", "title_match": "current"},                                   # no full name
            {"name": "Pat Past", "title_match": "past", "title_until": "2025-01-01"},     # left the role
            {"name": "Sam Roe", "email": "info@acme.com"},                               # a shared inbox
            {"name": "Zed Sup", "email": "zed@acme.com"},                                # suppressed
            {"name": "Mask Ed", "email": "m***@acme.com"}]                               # masked by the source
    fake = FakeTreg(rows=rows, finds={"Jane Doe": found()})
    monkeypatch.setattr(treg, "call_tool", fake)
    result = run("acme.com", titles=["CRO"], limit=3)
    assert [c["body"]["full_name"] for c in fake.of(FIND)] == ["Jane Doe"]  # the only paid email call
    assert {s["name"]: s["why"] for s in result["skipped"]} == {
        "Bob": "no full name", "Pat Past": "no longer holds the title", "Sam Roe": "shared or role inbox", "Zed Sup": "suppressed",
        "Mask Ed": "masked by the source"}


def test_a_play_where_no_email_passes_returns_each_reason_for_the_rejection(temp_db, monkeypatch):
    fake = FakeTreg(rows=[{"name": "Jane Doe"}, {"name": "Ann Lee"}, {"name": "Raj Rao"}],
                    finds={"Jane Doe": found(verdict="catch_all"), "Ann Lee": found("ann@acme.com", "risky"), "Raj Rao": found(None, "unknown", checked=False)})  # the last is a miss: nothing found, nothing to check
    monkeypatch.setattr(treg, "call_tool", fake)
    result = run("acme.com", titles=["CRO"], limit=3)
    assert [(c["email_status"], c["gate"], c["gate_reason"]) for c in result["contacts"]] == [
        ("catch_all", "fail", "email not verified: catch_all"), ("risky", "fail", "email not verified: risky"), ("", "fail", "no email")]


def test_the_charge_treg_reports_is_recorded_per_call_and_the_checked_address_with_it(temp_db, monkeypatch):
    fake = FakeTreg(rows=[{"name": "Jane Doe"}], finds={"Jane Doe": found(verdict="catch_all")}, search_cost=0.0004, find_cost=0.0211)
    monkeypatch.setattr(treg, "call_tool", fake)
    result = run("acme.com", titles=["CRO"])
    assert result["spent_usd"] == 0.0215 and result["run_spent_usd"] == 0.0215 and result["run_left_usd"] == 0.4785
    assert asyncio.run(data_spent("chat-1", "")) == pytest.approx(0.0215)
    assert asyncio.run(leads.checked_emails("chat-1")) == {"jane@acme.com": "catch_all"}


def test_without_a_cost_header_the_answers_own_charge_counts(temp_db, monkeypatch):
    async def no_header(server, tool, arguments):
        return json.dumps({"status": 200, "body": found()})  # `charged_micro` 21000 inside the answer

    monkeypatch.setattr(treg, "call_tool", no_header)
    run("acme.com", person="Jane Doe")
    assert asyncio.run(data_spent("chat-1", "")) == pytest.approx(0.021)


def test_the_run_stops_paying_when_one_more_call_could_pass_its_cap(temp_db, monkeypatch):
    monkeypatch.setenv("DAXAGENT_TREG_RUN_USD", "0.07")
    fake = FakeTreg(rows=[{"name": "Jane Doe"}, {"name": "Ann Lee"}], finds={"Jane Doe": found(), "Ann Lee": found("ann@acme.com")}, find_cost=0.03)
    monkeypatch.setattr(treg, "call_tool", fake)
    result = run("acme.com", titles=["CRO"], limit=2)  # search 0.002, find 0.03: 0.038 left, under the 0.05 ceiling
    assert len(fake.of(FIND)) == 1 and [c["full_name"] for c in result["contacts"]] == ["Jane Doe"]
    assert result["problems"] == ["this run's treg budget is used up"] and result["stopped_because"] == "budget_used_up"
    assert result["run_spent_usd"] == 0.032 and result["run_left_usd"] == 0.038
    again = run("acme.com", person="Ann Lee")
    assert again["contacts"] == [] and len(fake.calls) == 2  # nothing more is called, whoever asks


def test_the_cap_counts_from_the_runs_start_and_a_default_cap_applies(temp_db, monkeypatch):
    asyncio.run(record_data_spend("chat-1", FIND, 0.45))
    assert treg.run_cap() == 0.50 and not asyncio.run(treg.out("chat-1", ""))  # 0.05 left: one call fits exactly...
    asyncio.run(record_data_spend("chat-1", FIND, 0.0001))
    assert asyncio.run(treg.out("chat-1", ""))  # ...a hair less does not
    treg.begin_run("chat-1", "9999-01-01")  # a new run on the same chat starts from nothing
    assert asyncio.run(treg.spent("chat-1", "9999-01-01")) == 0 and not asyncio.run(treg.out("chat-1", "9999-01-01"))


def test_a_dropped_connection_counts_the_most_one_call_can_cost(temp_db, monkeypatch):
    monkeypatch.setattr(treg, "call_tool", AsyncMock(side_effect=ConnectionError("closed")))
    result = run("acme.com", person="Jane Doe")
    assert result["contacts"] == [] and "treg call failed" in result["problems"][0]
    assert result["spent_usd"] == 0.05  # treg may have answered and charged before the line dropped


def test_a_refusal_is_reported_and_costs_what_treg_says(temp_db, monkeypatch):
    refused = reply({"detail": "insufficient_balance"}, cost=0, status=402)
    monkeypatch.setattr(treg, "call_tool", FakeTreg(finds={"Jane Doe": refused}))
    result = run("acme.com", person="Jane Doe")
    assert result["contacts"] == [] and result["problems"][0].startswith("treg 402") and result["spent_usd"] == 0


def test_a_company_without_a_domain_or_a_search_term_is_not_searched(temp_db, monkeypatch):
    fake = FakeTreg()
    monkeypatch.setattr(treg, "call_tool", fake)
    assert run("")["problems"] == ["no company domain: give the company's website"]
    assert run("acme.com")["problems"] == ["give the person's name or the titles to search for"]
    assert fake.calls == []


def test_the_tool_is_there_only_with_a_token_and_only_for_the_agents_the_server_names(monkeypatch):
    ctx = lambda persona: SimpleNamespace(persona=persona, user_id="u", chat_id="chat-1", data_sources=set())  # noqa: E731
    assert [t.name for t in treg_tool.build(ctx("signal_play"))] == ["treg__find_contacts"]
    assert [t.name for t in treg_tool.build(ctx("contact_enricher"))] == ["treg__find_contacts"]
    assert treg_tool.build(ctx("outreach")) == []
    monkeypatch.delenv("TREG_TOKEN")
    assert not treg.configured() and treg_tool.build(ctx("signal_play")) == []  # no token: absent, the play runs as it did


def test_the_token_comes_from_the_environment(temp_db, monkeypatch):
    assert asyncio.run(is_connected("treg"))
    monkeypatch.delenv("TREG_TOKEN")
    assert not asyncio.run(is_connected("treg"))


def test_an_address_treg_checked_keeps_treg_s_word_whatever_the_saved_row_says(temp_db):
    asyncio.run(record_data_spend("chat-1", FIND, 0.02, "c1", "Jane@Acme.com", "catch_all"))
    rows = [{"full_name": "Jane Doe", "email": "jane@acme.com", "email_status": "valid", "email_verified": True},  # the agent wrote "valid"
            {"full_name": "Ann Lee", "email": "ann@acme.com", "email_status": "valid"}]                            # not one treg checked
    asyncio.run(leads.mark("u", "chat-1", rows))
    assert (rows[0]["gate"], rows[0]["gate_reason"], rows[0]["email_status"]) == ("fail", "email not verified: catch_all", "catch_all")
    assert rows[1]["gate"] == "pass"


def test_the_completion_carries_dollars_beside_credits_and_says_when_the_cap_ended_it(monkeypatch):
    monkeypatch.setattr(hm.treg, "spent", AsyncMock(return_value=0.46))
    monkeypatch.setattr(hm.treg, "out", AsyncMock(return_value=True))
    t, notes, done = run_completions(monkeypatch, [tally(1, 5)], target=0)  # a play: no target
    assert done[0]["data_spend_usd"] == 0.46 and done[0]["credits_spent"] == 0 and done[0]["leads"]["stopped_because"] == "budget_used_up"
    t, notes, done = run_completions(monkeypatch, [tally(1, 5 + 1)], target=5)  # a target not met, the dollars gone: it ends, it does not go on
    assert notes == [] and done[0]["leads"]["stopped_because"] == "budget_used_up"


def test_a_run_that_has_not_spent_at_treg_reports_zero_and_no_stop(monkeypatch):
    monkeypatch.setattr(hm.treg, "spent", AsyncMock(return_value=0.0))
    monkeypatch.setattr(hm.treg, "out", AsyncMock(return_value=False))
    t, notes, done = run_completions(monkeypatch, [tally(2, 9)], target=0)
    assert done[0]["data_spend_usd"] == 0 and "stopped_because" not in done[0]["leads"]


def test_target_titles_are_kept_as_a_checked_list():
    goal, why = signal_play.prepare('SIGNAL PLAY: {"company": "Acme", "date": "2026-11-14", "url": "https://x.co/a", '
                                    '"target_titles": ["VP Sales", " Head  of Revenue ", 7, ""], "website": "acme.com"}')
    assert why == "" and json.loads(goal.removeprefix("SIGNAL PLAY:"))["target_titles"] == ["VP Sales", "Head of Revenue"]
    _, why = signal_play.prepare('SIGNAL PLAY: {"company": "Acme", "date": "2026-11-14", "url": "https://x.co/a", "target_titles": ["' + "x" * 301 + '"]}')
    assert "target_titles" in why and why.startswith("SIGNAL PLAY rejected")
    goal, _ = signal_play.prepare('SIGNAL PLAY: {"company": "Acme", "date": "2026-11-14", "url": "https://x.co/a", "target_titles": "VP Sales"}')
    assert "target_titles" not in goal  # not a list: ignored


def test_a_play_whose_people_all_failed_the_gate_ends_with_the_rejection(temp_db, monkeypatch):
    monkeypatch.setattr(leads, "tally", AsyncMock(return_value=tally(0, 2, **{"email not verified: catch_all": 1, "no email": 1})))
    assert asyncio.run(signal_play.unmet("chat-1", "")) == "SIGNAL PLAY rejected: no contact passed (1 email not verified: catch_all, 1 no email)"
    monkeypatch.setattr(leads, "tally", AsyncMock(return_value=tally(1, 2)))
    assert asyncio.run(signal_play.unmet("chat-1", "")) == ""  # one passed
    monkeypatch.setattr(leads, "tally", AsyncMock(return_value=tally(0, 0)))
    assert asyncio.run(signal_play.unmet("chat-1", "")) == ""  # none saved: the play says why itself
    monkeypatch.setattr(leads, "tally", AsyncMock(return_value=tally(0, 2, **{"no email": 2})))
    monkeypatch.delenv("TREG_TOKEN")
    assert asyncio.run(signal_play.unmet("chat-1", "")) == ""  # without treg the play ends as it always has
