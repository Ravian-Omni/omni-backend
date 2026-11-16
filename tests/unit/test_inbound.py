"""Partner referrals and booked meetings, told to Brain_Hands on the reply-check round (contract [12], [13]). Gmail, the
calendar, the model and Brain_Hands are faked."""

import asyncio
import json

import pytest

from src.agent_runtime import inbound, llm
from src.agent_runtime.tools import sales
from src.database import connection, save_artifact, save_pref
from src.services import brain_hands
from tests.unit.test_leads import temp_db  # noqa: F401 - the temp_db fixture

INTRO = "Hi! Meet Ana Silva (ana@acme.com) at Acme, she needs help with outbound. Also cc'ing my colleague bo@partner.com."


@pytest.fixture
def world(temp_db, monkeypatch, tmp_path):
    monkeypatch.setenv("BRAIN_HANDS_URL", "http://bh")
    pushed, asked, reads = [], [], []
    mail = [{"messageId": "m1", "sender": "Pat <pat@partner.com>", "subject": "Intro", "messageText": INTRO}]

    async def gmail_call(user_id, slug, args):
        asked.append(args["query"])
        return {"successful": True, "data": {"messages": mail}}

    async def complete(system, user, max_tokens=800, json_mode=False):
        reads.append(user)
        return json.dumps({"referred": [{"name": "Ana Silva", "email": "ana@acme.com", "company": "Acme"},
                                        {"name": "Pat", "email": "pat@partner.com"},           # the partner's own address
                                        {"name": "Ghost", "email": "ghost@nowhere.com"}]})     # not in the message

    async def push(kind, id, title, text, **data):
        pushed.append({"kind": kind, "id": id, "title": title, "text": text, "data": {k: v for k, v in data.items() if v}})
        return True

    async def composio_call(user_id, toolkit, slug, args, label):
        return {"successful": True, "data": {"items": [
            {"id": "e1", "status": "confirmed", "summary": "Acme intro", "start": {"dateTime": "2026-11-20T15:00:00Z"},
             "attendees": [{"email": "me@us.com"}, {"email": "Ana@Acme.com", "displayName": "Ana Silva"}]},
            {"id": "e2", "status": "cancelled", "summary": "Dropped", "start": {"dateTime": "2026-11-21T15:00:00Z"},
             "attendees": [{"email": "ana@acme.com"}]},
            {"id": "e3", "status": "confirmed", "summary": "Dentist", "start": {"dateTime": "2026-11-22T09:00:00Z"},
             "attendees": [{"email": "dr@teeth.com"}]}]}}

    monkeypatch.setattr(sales, "gmail_call", gmail_call)
    monkeypatch.setattr(sales, "composio_call", composio_call)
    monkeypatch.setattr(llm, "complete", complete)
    monkeypatch.setattr(brain_hands, "push", push)
    log = tmp_path / "send_log.json"
    log.write_text(json.dumps({"rows": [{"to": "ana@acme.com", "status": "sent"}]}))
    asyncio.run(save_artifact({"id": "send_log-1", "chat_id": "chat-a", "task_id": None, "persona": "outreach", "kind": "send_log", "title": "log",
                               "path": str(log), "row_count": 1, "source": "", "created_at": "2026-11-01T00:00:00"}))
    asyncio.run(save_pref("local_user", "agenda:chat-a", "agd_1"))

    async def own_chat():
        db = await connection.get_db()
        await db.execute("INSERT INTO chats (user_id, chat_id, collection, created_at, updated_at) VALUES ('local_user', 'chat-a', 'omni', '', '')")
        await db.commit()
    asyncio.run(own_chat())
    return pushed, asked, reads, mail


def test_a_partner_s_referral_is_pushed_once_with_only_the_person_named_in_the_mail(world):
    pushed, asked, reads, _ = world
    assert asyncio.run(inbound.referrals("local_user", ["pat@partner.com", "agency.com"], None)) == 1
    assert asked[0].startswith("from:(pat@partner.com OR agency.com) after:")  # only partners' mail is asked for
    assert pushed == [{"kind": "inbound", "id": "referral:m1", "title": "Referral from pat@partner.com: Ana Silva", "text": INTRO,
                       "data": {"source": "referral", "partner": "pat@partner.com", "website": "acme.com",
                                "email": "ana@acme.com", "name": "Ana Silva", "company": "Acme"}}]
    asyncio.run(inbound.referrals("local_user", ["pat@partner.com"], None))
    assert len(pushed) == 1 and len(reads) == 1  # the message is neither pushed nor read by the model again
    assert inbound._website("ana@gmail.com") == "" and inbound._website("ana@acme.com") == "acme.com"


def test_with_no_partner_or_no_brain_hands_nothing_is_read(world, monkeypatch):
    pushed, asked, reads, _ = world
    assert asyncio.run(inbound.referrals("local_user", ["", " "], None)) == 0
    monkeypatch.delenv("BRAIN_HANDS_URL")
    assert asyncio.run(inbound.referrals("local_user", ["pat@partner.com"], None)) == 0
    assert asyncio.run(inbound.meetings("local_user")) == 0
    assert asked == [] and reads == [] and pushed == []


def test_a_message_brain_hands_did_not_take_is_tried_again(world, monkeypatch):
    pushed, _, reads, _ = world
    monkeypatch.setattr(brain_hands, "push", lambda *a, **k: asyncio.sleep(0, result=False))
    assert asyncio.run(inbound.referrals("local_user", ["pat@partner.com"], None)) == 0
    monkeypatch.setattr(brain_hands, "push", lambda kind, id, title, text, **d: asyncio.sleep(0, result=pushed.append(id) is None))
    assert asyncio.run(inbound.referrals("local_user", ["pat@partner.com"], None)) == 1 and pushed == ["referral:m1"] and len(reads) == 2


def test_a_meeting_with_someone_dax_wrote_to_is_pushed_once_and_others_never(world):
    pushed, *_ = world
    assert asyncio.run(inbound.meetings("local_user")) == 1
    assert pushed == [{"kind": "meeting.booked", "id": "meeting:e1", "title": "Acme intro", "text": "2026-11-20T15:00:00Z with Ana Silva",
                       "data": {"email": "ana@acme.com", "name": "Ana Silva", "when": "2026-11-20T15:00:00Z", "event_id": "e1", "agenda_id": "agd_1"}}]
    assert asyncio.run(inbound.meetings("local_user")) == 0 and len(pushed) == 1  # e2 is cancelled, e3 has no one we wrote to


def test_the_round_runs_both_after_the_replies_and_not_in_a_dry_run(world, monkeypatch):
    from src.agent_runtime import prefs, watcher

    pushed, *_ = world
    asyncio.run(prefs.put("local_user", "inbox", {"partners": ["pat@partner.com"], "dry_run": True}))
    assert "referrals" not in asyncio.run(watcher.sweep("local_user")) and pushed == []
    asyncio.run(prefs.put("local_user", "inbox", {"partners": ["pat@partner.com"], "dry_run": False}))
    summary = asyncio.run(watcher.sweep("local_user"))
    assert (summary["referrals"], summary["meetings"]) == (1, 1)
