"""Software Developer WebSocket and REST API endpoints.

This module provides:
- WebSocket endpoint for real-time AI coding assistance
- REST endpoints for chat session management
- Real-time streaming of AI responses with tool execution
"""

import asyncio
import json
import os
import uuid

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from loguru import logger

from src.capabilities.software_developer.manager import SoftwareDeveloper
from src.configs.datetime_utils import dt
from src.configs.llm_configs_manager import LLMConfigManager
from src.configs.settings import settings
from src.dependencies import get_websocket_manager
from src.managers.cancellation_token import CancellationToken
from src.managers.connection import WebSocketManager
from src.omni.memory import OmniMemory
from src.utilities.async_errors import AsyncErrorCode, create_error
from src.utilities.custom_manager import ChatContext
from src.utilities.storage import ensure_path

router = APIRouter()


# =============================================================================
# HELPER UTILITIES
# =============================================================================


def _create_tracked_task(
    coro,
    websocket: WebSocket,
    chat_id: str,
    operation: str,
) -> asyncio.Task:
    """Create an async task with automatic error logging and client notification."""
    task = asyncio.create_task(coro)

    def on_task_complete(t: asyncio.Task) -> None:
        try:
            if t.cancelled():
                logger.info(f"Task '{operation}' cancelled for session {chat_id}")
                return

            exc = t.exception()
            if exc:
                error = create_error(
                    AsyncErrorCode.TASK_EXECUTION_FAILED,
                    operation,
                    user_message="An error occurred while processing your request. Please try again.",
                    technical_message=str(exc),
                    context={"session_id": chat_id},
                )
                logger.error(f"[{error.code.value}] Task '{operation}' failed: {exc}")
                asyncio.create_task(_notify_error(websocket, error))
        except (asyncio.CancelledError, asyncio.InvalidStateError):
            pass

    task.add_done_callback(on_task_complete)
    return task


async def _notify_error(websocket: WebSocket, error) -> None:
    """Send error notification to client."""
    try:
        await websocket.send_json(
            {
                "type": "error",
                "error_code": error.code.value,
                "message": error.user_message,
                "support_reference": f"Contact support with code: {error.code.value}",
                "timestamp": dt.now_iso(),
            }
        )
    except Exception:
        pass


async def _send_error(websocket: WebSocket, chat_id: str, message: str) -> None:
    """Send a simple error response to client."""
    error = create_error(
        AsyncErrorCode.TASK_CREATION_FAILED,
        "message_handler",
        user_message=message,
        context={"session_id": chat_id},
    )
    logger.warning(f"[{error.code.value}] {message} for session {chat_id}")
    await websocket.send_json(
        {
            "type": "error",
            "error_code": error.code.value,
            "message": error.user_message,
            "support_reference": f"Contact support with code: {error.code.value}",
        }
    )


def get_default_chat_dir() -> str:
    """Get the default chat directory path."""
    return os.path.join(settings.ROOT_DIR, "ravian")


async def load_software_dev_history(chat_id: str, user_id: str) -> dict | None:
    """Load software developer chat history from API."""
    # query = {
    #     "user_id": user_id,
    #     "chat_id": chat_id,
    #     "call_id": "Individual",
    #     "capability_id": chat_id,
    # }

    # response = await api_client.post(
    #     RoutesConfig.API_OMNI_CHAT_HISTORY,
    #     params={"capability": settings.SOFTWARE_DEV_COLLECTION},
    #     data=query,
    # )
    # result = response.standard_response()

    # if not result.get("success"):
    #     logger.error(result)
    #     return None

    # return result.get("data")
    return []


# =============================================================================
# MESSAGE HANDLER
# =============================================================================


async def _handle_software_dev_messages(
    websocket: WebSocket,
    chat_id: str,
    ws_manager: WebSocketManager,
    software_dev: SoftwareDeveloper,
):
    """Handle WebSocket messages for software developer sessions.

    Args:
        websocket: WebSocket connection.
        chat_id: Session identifier.
        ws_manager: WebSocket manager.
        software_dev: SoftwareDeveloper instance.
    """
    while True:
        try:
            raw_message = await websocket.receive_text()
            message = json.loads(raw_message)
            msg_type = message.get("type")

            # === START: Begin chat stream ===
            if msg_type == "start":
                logger.info(f"Start request for software_developer session {chat_id}")

                if not message.get("task"):
                    await _send_error(
                        websocket,
                        chat_id,
                        "Invalid request format. Please provide a task.",
                    )
                    continue

                # Set task ID and cancellation token
                software_dev.set_task_id(str(uuid.uuid4()))
                cancellation_token = CancellationToken()
                software_dev._set_cancellation_token(cancellation_token)

                # Create and track the task
                coro = ws_manager.start_chat_stream(
                    session_id=chat_id,
                    initial_message=message,
                    omni=software_dev,
                )
                _create_tracked_task(
                    coro, websocket, chat_id, "software_developer_stream"
                )

            # === STOP: Cancel current session ===
            elif msg_type == "stop":
                logger.info(f"Stop request for session {chat_id}")
                LLMConfigManager.clear_cache()
                reason = message.get("reason", "User requested stop/cancellation")
                await ws_manager.stop_session(chat_id, reason=reason)

            # === PING: Keep-alive ===
            elif msg_type == "ping":
                await websocket.send_json({"type": "pong", "timestamp": dt.now_iso()})

            # === INPUT_RESPONSE: User input for prompts ===
            elif msg_type == "input_response":
                response = message.get("response")
                if response is not None:
                    await ws_manager.handle_input_response(chat_id, response)
                else:
                    logger.warning(f"Invalid input_response for session {chat_id}")

        except json.JSONDecodeError:
            logger.warning(f"Invalid JSON received for session {chat_id}")
            await websocket.send_json(
                {
                    "type": "error",
                    "error": "Invalid message format",
                    "timestamp": dt.now_iso(),
                }
            )


