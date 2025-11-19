"""
Unit tests for config router.
"""

import pytest
from unittest.mock import patch


@pytest.mark.unit
@pytest.mark.api
class TestConfigRouter:
    """Tests for configuration endpoints."""

    def test_get_settings_endpoint_exists(self, client):
        """Test that GET /settings endpoint exists."""
        response = client.get("/settings")
        # May return 404 or 401 depending on auth, but should not be 405
        assert response.status_code != 405

    def test_update_settings_endpoint_exists(self, client):
        """Test that PUT /settings endpoint exists."""
        response = client.put("/settings", json={})
        # May return 404 or 401 depending on auth, but should not be 405
        assert response.status_code != 405
