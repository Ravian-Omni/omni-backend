"""How a task runs and every prompt it reads (Settings > Orchestrator).

Every agent has one card: what it does, when to call it, when not to and what it needs first. The planner, the
router and the clarifier read the same cards, so they never disagree about who does what; the planner also reads
each agent's abilities (its functions) and gets them all as JSON. The user can attach a note to a core agent's
prompt (prefs ``orchestrator``.notes), rewrite any line of a card and any agent's own prompt (prefs
``agents``[name].card and .prompt), and add agents of their own (prefs ``custom_agents``). WORKFLOW is the happy
path in five lines, for the user.
"""

import asyncio
import json
from string import Template

from loguru import logger

from src.agent_runtime import prefs
from src.agent_runtime.personas import PERSONAS, Persona, custom
from src.configs.datetime_utils import dt
from src.omni import prompts

AGENTS_SLOT = "<<AGENT_CARDS>>"  # where the cards go in the router and clarifier prompts

# The planner's prompt (the user's JSON layout): <<AGENT_CARDS>> becomes every agent with its card, its MCP servers and
# their functions as abilities.
PLANNER_CORE = """{
  "planner_agent_config": {
    "system_prompt": {
      "role": "Planner Agent",
      "identity": "You are DAXAGENT's planner: you decide which capabilities do a task, and in what order.",
      "date_context": "ALWAYS REMEMBER today's date is --> $today_date",
      "core_responsibility": "Understand the user's request and write a TO DO list, in English, that gets it done exactly as asked. Each task goes to one capability from available_capabilities: write its assign_as value (e.g. lead_finder) as the task's capability.",
      "todo_format": "Write every task with [ ] so it can be ticked off once its work is done.",
      "data_requirement": "Data Axle is the main data source for companies and people. Read files and artifacts from the path or artifact id the request or the chat gives, and put that path or id in the task.",
      "completeness": "Make every task self-contained: what to do, its inputs (places, industries, counts, titles, artifact ids, file paths, dates) and the output wanted.",
      "intent_understanding": "Understand the underlying intent of the user, but perform only the task the user explicitly asked for. ANY TASK MUST BE DONE WITH THE CAPABILITIES BELOW; NOTHING ELSE EXISTS.",
      "high_level_capabilities": [
        "we can find companies in Data Axle by industry, place, size and revenue (free, masked previews)",
        "we can find the people at those companies by job title (free, masked previews)",
        "we can reveal full names, phones, websites and company details for 1 credit a record, once the user approves the spend",
        "we can analyse, chart, score and segment the user's files and data, and train models",
        "we can read market intelligence on competitors and turn it into a campaign strategy",
        "we can write an outbound campaign (segments, sequence, copy), and send or draft it through Gmail once the user approves each batch",
        "we can read and triage the replies to a sent campaign and hand them to their owners",
        "we can read and update the user's own memory: notes, decisions, people and past work",
        "we can work in the user's connected apps (Gmail, Google Calendar, web search and the others listed)",
        "we can ask the user to decide when a choice depends on results already produced"
      ]
    },
    "available_capabilities": <<AGENT_CARDS>>,
    "planning_guidelines": {
      "consciousness": "PLAN THE SOLUTION WITH THE CAPABILITIES ABOVE ONLY. Give each task to the one capability whose call_when matches it, and never to one whose not_when matches. Its abilities say what it can do and what it returns.",
      "order": "Use the fewest capabilities that cover the request, one task each, always in this order: $order; any other capability goes where its call_when says. An agent the user added goes where its call_when says, otherwise right after the capabilities whose output it needs.",
      "information_gathering": "Ask yourself whether you have everything the work needs (the data, the list, the contacts). When a capability needs something the chat does not have yet, plan the capability that produces it first.",
      "files": "When the user attached a file, the capability whose reads_files names that kind of file and matches the request takes it; if several match, the agent the user added comes first.",
      "depth_understanding": "Put dates in a task when the request depends on them.",
      "visuals": "Charts, maps and other visuals are made by the capability that owns the data. Never plan a separate task to show, chart or map results.",
      "plan_changes": "When the user answers a plan you proposed with a change instead of approving it ('outreach?', 'add outreach', 'skip the strategy', 'only 10 leads'), that change is an explicit ask. Answer with the WHOLE plan again: every task from before, changed as asked, plus each capability the change adds and every capability that one needs first (its needs), all pending and in the order above. Never answer with only the new or changed tasks, and never make a task conditional on the ask the user just made.",
      "plan_updates": "When a capability reports back, mark its task done and update the plan from what it reported. A result may end with 'USER UPDATE': the user changed the request while that step ran, and the capability already applied it. The update supersedes the original request: rewrite the affected tasks to match it, mark them done when the result already satisfies it, and never re-run the original version.",
      "task_completion": "WHEN A CAPABILITY HAS FINISHED ITS TASK, MARK THAT TASK DONE AND CONTINUE WITH THE NEXT ONE."
    },
    "critical_instructions": {
      "primary_rule": "JUST PERFORM THE TASK THE USER HAS ASKED FOR. Do not add steps to be helpful: no sending when they asked for writing, no enrichment when previews are enough.",
      "abilities": "Abilities are the functions a capability calls itself while it does its one task. Plan capabilities, never abilities: give each capability at most one task, and that task covers every ability of it the request needs.",
      "verification": "User verification already happened before you; the answers are in the chat. Never create a manual_verification task just to collect inputs: the first task is always real work. The capabilities ask the user themselves while they run (list review, credit approval, send approval), so do not add manual_verification tasks for those reviews.",
      "emails_to_lists": "Emails to the contacts of a list or campaign, drafts included, are always campaign_builder, then outreach; never a connected-app specialist.",
      "sender": "Anything written in the user's name (an email, a draft, a message, a post) is signed with the user's real name, title and company, from the saved memory or the chat. When they are not there and a memory capability is listed (user_context, or a connected memory app), plan it first to fetch the user's profile (name, title, company, signature) along with anything else asked, such as their writing style. The writing task says to sign with what it returns, or, if it is still unknown, to ask the user for it. Never plan placeholders such as [Your Name] or [Company] for the sender.",
      "limits": "Do not plan steps no capability can do (intent data, booking a meeting without Google Calendar). Say so in overall_strategy and plan the nearest achievable outcome.",
      "meetings": "When Outreach reports interested replies, or the user asks to book meetings, plan a task for the connected Google Calendar specialist (an mcp_*googlecalendar capability, if listed) to find free slots and create the event; Outreach drafts the reply with those slots. Without one, say that Google Calendar needs connecting.",
      "consistency": "Same request, same plan: decide only by available_capabilities and these rules, so asking the same thing twice gives the same tasks in the same order."
    }
  }
}"""

