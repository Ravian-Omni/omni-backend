"""Contract [21] item 4: add_touch stores Brain_Hands' copy for one person as a draft step, exactly as given, only for a
person who passed the lead gate in that chat; a plan with no `to` rows renders as it did before. Nothing is sent."""

import asyncio
import json

import pytest

from src.agent_runtime import creatives
from src.agent_runtime.tools import artifacts, campaign
from src.database import get_chat_repository, save_artifact
from src.routers import hands_mcp as hm
from tests.unit.test_leads import GOOD, ctx, temp_db  # noqa: F401 - the fixtures

BRIEF = {"sender_name": "Lo Kumar", "sender_company": "MarketWatch", "postal_address": "1 Main St", "opt_out": "Reply STOP to opt out"}
BO = {**GOOD, "first_name": "Bo", "last_name": "Park", "email": "bo@acme.com"}
FIRST = "Hi {{first_name}}, Rival Co cut prices 20% on Nov 12 (Retail Weekly). For {{company}} that means a price-led pitch lands harder this month."


@pytest.fixture
def chat(ctx, tmp_path):
    """A chat with a contacts list (Ana passes, info@ does not) and, in another chat, an older plan whose brief has the sign-off."""
    async def setup():
        repo = await get_chat_repository()
        for chat_id in ("chat-1", "chat-0"):
            await repo.create_chat({"user_id": "u", "chat_id": chat_id}, "omni")
        await artifacts.write(ctx, "enriched_contacts", "Contacts", [dict(GOOD), dict(BO), {**GOOD, "email": "info@acme.com"}])
        (path := tmp_path / "campaign_plan-old00000.json").write_text(json.dumps({"rows": [], "meta": {"brief": BRIEF}}))
        await save_artifact({"id": "campaign_plan-old00000", "chat_id": "chat-0", "persona": "campaign_builder", "kind": "campaign_plan",
                             "title": "old", "path": str(path), "row_count": 0, "source": "", "created_at": "2026-11-01T10:00:00+00:00"})
    asyncio.run(setup())
    return ctx


def touch(to="ana@acme.com", subject="Rival Co's price cut", body=FIRST, days=0, plan_id=""):
    return asyncio.run(campaign.add_touch("u", "chat-1", to, subject, body, days, plan_id))


def plan_of(ctx, plan_id):
    return asyncio.run(artifacts.find(ctx, plan_id))[0]


def test_the_first_touch_starts_a_plan_with_the_copy_as_given_and_the_newest_sign_off(chat):
    out = touch()
    assert out["step"] == 1 and out["status"] == "draft" and out["plan_id"].startswith("campaign_plan-")
    plan = plan_of(chat, out["plan_id"])
    [row] = plan["rows"]
    assert {k: row[k] for k in ("segment", "to", "step", "role", "send_after_days", "channel", "subject", "body", "status")} == {
        "segment": "ana@acme.com", "to": "ana@acme.com", "step": 1, "role": "opener", "send_after_days": 0, "channel": "email",
        "subject": "Rival Co's price cut", "body": FIRST, "status": "draft"}
    assert plan["meta"]["brief"] == BRIEF and plan["meta"]["audience_artifact_id"].startswith("enriched_contacts-")


def test_later_touches_number_on_and_only_their_person_gets_them_after_the_user_approves(chat):
    plan_id = touch()["plan_id"]
    assert touch(subject="Two", body="Also: Rival Co hired a CMO on Nov 14.", days=3, plan_id=plan_id) == {"plan_id": plan_id, "step": 2, "status": "draft"}
    assert touch("bo@acme.com", "For Bo", "Hi Bo, a short note.", plan_id=plan_id)["step"] == 1  # a second person in the same plan

    async def approve_and_render():
        record, plan = await artifacts.load_record("chat-1", plan_id)
        for r in plan["rows"]:
            r["status"] = "approved"  # as the user does on the campaign page
        await artifacts.save_payload(record, plan)
        return await campaign.render_plan(chat, plan_id)

    out = asyncio.run(approve_and_render())
    assert sorted((m["to"], m["step"]) for m in out["ready"]) == [("ana@acme.com", 1), ("bo@acme.com", 1)]  # step 2 waits for step 1
    ana = next(m for m in out["ready"] if m["to"] == "ana@acme.com")
    assert ana["body"].startswith("Hi Ana, Rival Co cut prices 20% on Nov 12 (Retail Weekly). For Acme that means") and ana["body"].endswith("Reply STOP to opt out")
    assert out["skipped"] == {"previous step not sent": 1, "not a lead: shared or role inbox": 1}  # info@ never had a step, but fails the gate first


