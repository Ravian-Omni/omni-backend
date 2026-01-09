"""Centralized routes configuration.

This module provides centralized management of all API routes and endpoints
used across the application.
"""

import os


class RoutesConfig:
    """Centralized configuration for all API routes and endpoints.

    All configuration values are class attributes and can be accessed directly
    without instantiation: RoutesConfig.BACKEND_URL
    """

    # External API Services
    BRAVE_SEARCH_BASE_URL = os.getenv(
        "BRAVE_SEARCH_BASE_URL", "https://api.search.brave.com/res/v1"
    )
    IPINFO_URL = os.getenv("IPINFO_URL", "https://ipinfo.io/json")

    # Backend URLs
    BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8001")
    BACKEND_URL_FALLBACK = os.getenv("BACKEND_URL_FALLBACK", "http://localhost:8001")

    # OMNI
    API_CREATE_OMNI_CHAT = "/chats/new"
    API_OMNI_CHAT_HISTORY = "/chats/history"
    API_OMNI_TASK_HISTORY = "/chats/history/task_id"
    API_UPDATE_OMNI_CHAT = "/chats/chat_update"

    # USER DETAILS
    API_USER_DETAILS = "/auth/user"

    # CHAT MODE
    API_CREATE_CHAT = "/chats/new"
    API_UPDATE_CHAT = "/chats/chat_update"
    API_CHAT_HISTORY = "/chats/history"
    API_CHAT_NO_AUTH_APPS = "/v1/composio/api/get-noAuth-apps"

    # Credits
    API_CREDIT_DEDUCT = "/v1/wallet/credits-update"

    # API Keys
    API_LLM_KEYS = "/chats/api_keys"

    # AGENT Configurations
    API_AGENT_CONFIGURATIONS = "/chats/configurations"

    # Server Check
    API_SERVER_CHECK = "/"

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
