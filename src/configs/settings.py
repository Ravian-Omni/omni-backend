"""Application configuration settings and environment variable management.

This module provides centralized configuration management for the OMNI application,
including thread-safe runtime updates and capability type definitions. It loads
settings from environment variables and provides a global settings instance.
"""

# src/config/settings.py
import os
import threading
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()


class Settings:
    """Thread-safe application settings manager.

    Manages application configuration loaded from environment variables with
    support for thread-safe runtime updates. All settings are loaded from
    environment variables at initialization.

    Attributes:
        PROJECT_NAME: Name of the project.
        PORT: Application port number.
        BACKEND_URL: Backend service URL.
        USER_TOKEN: User authentication token.
        ROOT_DIR: Root directory for application data.
        USER_EMAIL: User's email address for notifications.
        USER_EMAIL_PASSWORD: User's email password.
        USER_FILES_PATH: Path to user files storage.
        USER_NAME: User's display name.
        AG2AI_PYTHON_PATH: Path to Python executable for AG2AI.
        CHROME_EXECUTABLE_PATH: Path to Chrome browser executable.
        OMNI_COLLECTION: MongoDB collection name for omni.
        EMAIL_COLLECTION: MongoDB collection name for email manager.
        BROWSER_COLLECTION: MongoDB collection name for browser manager.
    """

    def __init__(self):
        """Initialize settings and load from environment variables."""
        self._lock = threading.RLock()  # Thread safety
        self._load_settings()

    def _load_settings(self):
        """Load settings from environment variables.

        Initialize all application settings from environment variables with
        appropriate defaults for optional settings.
        """
        self.PROJECT_NAME = "OMNI"
        self.PORT = os.getenv("PORT", "8000")
        self.BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8001")
        self.USER_TOKEN = None
        self.ROOT_DIR = os.path.join(Path.home(), ".daxagent")
        self.USER_EMAIL = os.getenv("email_username")
        self.USER_EMAIL_PASSWORD = os.getenv("email_password")
        self.USER_FILES_PATH = os.getenv("USER_FILES_PATH", "/mnt/data")
        self.USER_NAME = os.getenv("user_name")
        # Default to the .venv in project root if it exists, otherwise "python"
        _default_venv = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            ".venv",
        )
        self.AG2AI_PYTHON_PATH = os.getenv(
            "AG2AI_PYTHON_PATH",
            _default_venv if os.path.isdir(_default_venv) else "python",
        )
        self.CHROME_EXECUTABLE_PATH = os.getenv(
            "CHROME_EXECUTABLE_PATH",
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        )

        # MongoDB settings
        self.CHAT_COLLECTION = os.getenv("CHAT_COLLECTION", "chats")
        self.OMNI_COLLECTION = os.getenv("OMNI_COLLECTION", "omni")
        self.EMAIL_COLLECTION = os.getenv("EMAIL_COLLECTION", "email_manager")
        self.BROWSER_COLLECTION = os.getenv("BROWSER_COLLECTION", "browser_manager")
        self.SOFTWARE_DEV_COLLECTION = os.getenv(
            "SOFTWARE_DEV_COLLECTION", "software_developer"
        )

        # Agent runtime (personas): "openai" runs them on the chat-completions model from
        # configs/llm_model_mapping.json (gpt-5.6-luna); "anthropic" runs them on the Claude Agent SDK.
        self.AGENT_PROVIDER = (os.getenv("DAXAGENT_AGENT_PROVIDER") or "anthropic").strip().lower()
        self.AGENT_MODEL = os.getenv("DAXAGENT_AGENT_MODEL") or ("claude-sonnet-5" if self.AGENT_PROVIDER == "anthropic" else None)
        self.AGENT_MAX_OUTPUT_TOKENS = int(os.getenv("DAXAGENT_AGENT_MAX_OUTPUT_TOKENS", "0") or 0)  # 0 = runner default
        self.AGENT_MAX_TURNS = int(os.getenv("DAXAGENT_AGENT_MAX_TURNS", "0") or 0)  # 0 = persona default
        self.AGENT_EFFORT = os.getenv("DAXAGENT_AGENT_EFFORT") or None  # low | medium | high | xhigh | max
        self.AGENT_MAX_BUDGET_USD = float(os.getenv("DAXAGENT_AGENT_MAX_BUDGET_USD", "0") or 0) or None

        # LLM Provider API Keys
        self.OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
        self.ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
        self.TOGETHER_API_KEY = os.getenv("TOGETHER_API_KEY")
        self.TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
        self.BRAVE_API_KEY = os.getenv("BRAVE_API_KEY")
        self.COMPOSIO_API_KEY = os.getenv("COMPOSIO_API_KEY")

        # User Profile
        self.USER_FIRST_NAME = os.getenv("USER_FIRST_NAME", "")
        self.USER_LAST_NAME = os.getenv("USER_LAST_NAME", "")
        self.USER_DOB = os.getenv("USER_DOB", "")
        self.USER_GENDER = os.getenv("USER_GENDER", "")
        self.USER_COUNTRY = os.getenv("USER_COUNTRY", "")

    def get_date_time_now(self) -> datetime:
        """Get the current date and time in UTC timezone.

        Returns:
            Timezone-aware datetime object in UTC.
        """
        return datetime.now(timezone.utc)

    def update_setting(self, key: str, value: Any) -> bool:
        """Update a single setting at runtime.

        Thread-safe method to update an existing setting value. Only updates
        settings that already exist as attributes.

        Args:
            key: Name of the setting to update.
            value: New value for the setting.

        Returns:
            True if setting was updated successfully, False if key doesn't exist.
        """
        with self._lock:
            if hasattr(self, key):
                setattr(self, key, value)
                return True
            return False

    def update_settings(self, updates: dict[str, Any]) -> dict[str, bool]:
        """Update multiple settings at once.

        Thread-safe method to update multiple settings in a single operation.

        Args:
            updates: Dictionary mapping setting names to new values.

        Returns:
            Dictionary mapping setting names to update success status (True/False).
        """
        with self._lock:
            results = {}
            for key, value in updates.items():
                results[key] = self.update_setting(key, value)
            return results

    def get_setting(self, key: str, default=None):
        """Get a setting value.

        Retrieve the value of a setting by key with optional default fallback.

        Args:
            key: Name of the setting to retrieve.
            default: Default value to return if setting doesn't exist. Defaults to None.

        Returns:
            Value of the setting, or default if setting doesn't exist.
        """
        return getattr(self, key, default)

    def get_all_settings(self) -> dict[str, Any]:
        """Get all settings as dictionary.

        Retrieve all settings excluding internal attributes (those starting with _).

        Returns:
            Dictionary containing all public settings and their values.
        """
        return {
            key: value
            for key, value in self.__dict__.items()
            if not key.startswith("_")
        }


