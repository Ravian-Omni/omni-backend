"""WebSocket endpoints for real-time AI chat communication.

This module provides WebSocket endpoints for:
- Omni multi-capability AI conversations
- Individual capability-specific chats (browser, email, file finder, etc.)
- Real-time streaming of AI responses
- Chat history management and context preservation
"""

import asyncio
import json
import os

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from loguru import logger

from src.capabilities.browser_manager.manager import BrowserManager
from src.capabilities.email_manager.manager import EmailManager
from src.capabilities.file_finder.manager import FileFinder
from src.capabilities.image_generator.manager import ImageGenerator
from src.capabilities.python_developer.manager import PythonDeveloper
from src.chat.manager import Chat
from src.configs.datetime_utils import dt
from src.configs.llm_configs_manager import LLMConfigManager
from src.configs.routes import RoutesConfig
from src.configs.settings import CapabilityType, settings
from src.dependencies import get_websocket_manager
from src.managers.connection import WebSocketManager
from src.omni.manager import Omni
from src.omni.memory import OmniMemory
from src.utilities.api_client import api_client
from src.utilities.custom_manager import ChatContext


def extract_user_summary(data: dict) -> dict:
    """Extract and format user information summary.

    Args:
        data: Raw API response containing user information.

    Returns:
        dict: Cleaned dictionary with selected user fields including name, email, dob, etc.
    """
    first_name = data.get("first_name", "").strip()
    last_name = data.get("last_name", "").strip()
    full_name = f"{first_name} {last_name}".strip() if last_name else first_name

    return {
        "name": first_name,
        "email": data.get("email", ""),
        "full_name": full_name,
        "dob": data.get("dob", ""),
        "gender": data.get("gender", ""),
        "country": data.get("country", ""),
        "date": dt.today_date_iso(),
    }


router = APIRouter()


