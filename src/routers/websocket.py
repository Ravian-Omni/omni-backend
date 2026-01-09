"""WebSocket endpoints for real-time AI chat communication.

This module provides WebSocket endpoints for:
- Omni multi-capability AI conversations
- Chat mode conversations
- Individual capability-specific chats (browser, email, file finder, etc.)
- Real-time streaming of AI responses
- Chat history management and context preservation
"""

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from loguru import logger

from src.chat.manager import Chat
from src.configs.llm_configs_manager import LLMConfigManager
from src.configs.settings import CapabilityType
from src.dependencies import get_websocket_manager
from src.managers.connection import WebSocketManager
from src.omni.manager import Omni
from src.services.websocket_service import (
    CAPABILITY_CLASS_MAP,
    build_user_context,
    create_capability_context,
    create_error_response,
    create_pong_response,
    extract_user_summary,
    get_default_chat_dir,
    get_user_details,
    load_capability_chat_history,
    load_chat_mode_history,
    load_omni_chat_history,
)

router = APIRouter()


# =============================================================================
# OMNI MODE WEBSOCKET
# =============================================================================


@router.websocket("/omni/{chat_id}")
async def omni_websocket(
    websocket: WebSocket,
    chat_id: str,
    user_id: str = "f1d36dfa-4091-703f-c5bf-601c56ea20f3",
    ws_manager: WebSocketManager = Depends(get_websocket_manager),
):
    """WebSocket endpoint for Omni multi-capability AI chat.

    Handles real-time communication for Omni conversations with support for
    multiple AI capabilities, context preservation, and streaming responses.

    Uses early connection pattern: WebSocket is connected first, then heavy
    initialization happens in background with status updates to the client.

    Args:
        websocket: WebSocket connection instance.
        chat_id: Unique identifier for the chat session.
        user_id: User identifier. Defaults to test user ID.
        ws_manager: WebSocket manager dependency for connection handling.

    Raises:
        WebSocketDisconnect: When connection is closed by client or server.
    """
    # STEP 1: Connect WebSocket FIRST (before any heavy initialization)
    connected = await ws_manager.connect(websocket, chat_id)
    if not connected:
        await websocket.close(code=4002, reason="Failed to establish connection")
        return

    logger.info(f"WebSocket connection established for run {chat_id}")

    try:
        # Send initialization status to client
        await websocket.send_json(
            {
                "type": "init_status",
                "status": "connecting",
                "message": "Loading chat history...",
            }
        )

        # STEP 2: Load chat history (lightweight API call)
        history = await load_omni_chat_history(chat_id, user_id)
        if not history:
            logger.warning(f"Run not found: {user_id} & {chat_id}")
            await websocket.send_json(
                {
                    "type": "error",
                    "error": "Chat session not found",
                }
            )
            await websocket.close(code=4003, reason="Run not found")
            return

        chat_dir = history.get("chat_dir", get_default_chat_dir())
        messages = history.get("messages", [])

        await websocket.send_json(
            {
                "type": "init_status",
                "status": "initializing",
                "message": "Initializing Omni agent and loading tools...",
            }
        )

        # STEP 3: Initialize Omni instance (heavy - includes tool registration)
        omni = Omni(chat_id=chat_id, user_id=user_id, chat_dir=chat_dir)

        await websocket.send_json(
            {
                "type": "init_status",
                "status": "configuring",
                "message": "Loading user context...",
            }
        )

        # STEP 4: Load user context
        user_details = await get_user_details()
        user_context = extract_user_summary(user_details)
        context = build_user_context(user_context)

        # Update system message with user context
        omni.judge_question.update_system_message(
            omni.judge_question.system_message + context
        )

        # Resume from existing messages if available
        if messages:
            omni.manager.resume(messages=messages)
            omni.memory.load_main_messages(messages)

        # Set up input functions
        input_func = ws_manager._create_input_func(chat_id)
        omni.user_input.set_input_function(input_func)
        omni.get_user_acceptance.set_input_function(input_func)
        omni.set_input_function(input_func)

        # Send ready status
        await websocket.send_json(
            {
                "type": "init_status",
                "status": "ready",
                "message": "Omni ready",
            }
        )

        logger.info(f"Omni initialization complete for {chat_id}")

        # STEP 5: Handle messages
        await _handle_websocket_messages(
            websocket, chat_id, ws_manager, omni, is_chat_mode=False
        )

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for run {chat_id}")
        LLMConfigManager.clear_cache()
    except Exception as e:
        logger.error(f"WebSocket error: {str(e)}")
        LLMConfigManager.clear_cache()
        # Try to send error to client before closing
        try:
            await websocket.send_json(
                {
                    "type": "error",
                    "error": f"Initialization failed: {str(e)}",
                }
            )
        except Exception:
            pass
    finally:
        LLMConfigManager.clear_cache()
        await ws_manager.disconnect(chat_id)


