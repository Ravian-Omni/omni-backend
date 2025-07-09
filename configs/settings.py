# src/config/settings.py
from dotenv import load_dotenv
import os
from typing import Optional
load_dotenv()
from pathlib import Path

# Get the directory where the current file is located
current_file_path = Path(__file__).resolve()

class Settings:
    PROJECT_NAME = "OMNI"
    ROOT_DIR = os.path.dirname(current_file_path.parent)
    USER_EMAIL = os.getenv("email_username")
    USER_EMAIL_PASSWORD = os.getenv("email_password")
    USER_FILES_PATH = os.getenv("USER_FILES_PATH","/mnt/data")
    USER_NAME = os.getenv("user_name")
    
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
    AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY")
    AZURE_OPENAI_API_KEY_O3 = os.getenv("AZURE_OPENAI_API_KEY_O3")
    TOGETHER_API_KEY = os.getenv("TOGETHER_API_KEY")
    WEB_API = os.getenv("web_api")
    
    # MongoDB settings
    MONGODB_URI = os.getenv("MONGODB_URI","localhost")
    DATABASE_NAME=os.getenv("DATABASE_NAME","OMNI-DB")
    OMNI_COLLECTION= os.getenv("OMNI_COLLECTION","omni")
    EMAIL_COLLECTION= os.getenv("EMAIL_COLLECTION","email_manager")
    BROWSER_COLLECTION= os.getenv("BROWSER_COLLECTION","browser_manager")
    PYTHON_DEV_COLLECTION= os.getenv("PYTHON_DEV_COLLECTION","python_developer")
    FILE_FINDER_COLLECTION= os.getenv("FILE_FINDER_COLLECTION","file_finder")
    IMAGE_GENERATOR_COLLECTION= os.getenv("IMAGE_GENERATOR_COLLECTION","image_generator")
    
    
    
    class Config:
        env_file = ".env"
        case_sensitive = True

settings = Settings()
