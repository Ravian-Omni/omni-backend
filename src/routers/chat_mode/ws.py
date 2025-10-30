# api/ws.py
import asyncio
import json
from datetime import datetime, date
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, Query
from src.dependencies import get_websocket_manager
from src.managers.chat_mode.connection import WebSocketManager
from src.configs.settings import settings
from src.utilities.api_client import api_client
import os
from src.managers.chat_mode.groupchat import AgentChat
import os
from fastapi import HTTPException, Depends, status

router = APIRouter()

# chat_mode WebSocket endpoint


@router.websocket("/chat/{chat_id}")
async def run_chat_mode_websocket(
    websocket: WebSocket,
    chat_id: str,
    user_id: str = Query(None),
    ws_manager: WebSocketManager = Depends(get_websocket_manager),
):
    """WebSocket endpoint for chat_mode groupchat communication (with user_id and chat history check)"""
    # Verify chat exists and is in valid state
    chat_history = await api_client.post("/chats/history", params={"capability": "omni"}, data={"chat_id": chat_id, "user_id": user_id})
    chat_history = chat_history.standard_response()
    if not chat_history.get("success"):
        await websocket.close(code=3001, reason=chat_history.get("message", "Chat not found"))
        return

    history = chat_history.get("data")
    if not history:
        await websocket.close(code=4003, reason="Chat not found")
        return

    chat_dir = history.get(
        "chat_dir", os.path.join(settings.ROOT_DIR, "ravian"))

    # Pass user_id from WebSocket query parameter to AgentChat
    chat = AgentChat(chat_id=chat_id, user_id=user_id)
    messages = history.get("messages", [])
    # If you want to resume previous messages, add logic here (if supported by AgentChat)

    input_func = ws_manager._create_input_func(chat_id)
    chat.set_input_function(input_func)

    # Connect websocket
    connected = await ws_manager.connect(websocket, chat_id)
    if not connected:
        await websocket.close(code=4002, reason="Failed to establish connection")
        return

    try:
        while True:
            try:
                raw_message = await websocket.receive_text()
                message = json.loads(raw_message)

                if message.get("type") == "start":
                    # Handle start message
                    if message.get("task"):
                        # Use chat_mode specific method
                        asyncio.create_task(
                            ws_manager.start_chat_stream_chat_mode(chat_id, message, chat))
                    else:
                        await websocket.send_json(
                            {
                                "type": "error",
                                "error": "Invalid start message format",
                                "timestamp": datetime.utcnow().isoformat(),
                            }
                        )

                elif message.get("type") == "stop":
                    reason = message.get(
                        "reason") or "User requested stop/cancellation"
                    await ws_manager.stop_session(chat_id, reason=reason)
                    # break

                elif message.get("type") == "ping":
                    await websocket.send_json(
                        {"type": "pong", "timestamp": datetime.utcnow().isoformat()}
                    )

                elif message.get("type") == "input_response":
                    # Handle input response from client
                    response = message.get("response")
                    if response is not None:
                        await ws_manager.handle_input_response(chat_id, response)
            except json.JSONDecodeError:
                await websocket.send_json(
                    {
                        "type": "error",
                        "error": "Invalid message format",
                        "timestamp": datetime.utcnow().isoformat(),
                    }
                )

    except WebSocketDisconnect:
        raise
    except Exception as e:
        raise
    finally:
        await ws_manager.disconnect(chat_id)