# Create global settings instance
settings = Settings()


class CapabilityType(Enum):
    """Enumeration of all available system capabilities.

    Defines all available capability types in the OMNI system and their
    corresponding database collection names. Each capability represents a
    distinct functional module.

    Attributes:
        OMNI: Main orchestration capability.
        EMAIL_MANAGER: Email sending and management capability.
        BROWSER_MANAGER: Web browser automation capability.
    """

    CHAT = "chat"
    OMNI = "omni"
    EMAIL_MANAGER = "email_sender"
    BROWSER_MANAGER = "web_browser"
    SOFTWARE_DEVELOPER = "software_developer"
    ML_ENGINEER = "ml_engineer"
    LEAD_FINDER = "lead_finder"
    BUYER_FINDER = "buyer_finder"
    CONTACT_ENRICHER = "contact_enricher"
    CAMPAIGN_BUILDER = "campaign_builder"
    OUTREACH = "outreach"

    @classmethod
    def from_string(cls, capability_name: str):
        """Get CapabilityType instance from string.

        Convert a string capability name to its corresponding CapabilityType enum.

        Args:
            capability_name: String name of the capability.

        Returns:
            CapabilityType enum instance.

        Raises:
            ValueError: If capability_name is not a valid capability.
        """
        try:
            return cls(capability_name)
        except ValueError:
            valid_names = [cap.value for cap in cls]
            raise ValueError(
                f"Invalid capability name: {capability_name}. Valid names: {valid_names}"
            )

    @property
    def collection(self):
        """Return the MongoDB collection name for this capability.

        Returns:
            MongoDB collection name string for the capability.
        """
        return {
            CapabilityType.CHAT: settings.CHAT_COLLECTION,
            CapabilityType.OMNI: settings.OMNI_COLLECTION,
            CapabilityType.EMAIL_MANAGER: settings.EMAIL_COLLECTION,
            CapabilityType.BROWSER_MANAGER: settings.BROWSER_COLLECTION,
            CapabilityType.SOFTWARE_DEVELOPER: settings.SOFTWARE_DEV_COLLECTION,
        }.get(self, self.value)  # personas use their own name as collection

    @classmethod
    def from_collection(cls, collection_name: str):
        """Get CapabilityType instance from MongoDB collection name.

        Reverse lookup to find the capability type associated with a given
        collection name.

        Args:
            collection_name: MongoDB collection name.

        Returns:
            CapabilityType enum instance.

        Raises:
            ValueError: If no capability is found for the collection name.
        """
        for capability in cls:
            if capability.collection == collection_name:
                return capability
        raise ValueError(f"No capability found for collection: {collection_name}")
