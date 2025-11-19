"""Chat management REST API endpoints.

This module provides endpoints for:
- Creating new chat sessions (general and capability-specific)
- Retrieving chat history
- Filtering chat messages by task ID
- Managing capability-specific conversations
"""

import os
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Path, Query, Request, status
from pydantic import BaseModel

from src.configs.settings import CapabilityType, settings
from src.utilities.api_client import api_client
from src.utilities.storage import ensure_path

router = APIRouter()


class ChatRequest(BaseModel):
    """Request model for chat operations.

    Attributes:
        chat_id: Unique identifier for the chat session.
        message: The message content to send.
    """

    chat_id: str
    message: str


class Message(BaseModel):
    """Model for a chat message.

    Attributes:
        role: Role of the message sender (user, assistant, system).
        name: Name of the sender.
        content: The message content.
    """

    role: str
    name: str
    content: str


@router.post("/new_chat")
async def create_new_chat(
    request: Request,
    user_id: str = "default_user",
    chat_dir=os.path.join(settings.ROOT_DIR, "ravian"),
):
    """Create a new general chat session.

    Args:
        request: The FastAPI request object.
        user_id: User identifier. Defaults to "default_user".
        chat_dir: Directory path for storing chat data. Defaults to ROOT_DIR/ravian.

    Returns:
        dict: Created chat document containing chat_id, user_id, and timestamps.

    Raises:
        HTTPException: If chat creation fails with appropriate status code.
    """
    try:
        chat_dir = ensure_path(chat_dir)
        # Generate unique chat identifier
        chat_id = str(uuid.uuid4())

        # Check if the chat_id already exists for this user
        # existing_chat = await mongodb.find_one(
        #     settings.OMNI_COLLECTION,
        #     {"user_id": user_id, "chat_id": chat_id}
        # )

        # if existing_chat:
        #     raise HTTPException(
        #         status_code=status.HTTP_409_CONFLICT,
        #         detail="Chat already exists for this user with the generated ID"
        #     )

        # Prepare chat document
        chat_document = {
            "user_id": user_id,  # Placeholder for user_id, can be replaced with actual user ID logic
            "chat_id": chat_id,
            "chat_dir": chat_dir,
            "messages": [],
            "raw_messages": [],
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }

        # Create database record
        create_chat = await api_client.post(
            "/chats/new", params={"capability": "omni"}, data=chat_document
        )
        create_chat = create_chat.standard_response()
        if not create_chat.get("success"):
            raise Exception(
                f"Failed to create capbility_chat: {create_chat.get('message', 'Unknown error')}"
            )

        result = create_chat.get("data")

        # Return standardized response using Pydantic model
        return result

    except HTTPException:
        # Re-raise HTTP exceptions
        raise

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Chat creation failed due to server error: {e}",
        )


@router.post("capability/new-chat")
async def create_new_capability_chat(
    request: Request,
    capability_name: str = Query(..., description="Capability name"),
    user_id: str = "default_user",
    chat_dir=os.path.join(settings.ROOT_DIR, "ravian"),
):
    """Create a new capability-specific chat session.

    Args:
        request: The FastAPI request object.
        capability_name: Name of the capability (e.g., browser, email, file_finder).
        user_id: User identifier. Defaults to "default_user".
        chat_dir: Directory path for storing chat data. Defaults to ROOT_DIR/ravian.

    Returns:
        dict: Created capability chat document with chat_id, capability_id, and metadata.

    Raises:
        HTTPException: If capability is invalid or chat creation fails.
    """
    try:
        chat_dir = ensure_path(chat_dir)
        # Generate unique chat identifier
        chat_id = str(uuid.uuid4())

        capability = CapabilityType.from_string(capability_name)
        collection_name = capability.collection
        # Check if the chat_id already exists for this user
        # existing_chat = await mongodb.find_one(
        #     collection_name,
        #     {"user_id": user_id, "chat_id": chat_id}
        # )

        # if existing_chat:
        #     raise HTTPException(
        #         status_code=status.HTTP_409_CONFLICT,
        #         detail="Chat already exists for this user with the generated ID"
        #     )

        # Prepare chat document
        chat_document = {
            "user_id": user_id,  # Placeholder for user_id, can be replaced with actual user ID logic
            "chat_id": chat_id,
            "chat_dir": chat_dir,
            "call_id": "Individual",
            "capability_id": chat_id,
            "messages": [],
            "raw_messages": [],
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }

        # Create database record
        # await mongodb.insert_one(collection_name, chat_document)
        create_chat = await api_client.post(
            "/chats/new", params={"capability": collection_name}, data=chat_document
        )
        create_chat = create_chat.standard_response()
        if not create_chat.get("success"):
            raise Exception(
                f"Failed to create capbility_chat: {create_chat.get('message', 'Unknown error')}"
            )

        result = create_chat.get("data")

        # Return standardized response using Pydantic model
        return result

    except HTTPException:
        # Re-raise HTTP exceptions
        raise

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Chat creation failed due to server error: {e}",
        )