@pytest.mark.parametrize("args, why", [
    ({"to": "nobody@acme.com"}, "not a contact saved in this chat"),
    ({"to": "info@acme.com"}, "did not pass the lead gate: shared or role inbox"),
    ({"body": " ".join(["word"] * 86)}, "first email over 85 words"),
    ({"body": "See https://acme.com"}, "a link in the first email"),
    ({"body": "Hi {{nickname}}"}, "unknown token nickname; empty nickname"),
    ({"subject": " "}, "empty subject or body"),
    ({"plan_id": "campaign_plan-old00000"}, "not a campaign plan of this chat"),
])
def test_what_add_touch_refuses(chat, args, why):
    assert touch(**args) == {"refused": why}


def test_a_later_touch_may_carry_one_link_and_a_person_has_one_plan(chat):
    plan_id = touch()["plan_id"]
    assert touch(body="https://a.com and https://b.com", plan_id=plan_id) == {"refused": "more than one link"}
    assert touch(body="The report: https://a.com", plan_id=plan_id)["step"] == 2
    assert touch() == {"refused": f"already in plan {plan_id}: pass its plan_id"}


def test_a_person_who_replied_or_bounced_gets_no_new_touch(chat):
    plan_id = touch()["plan_id"]
    asyncio.run(campaign.record(chat, plan_id, {"to": "ana@acme.com", "status": "replied", "intent": "interested"}))
    assert touch(plan_id=plan_id) == {"refused": "replied"}


def test_without_a_brief_to_copy_the_sign_off_it_refuses(chat, tmp_path):
    (tmp_path / "campaign_plan-old00000.json").write_text(json.dumps({"rows": [], "meta": {"brief": {"opt_out": "Reply STOP"}}}))
    assert touch() == {"refused": "no sign-off: no campaign brief has a postal_address and opt_out to copy"}


def test_approve_plan_steps_approves_a_touch_like_any_step(chat, monkeypatch):
    """The user, 18 Nov 2026: a draft that passes every check is approved without them, product-led ones included."""
    monkeypatch.setattr(hm, "USER_ID", "u")
    plan_id = touch()["plan_id"]
    out = asyncio.run(hm.approve_plan_steps("chat-1", plan_id))
    assert out["approved_now"] == 1 and plan_of(chat, plan_id)["rows"][0]["status"] == "approved"


def _old_steps_for(plan, row):  # steps_for before `to` rows existed
    rows = plan.get("rows", [])
    seg_field = (plan.get("meta") or {}).get("segment_field")
    named = {str(s.get("segment") or "all") for s in rows} - {"all"}
    mine = str(row.get(seg_field, "")) if seg_field else (named.pop() if len(named) == 1 else "all")
    return [s for s in rows if str(s.get("segment") or "all") in ("all", mine)]


@pytest.mark.parametrize("plan", [
    {"rows": [{"segment": "all", "step": 1}, {"segment": "all", "step": 2}], "meta": {}},
    {"rows": [{"segment": "Retail", "step": 1}], "meta": {}},
    {"rows": [{"segment": "Retail", "step": 1}, {"segment": "Food", "step": 1}, {"segment": "all", "step": 2}], "meta": {}},
    {"rows": [{"segment": "Retail", "step": 1}, {"segment": "Food", "step": 1}], "meta": {"segment_field": "industry"}},
    {"rows": [{"segment": "follow", "step": 1, "recipient_email": "x@y.com"}], "meta": {"segment_field": "play"}},
])
def test_a_plan_with_no_to_rows_picks_the_same_steps_as_before(plan):
    for row in ({"email": "a@b.com", "industry": "Retail"}, {"email": "c@d.com", "industry": "Food", "play": "follow"}, {}):
        assert creatives.steps_for(plan, row) == _old_steps_for(plan, row)