# Built-in agents, in the order a plan uses them.
CARDS: dict[str, dict[str, str]] = {
    "user_context": {
        "does": "The user's own memory: notes, transcripts, meeting summaries, decisions, people and past work. Answers with cited memories, and stores or forgets memories when asked. Knows only what the user recorded.",
        "call_when": "The request depends on the user's history or preferences ('based on my notes', 'what did I decide', 'like last time', 'my usual customers'), or asks to remember or forget something. It goes first, and its summary is passed to the next task.",
        "not_when": "Everything needed is in the request or the chat.",
    },
    "lead_finder": {
        "does": "Finds companies in Data Axle by industry (SIC code), geography (city, state, zip, radius), employee count and revenue. Saves a lead_list of masked previews and maps or charts it. Never spends credits. Data Axle has no intent, technographic or funding data. It finds companies only: the people at them are a separate buyer_finder task.",
        "call_when": "The request needs companies: businesses, prospects, leads, accounts, a target list or a market size ('find N <kind of business> in <place>').",
        "not_when": "The user gave the companies, or a lead_list in this chat already covers them.",
    },
    "buyer_finder": {
        "does": "Finds the people at the companies of a lead list by title (owner, CEO, office manager, ...) through Data Axle contact search. Saves a buyer_map of masked previews. Never spends credits; coverage is partial.",
        "call_when": "The request is about people at the companies: it names a role or job title (owners, decision makers, HR managers, CTOs, buyers, contacts), or it will email or call people there.",
        "not_when": "Only companies or company details are needed (business phone, website, address, revenue), or a buyer_map in this chat already has the people.",
        "needs": "A lead_list, or companies the user named; otherwise plan lead_finder before it.",
    },
    "contact_enricher": {
        "does": "Reveals masked Data Axle records in full: names, emails, phones, websites, revenue. Costs 1 credit per record, and the user approves the spend first. Company details (business phone, website, address, revenue) come from a lead_list; people's names, titles and emails from a buyer_map. An email address is not guaranteed. It only reveals records that lead_finder or buyer_finder already found; it never finds people or companies itself.",
        "call_when": "The request asks for emails, phone numbers or full names, or messages will be sent or drafted to people (outreach).",
        "not_when": "Masked previews are enough: counts, lists to review, maps, market sizing, or a campaign that is built or written but not sent (it uses placeholders until sending).",
        "needs": "A lead_list or buyer_map with the records to reveal.",
    },
    "ml_engineer": {
        "does": "The Data Analyst. Reads files the user attached (CSV, Excel, JSON, parquet) or an artifact's data, and returns analysis, tables, charts, segments and scored lists. Trains lead-scoring, lookalike and segmentation models. Runs Python itself.",
        "call_when": "The task involves a data file the user attached or named, or analysing, scoring, segmenting or charting data that is already in an artifact. Pass it the file path or artifact id.",
        "not_when": "The data still has to be found (lead_finder or buyer_finder come first), or an agent of the user's own reads that kind of file and matches the request.",
    },
    "python_developer": {
        "does": "Writes, runs and fixes Python in the user's workspace: scripts, API calls, file conversions, cleaning and merging files, small automations. Runs what it writes before it reports, and saves the script and its output.",
        "call_when": "The deliverable is a Python script or what one produces: convert, clean, merge or generate files, call an API, automate a repeatable step.",
        "not_when": "Analysis, charts, scoring or models on the user's data (ml_engineer).",
    },
    "web_surfer": {
        "does": "Browses live websites in a headless browser (Obscura): opens pages, follows links, clicks, scrolls, uses a site's search and filters, and reads what JavaScript renders. Saves the facts found, each with its URL. Asks the user before submitting anything on a site.",
        "call_when": "The answer is on websites and needs browsing: named sites or URLs to read, several pages to follow, a site search or filter to use, or details to collect from many pages.",
        "not_when": "Companies or people from Data Axle (lead_finder, buyer_finder), or a quick fact one web search answers.",
        "needs": "The Obscura browser running (Settings, Connections).",
    },
    "campaign_strategizer": {
        "does": "Reads market intelligence on the user's competitors from MarketWatch and saves a strategy (where we win, pricing angle, objections, messaging, offer) that campaign_builder writes from. Every fact is cited.",
        "call_when": "The request mentions competitors, positioning or the campaign's angle, or a campaign is being written while MarketWatch is listed as connected.",
        "not_when": "The request says nothing about competitors, positioning or the angle, and MarketWatch is not listed as connected.",
        "needs": "MarketWatch connected in Settings, Connections.",
    },
    "campaign_builder": {
        "does": "Writes the outbound campaign: segments, the email and call sequence, subjects and bodies in the user's voice, saved as a campaign_plan. Sends nothing.",
        "call_when": "The request asks to build, create or write a campaign, a sequence, emails, messaging or copy. Building a campaign is writing it; sending is outreach's job and needs its own ask.",
        "not_when": "Only sending an existing approved plan is asked (that is outreach).",
        "needs": "An audience. A buyer_map is enough to write from (masked details become placeholders), so never plan contact_enricher just to write a campaign. When the request names a market instead ('HVAC companies in Texas'), plan lead_finder and buyer_finder before it.",
    },
    "outreach": {
        "does": "Sends or drafts an approved campaign_plan through the user's connected Gmail, one approved batch at a time, with a send log. It writes nothing: every email it sends comes from a campaign_plan that campaign_builder wrote.",
        "call_when": "The user asks to send, email, reach out to, launch to, or create Gmail drafts for the contacts of a list or campaign. Emails to a list always go through campaign_builder, then outreach, never through a Gmail specialist.",
        "not_when": "The user only asks to write or build a campaign. Sending needs its own ask.",
        "needs": "A campaign_plan, so plan campaign_builder before it unless the chat already has one. And contacts with email addresses: lead_finder and buyer_finder return masked records without emails, so plan contact_enricher before it unless the chat already has enriched contacts.",
    },
    "inbox_agent": {
        "does": "Reads the replies to a campaign's sent emails, records Jev's decision for each (unsubscribe, out of office, not now, a person answers), and hands the ones that need a person to their owner with a drafted answer. Sends nothing and books no meetings.",
        "call_when": "The user asks to check, triage or answer the replies to a campaign.",
        "not_when": "Nothing has been sent yet.",
        "needs": "A campaign that outreach has sent.",
    },
    "signal_play": {
        "does": "Turns one detected buying signal into a drafted outreach: enriches the company, finds the buyer (and, for a champion who moved, their replacement) and saves a campaign_plan whose first email cites the signal. Sends nothing.",
        "call_when": "The request starts with SIGNAL PLAY: followed by a JSON object. Plan this agent alone, as one step, and give it the request word for word.",
        "not_when": "The request does not start with SIGNAL PLAY:.",
        "needs": "Data Axle connected, for the company and the buyer.",
    },
    "meeting_prep": {
        "does": "Gets the user ready for one booked meeting: reads the calendar event and the email thread with the person, looks the person and company up in Data Axle, and saves a one-page meeting_brief. Sends nothing.",
        "call_when": "The request starts with MEETING PREP: followed by a JSON object. Plan this agent alone, as one step, and give it the request word for word.",
        "not_when": "The request does not start with MEETING PREP:.",
        "needs": "Gmail and Google Calendar connected; Data Axle for the company.",
    },
    "recovery_note": {
        "does": "Reads the email thread with a contact who went quiet and saves one short note to them as a draft (a recovery_note artifact). Sends nothing.",
        "call_when": "The request starts with RECOVERY NOTE: followed by a JSON object. Plan this agent alone, as one step, and give it the request word for word.",
        "not_when": "The request does not start with RECOVERY NOTE:.",
        "needs": "Gmail connected.",
    },
    "email_sender": {
        "does": "Sends one email from the user's connected Gmail; the recipient, subject and body come from the task. It cannot read, search or reply to email.",
        "call_when": "A one-off email to send to someone while no Gmail specialist (an mcp_*gmail agent) is listed.",
        "not_when": "A Gmail specialist is listed: give one-off email work to it, since it asks before sending. Reading, searching or replying to email needs the Gmail specialist. Emails to a list of contacts are campaign_builder, then outreach.",
    },
    "manual_verification": {
        "does": "Shows the user a short form when a decision depends on results that agents already produced.",
        "call_when": "Only for a decision that depends on results and the request left open, such as how many leads to enrich once a list exists.",
        "not_when": "Collecting inputs before work starts (already done), or approving credits, lists or sends (the agents ask themselves).",
    },
}
# What each built-in agent can call, written by hand: its abilities while it has no MCP server, or while its servers are
# offline. Otherwise its abilities are its servers' own functions (add_abilities).
ABILITIES: dict[str, list[str]] = {
    "user_context": [
        "profile: who the user is, their company and what they sell. Takes nothing.",
        "recall: memories on a topic, a person or a time range, each with its item id and date. Takes the topic, person or dates.",
        "graph tools (when the memory server lists them): the people, companies and decisions linked to a memory.",
        "remember / forget: stores the exact text the user asked to remember, or removes a memory (removing asks the user first).",
    ],
    "web_surfer": [
        "browser_navigate, then browser_snapshot / browser_markdown / browser_links / browser_extract: opens a URL and reads the rendered page.",
        "browser_click / browser_fill / browser_type / browser_select_option / browser_scroll: acts on the page by the references a snapshot returns.",
        "WebSearch: finds the pages to start from.",
        "save_artifact kind analysis or other: the findings or the list, one row per item with its source URL; returns the artifact id.",
        "ask_user: confirms before submitting a form, signing in, buying or posting on a site.",
    ],
    "lead_finder": [
        "sic_lookup: takes industry words (e.g. 'dentists'); returns the matching 4-digit SIC codes.",
        "salesgenie_business_search (Data Axle, free): takes primary_sic_code, a place (city, state, zip, or geo_lat + geo_lon + geo_radius), employee and sales ranges; returns the match count, how many have an email, and up to 10 businesses a call with infogroupId, address, phone, SIC and the contact's name and title when Data Axle has one.",
        "save_artifact kind lead_list: one row per business, deduplicated on infogroupId; returns the lead_list's artifact id.",
        "save_map / save_chart: draws the list on a map or as a chart in the chat.",
        "review_with_user: shows the list so the user can drop rows before it is final.",
    ],
    "buyer_finder": [
        "read_artifact: takes a lead_list artifact id; returns its companies.",
        "salesgenie_business_search (Data Axle, free): takes a company's name, city and state; returns its record with the contact's name and title when Data Axle has one. There is no people search by title.",
        "WebSearch: confirms a company's name or size when Data Axle finds nothing.",
        "save_artifact kind buyer_map: one row per company with its contact, ranked 1 = best fit with a reason; returns the buyer_map's artifact id.",
        "review_with_user: shows the people so the user can drop rows.",
    ],
    "contact_enricher": [
        "request_spend_approval: takes the enrichment tool, the exact record count and a reason; shows the user the credit cost and their balance, and returns their yes or no.",
        "salesgenie_business_enrichment (2 credits a record with an email, 1 without): up to 100 records in one call, each with name, street, suite, city, state, postal_code, country_code, phone, contact_first_name, contact_last_name; returns the full profiles with the email when Data Axle has one.",
        "salesgenie_fetch_available_credits (free): returns the credit balance.",
        "save_artifact kind enriched_contacts: every field returned, in the input's row order; returns the artifact id.",
    ],
    "ml_engineer": [
        "run_python: pandas, numpy, scikit-learn, statsmodels and matplotlib on a file path or an artifact's rows; returns tables, numbers and saved files.",
        "save_chart: draws an interactive chart in the chat (bar, line, pie, distributions, feature importance).",
        "save_artifact kind analysis, scored_leads or segments: the findings or the scored rows; returns the artifact id.",
        "newton_upload, then ask, get_answer, build_pipeline, train_pipeline, get_job, get_data_story and choose_model (Newton, when connected): a full analysis or a trained model; returns its findings, charts and the project_id.",
        "ask_user_for_data / ask_user_choice: asks for a dataset, the target column or the holdout.",
    ],
    "python_developer": [
        "run_python / execute_command: runs Python and shell commands in the workspace, installs packages.",
        "Read, Write, Edit, Glob, Grep: files under the working directory and the shared-files folder.",
        "read_artifact / save_artifact: data from other agents in, the script's output out; returns the artifact id.",
    ],
    "campaign_strategizer": [
        "catalog / scout_runs (MarketWatch, free): which competitors and topics are tracked, and how fresh the data is.",
        "campaign_brief: takes the goal, offer, segment and competitors; returns cited facts for each decision (audience, message, offer, channel) and what is missing.",
        "find / outline / read: a competitor's report card and battlecard rows (positioning, pricing, reviews, pros and cons), each with its date and source.",
        "search_events: takes a competitor, a category (pricing, product, marketing, review) and a since date; returns dated moves with links.",
        "save_artifact kind strategy: rows for landscape, where_we_win, pricing_angle, objection, messaging, offer and avoid, each with evidence and sources; returns the strategy's artifact id.",
    ],
    "campaign_builder": [
        "read_artifact: the audience (lead_list, buyer_map or enriched_contacts) and the strategy artifact when there is one.",
        "read_creatives: the user's uploaded ad creatives for the plan (headline, offer, numbers, call to action).",
        "WebSearch: facts about the user's own offer or a segment's industry, cited.",
        "save_artifact kind campaign_plan: one row per segment and step (subject, body with personalisation tokens, send_after_days, channel email or call); returns the plan's artifact id. update_artifact revises an existing plan.",
        "ask_user / ask_user_choice: the goal, offer, sender, tone and sequence length when the brief lacks them.",
    ],
    "outreach": [
        "check_replies / record_reply: before a follow-up step, the replies so far with their intent and route.",
        "render_campaign: takes the plan id and step; returns the finished messages, and what it held back and why.",
        "request_send_approval: takes the channel, the recipients, the subject and the exact body preview; returns the user's yes or no for that batch.",
        "gmail_send_email / gmail_create_draft: sends or drafts each rendered message from the user's Gmail (follow-ups in the same thread) and logs it in the send_log.",
        "gmail_search_emails: finds earlier messages of the campaign.",
    ],
    "inbox_agent": [
        "check_replies: takes a campaign plan id; returns each reply with Jev's intent and route (suppress, auto_reply, snooze, handoff, propose_meeting, answer).",
        "record_reply: stores a reply's intent, route and message_id on the plan.",
        "meeting_slots: free times to offer someone who asked to meet.",
        "hand_off: gives a reply and a drafted answer to its owner, or to the shared inbox; the owner sends.",
    ],
    "signal_play": [
        "salesgenie_business_search (Data Axle, free): the signal's company with the contact Data Axle holds there.",
        "request_spend_approval, then salesgenie_business_enrichment (2 credits with an email): the full record with the email; asks the user first.",
        "WebSearch: where a person who moved worked before, to find who replaced them.",
        "save_artifact kind enriched_contacts, then kind campaign_plan: the buyer (and the refill) and a three-email sequence whose first line cites the signal; returns both artifact ids. The user approves the steps on the campaign page.",
    ],
    "meeting_prep": [
        "calendar_events (free): takes the person's email and the meeting time; returns the events they are invited to.",
        "gmail_search_emails (free): the email thread with the person.",
        "Data Axle business search (free), and enrichment only after request_spend_approval: the company's size, industry and place.",
        "save_artifact kind meeting_brief: the one-page brief; returns its id.",
    ],
    "recovery_note": [
        "gmail_search_emails (free): the email thread with the person.",
        "save_artifact kind recovery_note: the drafted note (to, subject, body, thread_id); returns its id. Nothing is sent.",
    ],
    "email_sender": [
        "GMAIL_SEND_EMAIL: takes the task in plain words (the recipient's email, the subject and the body) and sends one email from the user's Gmail; returns sent, or that Gmail needs connecting.",
    ],
    "manual_verification": [
        "A short form: takes the decision and its options (costs in the labels); returns the user's answers.",
    ],
}
assert set(ABILITIES) == set(CARDS)
NAMES = {"email_sender": "Email sender", "manual_verification": "User verification"}
# Agents that exist only once the user has signed in to their MCP server (Settings, Connections): until then no step
# sees them; after, they and their server's functions reach the planner on the next task.
NEEDS_MCP = {"ml_engineer": "newton", "campaign_strategizer": "marketwatch", "web_surfer": "obscura"}
ORDER = list(CARDS)[:12]  # the pipeline, user_context to signal_play; email_sender and manual_verification have no place in it

