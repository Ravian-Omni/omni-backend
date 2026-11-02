"""What a task reads: one card per agent, every step's prompt and every agent's prompt, each editable by the user."""

import asyncio
import json

import pytest
from pydantic import ValidationError

from src.agent_runtime import prefs
from src.agent_runtime.personas import PERSONAS, PROMPT_FIELDS, fill, readable
from src.agent_runtime.prefs import SCHEMAS
from src.database import connection
from src.omni import orchestrator, prompts

OWN = {"display_name": "Brand Reviewer", "prompt": "Check ads against {brand} rules.", "routing": "Call to review ad creatives before a campaign.",
       "file_types": ["pdf", "image"], "mcp_servers": ["notion"]}


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(connection.settings, "ROOT_DIR", str(tmp_path))
    monkeypatch.setattr(connection, "_db", None)
    asyncio.run(connection.init_db())
    yield
    asyncio.run(connection.close_db())


def test_router_and_clarifier_read_the_same_cards():
    assert prompts.agent_router.count(orchestrator.AGENTS_SLOT) == 1 and prompts.clarifier.count(orchestrator.AGENTS_SLOT) == 1


def test_cards_follow_the_pipeline_and_take_the_users_lines():
    cards = orchestrator.card_list([], {"lead_finder": {"card": {"call_when": "Only dental practices.", "does": " "}}, "outreach": {"enabled": False}})
    text = orchestrator.render(cards)
    order = [n for n in orchestrator.CARDS if n != "outreach"]
    assert [text.index(f"### {n} (") for n in order] == sorted(text.index(f"### {n} (") for n in order)
    lead = next(c for c in cards if c["name"] == "lead_finder")
    assert lead["edited"] and lead["call_when"] == "Only dental practices."
    assert lead["does"] == orchestrator.CARDS["lead_finder"]["does"]  # a blank line keeps DAXAGENT's
    assert "Call when: Only dental practices." in text
    assert "### outreach" not in text  # switched off: never offered to the planner


def test_own_agents_get_ids_and_a_card():
    agents = SCHEMAS["custom_agents"].dump_python(SCHEMAS["custom_agents"].validate_python([OWN]))
    assert agents[0]["name"] == "custom_brand_reviewer"
    text = orchestrator.render(orchestrator.card_list(agents, {}))
    assert "### custom_brand_reviewer (Brand Reviewer, the user's own agent)" in text
    assert "Call when: Call to review ad creatives" in text and "Reads these attached files: PDF, images" in text


@pytest.mark.parametrize("bad", [
    [OWN, {**OWN, "display_name": "brand reviewer"}],  # same id twice
    [{**OWN, "display_name": "!!"}],  # no letters or digits to make an id from
    [{**OWN, "file_types": ["exe"]}],
    [{**OWN, "routing": ""}],  # the planner must be told when to call it
])
def test_own_agents_are_validated(bad):
    with pytest.raises(ValidationError):
        SCHEMAS["custom_agents"].validate_python(bad)


def test_own_agents_prompt_survives_formatting():
    persona = orchestrator.custom(SCHEMAS["custom_agents"].dump_python(SCHEMAS["custom_agents"].validate_python([OWN]))[0])
    text = persona.system_prompt.format(working_directory="w", file_location="f", artifacts_dir="a", python_executable="p", today="t", custom_instructions="")
    assert "Check ads against {brand} rules." in text and "read_image" in text
    assert persona.mcp_servers == ["notion"] and persona.remote_mcp and persona.kind == "custom"


def test_the_planner_reads_every_agent_with_its_abilities_as_json():
    agents = SCHEMAS["custom_agents"].dump_python(SCHEMAS["custom_agents"].validate_python([OWN]))
    cards = orchestrator.card_list(agents, {"outreach": {"enabled": False}})
    gmail = {"name": "mcp_composio_gmail", "display_name": "Gmail Agent", "does": "Works in your Gmail", "call_when": "Gmail work.",
             "mcp": [{"server": "Gmail", "online": True}], "abilities": [{"name": "GMAIL_SEND_EMAIL", "does": "Sends", "params": [], "source": "Gmail"}] * 25}
    text = orchestrator.with_cards(orchestrator.PLANNER_CORE.replace("$today_date", "today").replace("$order", "x"),
                                   orchestrator.capabilities(cards, [gmail]))
    caps = json.loads(text)["planner_agent_config"]["available_capabilities"]  # the user's layout stays valid JSON
    assert list(caps)[:3] == ["User's Context", "Lead Finder", "Buyer Finder"] and "Outreach" not in caps
    assert caps["Lead Finder"]["assign_as"] == "lead_finder" and caps["Buyer Finder"]["needs"]
    assert caps["Lead Finder"]["abilities"] == orchestrator.ABILITIES["lead_finder"]  # no server listed: the hand-written ones
    assert caps["Brand Reviewer"]["reads_files"] == ["PDF", "images"] and caps["Brand Reviewer"]["works_in"] == ["notion"]
    assert caps["Gmail Agent"]["assign_as"] == "mcp_composio_gmail" and len(caps["Gmail Agent"]["abilities"]) == 21  # 20, then names only


