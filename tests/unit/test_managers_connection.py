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
        assert hasattr(manager, 'active_connections')

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
