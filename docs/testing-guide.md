## Testing Guide

Comprehensive testing guide for the Omni Backend application.

## Table of Contents

1. [Overview](#overview)
2. [Test Structure](#test-structure)
3. [Running Tests](#running-tests)
4. [Writing Tests](#writing-tests)
5. [Test Coverage](#test-coverage)
6. [Continuous Integration](#continuous-integration)

## Overview

The Omni Backend uses pytest as the testing framework with comprehensive unit, integration, and end-to-end tests.

### Test Categories

- **Unit Tests**: Test individual components in isolation
- **Integration Tests**: Test interactions between multiple components
- **API Tests**: Test REST API endpoints
- **WebSocket Tests**: Test WebSocket functionality
- **Capability Tests**: Test AI capability modules
- **Smoke Tests**: Quick tests for basic functionality

## Test Structure

```
tests/
├── __init__.py
├── conftest.py              # Shared fixtures and configuration
├── pytest.ini              # Pytest configuration (in root)
├── unit/                   # Unit tests
│   ├── __init__.py
│   ├── test_main.py
│   ├── test_routers_config.py
│   ├── test_managers_connection.py
│   ├── test_utilities_*.py
│   ├── test_configs_*.py
│   ├── test_capabilities.py
│   └── test_omni.py
├── integration/            # Integration tests
│   ├── __init__.py
│   ├── test_api_endpoints.py
│   └── test_websocket.py
└── fixtures/               # Test fixtures and data
    └── __init__.py
```

## Running Tests

### Install Test Dependencies

```bash
# Install test dependencies
pip install -r requirements-test.txt

# Or install with main dependencies
pip install -r requirements.txt
pip install -r requirements-test.txt
```

### Run All Tests

```bash
# Run all tests
pytest

# Run with verbose output
pytest -v

# Run with coverage
pytest --cov=src --cov-report=html
```

### Run Specific Test Categories

```bash
# Run only unit tests
pytest -m unit

# Run only integration tests
pytest -m integration

# Run only API tests
pytest -m api

# Run only WebSocket tests
pytest -m websocket

# Run only capability tests
pytest -m capability

# Run smoke tests (quick validation)
pytest -m smoke

# Run specific test file
pytest tests/unit/test_main.py

# Run specific test class
pytest tests/unit/test_main.py::TestMainApp

# Run specific test function
pytest tests/unit/test_main.py::TestMainApp::test_health_check
```

### Run Tests in Parallel

```bash
# Run tests in parallel (faster)
pytest -n auto

# Run on 4 cores
pytest -n 4
```

### Run Tests with Different Options

```bash
# Stop on first failure
pytest -x

# Stop after 3 failures
pytest --maxfail=3

# Show local variables on failure
pytest -l

# Run last failed tests
pytest --lf

# Run tests that failed, then all others
pytest --ff

# Show slowest 10 tests
pytest --durations=10

# Run tests matching keyword
pytest -k "test_health"

# Run tests NOT matching keyword
pytest -k "not slow"
```

## Writing Tests

### Basic Test Structure

```python
import pytest
from unittest.mock import MagicMock, AsyncMock, patch


@pytest.mark.unit
class TestYourComponent:
    """Tests for YourComponent."""

    @pytest.fixture
    def component(self):
        """Create component instance."""
        return YourComponent()

    def test_something(self, component):
        """Test something about the component."""
        result = component.do_something()
        assert result == expected_value

    @pytest.mark.asyncio
    async def test_async_method(self, component):
        """Test async method."""
        result = await component.async_method()
        assert result is not None
```

### Using Fixtures

Fixtures are defined in [conftest.py](../tests/conftest.py):

```python
def test_with_client(client):
    """Test using TestClient fixture."""
    response = client.get("/health")
    assert response.status_code == 200


async def test_with_async_client(async_client):
    """Test using AsyncClient fixture."""
    response = await async_client.get("/health")
    assert response.status_code == 200


def test_with_mock_data(sample_chat_data):
    """Test using sample data fixture."""
    assert sample_chat_data["chat_id"] == "test-chat-123"
```

### Testing API Endpoints

```python
@pytest.mark.api
def test_endpoint(client):
    """Test API endpoint."""
    response = client.get("/endpoint")
    assert response.status_code == 200

    data = response.json()
    assert "key" in data
```

### Testing WebSocket

```python
@pytest.mark.websocket
def test_websocket(mock_websocket):
    """Test WebSocket functionality."""
    # Setup
    mock_websocket.receive_json.return_value = {"type": "ping"}

    # Test
    # ... your websocket logic

    # Verify
    mock_websocket.send_json.assert_called()
```

### Testing Async Functions

```python
@pytest.mark.asyncio
async def test_async_function():
    """Test async function."""
    result = await async_function()
    assert result is not None
```

### Mocking

```python
from unittest.mock import MagicMock, AsyncMock, patch


# Mock a regular function
@patch('src.module.function')
def test_with_mock(mock_function):
    mock_function.return_value = "mocked"
    result = your_function()
    assert result == "mocked"


# Mock an async function
@patch('src.module.async_function', new_callable=AsyncMock)
async def test_async_mock(mock_async):
    mock_async.return_value = "mocked"
    result = await your_async_function()
    assert result == "mocked"


# Mock environment variables
@patch.dict('os.environ', {'KEY': 'value'})
def test_with_env():
    import os
    assert os.environ['KEY'] == 'value'
```

### Testing Exceptions

```python
def test_raises_exception():
    """Test that function raises exception."""
    with pytest.raises(ValueError):
        function_that_raises()


def test_exception_message():
    """Test exception message."""
    with pytest.raises(ValueError, match="specific message"):
        function_that_raises()
```

### Parametrized Tests

```python
@pytest.mark.parametrize("input,expected", [
    ("hello", "HELLO"),
    ("world", "WORLD"),
    ("test", "TEST"),
])
def test_uppercase(input, expected):
    """Test with multiple inputs."""
    assert input.upper() == expected
```

## Test Markers

Available markers (defined in pytest.ini):

- `@pytest.mark.unit` - Unit tests
- `@pytest.mark.integration` - Integration tests
- `@pytest.mark.slow` - Slow running tests
- `@pytest.mark.api` - API endpoint tests
- `@pytest.mark.websocket` - WebSocket tests
- `@pytest.mark.database` - Database tests
- `@pytest.mark.capability` - AI capability tests
- `@pytest.mark.smoke` - Smoke tests

### Using Markers

```python
@pytest.mark.unit
@pytest.mark.slow
def test_something_slow():
    """This is a slow unit test."""
    pass
```

### Running by Marker

```bash
# Run only fast tests (exclude slow)
pytest -m "not slow"

# Run unit OR integration tests
pytest -m "unit or integration"

# Run unit AND api tests
pytest -m "unit and api"
```

## Test Coverage

### Generate Coverage Report

```bash
# Run tests with coverage
pytest --cov=src

# Generate HTML report
pytest --cov=src --cov-report=html

# Open HTML report
open htmlcov/index.html  # macOS
xdg-open htmlcov/index.html  # Linux
start htmlcov/index.html  # Windows
```

### Coverage Configuration

Coverage settings in [pytest.ini](../pytest.ini):

```ini
[pytest]
addopts =
    --cov=src
    --cov-report=html
    --cov-report=term-missing
    --cov-branch
```

### Coverage Goals

- **Overall**: Aim for >80% coverage
- **Critical paths**: >95% coverage
- **Utilities**: >90% coverage
- **Integration**: >70% coverage

## Continuous Integration

### GitHub Actions Example

```yaml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: [3.9, 3.10, 3.11, 3.12]

    steps:
    - uses: actions/checkout@v3

    - name: Set up Python
      uses: actions/setup-python@v4
      with:
        python-version: ${{ matrix.python-version }}

    - name: Install dependencies
      run: |
        pip install -r requirements.txt
        pip install -r requirements-test.txt

    - name: Run tests
      run: |
        pytest --cov=src --cov-report=xml

    - name: Upload coverage
      uses: codecov/codecov-action@v3
      with:
        file: ./coverage.xml
```

## Best Practices

### 1. Test Naming

- Use descriptive names: `test_health_check_returns_ok_status`
- Follow pattern: `test_<what>_<expected_behavior>`
- Use docstrings to explain complex tests

### 2. Test Organization

- One test class per component
- Group related tests together
- Keep tests in corresponding unit/integration folders

### 3. Fixtures

- Use fixtures for common setup
- Keep fixtures in conftest.py for reusability
- Use appropriate fixture scope (function, class, module, session)

### 4. Assertions

- Use descriptive assertions
- Test one thing per test
- Avoid multiple unrelated assertions

### 5. Mocking

- Mock external dependencies
- Don't mock what you're testing
- Use appropriate mock types (Mock, MagicMock, AsyncMock)

### 6. Async Tests

- Mark with `@pytest.mark.asyncio`
- Use `AsyncMock` for async mocks
- Properly await all async calls

### 7. Test Data

- Use fixtures for test data
- Keep test data minimal but representative
- Don't use production data in tests

### 8. Performance

- Keep unit tests fast (<1s each)
- Mark slow tests with `@pytest.mark.slow`
- Run slow tests separately in CI

## Debugging Tests

### Run with PDB

```bash
# Drop into debugger on failure
pytest --pdb

# Drop into debugger on first failure
pytest -x --pdb
```

### Show Print Statements

```bash
# Show print statements
pytest -s

# Show captured output
pytest --capture=no
```

### Verbose Output

```bash
# Very verbose
pytest -vv

# Show local variables on failure
pytest -l

# Show full diff
pytest -vv --tb=long
```

## Common Issues

### Import Errors

```bash
# Make sure src is in Python path
export PYTHONPATH="${PYTHONPATH}:${PWD}"
pytest
```

### Async Warnings

```python
# Use pytest-asyncio and mark tests
@pytest.mark.asyncio
async def test_async():
    pass
```

### Fixture Not Found

- Check fixture is in conftest.py
- Check fixture scope
- Check typos in fixture name

## Additional Resources

- [Pytest Documentation](https://docs.pytest.org/)
- [Pytest-Asyncio](https://pytest-asyncio.readthedocs.io/)
- [Coverage.py](https://coverage.readthedocs.io/)
- [FastAPI Testing](https://fastapi.tiangolo.com/tutorial/testing/)

## Quick Reference

```bash
# Common commands
pytest                                  # Run all tests
pytest -v                              # Verbose
pytest -m unit                         # Unit tests only
pytest --cov=src                       # With coverage
pytest -n auto                         # Parallel
pytest -x                              # Stop on first failure
pytest --lf                            # Run last failed
pytest tests/unit/test_main.py        # Specific file
pytest -k "test_health"               # Match keyword
pytest --durations=10                 # Show slowest tests
```

## Support

For issues with tests:
1. Check test output carefully
2. Run with `-vv` for more details
3. Use `--pdb` to debug failures
4. Check conftest.py for fixture definitions