HEADER = """## Agents you can assign
These cards, and the connected-app specialists listed after them, are the only agents that can be given tasks. For each part of the request, use the agent whose "Call when" matches it, and never one whose "Not when" matches. When an agent "Needs" something the chat does not have yet, plan the agent that produces it first. Use the fewest agents that cover the request, one task each, always in this order: $order. An agent of the user's own goes where its card says, otherwise right after the agents whose output it needs. When the user attached a file, the agent whose card names that kind of file and matches the request takes it; if several match, the user's own agent comes first."""


def display_name(name: str) -> str:
    return PERSONAS[name].display_name if name in PERSONAS else NAMES.get(name, name)


def card_list(custom_agents: list[dict], agent_prefs: dict) -> list[dict]:
    """Every agent the planner can call, built-in then the user's own, with the user's notes and on/off state."""
    from src.mcp_client import options

    out = []
    for name, card in CARDS.items():
        pref = agent_prefs.get(name) or {}
        mine = {k: v.strip() for k, v in (pref.get("card") or {}).items() if v.strip()}
        out.append({"name": name, "display_name": display_name(name), "kind": "built_in", "needs": "", **card, **mine,
                    "default": card, "edited": bool(mine), "enabled": pref.get("enabled", True)})
    for a in custom_agents:
        out.append({"name": a["name"], "display_name": a["display_name"], "kind": "custom", "call_when": a["routing"],
                    "file_types": a["file_types"], "apps": [options(s).get("display_name", s) for s in a["mcp_servers"]],
                    "enabled": (agent_prefs.get(a["name"]) or {}).get("enabled", True)})
    return out


