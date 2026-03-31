"""Pydantic schemas for Chat Service.

This module defines the data models for chat-related API responses.
"""

from typing import Any, Optional

from pydantic import BaseModel, Field


class RawMessage(BaseModel):
    """Schema for individual raw message in chat history."""

    role: str = Field(default="", description="Role of the message sender")
    name: str = Field(default="", description="Name of the sender")
    raw_message: Any = Field(default="", description="Raw message content")
    task_id: str = Field(default="", description="Task identifier")
    timestamp: str = Field(default="", description="Message timestamp")


class SimplifiedChatHistory(BaseModel):
    """Schema for simplified chat history response."""

    chat_id: str = Field(..., description="Unique chat identifier")
    chat_dir: str = Field(..., description="Chat storage directory")
    raw_messages: list[RawMessage] = Field(
        default_factory=list, description="List of raw messages"
    )
    feedback: Optional[dict] = Field(default=None, description="User feedback")


class ChatCreateResponse(BaseModel):
    """Schema for chat creation response."""

    chat_id: str = Field(..., description="Created chat identifier")
    user_id: str = Field(..., description="User identifier")
    chat_dir: str = Field(..., description="Chat storage directory")
    created_at: str = Field(..., description="Creation timestamp")


class ChatDeleteResponse(BaseModel):
    """Schema for chat deletion response."""

    message: str = Field(..., description="Success message")


class ErrorResponse(BaseModel):
    """Schema for error responses."""

    error: str = Field(..., description="Error type")
    detail: str = Field(..., description="Error details")