# =============================================================================
# CHAT MODE WEBSOCKET
# =============================================================================


@router.websocket("/chat/{chat_id}")
async def chat_websocket(
    websocket: WebSocket,
    chat_id: str,
    user_id: str = "f1d36dfa-4091-703f-c5bf-601c56ea20f3",
    ws_manager: WebSocketManager = Depends(get_websocket_manager),
):
    """WebSocket endpoint for Chat mode AI conversations.

    Handles real-time communication for Chat mode conversations with support for
    multiple AI capabilities, context preservation, and streaming responses.

    Uses early connection pattern: WebSocket is connected first, then heavy
    initialization happens in background with status updates to the client.

    Args:
        websocket: WebSocket connection instance.
        chat_id: Unique identifier for the chat session.
        user_id: User identifier. Defaults to test user ID.
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
        await websocket.send_json(
            {
                "type": "init_status",
                "status": "connecting",
                "message": "Loading chat history...",
            }
        )

        # STEP 2: Load chat history (lightweight API call)
        history = await load_chat_mode_history(chat_id, user_id)
        if not history:
            logger.warning(f"Run not found: {user_id} & {chat_id}")
            await websocket.send_json(
                {
                    "type": "error",
                    "error": "Chat session not found",
                }
            )
            await websocket.close(code=4003, reason="Run not found")
            return

        chat_dir = history.get("chat_dir", get_default_chat_dir())
        messages = history.get("messages", [])

        await websocket.send_json(
            {
                "type": "init_status",
                "status": "initializing",
                "message": "Initializing chat agent and loading tools...",
            }
        )

        # STEP 3: Initialize Chat instance (heavy - includes tool registration)
        # Note: Cannot use run_in_executor because Chat uses async_to_sync internally
        # which requires access to the same event loop
        chat = Chat(chat_id=chat_id, user_id=user_id, chat_dir=chat_dir)

        await websocket.send_json(
            {
                "type": "init_status",
                "status": "configuring",
                "message": "Loading user context...",
            }
        )

        # STEP 4: Load user context
        user_details = await get_user_details()
        user_context = extract_user_summary(user_details)
        context = build_user_context(user_context)

        # Update system message with user context
        chat.chat_agent.update_system_message(chat.chat_agent.system_message + context)

        # Resume from existing messages if available
        if messages:
            chat.manager.resume(messages=messages)

        # Set up input functions
        input_func = ws_manager._create_input_func(chat_id)
        chat.agent_executor.set_input_function(input_func)
        chat.set_input_function(input_func)

        # Send ready status
        await websocket.send_json(
            {
                "type": "init_status",
                "status": "ready",
                "message": "Chat ready",
            }
        )

        logger.info(f"Chat initialization complete for {chat_id}")

        # STEP 5: Handle messages
        await _handle_websocket_messages(
            websocket, chat_id, ws_manager, chat, is_chat_mode=True
        )

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for run {chat_id}")
        LLMConfigManager.clear_cache()
    except Exception as e:
        logger.error(f"WebSocket error: {str(e)}")
        LLMConfigManager.clear_cache()
        # Try to send error to client before closing
        try:
            await websocket.send_json(
                {
                    "type": "error",
                    "error": f"Initialization failed: {str(e)}",
                }
            )
        except Exception:
            pass
    finally:
        LLMConfigManager.clear_cache()
        await ws_manager.disconnect(chat_id)


# =============================================================================
# CAPABILITY-SPECIFIC WEBSOCKET
# =============================================================================


@router.websocket("/capability/{chat_id}")
async def capability_websocket(
    websocket: WebSocket,
    chat_id: str,
    user_id: str = "default_user",
    capability_name: str = "email_sender",
    ws_manager: WebSocketManager = Depends(get_websocket_manager),
):
    """WebSocket endpoint for single capability-specific chat.

    Handles real-time communication for individual capabilities like email,
    browser, file finder, image generator, and Python developer.

    Args:
        websocket: WebSocket connection instance.
        chat_id: Unique identifier for the chat session.
        user_id: User identifier. Defaults to "default_user".
        capability_name: Name of the capability to use. Defaults to "email_sender".
        ws_manager: WebSocket manager dependency for connection handling.

    Raises:
        HTTPException: If capability_name is invalid.
        WebSocketDisconnect: When connection is closed by client or server.
    """
    # Validate capability
    try:
        capability = CapabilityType.from_string(capability_name)
        collection_name = capability.collection
        class_instance = CAPABILITY_CLASS_MAP.get(capability_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if class_instance is None:
        raise HTTPException(
            status_code=400, detail=f"Unsupported capability: {capability_name}"
        )

    # Load chat history
    history = await load_capability_chat_history(chat_id, user_id, collection_name)
    if not history:
        logger.warning(f"Run not found: {user_id} & {chat_id}")
        await websocket.close(code=4003, reason="Run not found")
        return

    chat_dir = history.get("chat_dir", get_default_chat_dir())

    # Create capability context and instance
    chat_context = create_capability_context(
        user_id=user_id,
        chat_id=chat_id,
        chat_dir=chat_dir,
        capability_name=capability_name,
        collection_name=collection_name,
    )

    capability_instance = class_instance(chat_context)
    messages = history.get("messages", [])

    # Resume from existing messages if available
    if messages:
        capability_instance.manager.resume(messages=messages)

    # Set up input function
    ws_manager._create_input_func(chat_id)

    # Connect websocket
    connected = await ws_manager.connect(websocket, chat_id)
    if not connected:
        await websocket.close(code=4002, reason="Failed to establish connection")
        return

    try:
        logger.info(f"WebSocket connection established for run {chat_id}")
        await _handle_capability_websocket_messages(
            websocket, chat_id, ws_manager, capability_instance
        )

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for run {chat_id}")
    except Exception as e:
        logger.error(f"WebSocket error: {str(e)}")
    finally:
        await ws_manager.disconnect(chat_id)


# =============================================================================
# WEBSOCKET MESSAGE HANDLERS
# =============================================================================


async def _handle_websocket_messages(
    websocket: WebSocket,
    chat_id: str,
    ws_manager: WebSocketManager,
    instance,
    is_chat_mode: bool = False,
):
    """Handle incoming WebSocket messages for Omni and Chat modes.

    Args:
        websocket: WebSocket connection instance.
        chat_id: Chat session identifier.
        ws_manager: WebSocket manager instance.
        instance: Omni or Chat instance.
        is_chat_mode: Whether this is chat mode (True) or omni mode (False).
    """
    while True:
        try:
            raw_message = await websocket.receive_text()
            message = json.loads(raw_message)
            message_type = message.get("type")

            if message_type == "start":
                await _handle_start_message(
                    websocket, chat_id, ws_manager, instance, message, is_chat_mode
                )

            elif message_type == "stop":
                logger.info(f"Received stop request for run {chat_id}")
                LLMConfigManager.clear_cache()
                reason = message.get("reason") or "User requested stop/cancellation"
                await ws_manager.stop_session(chat_id, reason=reason)

            elif message_type == "ping":
                await websocket.send_json(create_pong_response())

            elif message_type == "executor_input":
                logger.info(f"Received input request for executor {chat_id}")
                process_id = message.get("process_id")
                input_text = message.get("response")
                await ws_manager.terminal_input(
                    session_id=chat_id, process_id=process_id, input_text=input_text
                )

            elif message_type == "executor_stop":
                logger.info(f"Received stop request for executor {chat_id}")
                process_id = message.get("process_id")
                await ws_manager.terminal_kill(
                    session_id=chat_id, process_id=process_id
                )

            elif message_type == "input_response":
                response = message.get("response")
                if response is not None:
                    await ws_manager.handle_input_response(chat_id, response)
                else:
                    logger.warning(f"Invalid input response format for run {chat_id}")

        except json.JSONDecodeError:
            logger.warning(f"Invalid JSON received: {raw_message}")
            await websocket.send_json(create_error_response("Invalid message format"))


async def _handle_start_message(
    websocket: WebSocket,
    chat_id: str,
    ws_manager: WebSocketManager,
    instance,
    message: dict,
    is_chat_mode: bool,
):
    """Handle start message for Omni and Chat modes.

    Args:
        websocket: WebSocket connection instance.
        chat_id: Chat session identifier.
        ws_manager: WebSocket manager instance.
        instance: Omni or Chat instance.
        message: The start message data.
        is_chat_mode: Whether this is chat mode (True) or omni mode (False).
    """
    logger.info(f"Received start request for run {chat_id}")

    if message.get("task"):
        if is_chat_mode:
            asyncio.create_task(
                ws_manager.chat_mode_initiate(
                    session_id=chat_id, initial_message=message, chat=instance
                )
            )
        else:
            asyncio.create_task(
                ws_manager.start_chat_stream(
                    session_id=chat_id, initial_message=message, omni=instance
                )
            )
    else:
        logger.warning(f"Invalid start message format for run {chat_id}")
        await websocket.send_json(create_error_response("Invalid start message format"))


async def _handle_capability_websocket_messages(
    websocket: WebSocket,
    chat_id: str,
    ws_manager: WebSocketManager,
    capability_instance,
):
    """Handle incoming WebSocket messages for capability-specific chats.

    Args:
        websocket: WebSocket connection instance.
        chat_id: Chat session identifier.
        ws_manager: WebSocket manager instance.
        capability_instance: Capability class instance.
    """
    while True:
        try:
            raw_message = await websocket.receive_text()
            message = json.loads(raw_message)
            message_type = message.get("type")

            if message_type == "start":
                logger.info(f"Received start request for run {chat_id}")
                if message.get("task"):
                    asyncio.create_task(
                        ws_manager.start_chat_stream(
                            session_id=chat_id,
                            initial_message=message,
                            omni=capability_instance,
                        )
                    )
                else:
                    logger.warning(f"Invalid start message format for run {chat_id}")
                    await websocket.send_json(
                        create_error_response("Invalid start message format")
                    )

            elif message_type == "stop":
                logger.info(f"Received stop request for run {chat_id}")
                reason = message.get("reason") or "User requested stop/cancellation"
                await ws_manager.stop_session(chat_id, reason=reason)

            elif message_type == "ping":
                await websocket.send_json(create_pong_response())

            elif message_type == "input_response":
                response = message.get("response")
                if response is not None:
                    await ws_manager.handle_input_response(chat_id, response)
                else:
                    logger.warning(f"Invalid input response format for run {chat_id}")

        except json.JSONDecodeError:
            logger.warning(f"Invalid JSON received: {raw_message}")
            await websocket.send_json(create_error_response("Invalid message format"))
