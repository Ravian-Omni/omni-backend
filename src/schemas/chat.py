"""Chat-related Pydantic schemas for request/response validation.

This module defines all schema models used by chat endpoints including:
- Chat creation requests
- Message models
- Chat history responses
- Task-based filtering
"""

from typing import Any

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """Request model for chat operations.

    Attributes:
        chat_id: Unique identifier for the chat session.
        message: The message content to send.
    """

    chat_id: str = Field(..., description="Unique identifier for the chat session")
    message: str = Field(..., description="The message content to send")


class Message(BaseModel):
    """Model for a chat message.

    Attributes:
        role: Role of the message sender (user, assistant, system).
        name: Name of the sender.
        content: The message content.
    """

    role: str = Field(..., description="Role of the message sender")
    name: str = Field(..., description="Name of the sender")
    content: str = Field(..., description="The message content")


class RawMessage(BaseModel):
    """Model for a raw chat message with metadata.

    Attributes:
        role: Role of the message sender (user, assistant, system).
        name: Name of the sender.
        raw_message: The raw message content (can be any type).
        task_id: Optional task identifier associated with the message.
        timestamp: ISO format timestamp of the message.
    """

    role: str = Field(..., description="Role of the message sender")
    name: str = Field(..., description="Name of the sender")
    raw_message: Any = Field(..., description="The raw message content")
    task_id: str | None = Field(default=None, description="Task identifier")
    timestamp: str = Field(..., description="ISO format timestamp")


class SimplifiedChatHistory(BaseModel):
    """Simplified chat history response model.

    Attributes:
        chat_id: Unique identifier for the chat session.
        chat_dir: Optional directory path where chat data is stored.
        raw_messages: List of raw messages in the chat.
    """

    chat_id: str = Field(..., description="Unique chat session identifier")
    chat_dir: str | None = Field(default=None, description="Chat data directory path")
    raw_messages: list[RawMessage] = Field(
        default_factory=list, description="List of raw messages"
    )
    feedback: dict[str, Any] = Field(
        default_factory=dict, description="Ratings given in this conversation, as {data: [...]}"
    )


class ChatHistoryByTaskId(BaseModel):
    """Request model for filtering chat history by task ID.

    Attributes:
        task_id: Task identifier to filter messages.
        user_id: User identifier.
        chat_id: Chat session identifier.
        capability: Capability name. Defaults to "omni".
    """

    task_id: str = Field(..., description="Task identifier to filter messages")
    user_id: str = Field(..., description="User identifier")
    chat_id: str = Field(..., description="Chat session identifier")
    capability: str = Field(default="omni", description="Capability name")


class EnhancedChatHistory(BaseModel):
    """Enhanced chat history response model with capability context.

    Attributes:
        call_id: Identifier for the capability call.
        capability_name: Name of the capability used.
        chat_id: Chat session identifier.
        raw_messages: List of raw messages in the chat.
    """

    call_id: str = Field(..., description="Capability call identifier")
    capability_name: str = Field(..., description="Name of the capability")
    chat_id: str = Field(..., description="Chat session identifier")
    raw_messages: list[RawMessage] = Field(
        default_factory=list, description="List of raw messages"
    )
