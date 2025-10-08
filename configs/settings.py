# src/config/settings.py
import os
import threading
from enum import Enum
from pathlib import Path
from typing import Any, Dict

from dotenv import load_dotenv

load_dotenv()


class Settings:
    def __init__(self):
        self._lock = threading.RLock()  # Thread safety
        self._load_settings()

    def _load_settings(self):
        """Load settings from environment"""
        self.PROJECT_NAME = "OMNI"
        self.PORT = os.getenv("PORT", "8000")
        self.BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8001")
        self.USER_TOKEN = None
        self.ROOT_DIR = os.path.join(Path.home(), ".ravian")
        self.USER_EMAIL = os.getenv("email_username")
        self.USER_EMAIL_PASSWORD = os.getenv("email_password")
        self.USER_FILES_PATH = os.getenv("USER_FILES_PATH", "/mnt/data")
        self.USER_NAME = os.getenv("user_name")
        self.AG2AI_PYTHON_PATH = os.getenv("AG2AI_PYTHON_PATH", "python")
        self.CHROME_EXECUTABLE_PATH = os.getenv(
            "CHROME_EXECUTABLE_PATH",
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        )

        # MongoDB settings
        self.OMNI_COLLECTION = os.getenv("OMNI_COLLECTION", "omni")
        self.EMAIL_COLLECTION = os.getenv("EMAIL_COLLECTION", "email_manager")
        self.BROWSER_COLLECTION = os.getenv("BROWSER_COLLECTION", "browser_manager")
        self.PYTHON_DEV_COLLECTION = os.getenv(
            "PYTHON_DEV_COLLECTION", "python_developer"
        )
        self.FILE_FINDER_COLLECTION = os.getenv("FILE_FINDER_COLLECTION", "file_finder")
        self.IMAGE_GENERATOR_COLLECTION = os.getenv(
            "IMAGE_GENERATOR_COLLECTION", "image_generator"
        )

    def update_setting(self, key: str, value: Any) -> bool:
        """Update a single setting at runtime"""
        with self._lock:
            if hasattr(self, key):
                setattr(self, key, value)
                return True
            return False

    def update_settings(self, updates: Dict[str, Any]) -> Dict[str, bool]:
        """Update multiple settings at once"""
        with self._lock:
            results = {}
            for key, value in updates.items():
                results[key] = self.update_setting(key, value)
            return results

    def get_setting(self, key: str, default=None):
        """Get a setting value"""
        return getattr(self, key, default)

    def get_all_settings(self) -> Dict[str, Any]:
        """Get all settings as dictionary"""
        return {
            key: value
            for key, value in self.__dict__.items()
            if not key.startswith("_")
        }


# Create global settings instance
settings = Settings()


class CapabilityType(Enum):
    """Enumeration of all available capabilities"""

    OMNI = "omni"
    EMAIL_MANAGER = "email_sender"
    BROWSER_MANAGER = "web_browser"
    PYTHON_DEVELOPER = "python_coder"
    FILE_FINDER = "file_finder"
    IMAGE_GENERATOR = "image_generator"

    @classmethod
    def from_string(cls, capability_name: str):
        """Get CapabilityType instance from string, raises ValueError if invalid"""
        try:
            return cls(capability_name)
        except ValueError:
            valid_names = [cap.value for cap in cls]
            raise ValueError(
                f"Invalid capability name: {capability_name}. Valid names: {valid_names}"
            )

    @property
    def collection(self):
        """Return the collection associated with each capability."""
        return {
            CapabilityType.OMNI: settings.OMNI_COLLECTION,
            CapabilityType.EMAIL_MANAGER: settings.EMAIL_COLLECTION,
            CapabilityType.BROWSER_MANAGER: settings.BROWSER_COLLECTION,
            CapabilityType.PYTHON_DEVELOPER: settings.PYTHON_DEV_COLLECTION,
            CapabilityType.FILE_FINDER: settings.FILE_FINDER_COLLECTION,
            CapabilityType.IMAGE_GENERATOR: settings.IMAGE_GENERATOR_COLLECTION,
        }[self]

    @classmethod
    def from_collection(cls, collection_name: str):
        """Get CapabilityType instance from collection name."""
        for capability in cls:
            if capability.collection == collection_name:
                return capability
        raise ValueError(f"No capability found for collection: {collection_name}")
