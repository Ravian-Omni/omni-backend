"""Persona definitions: one agent runtime, several jobs.

A persona is a system prompt, the built-in tools it may use, the DAXAGENT
in-process tools it may use, and whether it may reach remote MCP servers.
Which of those tools need a confirmation card is decided per tool (see
``tools.server`` and ``mcp_client.classify``), not per persona, so a persona
cannot opt out of the credit and send gates.
"""

from dataclasses import dataclass, field

from src.agent_runtime import prompts

READ_ONLY_BUILTINS = ["Read", "Glob", "Grep", "WebSearch", "WebFetch"]
CODING_BUILTINS = ["Read", "Write", "Edit", "MultiEdit", "Glob", "Grep", "WebSearch", "WebFetch"]

# In-process tools every persona gets so it can ask the user things and hand
# work over through artifacts.
COMMON_TOOLS = [
    "run_python",
    "save_chart",
    "save_map",
    "ask_user",
    "ask_user_choice",
    "save_artifact",
    "list_artifacts",
    "read_artifact",
    "update_artifact",
    "remember",
]


@dataclass(frozen=True)
class Persona:
    """What one persona is allowed to do."""

    name: str
    display_name: str
    description: str
    system_prompt: str
    builtin_tools: list[str] = field(default_factory=list)
    daxagent_tools: list[str] = field(default_factory=list)
    remote_mcp: bool = False
    max_turns: int = 40
    tagline: str = ""
    # Remote servers this persona may use. None = the reserved servers plus any
    # server whose config names this persona; a list = exactly those servers.
    mcp_servers: list[str] | None = None
    kind: str = "job"  # "job" (built in) or "specialist" (one per MCP server)
    server: str | None = None  # the MCP server a specialist owns
    icon: str = ""  # logo URL for specialists
    max_budget_usd: float | None = 2.0  # stop a runaway run; None = no ceiling


PERSONAS: dict[str, Persona] = {}


def _register(p: Persona) -> Persona:
    PERSONAS[p.name] = p
    return p


_register(Persona(
    name="software_developer",
    display_name="Growth Engineer",
    tagline="Writes and runs code in your workspace",
    description=prompts.SOFTWARE_DEVELOPER_DESCRIPTION,
    system_prompt=prompts.SOFTWARE_DEVELOPER,
    builtin_tools=CODING_BUILTINS,
    daxagent_tools=["execute_command", "run_python", "ask_user", "save_artifact", "list_artifacts", "read_artifact"],
    max_turns=60,
    max_budget_usd=None,
))

_register(Persona(
    name="ml_engineer",
    display_name="Data Analyst",
    tagline="Analysis, charts, lead scoring and segments from your data",
    description=prompts.ML_ENGINEER_DESCRIPTION,
    system_prompt=prompts.ML_ENGINEER,
    builtin_tools=CODING_BUILTINS,
    daxagent_tools=["execute_command", "run_python", "ask_user_for_data", "review_with_user", *COMMON_TOOLS],
    max_turns=60,
    max_budget_usd=None,
))

_register(Persona(
    name="lead_finder",
    display_name="Lead Finder",
    tagline="Turns an ideal customer profile into a lead list",
    description=prompts.LEAD_FINDER_DESCRIPTION,
    system_prompt=prompts.LEAD_FINDER,
    builtin_tools=READ_ONLY_BUILTINS,
    daxagent_tools=["sic_lookup", "review_with_user", *COMMON_TOOLS],
    remote_mcp=True,
))

_register(Persona(
    name="buyer_finder",
    display_name="Buyer Finder",
    tagline="Finds the right decision makers at each company",
    description=prompts.BUYER_FINDER_DESCRIPTION,
    system_prompt=prompts.BUYER_FINDER,
    builtin_tools=READ_ONLY_BUILTINS,
    daxagent_tools=["review_with_user", *COMMON_TOOLS],
    remote_mcp=True,
))

_register(Persona(
    name="contact_enricher",
    display_name="Contact Enricher",
    tagline="Reveals full contact details, with your approval of the credits",
    description=prompts.CONTACT_ENRICHER_DESCRIPTION,
    system_prompt=prompts.CONTACT_ENRICHER,
    builtin_tools=["Read"],
    daxagent_tools=["request_spend_approval", "review_with_user", *COMMON_TOOLS],
    remote_mcp=True,
))

_register(Persona(
    name="campaign_strategizer",
    display_name="Campaign Strategizer",
    tagline="The campaign's winning angle, from market intelligence on your competitors",
    description=prompts.CAMPAIGN_STRATEGIZER_DESCRIPTION,
    system_prompt=prompts.CAMPAIGN_STRATEGIZER,
    builtin_tools=["Read"],
    daxagent_tools=[*COMMON_TOOLS],
    remote_mcp=True,  # KnightWatch is tagged to this persona (configs/mcp_servers.json)
))

_register(Persona(
    name="campaign_builder",
    display_name="Campaign Builder",
    tagline="Segments, sequences and copy for an outbound campaign",
    description=prompts.CAMPAIGN_BUILDER_DESCRIPTION,
    system_prompt=prompts.CAMPAIGN_BUILDER,
    builtin_tools=["Read", "Write", "WebSearch", "WebFetch"],
    daxagent_tools=["ask_user_for_data", "review_with_user", *COMMON_TOOLS],
))

_register(Persona(
    name="outreach",
    display_name="Outreach",
    tagline="Sends the campaign, one approved batch at a time",
    description=prompts.OUTREACH_DESCRIPTION,
    system_prompt=prompts.OUTREACH,
    builtin_tools=["Read"],
    daxagent_tools=[
        "request_send_approval", "gmail_send_email", "gmail_create_draft", "gmail_search_emails",
        "review_with_user", *COMMON_TOOLS,
    ],
    remote_mcp=True,
))

_register(Persona(
    name="inbox_agent",
    display_name="Inbox Agent",
    tagline="Reads campaign replies, decides each next step with Jev, hands the rest to their owner",
    description=prompts.INBOX_AGENT_DESCRIPTION,
    system_prompt=prompts.INBOX_AGENT,
    builtin_tools=["Read"],
    daxagent_tools=["check_replies", "record_reply", "hand_off", "meeting_slots", *COMMON_TOOLS],
    remote_mcp=True,  # KnightWatch, for answers about competitors (configs/mcp_servers.json)
))

_register(Persona(
    name="assistant",
    display_name="DAXAGENT",
    tagline="Chat mode: answers and acts with every connected tool",
    description="Chat-mode assistant; not offered to the task planner.",
    system_prompt=prompts.ASSISTANT,
    builtin_tools=READ_ONLY_BUILTINS,
    daxagent_tools=[
        "sic_lookup", "review_with_user", "ask_user_for_data", "request_spend_approval", "request_send_approval",
        "gmail_send_email", "gmail_create_draft", "gmail_search_emails", *COMMON_TOOLS,
    ],
    remote_mcp=True,
    mcp_servers=["*"],  # every enabled, connected server
    max_turns=30,
))

SALES_PERSONAS = ["lead_finder", "buyer_finder", "contact_enricher", "campaign_strategizer", "campaign_builder", "outreach", "inbox_agent"]


def get_persona(name: str) -> Persona:
    if name in PERSONAS:
        return PERSONAS[name]
    from src.agent_runtime import specialists

    persona = specialists.get(name)
    if persona is not None:
        return persona
    raise ValueError(f"Unknown persona '{name}'. Known: {', '.join(persona_names())}")


def persona_names() -> list[str]:
    from src.agent_runtime import specialists

    return list(PERSONAS) + list(specialists.all())