def serialize_document(doc: dict) -> dict:
    """Convert MongoDB document to JSON serializable format.

    Handles conversion of MongoDB-specific types (ObjectId, datetime) to
    standard JSON-compatible types.

    Args:
        doc: MongoDB document dictionary to serialize.

    Returns:
        dict: JSON-serializable version of the document, or None if input is None.
    """
    if doc is None:
        return None

    serialized = {}
    for key, value in doc.items():
        # Detect ObjectId by its class name
        if type(value).__name__ == "ObjectId":
            serialized[key] = str(value)
        elif isinstance(value, datetime):
            serialized[key] = value.isoformat()
        elif isinstance(value, dict):
            serialized[key] = serialize_document(value)
        elif isinstance(value, list):
            serialized[key] = [
                serialize_document(v) if isinstance(v, dict) else v for v in value
            ]
        else:
            serialized[key] = value
    return serialized


class RawMessage(BaseModel):
    """Model for a raw chat message with metadata.

    Attributes:
        role: Role of the message sender (user, assistant, system).
        name: Name of the sender.
        raw_message: The raw message content (can be any type).
        task_id: Optional task identifier associated with the message.
        timestamp: ISO format timestamp of the message.
    """

    role: str
    name: str
    raw_message: Any
    task_id: str | None = None
    timestamp: str


class SimplifiedChatHistory(BaseModel):
    """Simplified chat history response model.

    Attributes:
        chat_id: Unique identifier for the chat session.
        chat_dir: Optional directory path where chat data is stored.
        raw_messages: List of raw messages in the chat.
    """

    chat_id: str
    chat_dir: str | None = None
    raw_messages: list[RawMessage]


