# api/ws.py
import asyncio
import json
from datetime import datetime
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from loguru import logger
from dependencies import get_websocket_manager, get_mongodb_service
from managers.connection import WebSocketManager
from configs.settings import settings
from omni.manager import Omni

router = APIRouter()

async def omni_start_chat(omni, message, function):
    response = await omni.manager.a_initiate_chat(omni.manager,message=message.get("task"),clear_history=False)
    return

@router.websocket("/runs/{chat_id}")
async def run_websocket(
    websocket: WebSocket,
    chat_id: str,
    ws_manager: WebSocketManager = Depends(get_websocket_manager),
    db=Depends(get_mongodb_service),
):
    """WebSocket endpoint for run communication"""
    # Verify run exists and is in valid state
    history = await db.find_one(settings.OMNI_COLLECTION,{"chat_id":chat_id})
    if not history:
        logger.warning(f"Run not found: {chat_id}")
        await websocket.close(code=4004, reason="Run not found")
        return
    
    omni = Omni(chat_id=chat_id)
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
                        # await ws_manager.start_stream(chat_id, task, team_config)
                        # asyncio.create_task(
                        #     ws_manager.start_stream(
                        #         chat_id, task, team_config, settings_config
                        #     )
                        # )
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
