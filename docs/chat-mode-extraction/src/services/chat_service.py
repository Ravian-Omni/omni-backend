"""Chat business logic service.

This module provides the ChatService class for chat-related operations:
- Chat session creation
- Chat history retrieval
- Document serialization
"""

import os
import uuid
from datetime import datetime
from typing import Any

from fastapi import HTTPException, status

from src.configs.datetime_utils import dt
from src.configs.routes import RoutesConfig
from src.configs.settings import settings
from src.utilities.api_client import api_client
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
        return os.path.join(settings.ROOT_DIR, "chats")

    @staticmethod
    def serialize_document(doc: dict) -> dict | None:
        """Convert MongoDB document to JSON serializable format.

        Args:
            doc: MongoDB document dictionary to serialize.

        Returns:
            dict | None: JSON-serializable version of the document.
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
                raw_messages.append({
                    "role": message.get("role", ""),
                    "name": message.get("name", ""),
                    "raw_message": message.get("raw_message", ""),
                    "task_id": message.get("task_id", ""),
                    "timestamp": message.get("timestamp", ""),
                })
        return raw_messages

    @staticmethod
    def build_chat_document(user_id: str, chat_id: str, chat_dir: str) -> dict:
        """Build a chat document for database insertion.

        Args:
            user_id: User identifier.
            chat_id: Chat session identifier.
            chat_dir: Directory path for chat storage.

        Returns:
            dict: Chat document ready for insertion.
        """
        return {
            "user_id": user_id,
            "chat_id": chat_id,
            "chat_dir": chat_dir,
            "messages": [],
            "raw_messages": [],
            "created_at": dt.now(),
            "updated_at": dt.now(),
        }

    @staticmethod
    async def create_chat_session(user_id: str, chat_dir: str | None = None) -> dict:
        """Create a new chat session.

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

        response = await api_client.post(
            RoutesConfig.API_CREATE_CHAT,
            params={"capability": settings.CHAT_COLLECTION},
            data=chat_document,
        )
        result = response.standard_response()

        if not result.get("success"):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to create chat: {result.get('message', 'Unknown error')}",
            )

        return result.get("data")

    @staticmethod
    async def get_chat_history(user_id: str, chat_id: str) -> dict:
        """Get chat history for a specific user and chat.

        Args:
            user_id: User identifier.
            chat_id: Chat session identifier.

        Returns:
            dict: Simplified chat history.

        Raises:
            HTTPException: If chat not found or retrieval fails.
        """
        query = {"user_id": user_id, "chat_id": chat_id}

        response = await api_client.post(
            RoutesConfig.API_CHAT_HISTORY,
            params={"capability": settings.CHAT_COLLECTION},
            data=query,
        )
        result = response.standard_response()

        if not result.get("success"):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Chat not found for user_id: {user_id} and chat_id: {chat_id}",
            )

        document = result.get("data")
        serialized_doc = ChatService.serialize_document(document)
        raw_messages = ChatService.transform_raw_messages(serialized_doc)

        return {
            "chat_id": serialized_doc.get("chat_id", ""),
            "chat_dir": serialized_doc.get("chat_dir", ""),
            "raw_messages": raw_messages,
            "feedback": serialized_doc.get("feedback", {}),
        }

    @staticmethod
    async def delete_chat_session(user_id: str, chat_id: str) -> dict:
        """Delete a chat session.

        Args:
            user_id: User identifier.
            chat_id: Chat session identifier.

        Returns:
            dict: Success message.

        Raises:
            HTTPException: If chat not found or deletion fails.
        """
        query = {"user_id": user_id, "chat_id": chat_id}

        response = await api_client.delete(
            RoutesConfig.API_DELETE_CHAT,
            params={"capability": settings.CHAT_COLLECTION},
            data=query,
        )
        result = response.standard_response()

        if not result.get("success"):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Chat not found: {chat_id}",
            )

        return {"message": f"Chat {chat_id} deleted successfully"}
