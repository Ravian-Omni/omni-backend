"""The lead gate: a contact is a lead only when a named person has a business email of their own that the source checked,
and is not suppressed or written to before. It is decided in code when rows are saved and when a campaign renders; a lead
target keeps a run sourcing until it is met, the source is dry or a round limit is hit."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src import database
from src.agent_runtime import leads
from src.agent_runtime.tools import artifacts, campaign
from src.database import connection, get_chat_repository, save_artifact, suppress_email
from src.routers import hands_mcp as hm

GOOD = {"first_name": "Ana", "last_name": "Silva", "email": "ana@acme.com", "email_status": "verified", "company": "Acme"}


def verdict(**changes):
    return leads.gate({**GOOD, **changes}, {"gone@acme.com"}, {"met@acme.com"})


def test_a_named_person_with_a_checked_business_email_of_their_own_passes():
    assert verdict() == ("pass", "")
    assert verdict(email_verified=True, email_status="")[0] == "pass"
    assert verdict(first_name="", last_name="", contact_name="Ana Silva")[0] == "pass"  # a full name in one column


@pytest.mark.parametrize("changes, why", [
    ({"email": "info@acme.com"}, "shared or role inbox"),
    ({"email": "newbiz@acme.com"}, "shared or role inbox"),
    ({"email": "Sales@acme.com"}, "shared or role inbox"),
    ({"email": "no-reply@acme.com"}, "shared or role inbox"),
    ({"email_status": ""}, "email not checked by the source"),  # an email nobody verified
    ({"email_status": "unknown"}, "email not verified: unknown"),  # a source's word that is not a yes
    ({"email_status": "catch_all"}, "email not verified: catch_all"),
    ({"email": "ana@gmail.com"}, "free-mail address, not a business email"),
    ({"email": ""}, "no email"),
    ({"last_name": ""}, "no full name"),
    ({"first_name": "A***", "last_name": "S****"}, "masked by the source"),
    ({"email": "gone@acme.com"}, "suppressed"),
    ({"email": "met@acme.com"}, "already written to"),
])
def test_each_way_to_fail_the_gate_says_why(changes, why):
    assert verdict(**changes) == ("fail", why)


def test_the_source_name_columns_the_enrichers_really_write_are_read():
    row = {"contact_first_name": "Ana", "contact_last_name": "Silva", "business_email": "ana@acme.com", "email_status": "valid"}
    assert leads.gate(row, set(), set()) == ("pass", "")


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(connection.settings, "ROOT_DIR", str(tmp_path))
    monkeypatch.setattr(connection, "_db", None)
    monkeypatch.setattr(database, "_chat_repository", None)
    asyncio.run(connection.init_db())
    yield
    asyncio.run(connection.close_db())


@pytest.fixture
def ctx(temp_db, tmp_path):
    return SimpleNamespace(chat_id="chat-1", user_id="u", persona="contact_enricher", task_id=None, artifacts_dir=str(tmp_path),
                           data_sources=set(), emit=AsyncMock())


def test_every_enriched_contacts_row_is_marked_with_its_gate_when_saved(ctx):
    rows = [dict(GOOD), {**GOOD, "email": "info@acme.com"}, {**GOOD, "email": "gone@acme.com", "email_status": "verified"}]

    async def scenario():
        await suppress_email("u", "Gone@Acme.com", "unsubscribe")
        record = await artifacts.write(ctx, "enriched_contacts", "Contacts", rows)
        return record, json.load(open(record["path"]))

    record, payload = asyncio.run(scenario())
    assert [(r["gate"], r["gate_reason"]) for r in payload["rows"]] == [("pass", ""), ("fail", "shared or role inbox"), ("fail", "suppressed")]
    assert {"gate", "gate_reason"} <= set(payload["columns"])  # shown in the table


def test_a_campaign_renders_only_for_the_contacts_that_pass(ctx, tmp_path):
    plan = {"rows": [{"segment": "all", "step": 1, "channel": "email", "status": "approved", "subject": "Hi {{first_name}}", "body": "Hello {{first_name}}."}],
            "meta": {"audience_artifact_id": "enriched_contacts-a1", "brief": {"opt_out": "Reply STOP", "postal_address": "1 Main St"}}}
    audience = [dict(GOOD), {**GOOD, "first_name": "Bo", "email": "info@bo.com"}, {**GOOD, "first_name": "Cy", "email": "cy@bo.com", "email_status": ""}]
    (tmp_path / "campaign_plan-p1.json").write_text(json.dumps(plan))
    (tmp_path / "enriched_contacts-a1.json").write_text(json.dumps({"rows": audience}))
    out = asyncio.run(campaign.render_plan(ctx, "campaign_plan-p1"))
    assert [m["to"] for m in out["ready"]] == ["ana@acme.com"]
    assert out["skipped"] == {"not a lead: shared or role inbox": 1, "not a lead: email not checked by the source": 1}


def test_follow_ups_to_contacts_already_written_to_still_go_but_shared_inboxes_do_not(ctx, tmp_path):
    # the live goal: follow-ups due to 6 people whose rows carry no email_status: the 3 named go, the 3 shared inboxes are skipped
    steps = [{"segment": "all", "step": n, "channel": "email", "status": "approved", "subject": "Hi {{first_name}}", "body": "Note {{first_name}}.",
              "send_after_days": 3 * (n - 1)} for n in (1, 2)]
    plan = {"rows": steps, "meta": {"audience_artifact_id": "enriched_contacts-a1", "brief": {"opt_out": "Reply STOP", "postal_address": "1 Main St"}}}
    named = [{"first_name": n, "last_name": "Lee", "email": f"{n.lower()}@acme.com", "company": "Acme"} for n in ("Ana", "Bo", "Cy")]
    shared = [{"first_name": "Dee", "last_name": "Lee", "email": f"{box}@acme.com", "company": "Acme"} for box in ("info", "newbiz", "hello")]
    (tmp_path / "campaign_plan-p1.json").write_text(json.dumps(plan))
    (tmp_path / "enriched_contacts-a1.json").write_text(json.dumps({"rows": named + shared}))

    async def scenario():
        for row in named + shared:  # step 1 went out five days ago
            await campaign.record(ctx, "campaign_plan-p1", {"to": row["email"], "status": "sent", "step": 1, "at": "2026-11-11T10:00:00+00:00"})
        await campaign.record(ctx, "campaign_plan-p1", {"to": "cy@acme.com", "status": "bounced"})  # a bounce takes the proof away
        return await campaign.render_plan(ctx, "campaign_plan-p1", 2)

    out = asyncio.run(scenario())
    assert sorted(m["to"] for m in out["ready"]) == ["ana@acme.com", "bo@acme.com"]
    assert out["skipped"] == {"not a lead: shared or role inbox": 3, "not a lead: email not checked by the source": 1}


def test_a_contact_this_chat_wrote_to_is_not_a_duplicate_but_another_chats_is(ctx, tmp_path):
    async def scenario():
        for chat, log in (("chat-1", "mine"), ("chat-2", "theirs")):
            await (await get_chat_repository()).create_chat({"user_id": "u", "chat_id": chat}, "omni")
            path = tmp_path / f"send_log-{log}.json"
            path.write_text(json.dumps({"rows": [{"to": "mine@acme.com" if chat == "chat-1" else "theirs@acme.com", "status": "sent"},
                                                 {"to": "draft@acme.com", "status": "drafted"}]}))
            await save_artifact({"id": f"send_log-{log}", "chat_id": chat, "persona": "outreach", "kind": "send_log", "title": "log",
                                 "path": str(path), "row_count": 2, "source": "", "created_at": "2026-11-16T10:00:00+00:00"})
        return await leads.contacted("u", "chat-1")

    assert asyncio.run(scenario()) == {"theirs@acme.com"}  # a draft is not "written to", and this chat's own sends are its follow-ups


# --- the lead target: sourcing continues until it is met, the source is dry or the round limit is hit
def thread(target=3):
    t = object.__new__(hm.HandsThread)
    t.chat_id, t.queue, t.lead_target, t.rounds, t.seen, t.agenda_id = "chat-1", asyncio.Queue(), target, 0, 5, ""
    t.pending, t.ready, t.notes, t.say, t.task = False, False, {}, AsyncMock(), SimpleNamespace(done=lambda: False)
    t.ask_text, t.plan, t.polling, t.last_poll, t.started_at = "", [], 0, 0.0, "2000-01-01T00:00:00+00:00"
    t.key, t.request = "key-1", ""
    t.stop_reason, t.asked_at, t.last_event = "", None, 0.0
    return t


def run_completions(monkeypatch, tallies, **thread_args):
    """One completion per tally; returns the thread, the notes the manager got and the completions that reached the caller."""
    notes, pending = [], iter(tallies)
    monkeypatch.setattr(hm.leads, "tally", AsyncMock(side_effect=lambda _chat: next(pending)))
    monkeypatch.setattr(hm.needs, "credits_approved", AsyncMock(return_value=0))
    monkeypatch.setattr(hm, "get_websocket_manager", AsyncMock(return_value=SimpleNamespace(add_note=lambda chat, text: notes.append(text))))
    t = thread(**thread_args)

    async def go():
        for _ in tallies:
            await t.send_json({"type": "completion", "status": "complete"})

    asyncio.run(go())
    return t, notes, [t.queue.get_nowait() for _ in range(t.queue.qsize())]


def tally(passed, seen, **failed):
    return {"passed": passed, "seen": seen, "failed": failed}


def test_sourcing_goes_on_until_the_target_is_met_and_the_completion_says_so(monkeypatch):
    t, notes, done = run_completions(monkeypatch, [tally(1, 8, **{"shared or role inbox": 7}), tally(3, 14, **{"shared or role inbox": 11})])
    assert len(notes) == 1 and "Lead target: 3" in notes[0] and "7 shared or role inbox" in notes[0]  # one more round, then done
    assert len(done) == 1 and done[0]["leads"] == {"target": 3, "passed": 3, "failed": {"shared or role inbox": 11}, "stopped_because": "target_met"}


def test_a_round_that_finds_nothing_new_ends_it_as_the_source_dry(monkeypatch):
    t, notes, done = run_completions(monkeypatch, [tally(1, 5)])  # 5 contacts seen when the round began, still 5
    assert notes == [] and done[0]["leads"]["stopped_because"] == "source_dry" and done[0]["leads"]["passed"] == 1


def test_the_round_limit_ends_a_run_that_never_dries_or_meets_its_target(monkeypatch):
    t, notes, done = run_completions(monkeypatch, [tally(1, 6 + i) for i in range(leads.MAX_ROUNDS + 1)])
    assert len(notes) == leads.MAX_ROUNDS and done[0]["leads"]["stopped_because"] == "round_limit"


def test_a_run_without_a_target_just_reports_its_leads_and_a_stopped_run_is_not_continued(monkeypatch):
    t, notes, done = run_completions(monkeypatch, [tally(2, 9)], target=0)
    assert notes == [] and done[0]["leads"] == {"target": None, "passed": 2, "failed": {}}
    monkeypatch.setattr(hm.leads, "tally", AsyncMock(return_value=tally(0, 9)))
    t = thread()
    asyncio.run(t.send_json({"type": "completion", "status": "cancelled"}))
    assert t.queue.get_nowait()["leads"]["stopped_because"] == "stopped"
