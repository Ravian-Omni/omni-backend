"""A question nobody answers never ends the run: the card stays open and answerable, and the answer carries on."""

import asyncio
import inspect
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agent_runtime.decisions import DecisionCards
from src.managers.connection import WebSocketManager


def test_no_question_has_a_time_limit():
    assert inspect.signature(WebSocketManager.request_input).parameters["timeout"].default is None
    assert inspect.signature(WebSocketManager._create_input_func).parameters["timeout"].default is None
    assert "timeout" not in inspect.signature(DecisionCards).parameters


@pytest.mark.asyncio
async def test_a_card_left_open_keeps_the_run_and_answering_it_continues_the_work():
    manager = WebSocketManager()
    await manager.connect(MagicMock(accept=AsyncMock(), send_json=AsyncMock()), "c1")
    cards = DecisionCards(manager, "c1", "contact_enricher")
    with patch("src.agent_runtime.decisions.log_decision", AsyncMock(return_value=1)), \
            patch("src.agent_runtime.decisions.answer_decision", AsyncMock()) as answered:
        asking = asyncio.create_task(cards.confirm_spend(tool="contact_enrichment", server="data-axle", count=3))
        await asyncio.sleep(0.2)
        assert not asking.done() and not manager._stop_flags["c1"]  # still waiting, not stopped
        assert manager.pending_request("c1")["data"]["content"]["card"] == "confirm_spend"  # and answerable
        await manager.handle_input_response("c1", "yes")
        decision = await asyncio.wait_for(asking, 10)
    assert decision.approved
    assert answered.await_args.args[0] == 1 and answered.await_args.args[1] != {"action": "abandoned"}
