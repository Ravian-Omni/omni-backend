"""An app's server becomes its app agent: the agent's name, job and rules, and only its chosen tools."""

import asyncio

from src.agent_runtime import app_agents, specialists


def test_hubspot_server_becomes_the_hubspot_agent(monkeypatch):
    tools = [{"name": "HUBSPOT_SEARCH_COMPANIES", "description": "Search companies"},
             {"name": "HUBSPOT_CREATE_CONTACT", "description": "Create a contact"},
             {"name": "HUBSPOT_DELETE_EVERYTHING", "description": "Not on the agent's list"}]

    async def yes(*a):
        return True

    async def listed(server):
        return tools

    async def no_overrides(server):
        return {}

    monkeypatch.setattr(specialists, "specialist_eligible", lambda s: True)
    monkeypatch.setattr(specialists, "is_connected", yes)
    monkeypatch.setattr(specialists, "list_tools", listed)
    monkeypatch.setattr(specialists, "load_mcp_tool_classes", no_overrides)
    monkeypatch.setattr(specialists, "options", lambda s: {"display_name": "HubSpot", "composio": {"toolkits": ["hubspot"]}})
    agent = asyncio.run(specialists.build("composio-hubspot"))
    assert agent.display_name == "HubSpot Agent" and agent.tagline == app_agents.APPS["hubspot"]["tagline"]
    assert "HUBSPOT_SEARCH_COMPANIES" in agent.system_prompt and "HUBSPOT_DELETE_EVERYTHING" not in agent.system_prompt
    assert "Search before you create" in agent.system_prompt and "Use the HubSpot Agent" in agent.description


def test_only_single_app_servers_are_app_agents():
    assert app_agents.for_options({"composio": {"toolkits": ["slack"]}})["agent"] == "Slack Agent"
    assert app_agents.for_options({"composio": {"toolkits": ["slack", "gmail"]}}) is None
    assert app_agents.for_options({"url": "http://localhost:8765/mcp"}) is None