def ready(card: dict) -> bool:
    """Whether a step may use the agent: switched on, and signed in to the MCP server it needs."""
    return card["enabled"] and card.get("needs_mcp", {}).get("connected", True)


def render(cards: list[dict]) -> str:
    """The cards as the router and clarifier read them. Switched-off agents, and those waiting for a sign-in, are left out."""
    parts = [Template(HEADER).safe_substitute(order=", ".join(c["name"] for c in cards if c["kind"] == "built_in" and ready(c) and c["name"] in ORDER))]
    for c in cards:
        if not ready(c):
            continue
        if c["kind"] == "custom":
            lines = [f"### {c['name']} ({c['display_name']}, the user's own agent)", f"Call when: {c['call_when'].strip()}"]
            if c["file_types"]:
                lines.append("Reads these attached files: " + ", ".join(prefs.FILE_TYPES[t] for t in c["file_types"]))
            if c["apps"]:
                lines.append("Works in: " + ", ".join(c["apps"]))
        else:
            lines = [f"### {c['name']} ({c['display_name']})", f"Does: {c['does']}", f"Call when: {c['call_when']}", f"Not when: {c['not_when']}"]
            if c["needs"]:
                lines.append(f"Needs: {c['needs']}")
        parts.append("\n".join(lines))
    return "\n\n".join(parts)


