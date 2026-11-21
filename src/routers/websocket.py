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
from src.configs.datetime_utils import dt
from src.configs.llm_configs_manager import LLMConfigManager
from src.configs.settings import CapabilityType, settings
from src.database import update_chat_history
from src.dependencies import get_websocket_manager
from src.managers.connection import WebSocketManager
from src.omni.manager import Omni
from src.omni.memory import COMPLETION, compact
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
from src.utilities.async_errors import AsyncErrorCode, create_error

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
    """Create an async task with automatic error logging and client notification.

    Args:
        coro: Coroutine to execute.
        websocket: WebSocket for error notifications.
        chat_id: Session identifier.
        operation: Operation name for error context.

    Returns:
        Created asyncio.Task with error callback attached.
    """
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

                # Send error to client
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
        pass  # Connection may be closed


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


# =============================================================================
# UNIFIED MESSAGE HANDLER
# =============================================================================


async def _ledger(chat_id: str) -> str:
    """The chat's saved files, newest first, for the agents: id, kind, title and rows, read from the database."""
    from src.database import list_artifacts

    files = await list_artifacts(chat_id)
    return ("Files saved in this chat (id, kind, title, rows), newest first; read one with read_artifact:\n"
            + "\n".join(f"- {a['id']} ({a['kind']}) {a['title']}, {a['row_count']} rows" for a in files)) if files else ""


async def _resume_running(websocket: WebSocket, chat_id: str, ws_manager: WebSocketManager) -> None:
    """A run that outlived a reload: tell the page it is working, and show what it waits on."""
    if ws_manager.is_running(chat_id):
        await websocket.send_json({"type": "run_started"})
        await ws_manager.resend_pending(chat_id, websocket)


