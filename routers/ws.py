# # api/ws.py
# import asyncio
# import json
# from datetime import datetime
# from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
# from loguru import logger
# from dependencies import get_websocket_manager, get_mongodb_service
# from managers.connection import WebSocketManager
# from configs.settings import settings
# from omni.manager import Omni

# router = APIRouter()

# async def omni_start_chat(omni, message, function):
#     response = await omni.manager.a_initiate_chat(omni.manager,message=message.get("task"),clear_history=False)
#     return

# @router.websocket("/runs/{chat_id}")
# async def run_websocket(
#     websocket: WebSocket,
#     chat_id: str,
#     ws_manager: WebSocketManager = Depends(get_websocket_manager),
#     db=Depends(get_mongodb_service),
# ):
#     """WebSocket endpoint for run communication"""
#     # Verify run exists and is in valid state
#     history = await db.find_one(settings.OMNI_COLLECTION,{"chat_id":chat_id})
#     if not history:
#         logger.warning(f"Run not found: {chat_id}")
#         await websocket.close(code=4004, reason="Run not found")
#         return
    
#     omni = Omni(chat_id=chat_id)
#     messages = history.get("messages",[])
#     if messages:
#         last_agent, last_message = omni.manager.resume(messages=messages)
#         omni.memory.load_main_messages(messages)
#     # run = run_response.data[0]
#     # if run.status not in [RunStatus.CREATED, RunStatus.ACTIVE]:
#     #     await websocket.close(code=4003, reason="Run not in valid state")
#     #     return

#     input_func = ws_manager._create_input_func(chat_id)
#     omni.user_input.set_input_function(input_func)
#     # Connect websocket
#     connected = await ws_manager.connect(websocket, chat_id)
#     if not connected:
#         await websocket.close(code=4002, reason="Failed to establish connection")
#         return

#     try:
#         logger.info(f"WebSocket connection established for run {chat_id}")

#         while True:
#             try:
#                 raw_message = await websocket.receive_text()
#                 message = json.loads(raw_message)

#                 if message.get("type") == "start":
#                     # Handle start message
#                     logger.info(f"Received start request for run {chat_id}")
#                     if message.get("task"):
#                         # await ws_manager.start_stream(chat_id, task, team_config)
#                         # asyncio.create_task(
#                         #     ws_manager.start_stream(
#                         #         chat_id, task, team_config, settings_config
#                         #     )
#                         # )
#                         asyncio.create_task(ws_manager.start_chat_stream(session_id=chat_id,initial_message=message,omni=omni))
#                     else:
#                         logger.warning(f"Invalid start message format for run {chat_id}")
#                         await websocket.send_json(
#                             {
#                                 "type": "error",
#                                 "error": "Invalid start message format",
#                                 "timestamp": datetime.utcnow().isoformat(),
#                             }
#                         )

#                 elif message.get("type") == "stop":
#                     logger.info(f"Received stop request for run {chat_id}")
#                     reason = message.get("reason") or "User requested stop/cancellation"
#                     await ws_manager.stop_run(chat_id, reason=reason)
#                     break

#                 elif message.get("type") == "ping":
#                     await websocket.send_json(
#                         {"type": "pong", "timestamp": datetime.utcnow().isoformat()}
#                     )

#                 elif message.get("type") == "input_response":
#                     # Handle input response from client
#                     response = message.get("response")
#                     if response is not None:
#                         await ws_manager.handle_input_response(chat_id, response)
#                     else:
#                         logger.warning(
#                             f"Invalid input response format for run {chat_id}"
#                         )
#                 # elif message.get("type") == "pause":
#                 #     logger.info(f"Received pause request for run {chat_id}")
#                 #     await ws_manager.pause_run(chat_id)

#                 # elif message.get("type") == "resume":
#                 #     logger.info(f"Received resume request for run {chat_id}")
#                 #     await ws_manager.resume_run(chat_id)
#             except json.JSONDecodeError:
#                 logger.warning(f"Invalid JSON received: {raw_message}")
#                 await websocket.send_json(
#                     {
#                         "type": "error",
#                         "error": "Invalid message format",
#                         "timestamp": datetime.utcnow().isoformat(),
#                     }
#                 )

#     except WebSocketDisconnect:
#         logger.info(f"WebSocket disconnected for run {chat_id}")
#     except Exception as e:
#         logger.error(f"WebSocket error: {str(e)}")
#     finally:
#         await ws_manager.disconnect(chat_id)






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

async def safe_start_chat_stream(ws_manager, chat_id, initial_message, omni):
    """Wrapper for chat stream with error handling"""
    try:
        await ws_manager.start_chat_stream(
            session_id=chat_id,
            initial_message=initial_message,
            omni=omni
        )
    except asyncio.CancelledError:
        logger.info(f"Chat stream cancelled for {chat_id}")
    except Exception as e:
        logger.opt(exception=e).error(f"Chat stream failed: {str(e)}")
        await ws_manager.send_error(chat_id, f"Processing failed: {str(e)}")
        await ws_manager.disconnect(chat_id)