def _ability(tool: dict, source: str) -> dict:
    """One MCP function as the planner and Settings read it: its name, what it does and what it takes (required first)."""
    schema = tool.get("input_schema") or {}
    required = set(schema.get("required") or [])
    params = sorted(schema.get("properties") or {}, key=lambda p: p not in required)[:8]
    does = " ".join((tool.get("description") or "").split()).split(". ")[0].rstrip(".")[:200]
    return {"name": tool["name"], "does": does, "params": [f"{p} (required)" if p in required else p for p in params], "source": source}


def _own(name: str) -> list[dict]:
    """A built-in agent's hand-written abilities, in the same shape."""
    return [{"name": n, "does": d, "params": [], "source": "DAXAGENT"} for n, d in (a.split(": ", 1) for a in ABILITIES[name])]


async def _tools(server: str) -> list[dict] | None:
    """A server's functions, live (cached five minutes, see list_tools), or None when it is not connected or offline."""
    from src.mcp_client import is_connected, list_tools

    try:
        return await asyncio.wait_for(list_tools(server), 10) if await is_connected(server) else None
    except Exception as e:
        logger.warning(f"Abilities: '{server}' unavailable: {e}")
        return None


async def add_abilities(cards: list[dict]) -> list[dict]:
    """Give each built-in agent its MCP servers (the ones hooked to it in Settings, Connections) and their functions as
    its abilities, read live, so a server's new functions reach the planner without a code change. An agent with no
    server, or whose servers are all offline, keeps its hand-written abilities."""
    from src.agent_runtime.session import offered
    from src.mcp_client import options
    from src.mcp_client.config import enabled_servers, in_mode

    servers = [s for s in enabled_servers() if in_mode(s, "task") and not options(s).get("guarded")]  # a guarded server's own tools are in ABILITIES
    listed = dict(zip(servers, await asyncio.gather(*(_tools(s) for s in servers))))
    for c in cards:
        if c["kind"] != "built_in":
            continue
        persona = PERSONAS.get(c["name"])
        hooked = [s for s in servers if persona and persona.remote_mcp and offered(persona, s)]
        c["mcp"] = [{"server": options(s).get("display_name", s), "online": listed[s] is not None} for s in hooked]
        live = [_ability(t, options(s).get("display_name", s)) for s in hooked for t in listed[s] or []]
        c["abilities"] = live or _own(c["name"])
    return cards


