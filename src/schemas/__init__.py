"""Pydantic schemas for API request/response validation.

This module exports all schema models used across the application.
"""

from src.schemas.chat import (
    ChatHistoryByTaskId,
    ChatRequest,
    EnhancedChatHistory,
    Message,
    RawMessage,
    SimplifiedChatHistory,
)
from src.schemas.settings import (
    APIKeysStatusResponse,
    APIKeysUpdateRequest,
    EmailCredentialsResponse,
    EmailUpdateRequest,
    SettingsResponse,
    UserProfileResponse,
    UserProfileUpdateRequest,
)

__all__ = [
    # Chat schemas
    "ChatRequest",
    "Message",
    "RawMessage",
    "SimplifiedChatHistory",
    "ChatHistoryByTaskId",
    "EnhancedChatHistory",
    # Settings schemas
    "SettingsResponse",
    "APIKeysUpdateRequest",
    "APIKeysStatusResponse",
    "UserProfileUpdateRequest",
    "UserProfileResponse",
    "EmailUpdateRequest",
    "EmailCredentialsResponse",
]
