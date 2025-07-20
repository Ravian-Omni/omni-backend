# api/ws.py
import asyncio
import json
from datetime import datetime
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from loguru import logger
from dependencies import get_websocket_manager, get_mongodb_service
from managers.connection import WebSocketManager
from configs.settings import settings, CapabilityType
from omni.manager import Omni
from capabilities.email_manager.manager import EmailManager
from capabilities.browser_manager.manager import BrowserManager
from capabilities.python_developer.manager import PythonDeveloper
from capabilities.file_finder.manager import FileFinder
from capabilities.image_generator.manager import ImageGenerator
from omni.memory import OmniMemory
import os
from fastapi import HTTPException, Depends, status
from utilities.custom_manager import ChatContext

router = APIRouter()

@router.websocket("/omni/{chat_id}")
async def run_websocket(
    websocket: WebSocket,
    chat_id: str,
    user_id: str = "default_user",
    ws_manager: WebSocketManager = Depends(get_websocket_manager),
    db=Depends(get_mongodb_service),
):
    """WebSocket endpoint for run communication"""
    # Verify run exists and is in valid state
    history = await db.find_one(settings.OMNI_COLLECTION,{"chat_id":chat_id, "user_id":user_id})
    if not history:
        logger.warning(f"Run not found: {user_id} & {chat_id}")
        await websocket.close(code=4004, reason="Run not found")
        return
    
    chat_dir = history.get("chat_dir", os.path.join(settings.ROOT_DIR, "ravian"))
    
    omni = Omni(chat_id=chat_id,user_id=user_id, chat_dir=chat_dir)
    messages = history.get("messages",[])
    if messages:
        last_agent, last_message = omni.manager.resume(messages=messages)
        omni.memory.load_main_messages(messages)
    # run = run_response.data[0]
    # if run.status not in [RunStatus.CREATED, RunStatus.ACTIVE]:
    #     await websocket.close(code=4003, reason="Run not in valid state")
    #     return

    input_func = ws_manager._create_input_func(chat_id)
    omni.user_input.set_input_function(input_func)
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
                        asyncio.create_task(ws_manager.start_chat_stream(session_id=chat_id,initial_message=message,omni=omni))
                    else:
                        logger.warning(f"Invalid start message format for run {chat_id}")
                        await websocket.send_json(
                            {
                                "type": "error",
                                "error": "Invalid start message format",
                                "timestamp": datetime.utcnow().isoformat(),
                            }
                        )

                elif message.get("type") == "stop":
                    logger.info(f"Received stop request for run {chat_id}")
                    reason = message.get("reason") or "User requested stop/cancellation"
                    await ws_manager.stop_run(chat_id, reason=reason)
                    break

                elif message.get("type") == "ping":
                    await websocket.send_json(
                        {"type": "pong", "timestamp": datetime.utcnow().isoformat()}
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
                        "timestamp": datetime.utcnow().isoformat(),
                    }
                )

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for run {chat_id}")
    except Exception as e:
        logger.error(f"WebSocket error: {str(e)}")
    finally:
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
async def run_websocket(
    websocket: WebSocket,
    chat_id: str,
    user_id: str = "default_user",
    capability_name: str = "email_sender",
    ws_manager: WebSocketManager = Depends(get_websocket_manager),
    db=Depends(get_mongodb_service),
):
    """WebSocket endpoint for run communication"""
    # Verify run exists and is in valid state
    try:
        capability = CapabilityType.from_string(capability_name)
        collection_name = capability.collection
        class_instance = CAPABILITY_CLASS_MAP.get(capability_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    query = {"user_id": user_id, "chat_id": chat_id, "call_id": "Individual", "capability_id": chat_id}
    
    history = await db.find_one(collection_name, query)
    if not history:
        logger.warning(f"Run not found: {user_id} & {chat_id}")
        await websocket.close(code=4004, reason="Run not found")
        return
    
    chat_dir = history.get("chat_dir", os.path.join(settings.ROOT_DIR, "ravian"))
    
    chat_context = ChatContext(
        user_id = user_id,
        chat_id = chat_id,
        chat_dir = chat_dir,
        call_id = "Individual",
        capability_id = chat_id,
        capability_name = capability_name,
        collection_name = collection_name,
        omni_memory = OmniMemory()
    )
    
    omni = class_instance(chat_context)
    messages = history.get("messages",[])
    if messages:
        last_agent, last_message = omni.manager.resume(messages=messages)
        # omni.omni_memory.load_main_messages(messages)
    # run = run_response.data[0]
    # if run.status not in [RunStatus.CREATED, RunStatus.ACTIVE]:
    #     await websocket.close(code=4003, reason="Run not in valid state")
    #     return

    input_func = ws_manager._create_input_func(chat_id)
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
                        asyncio.create_task(ws_manager.start_chat_stream(session_id=chat_id,initial_message=message,omni=omni))
                    else:
                        logger.warning(f"Invalid start message format for run {chat_id}")
                        await websocket.send_json(
                            {
                                "type": "error",
                                "error": "Invalid start message format",
                                "timestamp": datetime.utcnow().isoformat(),
                            }
                        )

                elif message.get("type") == "stop":
                    logger.info(f"Received stop request for run {chat_id}")
                    reason = message.get("reason") or "User requested stop/cancellation"
                    await ws_manager.stop_run(chat_id, reason=reason)
                    break

                elif message.get("type") == "ping":
                    await websocket.send_json(
                        {"type": "pong", "timestamp": datetime.utcnow().isoformat()}
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
                        "timestamp": datetime.utcnow().isoformat(),
                    }
                )

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for run {chat_id}")
    except Exception as e:
        logger.error(f"WebSocket error: {str(e)}")
    finally:
        await ws_manager.disconnect(chat_id)