@router.websocket("/runs/{chat_id}")
async def run_websocket(
    websocket: WebSocket,
    chat_id: str,
    ws_manager: WebSocketManager = Depends(get_websocket_manager),
    db=Depends(get_mongodb_service),
):
    """WebSocket endpoint for run communication with enhanced stability"""
    # Verify run exists
    try:
        history = await db.find_one(settings.OMNI_COLLECTION, {"chat_id": chat_id})
        if not history:
            logger.warning(f"Run not found: {chat_id}")
            await websocket.close(code=4004, reason="Run not found")
            return
    except Exception as e:
        logger.opt(exception=e).error(f"Database error: {str(e)}")
        await websocket.close(code=4005, reason="Database error")
        return

    # Initialize Omni with error handling
    try:
        omni = Omni(chat_id=chat_id)
        messages = history.get("messages", [])
        if messages:
            last_agent, last_message = omni.manager.resume(messages=messages)
            omni.memory.load_main_messages(messages)
    except Exception as e:
        logger.opt(exception=e).error(f"Omni initialization failed: {str(e)}")
        await websocket.close(code=4006, reason="Initialization failed")
        return

    # Set up input function
    try:
        input_func = ws_manager._create_input_func(chat_id)
        omni.user_input.set_input_function(input_func)
    except Exception as e:
        logger.opt(exception=e).error(f"Input setup failed: {str(e)}")
        await websocket.close(code=4007, reason="Input setup failed")
        return

    # Connect websocket
    try:
        connected = await ws_manager.connect(websocket, chat_id)
        if not connected:
            await websocket.close(code=4002, reason="Connection limit reached")
            return
    except Exception as e:
        logger.opt(exception=e).error(f"Connection failed: {str(e)}")
        await websocket.close(code=4008, reason="Connection error")
        return

    # Initialize tasks
    tasks = set()
    HEARTBEAT_INTERVAL = 15.0  # seconds
    LAST_MESSAGE_TIMEOUT = 300.0  # 5 minutes

    async def heartbeat():
        """Periodic heartbeat to keep connection alive"""
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            try:
                await websocket.send_json({"type": "ping"})
            except Exception:
                logger.warning(f"Heartbeat failed for {chat_id}")
                break

    async def message_handler():
        """Handle incoming messages with timeout"""
        while True:
            try:
                raw_message = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=LAST_MESSAGE_TIMEOUT
                )
                yield raw_message
            except asyncio.TimeoutError:
                logger.warning(f"Inactivity timeout for {chat_id}")
                await ws_manager.stop_run(chat_id, reason="Inactivity timeout")
                break
            except WebSocketDisconnect:
                logger.info(f"Client disconnected: {chat_id}")
                break
            except Exception as e:
                logger.opt(exception=e).error(f"Receive error: {str(e)}")
                break

    try:
        logger.info(f"WebSocket connection established for run {chat_id}")
        heartbeat_task = asyncio.create_task(heartbeat())
        tasks.add(heartbeat_task)
        heartbeat_task.add_done_callback(tasks.discard)

        async for raw_message in message_handler():
            try:
                message = json.loads(raw_message)
                message_type = message.get("type")

                if message_type == "start":
                    logger.info(f"Received start request for run {chat_id}")
                    if message.get("task"):
                        # Create supervised task
                        task = asyncio.create_task(
                            safe_start_chat_stream(ws_manager, chat_id, message, omni)
                        )
                        tasks.add(task)
                        task.add_done_callback(tasks.discard)
                    else:
                        logger.warning(f"Invalid start message for {chat_id}")
                        await websocket.send_json({
                            "type": "error",
                            "error": "Missing 'task' in start message",
                            "timestamp": datetime.utcnow().isoformat(),
                        })

                elif message_type == "stop":
                    logger.info(f"Received stop request for {chat_id}")
                    reason = message.get("reason", "User requested stop")
                    await ws_manager.stop_run(chat_id, reason=reason)
                    break

                elif message_type == "pong":
                    # Update last active timestamp if needed
                    pass

                elif message_type == "input_response":
                    response = message.get("response")
                    if response is not None:
                        await ws_manager.handle_input_response(chat_id, response)
                    else:
                        logger.warning(f"Invalid input response for {chat_id}")
                        await websocket.send_json({
                            "type": "error",
                            "error": "Missing response field",
                            "timestamp": datetime.utcnow().isoformat(),
                        })

            except json.JSONDecodeError:
                logger.warning(f"Invalid JSON received: {raw_message}")
                await websocket.send_json({
                    "type": "error",
                    "error": "Invalid JSON format",
                    "timestamp": datetime.utcnow().isoformat(),
                })
            except Exception as e:
                logger.opt(exception=e).error(f"Message handling error: {str(e)}")
                await websocket.send_json({
                    "type": "error",
                    "error": f"Internal error: {str(e)}",
                    "timestamp": datetime.utcnow().isoformat(),
                })

    except Exception as e:
        logger.opt(exception=e).error(f"Unexpected error: {str(e)}")

    finally:
        logger.info(f"Cleaning up connection for {chat_id}")
        
        # FIX 1: Create a snapshot of tasks to avoid modification during iteration
        tasks_snapshot = tasks.copy()
        
        # FIX 2: Cancel tasks safely
        cancel_tasks = []
        for task in tasks_snapshot:
            if not task.done():
                task.cancel()
                cancel_tasks.append(task)
        
        # FIX 3: Wait for cancellation to complete
        if cancel_tasks:
            try:
                await asyncio.wait(cancel_tasks, timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning("Some tasks didn't cancel in time")
        
        # FIX 4: Remove all tasks from original set
        tasks.clear()
        
        # Disconnect websocket
        await ws_manager.disconnect(chat_id)