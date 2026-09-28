"""Settings the user gives the agents: stored shapes are validated before they are saved."""

import pytest
from pydantic import ValidationError

from src.agent_runtime.prefs import SCHEMAS


def test_memory_items_get_ids_and_timestamps():
    memory = SCHEMAS["memory"].dump_python(SCHEMAS["memory"].validate_python({"items": [{"text": "Sells dental supplies"}]}))
    item = memory["items"][0]
    assert memory["enabled"] is True and item["source"] == "user" and item["id"] and item["created_at"]


def test_memory_text_cannot_be_empty():
    with pytest.raises(ValidationError):
        SCHEMAS["memory"].validate_python({"items": [{"text": ""}]})


def test_agent_instructions_are_keyed_by_agent():
    assert SCHEMAS["agents"].validate_python({"outreach": {"instructions": "CC my manager"}})["outreach"].instructions == "CC my manager"
