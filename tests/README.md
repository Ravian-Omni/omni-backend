# Omni Backend Tests

Comprehensive test suite for the Omni Backend application.

## Quick Start

```bash
# Install test dependencies
pip install -r requirements-test.txt

# Run all tests
pytest

# Run with coverage
pytest --cov=src --cov-report=html
```

## Test Structure

- **unit/** - Unit tests for individual components
- **integration/** - Integration tests for component interactions
- **fixtures/** - Shared test data and fixtures
- **conftest.py** - Shared fixtures and pytest configuration

## Test Categories

Use markers to run specific test categories:

```bash
pytest -m unit           # Unit tests
pytest -m integration    # Integration tests
pytest -m api            # API tests
pytest -m websocket      # WebSocket tests
pytest -m capability     # AI capability tests
pytest -m smoke          # Smoke tests
```

## Writing Tests

### Example Unit Test

```python
import pytest


@pytest.mark.unit
class TestMyComponent:
    def test_something(self):
        """Test something."""
        assert True
```

### Example Integration Test

```python
import pytest


@pytest.mark.integration
class TestAPIFlow:
    def test_full_flow(self, client):
        """Test complete API flow."""
        response = client.get("/endpoint")
        assert response.status_code == 200
```

## Available Fixtures

Defined in [conftest.py](conftest.py):

- `client` - FastAPI TestClient
- `async_client` - Async HTTP client
- `mock_websocket_manager` - Mock WebSocket manager
- `mock_websocket` - Mock WebSocket connection
- `mock_api_client` - Mock API client
- `mock_storage` - Mock storage service
- `sample_chat_data` - Sample chat data
- `sample_user_data` - Sample user data
- `temp_dir` - Temporary directory
- `websocket_messages` - Sample WebSocket messages

## Documentation

See [Testing Guide](../docs/testing-guide.md) for comprehensive documentation.

## Coverage

View coverage report after running tests:

```bash
pytest --cov=src --cov-report=html
open htmlcov/index.html
```

## Tips

- Keep unit tests fast (<1s each)
- Mark slow tests with `@pytest.mark.slow`
- Use fixtures for common setup
- Mock external dependencies
- Test one thing per test
- Use descriptive test names
