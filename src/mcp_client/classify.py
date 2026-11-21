"""Class every tool by what it can do to the user, so the runtime knows which
calls need a confirmation card before they run.

- ``read``: previews, searches, balances. Runs without asking.
- ``spend``: consumes credits or money (enrichment, purchases). Needs a
  "confirm spend" card.
- ``send``: leaves the system (emails, posts, messages, writes to a CRM,
  deletes). Needs a "confirm send" card.

The default comes from MCP tool annotations when the server sets them, then
from the tool's name and description; the user can override per tool.
"""

import re
from typing import Any

TOOL_CLASSES = ("read", "spend", "send")

_SPEND_NAME = re.compile(r"\b(enrich\w*|purchase|buy|charge|pay|billing|order|subscribe|unlock|reveal)\b", re.I)
_SPEND_DESC = re.compile(
    r"\d+\s*credits?\s*per\b|\bper\s+(successful\s+)?(match|record|result|row|lookup)|"
    r"\bconsumes?\s+\d*\s*credits?|\bwill be charged|\bcosts?\s+\d",
    re.I,
)
_FREE_DESC = re.compile(r"\b0\s*credits?\b|\bfree\b|\bno charge\b|\bpreview only\b", re.I)
_BALANCE_NAME = re.compile(r"\b(balance|available|remaining|usage|quota)\b", re.I)
_SEND_NAME = re.compile(
    r"\b(send|post|publish|email|message|notify|create|write|update|delete|remove|upload|"
    r"submit|schedule|invite|assign|reply|draft|share|add|set|move|archive|trash|forward|modify|mark|label|batch|insert|patch|put|execute|run|"
    r"duplicate|import|watch|copy|clone|cancel|stop|start|restore|merge|approve|accept|decline|rename)\b",
    re.I,
)
_READ_NAME = re.compile(r"\b(search|list|get|fetch|read|lookup|find|preview|check|count|describe)\b", re.I)


def _words(name: str) -> str:
    return re.sub(r"[_\-\.]+", " ", name)


def classify_tool(
    name: str,
    description: str = "",
    annotations: dict[str, Any] | None = None,
    override: str | None = None,
) -> str:
    """Return ``read``, ``spend`` or ``send`` for a tool."""
    if override in TOOL_CLASSES:
        return override
    annotations = annotations or {}
    words = _words(name)
    description = description or ""

    if _BALANCE_NAME.search(words) and not _SEND_NAME.search(words):
        return "read"
    if _SPEND_DESC.search(description) and not _FREE_DESC.search(description):
        return "spend"
    if _SPEND_NAME.search(words):
        return "spend"
    if annotations.get("readOnlyHint") is True or annotations.get("readOnly") is True:
        return "read"
    if annotations.get("destructiveHint") is True or annotations.get("destructive") is True:
        return "send"
    if _SEND_NAME.search(words):
        return "send"
    if _READ_NAME.search(words):
        return "read"
    return "read"
