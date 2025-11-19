"""
Unit tests for API client utilities.
"""

import pytest
from unittest.mock import AsyncMock, patch


@pytest.mark.unit
class TestAPIClient:
    """Tests for API client."""

    @pytest.mark.asyncio
    async def test_api_client_get(self, mock_api_client):
        """Test GET request."""
        response = await mock_api_client.get("/test")
        assert response is not None
        result = response.standard_response()
        assert "success" in result

    @pytest.mark.asyncio
    async def test_api_client_post(self, mock_api_client):
        """Test POST request."""
        response = await mock_api_client.post("/test", data={"key": "value"})
        assert response is not None
        result = response.standard_response()
        assert "success" in result

    @pytest.mark.asyncio
    async def test_api_client_put(self, mock_api_client):
        """Test PUT request."""
        response = await mock_api_client.put("/test", data={"key": "value"})
        assert response is not None
        result = response.standard_response()
        assert "success" in result

    @pytest.mark.asyncio
    async def test_api_client_delete(self, mock_api_client):
        """Test DELETE request."""
        response = await mock_api_client.delete("/test")
        assert response is not None
        result = response.standard_response()
        assert "success" in result

    @pytest.mark.asyncio
    async def test_api_client_standard_response(self, mock_api_client):
        """Test standard response format."""
        response = await mock_api_client.get("/test")
        result = response.standard_response()
        assert isinstance(result, dict)
        assert "success" in result
        assert "data" in result
        assert "message" in result
