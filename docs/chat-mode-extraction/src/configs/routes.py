"""Centralized routes configuration for Chat Service.

This module provides centralized management of all API routes and endpoints.
"""

import os


class RoutesConfig:
    """Centralized configuration for all API routes and endpoints."""

    # Backend URLs
    BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8001")

    # Chat API Routes
    API_CREATE_CHAT = "/chats/new"
    API_CHAT_HISTORY = "/chats/history"
    API_UPDATE_CHAT = "/chats/chat_update"
    API_DELETE_CHAT = "/chats/delete"

    # User Details
    API_USER_DETAILS = "/auth/user"

    # External Services
    BRAVE_SEARCH_BASE_URL = os.getenv(
        "BRAVE_SEARCH_BASE_URL", "https://api.search.brave.com/res/v1"
    )

    @classmethod
    def get_backend_url(cls, route: str = "") -> str:
        """Get backend URL with optional route.

        Args:
            route: Optional route to append to backend URL.

        Returns:
            Complete backend URL with route.
        """
        return f"{cls.BACKEND_URL}{route}"

    @classmethod
    def get_brave_search_url(cls, endpoint: str = "/web/search") -> str:
        """Get Brave Search API URL with specified endpoint.

        Args:
            endpoint: API endpoint path.

        Returns:
            Complete Brave Search API URL.
        """
        return f"{cls.BRAVE_SEARCH_BASE_URL}{endpoint}"