@router.get("/chat-history/{user_id}/{chat_id}", response_model=SimplifiedChatHistory)
async def get_specific_chat(
    user_id: str = Path(..., description="User ID"),
    chat_id: str = Path(..., description="Chat ID"),
):
    """Get a specific chat by user_id and chat_id.

    Args:
        user_id: User identifier.
        chat_id: Chat session identifier.

    Returns:
        SimplifiedChatHistory: Chat history containing chat_id, chat_dir, and raw_messages.

    Raises:
        HTTPException: 404 if chat not found, 500 if retrieval fails.
    """
    try:
        query = {"user_id": user_id, "chat_id": chat_id}
        # document = await mongodb.find_one(settings.OMNI_COLLECTION, query)
        chat_history = await api_client.post(
            "/chats/history", params={"capability": "omni"}, data=query
        )
        chat_history = chat_history.standard_response()
        if not chat_history.get("success"):
            raise HTTPException(
                status_code=404,
                detail=f"Chat not found for user_id: {user_id} and chat_id: {chat_id}",
            )

        document = chat_history.get("data")

        # Serialize the full document first
        serialized_doc = serialize_document(document)

        # Transform messages to raw_messages format
        raw_messages = []
        if "raw_messages" in serialized_doc:
            for message in serialized_doc["raw_messages"]:
                raw_messages.append(
                    {
                        "role": message.get("role", ""),
                        "name": message.get("name", ""),
                        "raw_message": message.get(
                            "raw_message", ""
                        ),  # Using content as raw_message
                        "task_id": message.get(
                            "task_id", ""
                        ),  # Using content as raw_message
                        "timestamp": message.get(
                            "timestamp", ""
                        ),  # Using content as raw_message
                    }
                )

        # Return only chat_id and raw_messages
        return {
            "chat_id": serialized_doc.get("chat_id", ""),
            "chat_dir": serialized_doc.get("chat_dir", ""),
            "raw_messages": raw_messages,
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch chat: {str(e)}")


class ChatHistoryByTaskId(BaseModel):
    """Request model for filtering chat history by task ID.

    Attributes:
        task_id: Task identifier to filter messages.
        user_id: User identifier.
        chat_id: Chat session identifier.
        capability: Capability name. Defaults to "omni".
    """

    task_id: str
    user_id: str
    chat_id: str
    capability: str = "omni"  # Default to "omni" if not provided


@router.post("/chat-history/task_id")
async def get_task_specific_chat(filter_criteria: ChatHistoryByTaskId):
    """Get chat messages filtered by task ID.

    Args:
        filter_criteria: Filter parameters including task_id, user_id, chat_id, and capability.

    Returns:
        dict: Filtered chat history for the specified task.

    Raises:
        HTTPException: 404 if chat not found, 500 if retrieval fails.
    """
    try:
        chat_history = await api_client.post(
            "/chats/history/task_id", data=filter_criteria.model_dump()
        )
        chat_history = chat_history.standard_response()
        if not chat_history.get("success"):
            raise HTTPException(
                status_code=404,
                detail=f"Chat not found for chat_id: {filter_criteria.chat_id} and task_id: {filter_criteria.task_id}",
            )

        # document = chat_history.get("data")

        # Return only chat_id and raw_messages
        return chat_history

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch chat: {str(e)}")


class EnhancedChatHistory(BaseModel):
    """Enhanced chat history response model with capability context.

    Attributes:
        call_id: Identifier for the capability call.
        capability_name: Name of the capability used.
        chat_id: Chat session identifier.
        raw_messages: List of raw messages in the chat.
    """

    call_id: str
    capability_name: str
    chat_id: str
    raw_messages: list[RawMessage]


@router.get(
    "/chat-history/capability/{user_id}/{chat_id}", response_model=EnhancedChatHistory
)
async def get_specific_capability_chat_messages(
    user_id: str = Path(..., description="User ID"),
    chat_id: str = Path(..., description="Chat ID"),
    call_id: str = Query(..., description="Call ID"),
    capability_name: str = Query(..., description="Capability name"),
):
    """Get capability-specific chat messages.

    Args:
        user_id: User identifier.
        chat_id: Chat session identifier.
        call_id: Capability call identifier.
        capability_name: Name of the capability (must be valid CapabilityType).

    Returns:
        EnhancedChatHistory: Chat history with call_id, capability_name, chat_id, and raw_messages.

    Raises:
        HTTPException: 400 if capability invalid, 404 if chat not found, 500 if retrieval fails.
    """
    try:
        query = {"user_id": user_id, "chat_id": chat_id, "call_id": call_id}
        if capability_name not in CapabilityType._value2member_map_:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid capability name: {capability_name}. Must be one of the valid capability names",
            )
        capability = CapabilityType._value2member_map_.get(capability_name)
        collection_name = capability.collection
        # document = await mongodb.find_one(collection_name, query)
        chat_history = await api_client.post(
            "/chats/history", params={"capability": collection_name}, data=query
        )
        chat_history = chat_history.standard_response()
        if not chat_history.get("success"):
            raise HTTPException(
                status_code=404,
                detail=f"Chat not found for user_id: {user_id} and chat_id: {chat_id}",
            )

        document = chat_history.get("data")

        # Serialize the full document first
        serialized_doc = serialize_document(document)

        # Transform messages to raw_messages format
        raw_messages = []
        if "raw_messages" in serialized_doc:
            for message in serialized_doc["raw_messages"]:
                raw_messages.append(
                    {
                        "role": message.get("role", ""),
                        "name": message.get("name", ""),
                        "raw_message": message.get("raw_message", ""),
                        "task_id": message.get("task_id", ""),
                        "timestamp": message.get("timestamp", ""),
                    }
                )

        # Return call_id, capability_name, chat_id and raw_messages
        return {
            "call_id": call_id,
            "capability_name": capability_name,
            "chat_id": serialized_doc.get("chat_id", ""),
            "raw_messages": raw_messages,
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch chat: {str(e)}")
