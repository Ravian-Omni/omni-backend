"""Goals Brain_Hands starts: "SIGNAL PLAY:" followed by the JSON of a signal found on the web, and "MEETING PREP:" and
"RECOVERY NOTE:" followed by the JSON of a contact.

A goal comes from outside, so it is data. It is parsed here and rebuilt from the known, checked fields only;
the text as sent never reaches the agents, and a goal that fails the checks is refused with its reason.
"""

import json
import re
from datetime import date

PREFIX = "SIGNAL PLAY:"
REQUIRED = ("company", "date", "url")
FIELDS = (*REQUIRED, "website", "person", "person_title", "category", "subcategory", "watch_type", "previous_company")  # target_titles (a list) is read apart
MAX_CHARS = 300  # a name, a title or a link; anything longer is prose trying to be read as instructions
MAX_TITLES = 10  # target_titles: the job titles of the people worth writing to; the person-finder searches the first few
GOALS = {  # prefix: (required fields, all fields) of the JSON after it
    PREFIX: (REQUIRED, FIELDS),
    "MEETING PREP:": (("email",), ("email", "name", "company", "website", "when", "agenda_id")),
    "RECOVERY NOTE:": (("email",), ("email", "name", "company", "thread_id", "last_event", "days_quiet", "agenda_id")),
}


def goal_of(task) -> str:
    """The goal's prefix, or "" when the task is not one of these goals."""
    return next((p for p in GOALS if str(task or "").lstrip().startswith(p)), "")


def is_goal(task) -> bool:
    return bool(goal_of(task))


def is_signal(task) -> bool:
    return goal_of(task) == PREFIX


def _value(v):
    """A field's value as kept: text with its whitespace collapsed, or a number; None for anything else."""
    if isinstance(v, str):
        return re.sub(r"\s+", " ", v).strip()
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


async def unmet(chat_id: str, since: str) -> str:
    """The play's rejection when treg found people for it and none passed the lead gate, else "". A play that saved no
    contact says why itself, and without treg connected the play ends as it always has."""
    from src.agent_runtime import leads, treg  # not at the top: agent_runtime imports the connection manager, which imports this

    if not treg.configured():
        return ""
    tally = await leads.tally(chat_id, since)
    if not tally["seen"] or tally["passed"]:
        return ""
    return f"SIGNAL PLAY rejected: no contact passed ({', '.join(f'{n} {why}' for why, n in tally['failed'].items())})"


def prepare(task: str) -> tuple[str, str]:
    """(the goal rebuilt from the checked fields, "") or (the task as given, why it is refused)."""

    prefix = goal_of(task)
    required, fields = GOALS[prefix]

    def refuse(why: str) -> tuple[str, str]:
        return task, f"{prefix[:-1]} rejected: {why} Nothing was planned or sent."

    body = task.lstrip()[len(prefix):].strip()
    try:
        data, end = json.JSONDecoder().raw_decode(body)
    except ValueError:
        return refuse("it must be followed by a JSON object.")
    if not isinstance(data, dict) or body[end:].strip():
        return refuse("it must be followed by one JSON object and nothing after it.")
    clean = {k: _value(data[k]) for k in fields if _value(data.get(k)) not in (None, "")}
    titles = data["target_titles"] if prefix == PREFIX and isinstance(data.get("target_titles"), list) else []
    if titles := [re.sub(r"\s+", " ", t).strip() for t in titles if isinstance(t, str) and t.strip()][:MAX_TITLES]:
        clean["target_titles"] = titles
    if missing := [k for k in required if k not in clean]:
        return refuse(f"missing required field(s): {', '.join(missing)}.")
    if long := [k for k, v in clean.items() if any(len(str(t)) > MAX_CHARS for t in (v if isinstance(v, list) else [v]))]:
        return refuse(f"field(s) too long to be a name, title or link: {', '.join(long)}.")
    if prefix != PREFIX:
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", str(clean["email"])):
            return refuse("email must be an email address.")
        return f"{prefix} {json.dumps(clean, ensure_ascii=False)}", ""
    try:
        date.fromisoformat(clean["date"][:10])
    except ValueError:
        return refuse("date must start with YYYY-MM-DD.")
    if not re.fullmatch(r"https?://\S+", clean["url"]):
        return refuse("url must be an http(s) link.")
    return f"{PREFIX} {json.dumps(clean, ensure_ascii=False)}", ""
