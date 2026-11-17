"""
Pytest configuration and shared fixtures.
"""

import asyncio
import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path
from collections.abc import AsyncGenerator, Generator
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from httpx import AsyncClient

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Before src is imported (its settings read this then): the suite never opens the real ~/.daxagent database or files
_DATA_DIR = tempfile.mkdtemp(prefix="daxagent-tests-")
os.environ["DAXAGENT_DATA_DIR"] = _DATA_DIR
atexit.register(shutil.rmtree, _DATA_DIR, True)

from src.main import app
from src.managers.connection import WebSocketManager

# ============================================================
# Session-scoped fixtures
# ============================================================


@pytest.fixture(scope="session")
def event_loop():
    """Create an event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
def test_app():
    """Get the FastAPI application instance."""
    return app


# ============================================================
# Function-scoped fixtures
# ============================================================


@pytest.fixture(autouse=True)
def _no_live_services(monkeypatch):
    """The real .env's CRM settings never reach a test: those calls write to live records."""
    for key in ("CRM_MCP_URL", "CRM_API_KEY"):
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def client(test_app) -> Generator[TestClient, None, None]:
    """Create a test client for the FastAPI app."""
    with TestClient(test_app) as test_client:
        yield test_client


@pytest.fixture
async def async_client(test_app) -> AsyncGenerator[AsyncClient, None]:
    """Create an async test client for the FastAPI app."""
    async with AsyncClient(app=test_app, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def mock_websocket_manager():
    """Create a mock WebSocket manager."""
    manager = MagicMock(spec=WebSocketManager)
    manager.connect = AsyncMock(return_value=True)
    manager.disconnect = AsyncMock()
    manager.send_json = AsyncMock()
    manager.start_chat_stream = AsyncMock()
    manager.stop_session = AsyncMock()
    manager.handle_input_response = AsyncMock()
    manager._create_input_func = MagicMock()
    manager.terminal_input = AsyncMock()
    manager.terminal_kill = AsyncMock()
    return manager


@pytest.fixture
def mock_env_vars(monkeypatch):
    """Set up test environment variables."""
    test_env = {
        "PORT": "8001",
        "PROJECT_NAME": "Test Omni Backend",
        "ROOT_DIR": "/tmp/test",  # nosec B108
        "OPENAI_API_KEY": "test-key",  # pragma: allowlist secret
        "TESTING": "true",
    }
    for key, value in test_env.items():
        monkeypatch.setenv(key, value)
    return test_env


@pytest.fixture
def temp_dir(tmp_path):
    """Create a temporary directory for testing."""
    return tmp_path


@pytest.fixture
def sample_chat_data():
    """Sample chat data for testing."""
    return {
        "chat_id": "test-chat-123",
        "user_id": "test-user-456",
        "messages": [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
        ],
        "chat_dir": "/tmp/test/chat",  # nosec B108
    }


@pytest.fixture
def sample_user_data():
    """Sample user data for testing."""
    return {
        "first_name": "Test",
        "last_name": "User",
        "email": "test@example.com",
        "dob": "1990-01-01",
        "gender": "Other",
        "country": "USA",
    }


@pytest.fixture
def mock_api_client():
    """Create a mock API client."""
    client = MagicMock()

    # Mock response class
    class MockResponse:
        def __init__(self, data, success=True):
            self._data = data
            self._success = success

        def standard_response(self):
            return {
                "success": self._success,
                "data": self._data,
                "message": "Success" if self._success else "Error",
            }

    client.get = AsyncMock(return_value=MockResponse({}))
    client.post = AsyncMock(return_value=MockResponse({}))
    client.put = AsyncMock(return_value=MockResponse({}))
    client.delete = AsyncMock(return_value=MockResponse({}))

    return client


# ============================================================
# WebSocket testing fixtures
# ============================================================


@pytest.fixture
def mock_websocket():
    """Create a mock WebSocket connection."""
    ws = MagicMock()
    ws.accept = AsyncMock()
    ws.send_json = AsyncMock()
    ws.send_text = AsyncMock()
    ws.receive_text = AsyncMock()
    ws.receive_json = AsyncMock()
    ws.close = AsyncMock()
    return ws


@pytest.fixture
def websocket_messages():
    """Sample WebSocket messages for testing."""
    return {
        "start": {
            "type": "start",
            "task": "Test task",
        },
        "stop": {
            "type": "stop",
            "reason": "User requested stop",
        },
        "ping": {
            "type": "ping",
        },
        "input_response": {
            "type": "input_response",
            "response": "Test input",
        },
        "executor_input": {
            "type": "executor_input",
            "process_id": "test-process",
            "response": "test input",
        },
        "executor_stop": {
            "type": "executor_stop",
            "process_id": "test-process",
        },
    }


# ============================================================
# Capability testing fixtures
# ============================================================


@pytest.fixture
def mock_llm_response():
    """Create a mock LLM response."""
    return {
        "content": "Test response from LLM",
        "role": "assistant",
        "function_call": None,
    }


@pytest.fixture
def mock_capability_manager():
    """Create a mock capability manager."""
    manager = MagicMock()
    manager.run = AsyncMock(return_value="Test result")
    manager.resume = MagicMock(return_value=(None, None))
    return manager


# ============================================================
# Database/Storage fixtures
# ============================================================


@pytest.fixture
def mock_storage():
    """Create a mock storage service."""
    storage = MagicMock()
    storage.save = AsyncMock()
    storage.load = AsyncMock(return_value={})
    storage.delete = AsyncMock()
    storage.exists = AsyncMock(return_value=True)
    return storage


# ============================================================
# Cleanup fixtures
# ============================================================


@pytest.fixture(autouse=True)
def cleanup_test_files(tmp_path):
    """Clean up test files after each test."""
    yield
    # Cleanup happens automatically with tmp_path


# ============================================================
# Markers
# ============================================================


def pytest_configure(config):
    """Configure custom markers."""
    config.addinivalue_line("markers", "unit: mark test as a unit test")
    config.addinivalue_line("markers", "integration: mark test as an integration test")
    config.addinivalue_line("markers", "slow: mark test as slow running")