# =============================================================================
# WEBSOCKET ENDPOINT
# =============================================================================


@router.websocket("/ws/{chat_id}")
async def software_developer_websocket(
    websocket: WebSocket,
    chat_id: str,
    user_id: str = "default_user",
    ws_manager: WebSocketManager = Depends(get_websocket_manager),
):
    """WebSocket endpoint for Software Developer AI coding assistant.

    Provides real-time streaming of AI responses with tool execution support
    for file operations, git integration, and code analysis.

    Args:
        websocket: WebSocket connection.
        chat_id: Unique chat session identifier.
        user_id: User identifier.
        ws_manager: WebSocket manager dependency.
    """
    connected = await ws_manager.connect(websocket, chat_id)
    if not connected:
        await websocket.close(code=4002, reason="Failed to establish connection")
        return

    logger.info(f"WebSocket connected for software_developer session {chat_id}")

    try:
        # Send initialization status
        await websocket.send_json(
            {
                "type": "init_status",
                "status": "connecting",
                "message": "Loading chat history...",
            }
        )

        # Load chat history
        # history = await load_software_dev_history(chat_id, user_id)
        # if not history:
        #     logger.warning(f"Software developer session not found: {chat_id}")
        #     await websocket.send_json(
        #         {"type": "error", "error": "Chat session not found"}
        #     )
        #     await websocket.close(code=4003, reason="Run not found")
        #     return
        history = {}

        chat_dir = history.get("chat_dir", get_default_chat_dir())
        messages = history.get("messages", [])

        await websocket.send_json(
            {
                "type": "init_status",
                "status": "initializing",
                "message": "Initializing Software Developer agent...",
            }
        )

        # Create chat context
        context = ChatContext(
            user_id=user_id,
            chat_id=chat_id,
            chat_dir=chat_dir,
            call_id="Individual",
            capability_id=chat_id,
            capability_name="software_developer",
            collection_name=settings.SOFTWARE_DEV_COLLECTION,
            omni_memory=OmniMemory(),
            manager_kwargs={"websocket_manager": ws_manager},
        )

        # Initialize software developer
        software_dev = SoftwareDeveloper(context)

        await websocket.send_json(
            {
                "type": "init_status",
                "status": "configuring",
                "message": "Loading tools and configuration...",
            }
        )

        # Resume history if exists
        if messages:
            software_dev.manager.resume(messages=messages)

        # Set up input function
        input_func = ws_manager._create_input_func(chat_id)
        software_dev.set_input_function(input_func)

        await websocket.send_json(
            {
                "type": "init_status",
                "status": "ready",
                "message": "Software Developer ready",
            }
        )

        logger.info(f"Software Developer ready for session {chat_id}")
        await _handle_software_dev_messages(
            websocket, chat_id, ws_manager, software_dev
        )

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for software_developer session {chat_id}")
    except Exception as e:
        logger.error(f"Software Developer WebSocket error: {e}")
        try:
            await websocket.send_json(
                {"type": "error", "error": f"Initialization failed: {str(e)}"}
            )
        except Exception:
            pass
    finally:
        LLMConfigManager.clear_cache()
        await ws_manager.disconnect(chat_id)


# =============================================================================
# REST API ENDPOINTS
# =============================================================================


@router.post("/new_chat")
async def create_software_dev_chat(
    request: Request,
    user_id: str = "default_user",
    chat_dir: str = None,
):
    """Create a new Software Developer chat session.

    Args:
        request: The FastAPI request object.
        user_id: User identifier. Defaults to "default_user".
        chat_dir: Directory path for storing chat data.

    Returns:
        dict: Created chat document containing chat_id, user_id, and timestamps.

    Raises:
        HTTPException: If chat creation fails.
    """
    try:
        chat_dir = ensure_path(chat_dir or get_default_chat_dir())
        chat_id = str(uuid.uuid4())

        chat_document = {
            "user_id": user_id,
            "chat_id": chat_id,
            "chat_dir": chat_dir,
            "call_id": "Individual",
            "capability_id": chat_id,
            "messages": [],
            "raw_messages": [],
            "created_at": dt.now(),
            "updated_at": dt.now(),
        }

        # response = await api_client.post(
        #     RoutesConfig.API_CREATE_OMNI_CHAT,
        #     params={"capability": settings.SOFTWARE_DEV_COLLECTION},
        #     data=chat_document,
        # )
        # result = response.standard_response()
        result = {"success": True, "data": chat_document}  # Placeholder

        if not result.get("success"):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to create chat: {result.get('message', 'Unknown error')}",
            )

        return result.get("data")

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Chat creation failed due to server error: {e}",
        )


@router.get("/chat-history/{user_id}/{chat_id}")
async def get_software_dev_chat_history(
    user_id: str,
    chat_id: str,
):
    """Get Software Developer chat history.

    Args:
        user_id: User identifier.
        chat_id: Chat session identifier.

    Returns:
        dict: Chat history with chat_id, chat_dir, and raw_messages.

    Raises:
        HTTPException: If chat not found or retrieval fails.
    """
    try:
        history = await load_software_dev_history(chat_id, user_id)

        if not history:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Chat not found for user_id: {user_id} and chat_id: {chat_id}",
            )

        return {
            "chat_id": history.get("chat_id", ""),
            "chat_dir": history.get("chat_dir", ""),
            "raw_messages": history.get("raw_messages", []),
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch chat: {str(e)}",
        )