@router.websocket("/omni/{chat_id}")
async def run_websocket(
    websocket: WebSocket,
    chat_id: str,
    user_id: str = "b38661d1-dbcf-4d3f-bd2a-fdf5e9789964",
    ws_manager: WebSocketManager = Depends(get_websocket_manager),
):
    """Websocket endpoint for Omni multi-capability AI chat.

    Handles real-time communication for Omni conversations with support for
    multiple AI capabilities, context preservation, and streaming responses.

    Args:
        websocket: WebSocket connection instance.
        chat_id: Unique identifier for the chat session.
        user_id: User identifier. Defaults to test user ID.
        ws_manager: WebSocket manager dependency for connection handling.

    Raises:
        WebSocketDisconnect: When connection is closed by client or server.
    """
    # Verify run exists and is in valid state
    chat_history = await api_client.post(
        RoutesConfig.API_OMNI_CHAT_HISTORY,
        params={"capability": "omni"},
        data={"chat_id": chat_id, "user_id": user_id},
    )
    chat_history = chat_history.standard_response()
    if not chat_history.get("success"):
        logger.error(chat_history)
        await websocket.close(
            code=3001, reason=chat_history.get("message", "Run not found")
        )
        return

    history = chat_history.get("data")
    # history = await db.find_one(settings.OMNI_COLLECTION,{"chat_id":chat_id, "user_id":user_id})
    if not history:
        logger.warning(f"Run not found: {user_id} & {chat_id}")
        await websocket.close(code=4003, reason="Run not found")
        return

    chat_dir = history.get("chat_dir", os.path.join(settings.ROOT_DIR, "ravian"))

    omni = Omni(chat_id=chat_id, user_id=user_id, chat_dir=chat_dir)
    messages = history.get("messages", [])
    user_details = await api_client.get(RoutesConfig.API_USER_DETAILS)
    user_details = user_details.standard_response()
    if not user_details.get("success"):
        raise Exception(
            f"Failed to update chat history: {user_details.get('message', 'Unknown error')}"
        )
    user_context = extract_user_summary(user_details.get("data"))
    context = f"""

    User Information:
    - User: {user_context['full_name']}
    - Birth Date: {user_context['dob']}
    - Email: {user_context['email']}
    - Gender: {user_context['gender']}
    - Location: {user_context['country']}
    - Today's Date: {user_context['date']}

    Please take this context into account when responding.

    """
    omni.judge_question.update_system_message(
        omni.judge_question.system_message + context
    )
    # messages.append({"role":"user", "name":"chat_manager", "content":context})
    if messages:
        last_agent, last_message = omni.manager.resume(messages=messages)
        omni.memory.load_main_messages(messages)

    input_func = ws_manager._create_input_func(chat_id)
    omni.user_input.set_input_function(input_func)
    omni.get_user_acceptance.set_input_function(input_func)
    omni.set_input_function(input_func)
    # Connect websocket
    connected = await ws_manager.connect(websocket, chat_id)
    if not connected:
        await websocket.close(code=4002, reason="Failed to establish connection")
        return

    try:
        logger.info(f"WebSocket connection established for run {chat_id}")

        while True:
            try:
                raw_message = await websocket.receive_text()
                message = json.loads(raw_message)

                if message.get("type") == "start":
                    # Handle start message
                    logger.info(f"Received start request for run {chat_id}")
                    if message.get("task"):
                        asyncio.create_task(
                            ws_manager.start_chat_stream(
                                session_id=chat_id, initial_message=message, omni=omni
                            )
                        )
                    else:
                        logger.warning(
                            f"Invalid start message format for run {chat_id}"
                        )
                        await websocket.send_json(
                            {
                                "type": "error",
                                "error": "Invalid start message format",
                                "timestamp": dt.now_iso(),
                            }
                        )

                elif message.get("type") == "stop":
                    logger.info(f"Received stop request for run {chat_id}")
                    LLMConfigManager.clear_cache()
                    reason = message.get("reason") or "User requested stop/cancellation"
                    await ws_manager.stop_session(chat_id, reason=reason)
                    # break

                elif message.get("type") == "ping":
                    await websocket.send_json(
                        {"type": "pong", "timestamp": dt.now_iso()}
                    )

                elif message.get("type") == "executor_input":
                    logger.info(f"Received input request for executor {chat_id}")
                    process_id = message.get("process_id")
                    input_text = message.get("response")
                    await ws_manager.terminal_input(
                        session_id=chat_id, process_id=process_id, input_text=input_text
                    )

                elif message.get("type") == "executor_stop":
                    logger.info(f"Received stop request for executor {chat_id}")
                    process_id = message.get("process_id")
                    await ws_manager.terminal_kill(
                        session_id=chat_id, process_id=process_id
                    )

                elif message.get("type") == "input_response":
                    # Handle input response from client
                    response = message.get("response")
                    if response is not None:
                        await ws_manager.handle_input_response(chat_id, response)
                    else:
                        logger.warning(
                            f"Invalid input response format for run {chat_id}"
                        )
                # elif message.get("type") == "pause":
                #     logger.info(f"Received pause request for run {chat_id}")
                #     await ws_manager.pause_run(chat_id)

                # elif message.get("type") == "resume":
                #     logger.info(f"Received resume request for run {chat_id}")
                #     await ws_manager.resume_run(chat_id)
            except json.JSONDecodeError:
                logger.warning(f"Invalid JSON received: {raw_message}")
                await websocket.send_json(
                    {
                        "type": "error",
                        "error": "Invalid message format",
                        "timestamp": dt.now_iso(),
                    }
                )

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for run {chat_id}")
        LLMConfigManager.clear_cache()
    except Exception as e:
        logger.error(f"WebSocket error: {str(e)}")
        LLMConfigManager.clear_cache()
    finally:
        LLMConfigManager.clear_cache()
        await ws_manager.disconnect(chat_id)


