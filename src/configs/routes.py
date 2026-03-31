"""Centralized routes configuration.

This module provides centralized management of external API routes and endpoints
used across the application. Cloud backend routes have been removed as the app
now uses local SQLite persistence.
"""

import os


class RoutesConfig:
    """Centralized configuration for external API routes and endpoints."""

    # External API Services
    BRAVE_SEARCH_BASE_URL = os.getenv(
        "BRAVE_SEARCH_BASE_URL", "https://api.search.brave.com/res/v1"
    )

    # Backend URL (kept for Composio and any remaining external calls)
    BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8001")
    BACKEND_URL_FALLBACK = os.getenv("BACKEND_URL_FALLBACK", "http://localhost:8001")

    # Composio (optional, works when online)
    API_CHAT_NO_AUTH_APPS = "/v1/composio/api/get-noAuth-apps"

    @classmethod
    def get_brave_search_url(cls, endpoint: str = "/web/search") -> str:
        """Get Brave Search API URL with specified endpoint.

        Args:
            endpoint: API endpoint path (default: "/web/search")

        Returns:
            Complete Brave Search API URL
        """
        return f"{cls.BRAVE_SEARCH_BASE_URL}{endpoint}"

    @classmethod
    def get_backend_url(cls, route: str = "") -> str:
        """Get backend URL with optional route.

        Args:
            route: Optional route to append to backend URL

        Returns:
            Complete backend URL with route
        """
        return f"{cls.BACKEND_URL}{route}"