async def specialist_cards() -> list[dict]:
    """The connected-app specialists, each with its server's functions as abilities, read live."""
    from src.agent_runtime import app_agents, specialists
    from src.mcp_client import options

    out = []
    for name, p in specialists.all().items():
        display, tools = options(p.server).get("display_name", p.server), await _tools(p.server)
        agent = app_agents.for_options(options(p.server))
        if tools and agent and agent["tools"]:  # an app agent uses only its own tools (see specialists.build)
            tools = [t for t in tools if t["name"] in agent["tools"]] or tools
        out.append({"name": name, "display_name": p.display_name, "does": p.tagline, "call_when": p.call_when,
                    "mcp": [{"server": display, "online": tools is not None}], "abilities": [_ability(t, display) for t in tools or []]})
    return out


def _lines(abilities: list[dict], most: int = 20) -> list[str]:
    """Abilities as the planner reads them; past `most`, only the names, to keep a large toolkit's prompt short."""
    line = lambda a: f"{a['name']}: {a['does']}" + (f" Takes: {', '.join(a['params'])}." if a["params"] else "") if a["does"] else a["name"]
    return [line(a) for a in abilities[:most]] + (["Also: " + ", ".join(a["name"] for a in abilities[most:])] if len(abilities) > most else [])


def capabilities(cards: list[dict], specialists: list[dict]) -> str:
    """Every agent as the planner reads it, as JSON keyed by its name: what to put in a task (assign_as), its card, its
    MCP servers and their functions. Built-in agents in pipeline order, then the user's own, then the connected-app
    specialists. Switched-off agents are left out."""
    out: dict[str, dict] = {}

    def put(c: dict, entry: dict) -> None:
        out[c["display_name"] if c["display_name"] not in out else f"{c['display_name']} ({c['name']})"] = {"assign_as": c["name"], **entry}

    for c in cards:
        if not ready(c):
            continue
        if c["kind"] == "custom":
            put(c, {"description": "An agent the user added; it does what its call_when says.", "call_when": c["call_when"].strip(),
                    "reads_files": [prefs.FILE_TYPES[t] for t in c["file_types"]], "works_in": c["apps"]})
        else:
            put(c, {"description": c["does"], "call_when": c["call_when"], "not_when": c["not_when"], **({"needs": c["needs"]} if c["needs"] else {}),
                    **({"mcp": [m["server"] for m in c.get("mcp", [])]} if c.get("mcp") else {}), "abilities": _lines(c.get("abilities") or _own(c["name"]))})
    for s in specialists:
        put(s, {"description": f"Connected app: {s['does']}.", "call_when": s["call_when"], "mcp": [m["server"] for m in s["mcp"]], "abilities": _lines(s["abilities"])})
    return json.dumps(out, indent=2, ensure_ascii=False).replace("\n", "\n    ")  # nested under "available_capabilities"


