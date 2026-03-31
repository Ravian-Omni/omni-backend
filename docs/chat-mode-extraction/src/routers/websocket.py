"""WebSocket endpoint for real-time chat communication.

This module provides WebSocket endpoints for:
- Real-time chat conversations
- Streaming AI responses
- User input handling
"""

import asyncio
import json

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from loguru import logger

from src.chat.manager import Chat
from src.configs.llm_configs_manager import LLMConfigManager
from src.dependencies import get_websocket_manager
from src.managers.connection import WebSocketManager
from src.services.websocket_service import (
    load_chat_history,
    get_default_chat_dir,
    get_user_details,
    extract_user_summary,
    build_user_context,
)

router = APIRouter()


@router.websocket("/chat/{chat_id}")
async def chat_websocket(
    websocket: WebSocket,
    chat_id: str,
    user_id: str = "default_user",
    ws_manager: WebSocketManager = Depends(get_websocket_manager),
):
    """WebSocket endpoint for Chat Mode AI conversations.

    Handles real-time communication for chat conversations with support for
    AI capabilities, context preservation, and streaming responses.

    Uses early connection pattern: WebSocket is connected first, then heavy
    initialization happens in background with status updates to the client.

    Args:
        websocket: WebSocket connection instance.
        chat_id: Unique identifier for the chat session.
        user_id: User identifier. Defaults to "default_user".
        ws_manager: WebSocket manager dependency for connection handling.

    Raises:
        WebSocketDisconnect: When connection is closed by client or server.
    """
    # STEP 1: Connect WebSocket FIRST (before any heavy initialization)
    connected = await ws_manager.connect(websocket, chat_id)
    if not connected:
        await websocket.close(code=4002, reason="Failed to establish connection")
        return

    logger.info(f"WebSocket connection established for chat {chat_id}")

    try:
        # Send initialization status to client
        await websocket.send_json({
            "type": "init_status",
            "status": "connecting",
            "message": "Loading chat history...",
        })

        # STEP 2: Load chat history
        history = await load_chat_history(chat_id, user_id)
        if not history:
            logger.warning(f"Chat not found: {user_id} & {chat_id}")
            await websocket.send_json({
                "type": "error",
                "error": "Chat session not found",
            })
            await websocket.close(code=4003, reason="Chat not found")
            return

        chat_dir = history.get("chat_dir", get_default_chat_dir())
        messages = history.get("messages", [])

        await websocket.send_json({
            "type": "init_status",
            "status": "initializing",
            "message": "Initializing chat agent...",
        })

        # STEP 3: Initialize Chat instance
        chat = Chat(chat_id=chat_id, user_id=user_id, chat_dir=chat_dir)

        await websocket.send_json({
            "type": "init_status",
            "status": "configuring",
            "message": "Loading user context...",
        })

        # STEP 4: Load user context
        user_details = await get_user_details()
        user_context = extract_user_summary(user_details)
        context = build_user_context(user_context)

        # Update system message with user context
        chat.chat_agent.update_system_message(
            chat.chat_agent.system_message + context
        )

        # Resume from existing messages if available
        if messages:
            chat.manager.resume(messages=messages)

        # Set up input functions
        input_func = ws_manager._create_input_func(chat_id)
        chat.agent_executor.set_input_function(input_func)
        chat.set_input_function(input_func)

        # Send ready status
        await websocket.send_json({
            "type": "init_status",
            "status": "ready",
            "message": "Chat ready",
        })

        logger.info(f"Chat initialization complete for {chat_id}")

        # STEP 5: Handle messages
        await _handle_websocket_messages(
            websocket, chat_id, ws_manager, chat
        )

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for chat {chat_id}")
        LLMConfigManager.clear_cache()
    except Exception as e:
        logger.error(f"WebSocket error: {str(e)}")
        LLMConfigManager.clear_cache()
        try:
            await websocket.send_json({
                "type": "error",
                "error": f"Initialization failed: {str(e)}",
            })
        except Exception:
            pass
    finally:
        LLMConfigManager.clear_cache()
        await ws_manager.disconnect(chat_id)


async def _handle_websocket_messages(
    websocket: WebSocket,
    chat_id: str,
    ws_manager: WebSocketManager,
    chat: Chat,
):
    """Handle incoming WebSocket messages for chat.

    Args:
        websocket: WebSocket connection instance.
        chat_id: Chat session identifier.
        ws_manager: WebSocket manager instance.
        chat: Chat instance.
    """
    while True:
        try:
            raw_message = await websocket.receive_text()
            message = json.loads(raw_message)
            message_type = message.get("type")

            if message_type == "start":
                await _handle_start_message(
                    websocket, chat_id, ws_manager, chat, message
                )

            elif message_type == "stop":
                logger.info(f"Received stop request for chat {chat_id}")
                LLMConfigManager.clear_cache()
                reason = message.get("reason") or "User requested stop"
                await ws_manager.stop_session(chat_id, reason=reason)

            elif message_type == "ping":
                await websocket.send_json({"type": "pong"})

            elif message_type == "input_response":
                response = message.get("response")
                if response is not None:
                    await ws_manager.handle_input_response(chat_id, response)
                else:
                    logger.warning(f"Invalid input response for chat {chat_id}")

        except json.JSONDecodeError:
            logger.warning(f"Invalid JSON received: {raw_message}")
            await websocket.send_json({
                "type": "error",
                "error": "Invalid message format"
            })


async def _handle_start_message(
    websocket: WebSocket,
    chat_id: str,
    ws_manager: WebSocketManager,
    chat: Chat,
    message: dict,
):
    """Handle start message for chat.

    Args:
        websocket: WebSocket connection instance.
        chat_id: Chat session identifier.
        ws_manager: WebSocket manager instance.
        chat: Chat instance.
        message: The start message data.
    """
    logger.info(f"Received start request for chat {chat_id}")

    if message.get("task"):
        asyncio.create_task(
            ws_manager.chat_initiate(
                session_id=chat_id,
                initial_message=message,
                chat=chat
            )
        )
    else:
        logger.warning(f"Invalid start message for chat {chat_id}")
        await websocket.send_json({
            "type": "error",
            "error": "Invalid start message format - 'task' field required"
        })
