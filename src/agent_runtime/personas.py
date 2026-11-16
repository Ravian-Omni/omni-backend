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
    kind: str = "job"  # "job" (built in), "specialist" (one per MCP server) or "custom" (one the user wrote)
    server: str | None = None  # the MCP server a specialist owns
    icon: str = ""  # logo URL for specialists
    call_when: str = ""  # when the planner gives a specialist a task
    max_budget_usd: float | None = 2.0  # stop a runaway run; None = no ceiling
    retired: bool = False  # not offered in tasks or listed; kept so older chats that used it still run


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
    retired=True,
))

_register(Persona(
    name="ml_engineer",
    display_name="Data Analyst",
    tagline="Analysis, charts, lead scoring and segments from your data",
    description=prompts.ML_ENGINEER_DESCRIPTION,
    system_prompt=prompts.ML_ENGINEER,
    builtin_tools=CODING_BUILTINS,
    daxagent_tools=["execute_command", "run_python", "ask_user_for_data", "review_with_user", "newton_upload", *COMMON_TOOLS],
    remote_mcp=True,  # Newton is assigned to this persona alone (its server config names ml_engineer)
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
    name="user_context",
    display_name="User's Context",
    tagline="Knows you: your notes, decisions, people and past work, from your own memory",
    description=prompts.USER_CONTEXT_DESCRIPTION,
    system_prompt=prompts.USER_CONTEXT,
    builtin_tools=["Read"],
    daxagent_tools=[*COMMON_TOOLS],
    remote_mcp=True,  # the user-context server is assigned to this persona alone (its config names it); chat reaches it via "*"
    max_turns=20,
))

_register(Persona(
    name="campaign_strategizer",
    display_name="Campaign Strategizer",
    tagline="The campaign's winning angle, from market intelligence on your competitors",
    description=prompts.CAMPAIGN_STRATEGIZER_DESCRIPTION,
    system_prompt=prompts.CAMPAIGN_STRATEGIZER,
    builtin_tools=["Read"],
    daxagent_tools=[*COMMON_TOOLS],
    remote_mcp=True,  # MarketWatch is assigned to this persona (its server config names it)
))

_register(Persona(
    name="campaign_builder",
    display_name="Campaign Builder",
    tagline="Segments, sequences and copy for an outbound campaign",
    description=prompts.CAMPAIGN_BUILDER_DESCRIPTION,
    system_prompt=prompts.CAMPAIGN_BUILDER,
    builtin_tools=["Read", "Write", "WebSearch", "WebFetch"],
    daxagent_tools=["ask_user_for_data", "review_with_user", *COMMON_TOOLS],
    remote_mcp=True,  # MarketWatch, for the competitors' current messaging (its server config names it)
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
    remote_mcp=True,  # any server assigned to it in Connections (e.g. MarketWatch, for answers about competitors)
))

_register(Persona(
    name="signal_play",
    display_name="Signal Play",
    tagline="Turns a detected buying signal into an outreach you approve",
    description=prompts.SIGNAL_PLAY_DESCRIPTION,
    system_prompt=prompts.SIGNAL_PLAY,
    builtin_tools=["Read", "WebSearch"],  # no WebFetch: the signal's link comes from outside and is cited, never opened
    daxagent_tools=["request_spend_approval", *COMMON_TOOLS],  # no send tools: nothing leaves from here
    remote_mcp=True,  # Data Axle (its server config names this persona)
))

_register(Persona(
    name="meeting_prep",
    display_name="Meeting Prep",
    tagline="Gets you ready for a booked meeting: the person, the company and the thread so far",
    description=prompts.MEETING_PREP_DESCRIPTION,
    system_prompt=prompts.MEETING_PREP,
    builtin_tools=["Read"],
    daxagent_tools=["calendar_events", "gmail_search_emails", "request_spend_approval", *COMMON_TOOLS],  # no send tools
    remote_mcp=True,  # Data Axle (its server config names this persona)
))

