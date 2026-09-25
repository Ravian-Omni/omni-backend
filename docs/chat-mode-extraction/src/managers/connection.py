"""WebSocket connection manager for Chat Service.

This module provides:
- WebSocket connection lifecycle management
- Message streaming to connected clients
- User input handling and response coordination
- Task cancellation and cleanup
"""

import asyncio
import logging
import traceback
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from src.configs.datetime_utils import dt
from src.configs.llm_configs_manager import LLMConfigManager
from src.managers.cancellation_token import CancellationToken

# Type aliases
InputFuncType = Callable[[str, str], Awaitable[str]]
InputRequestType = str

logger = logging.getLogger(__name__)


class WebSocketManager:
    """WebSocket manager for Chat Service.

    Handles WebSocket connections, message streaming, user input requests,
    and task cancellation for chat sessions.

    Attributes:
        _connections: Active WebSocket connections by session ID.
        _closed_connections: Set of closed session IDs.
        _input_responses: Queues for handling user input responses.
        _active_tasks: Currently running asyncio tasks by session.
        _cancellation_tokens: Cancellation tokens for task management.
        _stop_flags: Flags indicating stopped sessions.
    """

    def __init__(self):
        """Initialize WebSocketManager with empty connection state."""
        self._connections: dict[str, WebSocket] = {}
        self._closed_connections: set[str] = set()
        self._input_responses: dict[str, asyncio.Queue[str]] = {}
        self._active_tasks: dict[str, asyncio.Task] = {}
        self._cancellation_tokens: dict[str, CancellationToken] = {}
        self._stop_flags: dict[str, bool] = {}

    async def connect(self, websocket: WebSocket, session_id: str) -> bool:
        """Accept a new WebSocket connection.

        Args:
            websocket: FastAPI WebSocket instance to accept.
            session_id: Unique identifier for this session.

        Returns:
            True if connection successful, False otherwise.
        """
        try:
            await websocket.accept()
            self._connections[session_id] = websocket
            self._closed_connections.discard(session_id)
            self._input_responses[session_id] = asyncio.Queue()
            self._stop_flags[session_id] = False

            await self._send_message(
                session_id,
                {
                    "type": "system",
                    "status": "connected",
                    "timestamp": dt.now_iso(),
                },
            )

            logger.info(f"WebSocket connected for session {session_id}")
            return True
        except Exception as e:
            logger.error(f"Connection error for session {session_id}: {e}")
            return False

    async def chat_initiate(
        self,
        session_id: str,
        initial_message: str = "",
        chat=None,
    ) -> None:
        """Start a chat stream with the provided chat manager.

        Args:
            session_id: Session identifier.
            initial_message: Optional initial message to start the conversation.
            chat: Chat manager instance for handling the chat logic.

        Raises:
            ValueError: If no active connection exists for the session.
        """
        if (
            session_id not in self._connections
            or session_id in self._closed_connections
        ):
            raise ValueError(f"No active connection for session {session_id}")

        self._stop_flags[session_id] = False
        cancellation_token = CancellationToken()
        self._cancellation_tokens[session_id] = cancellation_token
        chat.set_task_id(str(uuid.uuid4()))
        
        try:
            # Send initial message acknowledgment
            if initial_message:
                await self._send_message(
                    session_id,
                    {
                        "type": "message",
                        "data": {
                            "source": "user",
                            "content": initial_message,
                            "timestamp": dt.now_iso(),
                        },
                    },
                )

            chat._set_cancellation_token(
                self._cancellation_tokens.get(session_id, None)
            )
            
            task = asyncio.create_task(
                chat.manager.a_initiate_chat(
                    chat.manager,
                    message=initial_message.get("task"),
                    clear_history=False,
                )
            )
            self._active_tasks[session_id] = task

            # Wait for completion or cancellation
            await task

            if (
                not self._stop_flags.get(session_id, True)
                and session_id not in self._closed_connections
            ):
                await self._send_message(
                    session_id,
                    {
                        "type": "completion",
                        "status": "complete",
                        "timestamp": dt.now_iso(),
                    },
                )
            else:
                await self._send_message(
                    session_id,
                    {
                        "type": "completion",
                        "status": "cancelled",
                        "timestamp": dt.now_iso(),
                    },
                )

        except Exception as e:
            logger.error(f"Chat stream error for session {session_id}: {e}")
            traceback.print_exc()
            await self._handle_stream_error(session_id, e)
        finally:
            self._cancellation_tokens.pop(session_id, None)
            self._active_tasks.pop(session_id, None)
            self._stop_flags.pop(session_id, None)

    def _create_input_func(self, session_id: str, timeout: int = 600) -> InputFuncType:
        """Create an input function for requesting user input during chat.

        Args:
            session_id: Session identifier.
            timeout: Timeout in seconds for input response. Defaults to 600.

        Returns:
            Async input function that accepts prompt and input_type parameters.
        """

        async def input_handler(
            prompt: str = "",
            input_type: InputRequestType = "text_input",
        ) -> str:
            """Handle input request from chat session."""
            try:
                logger.info(
                    f"Requesting input for session {session_id}: ({input_type}) {prompt}"
                )

                # Send input request to client
                await self._send_message(
                    session_id,
                    {
                        "type": "input_request",
                        "input_type": input_type,
                        "prompt": prompt,
                        "data": {"source": "system", "content": prompt},
                        "timestamp": dt.now_iso(),
                    },
                )

                # Wait for response with timeout
                if session_id in self._input_responses:
                    try:
                        async def poll_for_response():
                            while True:
                                if (
                                    session_id in self._closed_connections
                                    or self._stop_flags.get(session_id, False)
                                ):
                                    raise ValueError("Session was closed or stopped")

                                try:
                                    response = await asyncio.wait_for(
                                        self._input_responses[session_id].get(),
                                        timeout=min(timeout, 5),
                                    )
                                    return response
                                except asyncio.TimeoutError:
                                    continue

                        response = await asyncio.wait_for(
                            poll_for_response(), timeout=timeout
                        )
                        return response

                    except asyncio.TimeoutError:
                        logger.warning(f"Input response timeout for session {session_id}")
                        await self.stop_session(session_id, "Input timeout")
                        raise
                else:
                    raise ValueError(f"No input queue for session {session_id}")

            except Exception as e:
                logger.error(f"Error handling input for session {session_id}: {e}")
                raise

        return input_handler

    async def send_message(self, session_id: str, message: dict[str, Any]) -> None:
        """Send a message to the client.

        Args:
            session_id: Session identifier.
            message: Message dictionary to send.
        """
        await self._send_message(session_id, message)

    async def send_chat_message(
        self, session_id: str, content: str, source: str = "assistant"
    ) -> None:
        """Send a formatted chat message to the client.

        Args:
            session_id: Session identifier.
            content: Message content.
            source: Message source. Defaults to "assistant".
        """
        await self._send_message(
            session_id,
            {
                "type": "message",
                "data": {
                    "source": source,
                    "content": content,
                    "timestamp": dt.now_iso(),
                },
            },
        )

    async def handle_input_response(self, session_id: str, response: str) -> None:
        """Handle input response from client.

        Args:
            session_id: Session identifier.
            response: User's input response.
        """
        if session_id in self._input_responses:
            await self._input_responses[session_id].put(response)
        else:
            logger.warning(f"Received input response for inactive session {session_id}")

    async def stop_session(
        self, session_id: str, reason: str = "Session stopped"
    ) -> None:
        """Stop an active session.

        Args:
            session_id: Session identifier.
            reason: Reason for stopping. Defaults to "Session stopped".
        """
        LLMConfigManager.clear_cache()
        
        if session_id in self._cancellation_tokens:
            logger.info(f"Stopping session {session_id}: {reason}")

            try:
                # Set stop flag
                self._stop_flags[session_id] = True

                # Cancel the token
                self._cancellation_tokens[session_id].cancel()

                # Cancel the main task if it exists
                if session_id in self._active_tasks:
                    task = self._active_tasks[session_id]
                    if not task.done():
                        task.cancel()
                        try:
                            await asyncio.wait_for(task, timeout=3.0)
                        except asyncio.TimeoutError:
                            logger.warning(f"Task wait timed out for {session_id}")
                        except asyncio.CancelledError:
                            pass

                # Send completion message
                if (
                    session_id in self._connections
                    and session_id not in self._closed_connections
                ):
                    await self._send_message(
                        session_id,
                        {
                            "type": "completion",
                            "status": "stopped",
                            "reason": reason,
                            "timestamp": dt.now_iso(),
                        },
                    )

            except Exception as e:
                logger.error(f"Error stopping session {session_id}: {e}")

    async def disconnect(self, session_id: str) -> None:
        """Clean up connection and associated resources.

        Args:
            session_id: Session identifier.
        """
        LLMConfigManager.clear_cache()
        logger.info(f"Disconnecting session {session_id}")

        # Mark as closed before cleanup
        self._closed_connections.add(session_id)

        # Stop the session
        await self.stop_session(session_id, "Connection closed")

        # Clean up resources
        self._connections.pop(session_id, None)
        self._cancellation_tokens.pop(session_id, None)
        self._input_responses.pop(session_id, None)
        self._active_tasks.pop(session_id, None)
        self._stop_flags.pop(session_id, None)

    async def _send_message(self, session_id: str, message: dict[str, Any]) -> None:
        """Internal method to send a message through WebSocket.

        Args:
            session_id: Session identifier.
            message: Message dictionary to send.
        """
        if session_id in self._closed_connections:
            logger.warning(f"Attempted to send message to closed session {session_id}")
            raise Exception(f"Session closed for {session_id}")

        try:
            if session_id in self._connections:
                websocket = self._connections[session_id]
                await websocket.send_json(message)
        except WebSocketDisconnect:
            logger.warning(f"WebSocket disconnected for session {session_id}")
            await self.disconnect(session_id)
        except Exception as e:
            logger.error(f"Error sending message for session {session_id}: {e}")
            await self.disconnect(session_id)

    async def _handle_stream_error(self, session_id: str, error: Exception) -> None:
        """Handle stream errors.

        Args:
            session_id: Session identifier.
            error: Exception that occurred.
        """
        if session_id not in self._closed_connections:
            await self._send_message(
                session_id,
                {
                    "type": "error",
                    "message": str(error),
                    "timestamp": dt.now_iso(),
                },
            )

    async def cleanup(self) -> None:
        """Clean up all active connections and resources."""
        logger.info(f"Cleaning up {len(self.active_connections)} active connections")

        try:
            # Stop all sessions
            for session_id in list(self._active_tasks.keys()):
                self._stop_flags[session_id] = True
                if session_id in self._cancellation_tokens:
                    self._cancellation_tokens[session_id].cancel()

            # Disconnect all websockets
            async def disconnect_all():
                for session_id in list(self.active_connections):
                    try:
                        await asyncio.wait_for(self.disconnect(session_id), timeout=2)
                    except asyncio.TimeoutError:
                        logger.warning(f"Timeout disconnecting session {session_id}")
                    except Exception as e:
                        logger.error(f"Error disconnecting session {session_id}: {e}")

            await asyncio.wait_for(disconnect_all(), timeout=10)

        except asyncio.TimeoutError:
            logger.warning("WebSocketManager cleanup timed out")
        except Exception as e:
            logger.error(f"Error during WebSocketManager cleanup: {e}")
        finally:
            LLMConfigManager.clear_cache()
            self._connections.clear()
            self._cancellation_tokens.clear()
            self._closed_connections.clear()
            self._input_responses.clear()
            self._active_tasks.clear()
            self._stop_flags.clear()

    @property
    def active_connections(self) -> set[str]:
        """Get set of active session IDs."""
        return set(self._connections.keys()) - self._closed_connections

    def is_connected(self, session_id: str) -> bool:
        """Check if a session is actively connected."""
        return (
            session_id in self._connections
            and session_id not in self._closed_connections
        )

    def is_session_stopped(self, session_id: str) -> bool:
        """Check if a session has been stopped."""
        return self._stop_flags.get(session_id, False)