def test_an_agent_that_needs_an_mcp_waits_for_the_sign_in(monkeypatch):
    from src import mcp_client
    from src.mcp_client import config

    signed_in = set()

    async def connected(server):
        return server in signed_in

    monkeypatch.setattr(config, "enabled_servers", lambda: ["newton", "marketwatch"])
    monkeypatch.setattr(mcp_client, "is_connected", connected)
    monkeypatch.setattr(mcp_client, "options", lambda s: {"display_name": s.title()})
    monkeypatch.setattr(prefs, "get", lambda user_id, key: asyncio.sleep(0, {"custom_agents": [], "agents": {}}[key]))
    cards = asyncio.run(orchestrator.user_cards("u1"))
    caps = json.loads(orchestrator.capabilities(cards, []))
    assert "Data Analyst" not in caps and "Campaign Strategizer" not in caps and "Lead Finder" in caps
    assert "### ml_engineer" not in orchestrator.render(cards)  # the router and clarifier don't see it either
    assert "Data Analyst (ml_engineer) needs Newton" in orchestrator.waiting_notes(cards)
    signed_in.add("newton")  # the key is added: the agent is back on the next task, MarketWatch's still waits
    cards = asyncio.run(orchestrator.user_cards("u1"))
    assert "Data Analyst" in json.loads(orchestrator.capabilities(cards, [])) and "Newton" not in orchestrator.waiting_notes(cards)


def test_an_agents_abilities_are_its_mcp_servers_functions_live(monkeypatch):
    from src import mcp_client
    from src.agent_runtime import session
    from src.mcp_client import config

    tools = {"data-axle": [{"name": "business_search", "description": "Search businesses. Free; masked.",
                            "input_schema": {"properties": {"limit": {}, "city": {}, "sic": {}}, "required": ["sic"]}}],
             "marketwatch": None}  # offline

    async def listed(server):
        if tools[server] is None:
            raise ConnectionError("down")
        return tools[server]

    async def connected(server):
        return True

    monkeypatch.setattr(config, "enabled_servers", lambda: list(tools))
    monkeypatch.setattr(config, "in_mode", lambda s, m: True)
    monkeypatch.setattr(mcp_client, "is_connected", connected)
    monkeypatch.setattr(mcp_client, "list_tools", listed)
    monkeypatch.setattr(mcp_client, "options", lambda s: {"display_name": {"data-axle": "Data Axle", "marketwatch": "MarketWatch"}[s]})
    monkeypatch.setattr(session, "offered", lambda p, s: (p.name, s) in {("lead_finder", "data-axle"), ("campaign_strategizer", "marketwatch")})
    cards = {c["name"]: c for c in asyncio.run(orchestrator.add_abilities(orchestrator.card_list([], {})))}
    assert cards["lead_finder"]["mcp"] == [{"server": "Data Axle", "online": True}]
    assert cards["lead_finder"]["abilities"] == [{"name": "business_search", "does": "Search businesses", "params": ["sic (required)", "limit", "city"], "source": "Data Axle"}]
    strategist = cards["campaign_strategizer"]  # its server is offline: the hand-written list, and Settings says so
    assert strategist["mcp"] == [{"server": "MarketWatch", "online": False}] and strategist["abilities"][0]["source"] == "DAXAGENT"
    assert cards["outreach"]["mcp"] == [] and cards["outreach"]["abilities"] == orchestrator._own("outreach")


def test_a_step_without_the_cards_line_still_gets_the_cards():
    assert orchestrator.with_cards("Route.\n<<AGENT_CARDS>>\nThen go.", "CARDS") == "Route.\nCARDS\nThen go."
    assert orchestrator.with_cards("My own router prompt.", "CARDS") == "My own router prompt.\n\nCARDS"


def test_agent_prompts_read_back_exactly():
    values = {k: k.upper() for k in PROMPT_FIELDS}
    for persona in PERSONAS.values():  # shown, saved unchanged, run: the same prompt the agent had
        assert fill(readable(persona.system_prompt), values) == persona.system_prompt.format(**values), persona.name
    assert fill("Use {{token}} and {today}.", values) == "Use {{token}} and TODAY."  # the user's braces stay as typed


def test_core_agents_take_the_users_notes(temp_db):
    async def scenario():
        default = await orchestrator.planner_core("u1")
        await prefs.put("u1", "orchestrator", {"notes": {"planner": "Plan briefly. Today is $today_date.", "judge": " Classify. "}})
        await prefs.put("u1", "agents", {"lead_finder": {"prompt": "Find {today} leads."}})
        steps, lead = await orchestrator.stage_prompts("u1"), await prefs.agent_prompt("u1", "lead_finder")
        mine = await orchestrator.planner_core("u1")
        await prefs.put("u1", "custom_agents", [OWN])
        found, gone = await orchestrator.custom_persona("u1", "custom_brand_reviewer"), await orchestrator.custom_persona("u2", "custom_brand_reviewer")
        return default, mine, found, gone, steps, lead

    default, mine, found, gone, steps, lead = asyncio.run(scenario())
    assert steps["judge"] == orchestrator.with_note(prompts.judge_question, "Classify.") and steps["router"] == prompts.agent_router
    assert steps["judge"].startswith(prompts.judge_question) and steps["judge"].count("Classify.") == 1  # a note adds, never replaces
    assert lead == "Find {today} leads."
    assert "today's date is --> " in default and "$today_date" not in default
    assert mine.startswith(default) and "Plan briefly. Today is " in mine and "$today_date" not in mine
    assert found.display_name == "Brand Reviewer" and gone is None  # another user's agent is not theirs
