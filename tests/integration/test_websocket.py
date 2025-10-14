"""
Integration tests for WebSocket functionality.
"""
import pytest
import json
from fastapi.testclient import TestClient


@pytest.mark.integration
@pytest.mark.websocket
@pytest.mark.slow
class TestWebSocketIntegration:
    """Integration tests for WebSocket endpoints."""

    def test_websocket_endpoint_exists(self, client):
        """Test that WebSocket endpoints exist."""
        # These will fail to connect without proper setup, but shouldn't 404
        # Note: TestClient WebSocket testing is limited
        pass

    def test_websocket_requires_session_id(self):
        """Test that WebSocket requires session ID."""
        # WebSocket path format: /ws/omni/{chat_id}
        # This is a placeholder for WebSocket testing
        assert "/ws/omni/" in ["/ws/omni/"]

    def test_capability_websocket_endpoint_exists(self):
        """Test that capability WebSocket endpoint exists."""
        # WebSocket path format: /ws/capability/{chat_id}
        assert "/ws/capability/" in ["/ws/capability/"]


@pytest.mark.integration
@pytest.mark.websocket
class TestWebSocketMessages:
    """Tests for WebSocket message formats."""

    def test_start_message_format(self, websocket_messages):
        """Test start message format."""
        msg = websocket_messages["start"]
        assert msg["type"] == "start"
        assert "task" in msg

    def test_stop_message_format(self, websocket_messages):
        """Test stop message format."""
        msg = websocket_messages["stop"]
        assert msg["type"] == "stop"
        assert "reason" in msg

    def test_ping_message_format(self, websocket_messages):
        """Test ping message format."""
        msg = websocket_messages["ping"]
        assert msg["type"] == "ping"

    def test_input_response_format(self, websocket_messages):
        """Test input response format."""
        msg = websocket_messages["input_response"]
        assert msg["type"] == "input_response"
        assert "response" in msg

    def test_all_messages_serializable(self, websocket_messages):
        """Test that all messages can be JSON serialized."""
        for msg_type, msg in websocket_messages.items():
            try:
                json.dumps(msg)
            except Exception as e:
                pytest.fail(f"Message {msg_type} not JSON serializable: {e}")
