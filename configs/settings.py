# src/config/settings.py
from dotenv import load_dotenv, set_key
import os
from typing import Dict, Any
from pathlib import Path
import threading
from enum import Enum

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
        self.BROWSER_COLLECTION = os.getenv("BROWSER_COLLECTION", "browser_manager")
        self.PYTHON_DEV_COLLECTION = os.getenv("PYTHON_DEV_COLLECTION", "python_developer")
        self.FILE_FINDER_COLLECTION = os.getenv("FILE_FINDER_COLLECTION", "file_finder")
        self.IMAGE_GENERATOR_COLLECTION = os.getenv("IMAGE_GENERATOR_COLLECTION", "image_generator")
    
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