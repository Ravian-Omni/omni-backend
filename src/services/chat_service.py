"""Chat business logic service.

This module provides the ChatService class that encapsulates all
chat-related business logic including:
- Chat session creation
- Chat history retrieval
- Document serialization
- Message transformation
"""

import os
import uuid
from typing import Any

from fastapi import HTTPException, status

from src.configs.datetime_utils import dt
from src.configs.settings import CapabilityType, settings
from src.database import get_chat_repository
from src.utilities.storage import ensure_path


class ChatService:
    """Service class for chat-related business logic."""

    @staticmethod
    def generate_chat_id() -> str:
        """Generate a unique chat identifier.

        Returns:
            str: UUID string for the chat session.
        """
        return str(uuid.uuid4())

    @staticmethod
    def get_default_chat_dir() -> str:
        """Get the default chat directory path.

        Returns:
            str: Default chat directory path.
        """
        return os.path.join(settings.ROOT_DIR, "ravian")

    @staticmethod
    def serialize_document(doc: dict) -> dict | None:
        """Convert MongoDB document to JSON serializable format.

        Handles conversion of MongoDB-specific types (ObjectId, datetime) to
        standard JSON-compatible types.

        Args:
            doc: MongoDB document dictionary to serialize.

        Returns:
            dict | None: JSON-serializable version of the document, or None if input is None.
        """
        if doc is None:
            return None

        serialized = {}
        for key, value in doc.items():
            if type(value).__name__ == "ObjectId":
                serialized[key] = str(value)
            elif isinstance(value, datetime):
                serialized[key] = value.isoformat()
            elif isinstance(value, dict):
                serialized[key] = ChatService.serialize_document(value)
            elif isinstance(value, list):
                serialized[key] = [
                    ChatService.serialize_document(v) if isinstance(v, dict) else v
                    for v in value
                ]
            else:
                serialized[key] = value
        return serialized

    @staticmethod
    def transform_raw_messages(serialized_doc: dict) -> list[dict[str, Any]]:
        """Transform raw messages from document to standardized format.

        Args:
            serialized_doc: Serialized document containing raw_messages.

        Returns:
            list[dict]: List of transformed message dictionaries.
        """
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
        return raw_messages

    @staticmethod
    def build_chat_document(
        user_id: str, chat_id: str, chat_dir: str, is_capability: bool = False
    ) -> dict:
        """Build a chat document for database insertion.

        Args:
            user_id: User identifier.
            chat_id: Chat session identifier.
            chat_dir: Directory path for chat storage.
            is_capability: Whether this is a capability-specific chat.

        Returns:
            dict: Chat document ready for insertion.
        """
        document = {
            "user_id": user_id,
            "chat_id": chat_id,
            "chat_dir": chat_dir,
            "messages": [],
            "raw_messages": [],
            "created_at": dt.now(),
            "updated_at": dt.now(),
        }

        if is_capability:
            document["call_id"] = "Individual"
            document["capability_id"] = chat_id

        return document

    @staticmethod
    async def create_omni_chat(user_id: str, chat_dir: str | None = None) -> dict:
        """Create a new omni chat session.

        Args:
            user_id: User identifier.
            chat_dir: Optional directory path for chat storage.

        Returns:
            dict: Created chat document.

        Raises:
            HTTPException: If chat creation fails.
        """
        chat_dir = ensure_path(chat_dir or ChatService.get_default_chat_dir())
        chat_id = ChatService.generate_chat_id()

        chat_document = ChatService.build_chat_document(user_id, chat_id, chat_dir)

        repo = await get_chat_repository()
        return await repo.create_chat(chat_document, "omni")

    @staticmethod
    async def create_capability_chat(
        capability_name: str, user_id: str, chat_dir: str | None = None
    ) -> dict:
        """Create a new capability-specific chat session.

        Args:
            capability_name: Name of the capability.
            user_id: User identifier.
            chat_dir: Optional directory path for chat storage.

        Returns:
            dict: Created chat document.

        Raises:
            HTTPException: If capability is invalid or creation fails.
        """
        chat_dir = ensure_path(chat_dir or ChatService.get_default_chat_dir())
        chat_id = ChatService.generate_chat_id()

        capability = CapabilityType.from_string(capability_name)
        collection_name = capability.collection

        chat_document = ChatService.build_chat_document(
            user_id, chat_id, chat_dir, is_capability=True
        )

        repo = await get_chat_repository()
        return await repo.create_chat(chat_document, collection_name)

    @staticmethod
    async def create_chat_mode_session(
        user_id: str, chat_dir: str | None = None
    ) -> dict:
        """Create a new chat mode session.

        Args:
            user_id: User identifier.
            chat_dir: Optional directory path for chat storage.

        Returns:
            dict: Created chat document.

        Raises:
            HTTPException: If chat creation fails.
        """
        chat_dir = ensure_path(chat_dir or ChatService.get_default_chat_dir())
        chat_id = ChatService.generate_chat_id()

        chat_document = ChatService.build_chat_document(user_id, chat_id, chat_dir)

        repo = await get_chat_repository()
        return await repo.create_chat(chat_document, "chats")

    @staticmethod
    async def get_omni_chat_history(user_id: str, chat_id: str, collection: str = "omni") -> dict:
        """Get chat history for a specific user and chat.

        Args:
            user_id: User identifier.
            chat_id: Chat session identifier.
            collection: Collection/capability name (omni, chats, etc.).

        Returns:
            dict: Simplified chat history with chat_id, chat_dir, and raw_messages.

        Raises:
            HTTPException: If chat not found or retrieval fails.
        """
        repo = await get_chat_repository()
        document = await repo.get_chat(user_id, chat_id, collection)

        if not document:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Chat not found for user_id: {user_id} and chat_id: {chat_id}",
            )

        raw_messages = ChatService.transform_raw_messages(document)

        return {
            "chat_id": document.get("chat_id", ""),
            "chat_dir": document.get("chat_dir", ""),
            "raw_messages": raw_messages,
        }

    @staticmethod
    async def get_chat_history_by_task(
        task_id: str, user_id: str, chat_id: str, capability: str
    ) -> dict:
        """Get chat history filtered by task ID.

        Args:
            task_id: Task identifier to filter messages.
            user_id: User identifier.
            chat_id: Chat session identifier.
            capability: Capability name.

        Returns:
            dict: Filtered chat history.

        Raises:
            HTTPException: If chat not found or retrieval fails.
        """
        capability_type = CapabilityType.from_string(capability)
        collection = capability_type.collection if capability_type else "omni"

        repo = await get_chat_repository()
        document = await repo.get_chat_by_task(task_id, user_id, chat_id, collection)

        if not document:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Chat not found for chat_id: {chat_id} and task_id: {task_id}",
            )

        return {
            "success": True,
            "message": "Chat history retrieved",
            "data": document,
        }

    @staticmethod
    async def get_capability_chat_history(
        user_id: str, chat_id: str, call_id: str, capability_name: str
    ) -> dict:
        """Get capability-specific chat history.

        Args:
            user_id: User identifier.
            chat_id: Chat session identifier.
            call_id: Capability call identifier.
            capability_name: Name of the capability.

        Returns:
            dict: Enhanced chat history with capability context.

        Raises:
            HTTPException: If capability invalid, chat not found, or retrieval fails.
        """
        if capability_name not in CapabilityType._value2member_map_:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid capability name: {capability_name}",
            )

        capability = CapabilityType._value2member_map_.get(capability_name)
        collection_name = capability.collection

        repo = await get_chat_repository()
        document = await repo.get_chat(
            user_id, chat_id, collection_name, call_id=call_id
        )

        if not document:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Chat not found for user_id: {user_id} and chat_id: {chat_id}",
            )

        raw_messages = ChatService.transform_raw_messages(document)

        return {
            "call_id": call_id,
            "capability_name": capability_name,
            "chat_id": document.get("chat_id", ""),
            "raw_messages": raw_messages,
        }

    @staticmethod
    async def get_chat_mode_history(user_id: str, chat_id: str) -> dict:
        """Get chat mode history for a specific user and chat.

        Args:
            user_id: User identifier.
            chat_id: Chat session identifier.

        Returns:
            dict: Simplified chat history with chat_id, chat_dir, raw_messages, and feedback.

        Raises:
            HTTPException: If chat not found or retrieval fails.
        """
        repo = await get_chat_repository()
        document = await repo.get_chat(user_id, chat_id, "chats")

        if not document:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Chat not found for user_id: {user_id} and chat_id: {chat_id}",
            )

        raw_messages = ChatService.transform_raw_messages(document)

        return {
            "chat_id": document.get("chat_id", ""),
            "chat_dir": document.get("chat_dir", ""),
            "raw_messages": raw_messages,
            "feedback": document.get("feedback", {}),
        }
