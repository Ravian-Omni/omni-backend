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
    USER_EMAIL = "suryapratapsinghrathore@gmail.com"
    USER_FILES_PATH = os.getenv("USER_FILES_PATH","/mnt/data")
    
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
    AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY")
    AZURE_OPENAI_API_KEY_O3 = os.getenv("AZURE_OPENAI_API_KEY_O3")
    TOGETHER_DEEPSEEK_API_KEY = os.getenv("TOGETHER_DEEPSEEK_API_KEY")
    
    # MongoDB settings
    MONGODB_URI = os.getenv("MONGODB_URI","localhost")
    DATABASE_NAME=os.getenv("DATABASE_NAME","user-management")
    CHAT_COLLECTION= os.getenv("CHAT_COLLECTION","chat-history")
    
    
    # Redis settings
    REDIS_HOST: str = os.getenv("REDIS_HOST", "redis")
    REDIS_PORT: int = int(os.getenv("REDIS_PORT", "6379"))
    REDIS_PASSWORD: Optional[str] = os.getenv("REDIS_PASSWORD", "redis")
    REDIS_MAX_CONNECTIONS:int=int(os.getenv("REDIS_MAX_CONNECTIONS",100))
    REDIS_CHAT_TTL_SECONDS:int = int(os.getenv("REDIS_CHAT_TTL_SECONDS",3600))
    
    class Config:
        env_file = ".env"
        case_sensitive = True

settings = Settings()