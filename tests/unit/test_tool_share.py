"""On OpenAI an app gets a share of the 128 tools: its read tools come first, and writes are never mistaken for reads."""

import pytest

from src.agent_runtime.openai_runner import read_first
from src.mcp_client.classify import classify_tool


@pytest.mark.parametrize("name, cls", [
    ("GOOGLECALENDAR_DUPLICATE_CALENDAR", "send"), ("GOOGLECALENDAR_EVENTS_IMPORT", "send"), ("GOOGLECALENDAR_EVENTS_WATCH", "send"),
    ("GMAIL_DELETE_MESSAGE", "send"), ("GOOGLECALENDAR_EVENTS_LIST", "read"), ("GMAIL_FETCH_EMAILS", "read"), ("GOOGLECALENDAR_COLORS_GET", "read"),
])
def test_writes_with_uncommon_verbs_ask_first_and_reads_do_not(name, cls):
    assert classify_tool(name) == cls


def test_an_apps_read_tools_come_first_in_their_own_order():
    tools = [{"name": n} for n in ("ACL_DELETE", "ACL_GET", "BATCH_EVENTS", "EVENTS_LIST", "FIND_EVENT")]
    classes = {f"mcp__cal__{t['name']}": classify_tool(t["name"]) for t in tools}
    assert [t["name"] for t in read_first("cal", tools, classes)][:3] == ["ACL_GET", "EVENTS_LIST", "FIND_EVENT"]
