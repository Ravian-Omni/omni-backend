"""App agents: one agent per sales app the user connects (Settings, Agents).

Each is a specialist (agent_runtime/specialists.py) built on the app's Composio server, with its own
name, job, working rules and a short list of tools instead of the app's hundreds. Switching one off
keeps it out of tasks; the chat assistant can still use the app.
"""

from typing import Any

APPS: dict[str, dict[str, Any]] = {
    "salesforce": {
        "logo": "https://logos.composio.dev/api/salesforce",
        "agent": "Salesforce Agent",
        "app": "Salesforce",
        "tagline": "Keeps Salesforce in step with your outreach: leads, contacts, accounts and opportunities",
        "abilities": [
            "Checks whether a company or person is already in Salesforce",
            "Creates or updates leads, contacts and accounts from your lists",
            "Reads and updates opportunities and their stages",
            "Logs calls, tasks and notes, and adds people to Salesforce campaigns",
            "Tells you who owns an account",
        ],
        "tools": [
            "SALESFORCE_EXECUTE_SOQL_QUERY", "SALESFORCE_EXECUTE_SOSL_SEARCH", "SALESFORCE_QUERY_CONTACTS_BY_NAME",
            "SALESFORCE_GET_ACCOUNT", "SALESFORCE_GET_CONTACT", "SALESFORCE_GET_LEAD", "SALESFORCE_GET_OPPORTUNITY", "SALESFORCE_GET_USER_INFO",
            "SALESFORCE_CREATE_LEAD", "SALESFORCE_CREATE_CONTACT", "SALESFORCE_CREATE_ACCOUNT", "SALESFORCE_CREATE_OPPORTUNITY",
            "SALESFORCE_UPDATE_LEAD", "SALESFORCE_UPDATE_CONTACT", "SALESFORCE_UPDATE_ACCOUNT", "SALESFORCE_UPDATE_OPPORTUNITY",
            "SALESFORCE_CREATE_TASK", "SALESFORCE_CREATE_NOTE", "SALESFORCE_LOG_CALL",
            "SALESFORCE_ADD_LEAD_TO_CAMPAIGN", "SALESFORCE_ADD_CONTACT_TO_CAMPAIGN", "SALESFORCE_CREATE_CAMPAIGN",
        ],
        "instructions": (
            "- Search before you create (SOQL or SOSL by email, then by company name) so nothing is duplicated; update the record you find.\n"
            "- Never delete records. Writes change data the whole team shares: say exactly what you will create or update before doing it.\n"
            "- An account's owner is its OwnerId user: report the owner's name and email when asked who owns it.\n"
            "- When you work from a DAXAGENT list (an artifact), map its columns to Salesforce fields and say which ones had no match."
        ),
        "planner_note": "Use the Salesforce Agent for anything in the user's Salesforce: checking whether accounts or people already exist, "
                        "creating or updating leads, contacts, accounts and opportunities, logging activity, and finding account owners.",
    },
    "hubspot": {
        "logo": "https://logos.composio.dev/api/hubspot",
        "agent": "HubSpot Agent",
        "app": "HubSpot",
        "tagline": "Keeps HubSpot in step with your outreach: contacts, companies and deals",
        "abilities": [
            "Checks whether a company or person is already in HubSpot",
            "Creates or updates contacts and companies from your lists, and links them",
            "Creates deals and moves them through the pipeline",
            "Logs notes, tasks and meetings on the right records",
            "Tells you who owns a contact or company",
        ],
        "tools": [
            "HUBSPOT_SEARCH_CONTACTS_BY_CRITERIA", "HUBSPOT_SEARCH_COMPANIES", "HUBSPOT_SEARCH_DEALS", "HUBSPOT_READ_CONTACT",
            "HUBSPOT_GET_COMPANY", "HUBSPOT_GET_DEAL", "HUBSPOT_RETRIEVE_OWNERS", "HUBSPOT_RETRIEVE_OWNER_BY_ID_OR_USER_ID",
            "HUBSPOT_CREATE_CONTACT", "HUBSPOT_CREATE_COMPANY", "HUBSPOT_CREATE_DEAL",
            "HUBSPOT_UPDATE_CONTACT", "HUBSPOT_UPDATE_COMPANY", "HUBSPOT_UPDATE_DEAL",
            "HUBSPOT_CREATE_ASSOCIATION", "HUBSPOT_LIST_OBJECT_ASSOCIATIONS",
            "HUBSPOT_CREATE_NOTE", "HUBSPOT_CREATE_TASK", "HUBSPOT_CREATE_MEETING",
        ],
        "instructions": (
            "- Search before you create (contacts by email, companies by domain) so nothing is duplicated; update the record you find.\n"
            "- Link what belongs together: a contact to its company, and both to a deal you create.\n"
            "- Never delete records. Writes change data the whole team shares: say exactly what you will create or update before doing it.\n"
            "- A record's owner is its hubspot_owner_id: look the owner up and report their name and email when asked."
        ),
        "planner_note": "Use the HubSpot Agent for anything in the user's HubSpot: checking whether contacts or companies already exist, "
                        "creating or updating contacts, companies and deals, logging notes and tasks, and finding owners.",
    },
    "slack": {
        "logo": "https://logos.composio.dev/api/slack",
        "agent": "Slack Agent",
        "app": "Slack",
        "tagline": "Tells your team on Slack: posts updates, finds people and reads channels for context",
        "abilities": [
            "Posts a message to a channel or a person, now or scheduled",
            "Finds a teammate by name or email",
            "Reads a channel's recent messages or searches them for context",
        ],
        "tools": [
            "SLACK_SEND_MESSAGE", "SLACK_SCHEDULE_MESSAGE", "SLACK_OPEN_DM", "SLACK_FIND_USERS", "SLACK_FIND_USER_BY_EMAIL_ADDRESS",
            "SLACK_FIND_CHANNELS", "SLACK_LIST_ALL_CHANNELS", "SLACK_FETCH_CONVERSATION_HISTORY", "SLACK_SEARCH_MESSAGES",
            "SLACK_ADD_REACTION_TO_AN_ITEM",
        ],
        "instructions": (
            "- Post only where the user asked: a named channel or person. Find people by email when you have it.\n"
            "- Keep messages short and plain; link to the artifact or task instead of pasting long lists.\n"
            "- Reading a channel is for context only: never repeat private messages elsewhere."
        ),
        "planner_note": "Use the Slack Agent to tell people on Slack (post or schedule a message to a channel or person) or to read Slack for context.",
    },
    "gmail": {
        "logo": "https://logos.composio.dev/api/gmail",
        "agent": "Gmail Agent",
        "app": "Gmail",
        "tagline": "Works in your Gmail: finds and reads threads, drafts and labels email",
        "abilities": [
            "Finds and reads emails and whole threads",
            "Drafts emails for you to review",
            "Labels and organises threads",
        ],
        "tools": [],  # the Gmail server keeps its full list (60 tools, well inside the limit)
        "instructions": (
            "- Campaign emails to prospects go out through Outreach after the user approves each batch, not through you.\n"
            "- You send only what the user asked for in this task, after the confirmation card; otherwise make a draft."
        ),
        "planner_note": "Use the Gmail Agent for work in the user's Gmail that is not a campaign send: finding or reading threads, drafting, labelling.",
    },
}


def toolkit_of(options: dict[str, Any]) -> str | None:
    """The app a Composio server was made for, when it holds exactly one."""
    kits = (options.get("composio") or {}).get("toolkits") or []
    return kits[0] if len(kits) == 1 else None


def for_options(options: dict[str, Any]) -> dict[str, Any] | None:
    """The app agent behind a server's options, or None for any other server."""
    return APPS.get(toolkit_of(options) or "")