async def _handle_messages(
    websocket: WebSocket,
    chat_id: str,
    ws_manager: WebSocketManager,
    instance,
    mode: str = "omni",
):
    """Unified WebSocket message handler for all chat modes.

    Handles: start, stop, ping, input_response, executor_input, executor_stop

    Args:
        websocket: WebSocket connection.
        chat_id: Session identifier.
        ws_manager: WebSocket manager.
        instance: Chat/Omni/Capability instance.
        mode: One of "omni", "chat", or "capability".
    """
    while True:
        try:
            raw_message = await websocket.receive_text()
            message = json.loads(raw_message)
            msg_type = message.get("type")

            # === USER_NOTE: a message sent while agents are working ===
            # With nothing running it is simply the next task.
            if msg_type == "user_note" and not ws_manager.is_running(chat_id):
                message, msg_type = {"type": "start", "task": message.get("text"), "files": []}, "start"
            # One run per task: a request while a run is going (e.g. the page reloaded and lost its
            # state) is a note for the agents, and the question the run waits on is shown again.
            elif msg_type == "start" and ws_manager.is_running(chat_id):
                message, msg_type = {"type": "user_note", "text": message.get("task")}, "user_note"
                await ws_manager.resend_pending(chat_id, websocket)

            # === START: Begin chat stream ===
            if msg_type == "start":
                logger.info(f"Start request for {mode} session {chat_id}")

                if not message.get("task"):
                    await _send_error(
                        websocket,
                        chat_id,
                        "Invalid request format. Please provide a task.",
                    )
                    continue

                # Determine which coroutine to run based on mode
                if mode == "chat":
                    coro = ws_manager.chat_mode_initiate(
                        session_id=chat_id, initial_message=message, chat=instance
                    )
                else:  # "omni" or "capability"
                    if mode == "omni" and any(m.get("name") == COMPLETION for m in instance.manager.groupchat.messages):
                        # an open chat taking its next task: the runs it finished are kept as their results, as on a reload
                        instance.manager.resume(messages=compact(list(instance.manager.groupchat.messages), await _ledger(chat_id)))
                    coro = ws_manager.start_chat_stream(
                        session_id=chat_id, initial_message=message, omni=instance
                    )

                _create_tracked_task(coro, websocket, chat_id, f"{mode}_stream")

            elif msg_type == "user_note":
                text = str(message.get("text") or "").strip()
                if text:
                    ws_manager.add_note(chat_id, text)
                    collection = {"omni": "omni", "chat": settings.CHAT_COLLECTION}.get(mode)
                    if collection:  # raw history only: AutoGen's resume rejects unknown speakers
                        await update_chat_history(chat_id, {
                            "role": "user", "name": "user", "usage": {},
                            "raw_message": {"role": "user", "content": text, "type": "user_note"},
                            "task_id": getattr(instance, "task_id", None),
                        }, collection)

            # === STOP: Cancel current session ===
            elif msg_type == "stop":
                logger.info(f"Stop request for session {chat_id}")
                LLMConfigManager.clear_cache()
                reason = message.get("reason", "User requested stop/cancellation")
                await ws_manager.stop_session(chat_id, reason=reason)

            # === PING: Keep-alive ===
            elif msg_type == "ping":
                await websocket.send_json(create_pong_response())

            # === INPUT_RESPONSE: User input for prompts ===
            elif msg_type == "input_response":
                response = message.get("response")
                if response is not None:
                    await ws_manager.handle_input_response(chat_id, response)
                else:
                    logger.warning(f"Invalid input_response for session {chat_id}")

            # === EXECUTOR_INPUT: Terminal input (omni/chat mode only) ===
            elif msg_type == "executor_input" and mode in ("omni", "chat"):
                logger.info(f"Executor input for session {chat_id}")
                await ws_manager.terminal_input(
                    session_id=chat_id,
                    process_id=message.get("process_id"),
                    input_text=message.get("response"),
                )

            # === EXECUTOR_STOP: Kill terminal process (omni/chat mode only) ===
            elif msg_type == "executor_stop" and mode in ("omni", "chat"):
                logger.info(f"Executor stop for session {chat_id}")
                await ws_manager.terminal_kill(
                    session_id=chat_id,
                    process_id=message.get("process_id"),
                )

            # === CONNECT_APP: Connect a new Composio app (chat/omni mode) ===
            elif msg_type == "connect_app" and mode in ("chat", "omni"):
                app_name = message.get("app")
                if not app_name:
                    await websocket.send_json(
                        {
                            "type": "app_connection_result",
                            "success": False,
                            "message": "Missing 'app' field in request",
                        }
                    )
                    continue

                logger.info(f"Connect app request: {app_name} for session {chat_id}")
                try:
                    result = await instance.connect_app(app_name)
                    await websocket.send_json(
                        {
                            "type": "app_connection_result",
                            "action": "connect",
                            **result,
                        }
                    )
                except Exception as e:
                    logger.error(f"Failed to connect app {app_name}: {e}")
                    await websocket.send_json(
                        {
                            "type": "app_connection_result",
                            "action": "connect",
                            "success": False,
                            "app": app_name,
                            "message": f"Failed to connect app: {str(e)}",
                        }
                    )

            # === DISCONNECT_APP: Disconnect a Composio app (chat/omni mode) ===
            elif msg_type == "disconnect_app" and mode in ("chat", "omni"):
                app_name = message.get("app")
                if not app_name:
                    await websocket.send_json(
                        {
                            "type": "app_connection_result",
                            "success": False,
                            "message": "Missing 'app' field in request",
                        }
                    )
                    continue

                logger.info(f"Disconnect app request: {app_name} for session {chat_id}")
                try:
                    result = await instance.disconnect_app(app_name)
                    await websocket.send_json(
                        {
                            "type": "app_connection_result",
                            "action": "disconnect",
                            **result,
                        }
                    )
                except Exception as e:
                    logger.error(f"Failed to disconnect app {app_name}: {e}")
                    await websocket.send_json(
                        {
                            "type": "app_connection_result",
                            "action": "disconnect",
                            "success": False,
                            "app": app_name,
                            "message": f"Failed to disconnect app: {str(e)}",
                        }
                    )

        except json.JSONDecodeError:
            logger.warning(f"Invalid JSON received for session {chat_id}")
            await websocket.send_json(create_error_response("Invalid message format"))


# =============================================================================
# OMNI MODE WEBSOCKET
# =============================================================================


