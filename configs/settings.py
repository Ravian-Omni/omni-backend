# src/config/settings.py
from dotenv import load_dotenv, set_key
import os
import sys
from typing import Dict, Any
from pathlib import Path
import threading
from enum import Enum
import sys

load_dotenv()

# Get the directory where the current file is located
current_file_path = Path(__file__).resolve()


class Settings:
    def __init__(self):
        self._lock = threading.RLock()  # Thread safety
        self._load_settings()

    def _load_settings(self):
        """Load settings from environment"""
        self.PROJECT_NAME = "OMNI"
        self.ROOT_DIR = os.path.dirname(current_file_path.parent)
        self.USER_EMAIL = os.getenv("email_username")
        self.USER_EMAIL_PASSWORD = os.getenv("email_password")
        self.USER_FILES_PATH = os.getenv("USER_FILES_PATH", "/mnt/data")
        self.USER_NAME = os.getenv("user_name")

        self.OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
        self.ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
        self.AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY")
        self.AZURE_OPENAI_API_KEY_O3 = os.getenv("AZURE_OPENAI_API_KEY_O3")
        self.TOGETHER_API_KEY = os.getenv("TOGETHER_API_KEY")
        self.TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")

        # MongoDB settings
        self.MONGODB_URI = os.getenv("MONGODB_URI", "localhost")
        self.DATABASE_NAME = os.getenv("DATABASE_NAME", "OMNI-DB")
        self.OMNI_COLLECTION = os.getenv("OMNI_COLLECTION", "omni")
        self.EMAIL_COLLECTION = os.getenv("EMAIL_COLLECTION", "email_manager")
        self.BROWSER_COLLECTION = os.getenv(
            "BROWSER_COLLECTION", "browser_manager")
        self.PYTHON_DEV_COLLECTION = os.getenv(
            "PYTHON_DEV_COLLECTION", "python_developer")
        self.FILE_FINDER_COLLECTION = os.getenv(
            "FILE_FINDER_COLLECTION", "file_finder")
        self.IMAGE_GENERATOR_COLLECTION = os.getenv(
            "IMAGE_GENERATOR_COLLECTION", "image_generator")

        # browser settings
        self.CHROME_EXECUTABLE_PATH = os.getenv("CHROME_EXECUTABLE_PATH",
                                                "/Users/voidfinder/Library/Caches/ms-playwright/chromium-1169/chrome-mac/Chromium.app/Contents/MacOS/Chromium")

        # Detect if running from executable
        self.IS_EXECUTABLE = getattr(
            sys, 'frozen', False) and hasattr(sys, '_MEIPASS')

        # Browser-specific settings for executable environment
        if self.IS_EXECUTABLE:
            # Set a stable temp directory for browser data when running as executable
            self.BROWSER_DATA_DIR = os.path.join(
                os.path.expanduser("~"), ".omni_browser_data")
            # Disable certain features that might cause path issues in executable
            self.BROWSER_DISABLE_EXTENSIONS = True
            self.BROWSER_DISABLE_DEV_SHM = True
        else:
            self.BROWSER_DATA_DIR = os.path.join(
                os.path.expanduser("~"), "browser_use_data")
            self.BROWSER_DISABLE_EXTENSIONS = False
            self.BROWSER_DISABLE_DEV_SHM = False

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
            key: value for key, value in self.__dict__.items()
            if not key.startswith('_')
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
