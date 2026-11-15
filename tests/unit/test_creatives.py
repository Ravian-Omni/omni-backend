"""Campaign copy rendering: tokens, Data Axle masking, legal-name cleanup, footer and lint."""

from src.agent_runtime import creatives

BRIEF = {"sender_name": "Sam", "postal_address": "1 Main St, Austin TX", "opt_out": "Reply 'stop' to opt out.",
         "fallbacks": {"first_name": "there"}}


def test_fills_tokens_and_tidies_legal_names():
    text, issues = creatives.render("Hi {{first_name}} at {{company}}", {"name": "Ann Lee", "business_name": "ACME PLUMBING LLC"}, BRIEF)
    assert text == "Hi Ann at Acme Plumbing" and issues == []


def test_masked_value_falls_back_and_is_flagged():
    text, issues = creatives.render("Hi {{first_name}}", {"first_name": "J***"}, BRIEF)
    assert text == "Hi there" and issues == ["masked first_name"]


def test_empty_and_unknown_tokens_are_flagged():
    _, issues = creatives.render("{{title}} {{nonsense}}", {}, {})
    assert "empty title" in issues and "unknown token nonsense" in issues


def test_email_message_gets_footer_and_blocks_without_address():
    m = creatives.message({"step": 1, "channel": "email", "subject": "Hi", "body": "Body"}, {"email": ""}, BRIEF)
    assert m["body"].endswith("Reply 'stop' to opt out.") and creatives.blocking(m["issues"]) == ["no email"]


def test_a_step_written_for_one_recipient_goes_to_its_address():
    # campaign_plan-be8d6513: the audience (a buyer map) had no email column, each company's step held recipient_email
    step = {"step": 1, "channel": "email", "subject": "Hi", "body": "Body", "recipient_email": " newbiz@pereiraodell.com "}
    m = creatives.message(step, {"company": "Pereira O'Dell LLC", "public_route": "newbiz@pereiraodell.com; +1 415"}, BRIEF)
    assert m["to"] == "newbiz@pereiraodell.com" and creatives.blocking(m["issues"]) == []
    assert creatives.message({**step, "recipient_email": ""}, {"email": "ann@x.com"}, BRIEF)["to"] == "ann@x.com"


def test_steps_for_segment_and_all():
    plan = {"meta": {"segment_field": "sic"}, "rows": [{"segment": "8021"}, {"segment": "all"}, {"segment": "5411"}]}
    assert [s["segment"] for s in creatives.steps_for(plan, {"sic": "8021"})] == ["8021", "all"]


def test_steps_without_segment_field():
    one = {"rows": [{"segment": "Dentists"}, {"segment": "all"}]}
    two = {"rows": [{"segment": "Dentists"}, {"segment": "Orthodontists"}, {"segment": "all"}]}
    assert len(creatives.steps_for(one, {})) == 2 and [s["segment"] for s in creatives.steps_for(two, {})] == ["all"]


def test_apostrophe_title_case():
    assert creatives.render("{{company}}", {"company": "JOE'S PIZZA LLC"}, {})[0] == "Joe's Pizza"