def specialists_block() -> str:
    """The connected-app specialists (one per MCP server), as they stand now."""
    from src.agent_runtime import specialists

    found = specialists.all()
    if not found:
        return ""
    return ("\n\n## Connected-app specialists\nThese are agents exactly like lead_finder: assign a task to one by its name. "
            "Each owns one connected app and asks the user before spending or sending. Emails to the contacts of a list or campaign "
            "are never a specialist's job, drafts included: those are campaign_builder, then outreach.\n"
            + "\n".join(f"- {name} ({p.display_name}): {p.description}" for name, p in found.items()))


async def mcp_context() -> str:
    """Describe the connected MCP servers for the planner.

    The planner routes by agent name, and MCP tools are not agents: naming the servers here, with
    what each says about itself, keeps the planner from routing around them.
    """
    from src.mcp_client import is_connected, list_tools, options
    from src.mcp_client.client import server_instructions
    from src.mcp_client.config import enabled_servers, in_mode

    sections = []
    for server in enabled_servers():
        if not in_mode(server, "task") or options(server).get("guarded") or not await is_connected(server):
            continue
        try:
            tools = await list_tools(server)  # also reads the server's instructions
        except Exception as e:
            logger.warning(f"Could not describe MCP server '{server}' to planner: {e}")
            continue
        # What the server says about itself comes from the server; the config note only
        # adds what it cannot know: which agents reach it here.
        published = server_instructions(server)
        note = options(server).get("planner_note", "")
        if not published and not note:
            continue
        display = options(server).get("display_name", server)
        sections.append(  # its functions are the abilities of the agents it is hooked to, in available_capabilities
            f"\n\n## {display} (connected)\n{note}"
            + (f"\nWhat it says about itself:\n{published}\n" if published else "")
        )
    return "".join(sections)


