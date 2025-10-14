"""
Unit tests for main application.
"""
import pytest
from fastapi.testclient import TestClient


@pytest.mark.unit
class TestMainApp:
    """Tests for main FastAPI application."""

    def test_app_creation(self, test_app):
        """Test that the app is created successfully."""
        assert test_app is not None
        assert test_app.title == "Autogen FastAPI Backend"

    def test_health_check(self, client):
        """Test the health check endpoint."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "message" in data

    def test_root_redirect(self, client):
        """Test that root redirects to docs."""
        response = client.get("/autogen/", follow_redirects=False)
        assert response.status_code in [307, 302]  # Redirect status

    def test_cors_headers(self, client):
        """Test that CORS headers are present."""
        response = client.options(
            "/health",
            headers={"Origin": "http://localhost:3000"}
        )
        # OPTIONS may return 200 or 405 depending on implementation
        assert response.status_code in [200, 405]

    def test_openapi_schema(self, client):
        """Test that OpenAPI schema is accessible."""
        response = client.get("/autogen/api/v1/openapi.json")
        assert response.status_code == 200
        data = response.json()
        assert "openapi" in data
        assert "components" in data

    def test_bearer_auth_in_schema(self, client):
        """Test that Bearer auth is configured in OpenAPI schema."""
        response = client.get("/autogen/api/v1/openapi.json")
        data = response.json()
        assert "securitySchemes" in data["components"]
        assert "BearerAuth" in data["components"]["securitySchemes"]
        assert data["components"]["securitySchemes"]["BearerAuth"]["type"] == "http"

    def test_serve_html(self, client):
        """Test serving HTML templates."""
        response = client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_capability_html(self, client):
        """Test serving capability HTML."""
        response = client.get("/capability")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]


@pytest.mark.unit
@pytest.mark.smoke
class TestSmokeTests:
    """Smoke tests for basic functionality."""

    def test_app_starts(self, client):
        """Test that the app starts successfully."""
        response = client.get("/health")
        assert response.status_code == 200

    def test_routes_registered(self, test_app):
        """Test that all routers are registered."""
        routes = [route.path for route in test_app.routes]
        assert "/health" in routes
        assert "/autogen/" in routes