@router.websocket("/omni/{chat_id}")
async def omni_websocket(
    websocket: WebSocket,
    chat_id: str,
    user_id: str = "local_user",
    ws_manager: WebSocketManager = Depends(get_websocket_manager),
):
    """WebSocket endpoint for Omni multi-capability AI chat."""
    connected = await ws_manager.connect(websocket, chat_id)
    if not connected:
        await websocket.close(code=4002, reason="Failed to establish connection")
        return

    logger.info(f"WebSocket connected for omni session {chat_id}")

    try:
        # Initialize
        await websocket.send_json(
            {
                "type": "init_status",
                "status": "connecting",
                "message": "Loading chat history...",
            }
        )

        history = await load_omni_chat_history(chat_id, user_id)
        if not history:
            logger.warning(f"Omni session not found: {chat_id}")
            await websocket.send_json(
                {"type": "error", "error": "Chat session not found"}
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

        omni = await Omni.create(chat_id=chat_id, user_id=user_id, chat_dir=chat_dir)

        await websocket.send_json(
            {
                "type": "init_status",
                "status": "configuring",
                "message": "Loading user context...",
            }
        )

        # Load user context
        user_details = await get_user_details()
        user_context = extract_user_summary(user_details)
        context = build_user_context(user_context)
        omni.judge_question.update_system_message(
            omni.judge_question.system_message + context
        )
        omni.clarifier.update_system_message(omni.clarifier.system_message + context)

        # Resume history
        if messages:
            messages = compact(messages, await _ledger(chat_id))  # finished runs as their results, not their whole transcripts
            omni.manager.resume(messages=messages)
            omni.memory.load_main_messages(messages)

        # Set up input functions
        input_func = ws_manager._create_input_func(chat_id)
        omni.user_input.set_input_function(input_func)
        omni.get_user_acceptance.set_input_function(input_func)
        omni.user_form.set_input_function(input_func)
        omni.set_input_function(input_func)

        await websocket.send_json(
            {
                "type": "init_status",
                "status": "ready",
                "message": "Omni ready",
            }
        )

        logger.info(f"Omni ready for session {chat_id}")
        await _resume_running(websocket, chat_id, ws_manager)
        await _handle_messages(websocket, chat_id, ws_manager, omni, mode="omni")

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for omni session {chat_id}")
    except Exception as e:
        logger.error(f"Omni WebSocket error: {e}")
        try:
            await websocket.send_json(
                {"type": "error", "error": f"Initialization failed: {str(e)}"}
            )
        except Exception:
            pass
    finally:
        LLMConfigManager.clear_cache()
        await ws_manager.disconnect(chat_id, websocket)


# =============================================================================
# CHAT MODE WEBSOCKET
# =============================================================================


def _sdk_chat(chat_id: str, user_id: str, chat_dir: str, ws_manager: WebSocketManager):
    """Chat mode on the persona runtime: one assistant with every connected tool."""
    from src.agent_runtime.session import PersonaSession
    from src.omni.memory import OmniMemory
    from src.utilities.custom_manager import ChatContext

    context = ChatContext(
        user_id=user_id, chat_id=chat_id, chat_dir=chat_dir, call_id=None, capability_id=None,
        capability_name="assistant", collection_name=settings.CHAT_COLLECTION, omni_memory=OmniMemory(),
        manager_kwargs={"websocket_manager": ws_manager},
    )
    return PersonaSession(context, "assistant")


@router.websocket("/chat/{chat_id}")
async def chat_websocket(
    websocket: WebSocket,
    chat_id: str,
    user_id: str = "local_user",
    ws_manager: WebSocketManager = Depends(get_websocket_manager),
):
    """WebSocket endpoint for Chat mode AI conversations."""
    connected = await ws_manager.connect(websocket, chat_id)
    if not connected:
        await websocket.close(code=4002, reason="Failed to establish connection")
        return

    logger.info(f"WebSocket connected for chat session {chat_id}")
    chat = None

    try:
        await websocket.send_json(
            {
                "type": "init_status",
                "status": "connecting",
                "message": "Loading chat history...",
            }
        )

        history = await load_chat_mode_history(chat_id, user_id)
        if not history:
            logger.warning(f"Chat session not found: {chat_id}")
            await websocket.send_json(
                {"type": "error", "error": "Chat session not found"}
            )
            await websocket.close(code=4003, reason="Run not found")
            return

        chat_dir = history.get("chat_dir", get_default_chat_dir())
        messages = history.get("messages", [])

        await websocket.send_json(
            {
                "type": "init_status",
                "status": "initializing",
                "message": "Initializing chat agent...",
            }
        )

        # Use async factory method for non-blocking tool registration
        if settings.CHAT_ENGINE == "sdk":
            chat = _sdk_chat(chat_id, user_id, chat_dir, ws_manager)
        else:
            chat = await Chat.create(chat_id=chat_id, user_id=user_id, chat_dir=chat_dir)

        await websocket.send_json(
            {
                "type": "init_status",
                "status": "configuring",
                "message": "Loading user context...",
            }
        )

        # Load user context
        user_details = await get_user_details()
        user_context = extract_user_summary(user_details)
        context = build_user_context(user_context)
        if isinstance(chat, Chat):
            chat.chat_agent.update_system_message(chat.chat_agent.system_message + context)
        else:
            chat.load_custom_instructions(context)

        # Resume history
        if messages:
            chat.manager.resume(messages=messages)

        # Set up input functions
        input_func = ws_manager._create_input_func(chat_id)
        if isinstance(chat, Chat):
            chat.agent_executor.set_input_function(input_func)
        else:
            chat.start_warm_up()  # connect the SDK and its apps while the user types
        chat.set_input_function(input_func)

        await websocket.send_json(
            {
                "type": "init_status",
                "status": "ready",
                "message": "Chat ready",
            }
        )

        logger.info(f"Chat ready for session {chat_id}")
        await _resume_running(websocket, chat_id, ws_manager)
        await _handle_messages(websocket, chat_id, ws_manager, chat, mode="chat")

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for chat session {chat_id}")
    except Exception as e:
        logger.error(f"Chat WebSocket error: {e}")
        try:
            await websocket.send_json(
                {"type": "error", "error": f"Initialization failed: {str(e)}"}
            )
        except Exception:
            pass
    finally:
        LLMConfigManager.clear_cache()
        await ws_manager.disconnect(chat_id, websocket)
        if chat is not None and not isinstance(chat, Chat):
            try:  # stop the SDK client process, but never hold up a server reload or shutdown
                await asyncio.wait_for(chat.cleanup(), timeout=5)
            except Exception as e:
                logger.warning(f"Chat session cleanup for {chat_id} cut short: {e!r}")


# =============================================================================
# CAPABILITY-SPECIFIC WEBSOCKET
# =============================================================================


@router.websocket("/capability/{chat_id}")
async def capability_websocket(
    websocket: WebSocket,
    chat_id: str,
    user_id: str = "local_user",
    capability_name: str = "email_sender",
    ws_manager: WebSocketManager = Depends(get_websocket_manager),
):
    """WebSocket endpoint for single capability-specific chat."""
    # Validate capability
    try:
        capability = CapabilityType.from_string(capability_name)
        collection_name = capability.collection
        class_instance = CAPABILITY_CLASS_MAP.get(capability_name)
    except ValueError as e:
        if not capability_name.startswith("mcp_"):
            raise HTTPException(status_code=400, detail=str(e))
        from src.services.websocket_service import get_capability_class

        collection_name = capability_name
        class_instance = get_capability_class(capability_name)

    if class_instance is None:
        raise HTTPException(
            status_code=400, detail=f"Unsupported capability: {capability_name}"
        )

    # Load chat history
    history = await load_capability_chat_history(chat_id, user_id, collection_name)
    if not history:
        logger.warning(f"Capability session not found: {chat_id}")
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

    # Resume history
    messages = history.get("messages", [])
    if messages:
        capability_instance.manager.resume(messages=messages)

    # Set up input function and connect
    ws_manager._create_input_func(chat_id)
    connected = await ws_manager.connect(websocket, chat_id)
    if not connected:
        await websocket.close(code=4002, reason="Failed to establish connection")
        return

    try:
        logger.info(f"WebSocket connected for capability session {chat_id}")
        await _handle_messages(
            websocket, chat_id, ws_manager, capability_instance, mode="capability"
        )

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for capability session {chat_id}")
    except Exception as e:
        logger.error(f"Capability WebSocket error: {e}")
    finally:
        await ws_manager.disconnect(chat_id, websocket)
