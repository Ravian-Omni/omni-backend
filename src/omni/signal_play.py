"""The signal play: a goal that starts "SIGNAL PLAY:" followed by the JSON of a signal found on the web.

The goal comes from outside, so it is data. It is parsed here and rebuilt from the known, checked fields only;
the text as sent never reaches the agents, and a goal that fails the checks is refused with its reason.
"""

import json
import re
from datetime import date

PREFIX = "SIGNAL PLAY:"
REQUIRED = ("company", "date", "url")
FIELDS = (*REQUIRED, "website", "person", "person_title", "category", "subcategory", "watch_type", "previous_company")
MAX_CHARS = 300  # a name, a title or a link; anything longer is prose trying to be read as instructions


def is_signal(task) -> bool:
    return str(task or "").lstrip().startswith(PREFIX)


def prepare(task: str) -> tuple[str, str]:
    """(the goal rebuilt from the checked fields, "") or (the task as given, why it is refused)."""

    def refuse(why: str) -> tuple[str, str]:
        return task, f"SIGNAL PLAY rejected: {why} Nothing was planned or sent."

    body = task.lstrip()[len(PREFIX):].strip()
    try:
        data, end = json.JSONDecoder().raw_decode(body)
    except ValueError:
        return refuse("it must be followed by a JSON object.")
    if not isinstance(data, dict) or body[end:].strip():
        return refuse("it must be followed by one JSON object and nothing after it.")
    clean = {k: re.sub(r"\s+", " ", data[k]).strip() for k in FIELDS if isinstance(data.get(k), str) and data[k].strip()}
    if missing := [k for k in REQUIRED if k not in clean]:
        return refuse(f"missing required field(s): {', '.join(missing)}.")
    if long := [k for k, v in clean.items() if len(v) > MAX_CHARS]:
        return refuse(f"field(s) too long to be a name, title or link: {', '.join(long)}.")
    try:
        date.fromisoformat(clean["date"][:10])
    except ValueError:
        return refuse("date must start with YYYY-MM-DD.")
    if not re.fullmatch(r"https?://\S+", clean["url"]):
        return refuse("url must be an http(s) link.")
    return f"{PREFIX} {json.dumps(clean, ensure_ascii=False)}", ""
