"""Storage and utility functions for chat history, text-to-speech, and path management.

This module provides utility functions for managing chat history persistence,
macOS text-to-speech capabilities, and directory path management with validation.
"""

import asyncio
import os
import subprocess
import sys
from pathlib import Path

from loguru import logger

from src.configs.datetime_utils import dt
from src.configs.routes import RoutesConfig
from src.utilities.api_client import api_client


async def update_chat_history(
    chat_id: str, message: dict, collection_name: str
) -> bool:
    """Update chat history in MongoDB with message data.

    Args:
        chat_id: Unique identifier for the chat session
        message: Message dictionary containing role, name, content, and raw_message
        collection_name: MongoDB collection name for the capability

    Returns:
        bool: True if update was successful

    Raises:
        Exception: If MongoDB operation fails
    """
    try:

        # Extract required fields for different message types
        required_fields = ["role", "name", "raw_message", "usage", "task_id"]
        content_fields = ["role", "name", "content"]

        raw_message_data = {
            field: message[field] for field in required_fields if field in message
        }
        content_message_data = {
            field: message[field] for field in content_fields if field in message
        }

        raw_message_data["timestamp"] = dt.now_iso()  # Add timestamp to raw message
        # Build push operations
        push_operations = {"raw_messages": raw_message_data}

        # Only add to messages if content exists and is not empty
        if content_message_data.get("content"):
            push_operations["messages"] = content_message_data

        # Prepare update document
        update_document = {
            "$push": push_operations,
            "$set": {"updated_at": dt.now()},
        }

        # Execute update operation
        filter_criteria = {"chat_id": chat_id}
        update_result = await api_client.post(
            RoutesConfig.API_UPDATE_OMNI_CHAT,
            params={"capability": collection_name},
            data={"filter_criteria": filter_criteria, "document": update_document},
        )
        update_result = update_result.standard_response()
        if not update_result.get("success"):
            raise Exception(f"Failed: {update_result.get('message', 'Unknown error')}")

        update_result = update_result.get("data")
        # update_result = await mongodb_service.update_one(
        #     collection_name,
        #     filter_criteria,
        #     update_document
        # )

        # Log the actual result, not the task object
        logger.info(f"MongoDB update completed for chat_id: {chat_id}")

        return update_result

    except Exception as e:
        logger.error(f"Failed to update chat history for chat_id {chat_id}: {str(e)}")
        raise


async def a_speak(text, voice="Samantha"):
    """Asynchronously speak text using macOS 'say' command.

    Use the macOS text-to-speech system to speak the provided text with
    the specified voice. Falls back to system default if the specified
    voice is not available.

    Args:
        text: The text to be spoken.
        voice: Voice name to use. Defaults to "Samantha".

    Note:
        This function only works on macOS (Darwin platform). On other
        platforms, it prints a message and returns without action.

    Example:
        >>> await a_speak("Hello, world!", voice="Samantha")
    """
    if sys.platform != "darwin":
        print("This function only works on macOS")
        return

    try:
        # Try with specified voice first
        process = await asyncio.create_subprocess_exec(
            "say",
            "-v",
            voice,
            text,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await process.wait()

        if process.returncode != 0:
            raise Exception("Voice not available")

    except Exception:
        # If specified voice fails, use system default
        print(f"Voice '{voice}' not available, using system default")
        process = await asyncio.create_subprocess_exec("say", text)
        await process.wait()


def speak(text, voice="Samantha"):
    """Speak text using macOS 'say' command (synchronous).

    Synchronous version of text-to-speech using macOS system voice.
    Falls back to system default if the specified voice is not available.

    Args:
        text: The text to be spoken.
        voice: Voice name to use. Defaults to "Samantha".

    Raises:
        subprocess.CalledProcessError: If the 'say' command fails.

    Note:
        This function only works on macOS. On other platforms, it prints
        a message and returns without action.

    Example:
        >>> speak("Hello, world!", voice="Alex")
    """
    if sys.platform != "darwin":
        print("This function only works on macOS")
        return

    try:
        # Try with specified voice first
        subprocess.run(
            ["say", "-v", voice, text],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError:
        # If specified voice fails, use system default
        subprocess.run(["say", text], check=True)


def list_available_voices():
    """List all available voices on the system in a readable format.

    Query the macOS system for all installed text-to-speech voices and
    display them with their descriptions.

    Note:
        This function only works on macOS. On other platforms, it prints
        a message and returns without action.

    Example:
        >>> list_available_voices()
        Available voices:
        Alex              en_US    # Most people recognize me by my voice.
        Samantha          en_US    # Hello, my name is Samantha...
    """
    try:
        if sys.platform != "darwin":
            print("This function only works on macOS")
            return

        result = subprocess.run(
            ["say", "-v", "?"], capture_output=True, text=True, check=True
        )
        print("Available voices:")
        print(result.stdout)

    except Exception as e:
        print(f"Error listing voices: {e}")


def ensure_path(path: str | Path, create_if_missing: bool = True) -> str:
    """Ensure a directory path exists and return the absolute path.

    Args:
        path: The directory path to check/create
        create_if_missing: Whether to create the directory if it doesn't exist (default: True)

    Returns:
        str: The absolute path of the directory

    Raises:
        OSError: If path creation fails
        FileExistsError: If path exists but is a file, not a directory
    """
    # Convert to Path object for easier handling
    path_obj = Path(path)

    # Convert to absolute path
    abs_path = path_obj.resolve()

    if abs_path.exists():
        if abs_path.is_file():
            raise FileExistsError(
                f"Path exists but is a file, not a directory: {abs_path}"
            )
        # Directory already exists
        return str(abs_path)

    if create_if_missing:
        try:
            abs_path.mkdir(parents=True, exist_ok=True)
            print(f"Created directory: {abs_path}")
        except OSError as e:
            raise OSError(f"Failed to create directory {abs_path}: {e}")

    return str(abs_path)


def simple_ensure_path(path: str | Path) -> str:
    """Create directory if it doesn't exist and return absolute path.

    Simplified version of ensure_path that always creates the directory
    and returns its absolute path.

    Args:
        path: Directory path to ensure exists.

    Returns:
        Absolute path string of the directory.

    Example:
        >>> path = simple_ensure_path("data/cache")
        >>> print(path)
        /Users/username/project/data/cache
    """
    abs_path = os.path.abspath(path)
    os.makedirs(abs_path, exist_ok=True)
    return abs_path


def ensure_paths(*paths: str | Path, create_if_missing: bool = True) -> list[str]:
    """Ensure multiple directory paths exist and return their absolute paths.

    Args:
        *paths: Variable number of directory paths to check/create
        create_if_missing: Whether to create directories if they don't exist (default: True)

    Returns:
        list[str]: List of absolute paths
    """
    return [ensure_path(path, create_if_missing) for path in paths]
