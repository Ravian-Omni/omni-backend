"""Application configuration settings for Chat Service.

Simplified settings specifically for the Chat Service microservice.
"""

import os
import threading
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()


class Settings:
    """Thread-safe application settings manager for Chat Service.

    Attributes:
        PROJECT_NAME: Name of the project.
        PORT: Application port number.
        DEBUG: Debug mode flag.
        BACKEND_URL: Backend API service URL.
        ROOT_DIR: Root directory for application data.
        CHAT_COLLECTION: MongoDB collection name for chats.
        LOG_LEVEL: Logging level.
    """

    def __init__(self):
        """Initialize settings from environment variables."""
        self._lock = threading.RLock()
        self._load_settings()

    def _load_settings(self):
        """Load settings from environment variables."""
        # Application settings
        self.PROJECT_NAME = "Chat Service"
        self.PORT = os.getenv("PORT", "8000")
        self.DEBUG = os.getenv("DEBUG", "false").lower() == "true"
        self.LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

        # External services
        self.BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8001")

        # Storage
        self.ROOT_DIR = os.getenv("ROOT_DIR", os.path.join(Path.home(), ".chat-service"))

        # MongoDB collections
        self.CHAT_COLLECTION = os.getenv("CHAT_COLLECTION", "chats")

        # API Keys (loaded from environment/secrets)
        self.BRAVE_API_KEY = os.getenv("BRAVE_API_KEY")
        self.TOGETHER_API_KEY = os.getenv("TOGETHER_API_KEY")
        self.OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

    def update_setting(self, key: str, value: Any) -> bool:
        """Update a single setting at runtime.

        Args:
            key: Name of the setting to update.
            value: New value for the setting.

        Returns:
            True if setting was updated, False if key doesn't exist.
        """
        with self._lock:
            if hasattr(self, key):
                setattr(self, key, value)
                return True
            return False

    def get_setting(self, key: str, default=None):
        """Get a setting value.

        Args:
            key: Name of the setting to retrieve.
            default: Default value if setting doesn't exist.

        Returns:
            Value of the setting, or default.
        """
        return getattr(self, key, default)

    def get_all_settings(self) -> dict[str, Any]:
        """Get all settings as dictionary (excluding private attributes).

        Returns:
            Dictionary of all public settings.
        """
        return {
            key: value
            for key, value in self.__dict__.items()
            if not key.startswith("_")
        }


# Global settings instance
settings = Settings()