@router.websocket("/chat/{chat_id}")
async def run_chat_websocket(
    websocket: WebSocket,
    chat_id: str,
    user_id: str = "b38661d1-dbcf-4d3f-bd2a-fdf5e9789964",
    ws_manager: WebSocketManager = Depends(get_websocket_manager),
):
    """Websocket endpoint for Chat multi-capability AI chat.

    Handles real-time communication for Chat conversations with support for
    multiple AI capabilities, context preservation, and streaming responses.

    Args:
        websocket: WebSocket connection instance.
        chat_id: Unique identifier for the chat session.
        user_id: User identifier. Defaults to test user ID.
        ws_manager: WebSocket manager dependency for connection handling.

    Raises:
        WebSocketDisconnect: When connection is closed by client or server.
    """
    # Verify run exists and is in valid state
    chat_history = await api_client.post(
        RoutesConfig.API_CHAT_HISTORY,
        params={"capability": "chats"},
        data={"chat_id": chat_id, "user_id": user_id},
    )
    chat_history = chat_history.standard_response()
    if not chat_history.get("success"):
        logger.error(chat_history)
        await websocket.close(
            code=3001, reason=chat_history.get("message", "Run not found")
        )
        return

    history = chat_history.get("data")
    if not history:
        logger.warning(f"Run not found: {user_id} & {chat_id}")
        await websocket.close(code=4003, reason="Run not found")
        return

    chat_dir = history.get("chat_dir", os.path.join(settings.ROOT_DIR, "ravian"))
    # chat_dir = os.path.join(settings.ROOT_DIR, "ravian")

    omni = Chat(chat_id=chat_id, user_id=user_id, chat_dir=chat_dir)
    messages = history.get("messages", [])
    # user_details = await api_client.get(RoutesConfig.API_USER_DETAILS)
    # user_details = user_details.standard_response()
    # if not user_details.get("success"):
    #     raise Exception(
    #         f"Failed to update chat history: {user_details.get('message', 'Unknown error')}"
    #     )
    # user_context = extract_user_summary(user_details.get("data"))
    # context = f"""

    # User Information:
    # - User: {user_context['full_name']}
    # - Birth Date: {user_context['dob']}
    # - Email: {user_context['email']}
    # - Gender: {user_context['gender']}
    # - Location: {user_context['country']}
    # - Today's Date: {user_context['date']}

    # Please take this context into account when responding.

    # """
    # omni.judge_question.update_system_message(
    #     omni.judge_question.system_message + context
    # )
    # messages.append({"role":"user", "name":"chat_manager", "content":context})
    if messages:
        last_agent, last_message = omni.manager.resume(messages=messages)

    input_func = ws_manager._create_input_func(chat_id)
    omni.agent_executor.set_input_function(input_func)
    omni.set_input_function(input_func)
    # Connect websocket
    connected = await ws_manager.connect(websocket, chat_id)
    if not connected:
        await websocket.close(code=4002, reason="Failed to establish connection")
        return

    try:
        logger.info(f"WebSocket connection established for run {chat_id}")

        while True:
            try:
                raw_message = await websocket.receive_text()
                message = json.loads(raw_message)

                if message.get("type") == "start":
                    # Handle start message
                    logger.info(f"Received start request for run {chat_id}")
                    if message.get("task"):
                        asyncio.create_task(
                            ws_manager.chat_mode_initiate(
                                session_id=chat_id, initial_message=message, omni=omni
                            )
                        )
                    else:
                        logger.warning(
                            f"Invalid start message format for run {chat_id}"
                        )
                        await websocket.send_json(
                            {
                                "type": "error",
                                "error": "Invalid start message format",
                                "timestamp": dt.now_iso(),
                            }
                        )

                elif message.get("type") == "stop":
                    logger.info(f"Received stop request for run {chat_id}")
                    LLMConfigManager.clear_cache()
                    reason = message.get("reason") or "User requested stop/cancellation"
                    await ws_manager.stop_session(chat_id, reason=reason)
                    # break

                elif message.get("type") == "ping":
                    await websocket.send_json(
                        {"type": "pong", "timestamp": dt.now_iso()}
                    )

                elif message.get("type") == "executor_input":
                    logger.info(f"Received input request for executor {chat_id}")
                    process_id = message.get("process_id")
                    input_text = message.get("response")
                    await ws_manager.terminal_input(
                        session_id=chat_id, process_id=process_id, input_text=input_text
                    )

                elif message.get("type") == "executor_stop":
                    logger.info(f"Received stop request for executor {chat_id}")
                    process_id = message.get("process_id")
                    await ws_manager.terminal_kill(
                        session_id=chat_id, process_id=process_id
                    )

                elif message.get("type") == "input_response":
                    # Handle input response from client
                    response = message.get("response")
                    if response is not None:
                        await ws_manager.handle_input_response(chat_id, response)
                    else:
                        logger.warning(
                            f"Invalid input response format for run {chat_id}"
                        )
                # elif message.get("type") == "pause":
                #     logger.info(f"Received pause request for run {chat_id}")
                #     await ws_manager.pause_run(chat_id)

                # elif message.get("type") == "resume":
                #     logger.info(f"Received resume request for run {chat_id}")
                #     await ws_manager.resume_run(chat_id)
            except json.JSONDecodeError:
                logger.warning(f"Invalid JSON received: {raw_message}")
                await websocket.send_json(
                    {
                        "type": "error",
                        "error": "Invalid message format",
                        "timestamp": dt.now_iso(),
                    }
                )

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for run {chat_id}")
        LLMConfigManager.clear_cache()
    except Exception as e:
        logger.error(f"WebSocket error: {str(e)}")
        LLMConfigManager.clear_cache()
    finally:
        LLMConfigManager.clear_cache()
        await ws_manager.disconnect(chat_id)


CAPABILITY_CLASS_MAP = {
    "omni": Omni,
    "email_sender": EmailManager,
    "web_browser": BrowserManager,
    "python_coder": PythonDeveloper,
    "file_finder": FileFinder,
    "image_generator": ImageGenerator,
}


