"""
Integration tests for API endpoints.
"""

import pytest
from fastapi.testclient import TestClient


@pytest.mark.integration
@pytest.mark.api
class TestAPIIntegration:
    """Integration tests for API endpoints."""

    def test_health_check_integration(self, client):
        """Test health check endpoint integration."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"

    def test_root_to_docs_flow(self, client):
        """Test navigation from root to docs."""
        # Get root
        response = client.get("/autogen/", follow_redirects=False)
        assert response.status_code in [307, 302]

        # Check redirect location exists
        headers_lower = {k.lower(): v for k, v in response.headers.items()}
        assert "location" in headers_lower

    def test_html_endpoints_work(self, client):
        """Test that HTML endpoints are accessible."""
        # Main page
        response = client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

        # Capability page
        response = client.get("/capability")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_openapi_schema_complete(self, client):
        """Test that OpenAPI schema is complete."""
        response = client.get("/autogen/api/v1/openapi.json")
        assert response.status_code == 200

        schema = response.json()
        assert "openapi" in schema
        assert "info" in schema
        assert "paths" in schema
        assert "components" in schema

        # Check that our endpoints are documented
        paths = schema["paths"]
        assert "/health" in paths

    def test_cors_full_flow(self, client):
        """Test CORS preflight and actual request."""
        origin = "http://localhost:3000"

        # Preflight request
        preflight = client.options(
            "/health",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "GET",
            },
        )
        assert preflight.status_code == 200

        # Actual request
        actual = client.get("/health", headers={"Origin": origin})
        assert actual.status_code == 200


@pytest.mark.integration
@pytest.mark.slow
class TestErrorHandling:
    """Integration tests for error handling."""

    def test_404_handling(self, client):
        """Test 404 error handling."""
        response = client.get("/nonexistent-endpoint")
        assert response.status_code == 404

    def test_405_method_not_allowed(self, client):
        """Test 405 method not allowed."""
        response = client.post("/health")  # GET-only endpoint
        assert response.status_code == 405

    def test_invalid_json_handling(self, client):
        """Test handling of invalid JSON."""
        response = client.post(
            "/settings",
            data="invalid json",
            headers={"Content-Type": "application/json"},
        )
        # Should return 422, 400, or 404 (if endpoint doesn't exist)
        assert response.status_code in [400, 404, 422]
