"""
Unit tests for WebSocket connection manager.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.managers.connection import WebSocketManager


@pytest.mark.unit
class TestWebSocketManager:
    """Tests for WebSocketManager class."""

    @pytest.fixture
    def manager(self):
        """Create a WebSocketManager instance."""
        return WebSocketManager()

    @pytest.mark.asyncio
    async def test_manager_initialization(self, manager):
        """Test that manager initializes correctly."""
        assert manager is not None
        assert hasattr(manager, "active_connections")

    @pytest.mark.asyncio
    async def test_connect(self, manager, mock_websocket):
        """Test connecting a WebSocket."""
        session_id = "test-session"
        result = await manager.connect(mock_websocket, session_id)
        assert isinstance(result, bool)

    @pytest.mark.asyncio
    async def test_disconnect(self, manager):
        """Test disconnecting a WebSocket."""
        session_id = "test-session"
        await manager.disconnect(session_id)
        # Should not raise an error

    @pytest.mark.asyncio
    async def test_create_input_func(self, manager):
        """Test creating an input function."""
        session_id = "test-session"
        input_func = manager._create_input_func(session_id)
        assert callable(input_func)

    @pytest.mark.asyncio
    async def test_multiple_connections(self, manager):
        """Test managing multiple WebSocket connections."""
        ws1 = MagicMock()
        ws1.accept = AsyncMock()
        ws2 = MagicMock()
        ws2.accept = AsyncMock()

        await manager.connect(ws1, "session-1")
        await manager.connect(ws2, "session-2")

        await manager.disconnect("session-1")
        await manager.disconnect("session-2")


@pytest.mark.asyncio
async def test_a_thread_driving_a_run_keeps_it_when_the_page_opens_and_leaves_the_chat():
    """An MCP (or Slack, Teams) thread started the run; the web app opening the chat must not take its questions or end it."""
    manager = WebSocketManager()
    thread = MagicMock(drives_run=True, accept=AsyncMock(), send_json=AsyncMock())
    page = MagicMock(spec=["accept", "send_json"], accept=AsyncMock(), send_json=AsyncMock())
    await manager.connect(thread, "chat")
    await manager.connect(page, "chat")

    question = {"type": "input_request", "data": {"content": {"card": "form"}}}
    await manager._send_message("chat", question)
    assert question in [c.args[0] for c in thread.send_json.call_args_list]  # the thread gets the clarifier's question too
    assert question in [c.args[0] for c in page.send_json.call_args_list]

    manager._pending_requests["chat"] = question
    thread.send_json.reset_mock()
    await manager.resend_pending("chat", page)  # a reload shows it again on the page only, never twice to the thread
    thread.send_json.assert_not_called()

    await manager.disconnect("chat", page)  # the page leaves: the run goes on, driven by the thread again
    assert manager._connections["chat"] is thread and not manager._stop_flags["chat"]
    await manager.disconnect("chat", thread)
    assert "chat" not in manager._connections
