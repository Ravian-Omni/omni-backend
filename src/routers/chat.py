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
    chat_id: str
    message: str


class Message(BaseModel):
    role: str
    name: str
    content: str


@router.post("/new_chat")
async def create_new_chat(
    request: Request,
    user_id: str = "default_user",
    chat_dir=os.path.join(settings.ROOT_DIR, "ravian"),
):
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


def serialize_document(doc: dict[Any, Any]) -> dict[str, Any]:
    """Convert MongoDB document to JSON serializable format"""
    if doc is None:
        return None

    # Convert ObjectId to string
    if "_id" in doc:
        doc["_id"] = str(doc["_id"])

    # Convert datetime objects to ISO format
    for key, value in doc.items():
        if isinstance(value, datetime):
            doc[key] = value.isoformat()
        else:
            doc[key] = str(value)

    return doc


class RawMessage(BaseModel):
    role: str
    name: str
    raw_message: Any
    task_id: str | None = None
    timestamp: str


# Modified response model to only include chat_id and raw_messages
class SimplifiedChatHistory(BaseModel):
    chat_id: str
    chat_dir: str | None = None
    raw_messages: list[RawMessage]


@router.get("/chat-history/{user_id}/{chat_id}", response_model=SimplifiedChatHistory)
async def get_specific_chat(
    user_id: str = Path(..., description="User ID"),
    chat_id: str = Path(..., description="Chat ID"),
):
    """Get a specific chat by user_id and chat_id - returns only chat_id and raw_messages"""
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
    task_id: str
    user_id: str
    chat_id: str
    capability: str = "omni"  # Default to "omni" if not provided


@router.post("/chat-history/task_id")
async def get_task_specific_chat(filter_criteria: ChatHistoryByTaskId):
    """Get a specific chat by user_id and chat_id - returns only chat_id and raw_messages"""
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
    """Get a specific chat by user_id and chat_id - returns call_id, capability_name, chat_id and raw_messages"""
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