async def user_cards(user_id: str, chat_id: str = "") -> list[dict]:
    """The user's cards; an agent in NEEDS_MCP says which server it needs and whether the user has signed in to it.
    A chat that serves an agenda has no user_context card: the user's saved profile never reaches an outside goal."""
    from src.database import chat_agenda
    from src.mcp_client import is_connected, options
    from src.mcp_client.config import enabled_servers

    cards = card_list(await prefs.get(user_id, "custom_agents"), await prefs.get(user_id, "agents"))
    if chat_id and await chat_agenda(chat_id):
        cards = [c for c in cards if c["name"] != "user_context"]
    for c in cards:
        if server := NEEDS_MCP.get(c["name"]):
            c["needs_mcp"] = {"server": options(server).get("display_name", server),
                              "connected": server in enabled_servers() and await is_connected(server)}
    return cards


def waiting_notes(cards: list[dict]) -> str:
    """The agents waiting for an MCP sign-in, as a planner section ("" when none)."""
    waiting = [f"{c['display_name']} ({c['name']}) needs {c['needs_mcp']['server']}" for c in cards if c["enabled"] and not ready(c)]
    if not waiting:
        return ""
    return ("\n\n## Agents waiting for a sign-in\n" + "; ".join(waiting) + ". They are not connected yet, so never plan them. "
            "If the request needs one, say so in overall_strategy and tell the user to connect it in Settings, Connections.")


async def custom_persona(user_id: str, name: str) -> Persona | None:
    """The user's own agent by name, ready to run (None when it no longer exists)."""
    agent = next((a for a in await prefs.get(user_id, "custom_agents") if a["name"] == name), None)
    return custom(agent) if agent else None


# The core agents every task runs through: key -> (name in Settings, what it does, DAXAGENT's prompt). The user sees
# the prompt and can only attach a note to it.
STAGES: dict[str, tuple[str, str, str]] = {
    "judge": ("Judge", "Decides whether a message is a chat or a task.", prompts.judge_question),
    "conversation": ("Conversation", "Answers small talk without starting a task.", prompts.conversation),
    "clarifier": ("Clarifier", "Asks for what a task is missing, as a short form.", prompts.clarifier),
    "planner": ("Planner", "Picks the agents for a task and their order.", PLANNER_CORE),
    "aligner": ("Aligner", "After each step, decides who acts next.", prompts.agent_aligner),
    "router": ("Router", "Hands the next tasks to the agents, together when they can run at once.", prompts.agent_router),
    "verification": ("Verifier", "Asks you to decide before credits are spent or email is sent.", prompts.manual_verification),
    "wrap_up": ("Wrap-up", "Writes the summary when the task is done.", prompts.process_completion),
}
assert set(STAGES) == set(prefs.STAGE_KEYS)

# The happy path of a task, one line per step, as Settings shows it; `prompts` are the steps' prompts, listed under it.
WORKFLOW = [
    {"title": "You ask", "text": "For example: \"Find 20 dental offices in Austin and email the owners our offer.\"", "prompts": ["judge", "conversation"]},
    {"title": "It asks what's missing", "text": "A short form. Answer it, or skip and it uses the defaults.", "prompts": ["clarifier"]},
    {"title": "It shows the plan", "text": "Approve it, or say what to change.", "prompts": ["planner"]},
    {"title": "Agents do the work", "text": "They ask before spending credits or sending email. You approve or decline.", "prompts": ["aligner", "router", "verification"]},
    {"title": "Done", "text": "You get a summary, with the lists and campaign it made.", "prompts": ["wrap_up"]},
]


def with_note(prompt: str, note: str) -> str:
    """A core agent's prompt with the user's note on it added at the end."""
    note = note.strip()
    return f"{prompt}\n\n## The user's note for you\n{note}\nFollow it, but keep the answer format set above." if note else prompt


async def stage_prompts(user_id: str) -> dict[str, str]:
    """Every core agent's prompt: DAXAGENT's, with the user's note on it (Settings > Orchestrator) at the end."""
    notes = (await prefs.get(user_id, "orchestrator"))["notes"]
    return {key: with_note(default, notes.get(key, "")) for key, (_, _, default) in STAGES.items()}


def with_cards(text: str, cards: str) -> str:
    """A prompt with the agent cards where its <<AGENT_CARDS>> line is, or at the end when an edit removed it."""
    return text.replace(AGENTS_SLOT, cards) if AGENTS_SLOT in text else f"{text}\n\n{cards}"


async def planner_core(user_id: str) -> str:
    """The planner's core prompt: the user's version or DAXAGENT's, with today's date."""
    text = (await stage_prompts(user_id))["planner"]
    return Template(text).safe_substitute(today_date=dt.now().strftime("%A, %d %B %Y"), order=", ".join(ORDER))


async def planner_prompt(user_id: str, chat_id: str = "") -> str:
    """Everything the planner reads when a task starts, except the Composio app list Omni adds on top."""
    cards = await add_abilities(await user_cards(user_id, chat_id))
    return (with_cards(await planner_core(user_id), capabilities(cards, await specialist_cards()))
            + waiting_notes(cards) + await mcp_context()
            + await prefs.memory_notes(user_id, chat_id) + await prefs.off_agents_notes(user_id))