@router.websocket("/capability/{chat_id}")
async def run_capability_websocket(
    websocket: WebSocket,
    chat_id: str,
    user_id: str = "default_user",
    capability_name: str = "email_sender",
    ws_manager: WebSocketManager = Depends(get_websocket_manager),
):
    """Websocket endpoint for single capability-specific chat.

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
    # Verify run exists and is in valid state
    try:
        capability = CapabilityType.from_string(capability_name)
        collection_name = capability.collection
        class_instance = CAPABILITY_CLASS_MAP.get(capability_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    query = {
        "user_id": user_id,
        "chat_id": chat_id,
        "call_id": "Individual",
        "capability_id": chat_id,
    }

    # Verify run exists and is in valid state
    chat_history = await api_client.post(
        RoutesConfig.API_OMNI_CHAT_HISTORY,
        params={"capability": collection_name},
        data=query,
    )
    chat_history = chat_history.standard_response()
    if not chat_history.get("success"):
        logger.error(chat_history)
        await websocket.close(
            code=3001, reason=chat_history.get("message", "Run not found")
        )
        return

    history = chat_history.get("data")
    # history = await db.find_one(settings.OMNI_COLLECTION,{"chat_id":chat_id, "user_id":user_id})
    if not history:
        logger.warning(f"Run not found: {user_id} & {chat_id}")
        await websocket.close(code=4003, reason="Run not found")
        return

    chat_dir = history.get("chat_dir", os.path.join(settings.ROOT_DIR, "ravian"))

    chat_context = ChatContext(
        user_id=user_id,
        chat_id=chat_id,
        chat_dir=chat_dir,
        call_id="Individual",
        capability_id=chat_id,
        capability_name=capability_name,
        collection_name=collection_name,
        omni_memory=OmniMemory(),
    )

    omni = class_instance(chat_context)
    messages = history.get("messages", [])
    if messages:
        last_agent, last_message = omni.manager.resume(messages=messages)
        # omni.omni_memory.load_main_messages(messages)
    # run = run_response.data[0]
    # if run.status not in [RunStatus.CREATED, RunStatus.ACTIVE]:
    #     await websocket.close(code=4003, reason="Run not in valid state")
    #     return

    ws_manager._create_input_func(chat_id)
    # omni.user_input.set_input_function(input_func)
    # Connect websocket
    connected = await ws_manager.connect(websocket, chat_id)
    if not connected:
        await websocket.close(code=4002, reason="Failed to establish connection")
        return

    try:
        logger.info(f"WebSocket connection established for run {chat_id}")

        while True:
            try:
                raw_message = await websocket.receive_text()
                message = json.loads(raw_message)

                if message.get("type") == "start":
                    # Handle start message
                    logger.info(f"Received start request for run {chat_id}")
                    if message.get("task"):
                        asyncio.create_task(
                            ws_manager.start_chat_stream(
                                session_id=chat_id, initial_message=message, omni=omni
                            )
                        )
                    else:
                        logger.warning(
                            f"Invalid start message format for run {chat_id}"
                        )
                        await websocket.send_json(
                            {
                                "type": "error",
                                "error": "Invalid start message format",
                                "timestamp": dt.now_iso(),
                            }
                        )

                elif message.get("type") == "stop":
                    logger.info(f"Received stop request for run {chat_id}")
                    reason = message.get("reason") or "User requested stop/cancellation"
                    await ws_manager.stop_session(chat_id, reason=reason)
                    # break

                elif message.get("type") == "ping":
                    await websocket.send_json(
                        {"type": "pong", "timestamp": dt.now_iso()}
                    )

                elif message.get("type") == "input_response":
                    # Handle input response from client
                    response = message.get("response")
                    if response is not None:
                        await ws_manager.handle_input_response(chat_id, response)
                    else:
                        logger.warning(
                            f"Invalid input response format for run {chat_id}"
                        )
                # elif message.get("type") == "pause":
                #     logger.info(f"Received pause request for run {chat_id}")
                #     await ws_manager.pause_run(chat_id)

                # elif message.get("type") == "resume":
                #     logger.info(f"Received resume request for run {chat_id}")
                #     await ws_manager.resume_run(chat_id)
            except json.JSONDecodeError:
                logger.warning(f"Invalid JSON received: {raw_message}")
                await websocket.send_json(
                    {
                        "type": "error",
                        "error": "Invalid message format",
                        "timestamp": dt.now_iso(),
                    }
                )

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for run {chat_id}")
    except Exception as e:
        logger.error(f"WebSocket error: {str(e)}")
    finally:
        await ws_manager.disconnect(chat_id)