_register(Persona(
    name="recovery_note",
    display_name="Recovery Note",
    tagline="Drafts one short note to restart a conversation that went quiet",
    description=prompts.RECOVERY_NOTE_DESCRIPTION,
    system_prompt=prompts.RECOVERY_NOTE,
    builtin_tools=["Read"],
    daxagent_tools=["gmail_search_emails", *COMMON_TOOLS],  # the note is saved as an artifact; nothing is sent or drafted in Gmail
))

_register(Persona(
    name="assistant",
    display_name="DAXAGENT",
    tagline="Chat mode: answers and acts with every connected tool",
    description="Chat-mode assistant; not offered to the task planner.",
    system_prompt=prompts.ASSISTANT,
    builtin_tools=READ_ONLY_BUILTINS,
    daxagent_tools=[
        "sic_lookup", "review_with_user", "ask_user_for_data", "suggest_task", "request_spend_approval", "request_send_approval",
        "gmail_send_email", "gmail_create_draft", "gmail_search_emails", *COMMON_TOOLS,
    ],
    remote_mcp=True,
    mcp_servers=["*"],  # every enabled, connected server
    max_turns=30,
))

SALES_PERSONAS = ["lead_finder", "buyer_finder", "contact_enricher", "campaign_strategizer", "campaign_builder", "outreach", "inbox_agent", "signal_play", "meeting_prep", "recovery_note"]


# The values a persona prompt is filled with when its session starts (PersonaSession._system_prompt).
PROMPT_FIELDS = ("working_directory", "file_location", "artifacts_dir", "python_executable", "today", "custom_instructions")


def readable(template: str) -> str:
    """A persona prompt as the user reads and edits it: the session's values shown as {name}, literal braces single."""
    return template.format(**{k: "{" + k + "}" for k in PROMPT_FIELDS})


def fill(text: str, values: dict) -> str:
    """The user's version of a persona prompt with the session's values put in; every other brace stays as typed."""
    for k, v in values.items():
        text = text.replace("{" + k + "}", str(v))
    return text


# How a user's own agent reads each kind of file it accepts (prefs.FILE_TYPES).
_READ_HOW = {
    "csv": "CSV: pandas.read_csv in run_python",
    "excel": "Excel: pandas.read_excel in run_python",
    "json": "JSON: Read, or json/pandas in run_python when large",
    "parquet": "Parquet: pandas.read_parquet in run_python",
    "pdf": "PDF: pypdf in run_python (PdfReader(path).pages[i].extract_text())",
    "text": "text and Markdown: Read",
    "image": "images: read_image with the file path and what to look for",
}

CUSTOM_PROMPT = """You are {display_name}, an agent the user added to DAXAGENT. The orchestrator hands you tasks; do them the way the user's instructions below say.

## The user's instructions for you
{prompt}
{files}"""


def custom(agent: dict) -> Persona:
    """A persona from an agent the user wrote (prefs ``custom_agents``)."""
    esc = lambda text: text.replace("{", "{{").replace("}", "}}")  # the session formats the prompt
    files = ""
    if agent["file_types"]:
        files = ("\n## Files the user can give you\nFiles attached to a task are listed in it with their paths. Read them yourself:\n"
                 + "\n".join(f"- {_READ_HOW[t]}" for t in agent["file_types"]) + "\n")
    prompt = CUSTOM_PROMPT.format(display_name=esc(agent["display_name"]), prompt=esc(agent["prompt"].strip()), files=files)
    servers = list(agent["mcp_servers"])
    return Persona(
        name=agent["name"], display_name=agent["display_name"], tagline=agent["routing"].strip().split("\n")[0][:160],
        description=f"{agent['display_name']} (added by the user). {agent['routing'].strip()} "
                    "Parameters: query (required): the complete task, with any file paths, artifact ids or names it needs.",
        system_prompt=prompt + prompts._COMMON_RULES,
        builtin_tools=READ_ONLY_BUILTINS, daxagent_tools=["read_image", "ask_user_for_data", "review_with_user", *COMMON_TOOLS],
        remote_mcp=bool(servers), mcp_servers=servers, kind="custom",
    )


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
