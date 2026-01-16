"""WebSocket connection manager for real-time AI chat sessions.

This module provides:
- WebSocket connection lifecycle management
- Message streaming to connected clients
- User input handling and response coordination
- Task cancellation and cleanup
- Browser and executor process management
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

# Type aliases for input handling
InputFuncType = Callable[[str, str], Awaitable[str]]
InputRequestType = str  # "text_input", "file_upload", etc.

logger = logging.getLogger(__name__)


class WebSocketManager:
    """Simplified WebSocket manager for AG2AI GroupChat workflows.

    Handles WebSocket connections, message streaming, user input requests,
    and task cancellation for AI chat sessions.

    Attributes:
        _connections: Active WebSocket connections by session ID.
        _closed_connections: Set of closed session IDs.
        _input_responses: Queues for handling user input responses.
        _active_tasks: Currently running asyncio tasks by session.
        active_browser: Active browser instances by session.
        active_executor: Active code executor instances.
        _cancellation_tokens: Cancellation tokens for task management.
        _stop_flags: Flags indicating stopped sessions.
    """

    def __init__(self):
        """Initialize WebSocketManager with empty connection state."""
        self._connections: dict[str, WebSocket] = {}
        self._closed_connections: set[str] = set()
        self._input_responses: dict[str, asyncio.Queue[str]] = {}
        self._active_tasks: dict[str, asyncio.Task] = {}
        self.active_browser: dict[str, asyncio.Task] = {}
        self.active_executor: dict = {}
        self._cancellation_tokens: dict[int, CancellationToken] = {}
        self._stop_flags: dict[str, bool] = {}

    async def connect(self, websocket: WebSocket, session_id: str) -> bool:
        """Accept a new WebSocket connection.

        Initializes connection state, creates input response queue,
        and sends connection confirmation to the client.

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

    async def chat_mode_initiate(
        self,
        session_id: str,
        # chat_handler: Callable[[str, InputFuncType], Awaitable[Any]],
        initial_message: str = "",
        chat=None,
    ) -> None:
        """Start a chat stream with the provided chat manager.

        Initiates an async chat session, manages the conversation lifecycle,
        handles cancellation, and sends completion/cancellation notifications.

        Args:
            session_id: Session identifier.
            initial_message: Optional initial message to start the conversation.
            chat: chat manager instance for handling the chat logic.

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
            # Send initial message if provided
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

    async def start_chat_stream(
        self,
        session_id: str,
        # chat_handler: Callable[[str, InputFuncType], Awaitable[Any]],
        initial_message: str = "",
        omni=None,
    ) -> None:
        """Start a chat stream with the provided omni manager.

        Initiates an async chat session, manages the conversation lifecycle,
        handles cancellation, and sends completion/cancellation notifications.

        Args:
            session_id: Session identifier.
            initial_message: Optional initial message to start the conversation.
            omni: Omni manager instance for handling the chat logic.

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

        try:
            # Send initial message if provided
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

            omni._set_cancellation_token(
                self._cancellation_tokens.get(session_id, None)
            )
            omni.set_task_id(str(uuid.uuid4()))
            task = asyncio.create_task(
                omni.manager.a_initiate_chat(
                    omni.manager,
                    message=str(
                        {
                            "task": initial_message.get("task"),
                            "files": initial_message.get("files"),
                        }
                    ),
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

        Returns an async function that can be called to request input from
        the client and wait for a response with timeout handling.

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
            """Handle input request from chat session.

            Args:
                prompt: Prompt to display to user.
                input_type: Type of input requested. Defaults to "text_input".

            Returns:
                User's input response.

            Raises:
                TimeoutError: If no response received within timeout.
                ValueError: If no input queue exists or session closed.
            """
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
                            """Poll for user response while checking session status."""
                            while True:
                                # Check if session was closed/stopped
                                if (
                                    session_id in self._closed_connections
                                    or self._stop_flags.get(session_id, False)
                                ):
                                    raise ValueError("Session was closed or stopped")

                                # Try to get response with short timeout
                                try:
                                    response = await asyncio.wait_for(
                                        self._input_responses[session_id].get(),
                                        timeout=min(timeout, 5),
                                    )
                                    return response
                                except TimeoutError:
                                    continue  # Keep checking for closed status

                        response = await asyncio.wait_for(
                            poll_for_response(), timeout=timeout
                        )
                        return response

                    except TimeoutError:
                        logger.warning(
                            f"Input response timeout for session {session_id}"
                        )
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
            source: Message source (e.g., "assistant", "user", agent name).
                Defaults to "assistant".
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

    async def send_agent_message(
        self, session_id: str, agent_name: str, content: str
    ) -> None:
        """Send a message from a specific agent.

        Args:
            session_id: Session identifier.
            agent_name: Name of the agent sending the message.
            content: Message content.
        """
        await self.send_chat_message(session_id, content, source=agent_name)

    async def handle_input_response(self, session_id: str, response: str) -> None:
        """Handle input response from client.

        Places the user's response into the input queue for processing
        by the waiting input handler.

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

        Cancels active tasks, cleans up browser and executor resources,
        triggers cancellation token, and notifies the client.

        The cancellation flow:
        1. Set stop flag to signal all operations to check for cancellation
        2. Cancel the cancellation token (triggers callbacks in StreamingAgent)
        3. Cancel asyncio tasks (browser agent, main task)
        4. Close browser session explicitly
        5. Cleanup executor resources
        6. Send completion message to client

        Args:
            session_id: Session identifier.
            reason: Reason for stopping. Defaults to "Session stopped".
        """
        LLMConfigManager.clear_cache()
        if session_id in self._cancellation_tokens:
            logger.info(f"Stopping session {session_id}: {reason}")

            try:
                # Step 1: Set stop flag immediately
                self._stop_flags[session_id] = True

                # Step 2: Cancel the token FIRST to trigger StreamingAgent callbacks
                # This sets _is_shutting_down flag in the agent, causing it to raise
                # CancelledError at the next cancellation check point
                self._cancellation_tokens[session_id].cancel()

                # Step 3: Clean up executor resources
                if session_id in self.active_executor:
                    executor = self.active_executor[session_id]
                    if hasattr(executor, "cleanup"):
                        try:
                            await executor.cleanup()
                        except Exception as e:
                            logger.warning(f"Error cleaning up executor: {e}")
                    self.active_executor.pop(session_id, None)

                # Step 4: Handle browser cleanup
                if session_id in self.active_browser:
                    agent_task, browser = self.active_browser[session_id]

                    # Cancel the browser agent task
                    if not agent_task.done():
                        agent_task.cancel()

                    # Close browser session explicitly (may already be closing via callback)
                    try:
                        await asyncio.wait_for(
                            self.close_browser_session(browser),
                            timeout=5.0  # 5 second timeout for browser close
                        )
                    except asyncio.TimeoutError:
                        logger.warning(f"Browser close timed out for {session_id}")
                    except Exception as e:
                        logger.warning(f"Error closing browser for {session_id}: {e}")

                    # Wait for browser task to complete
                    try:
                        await asyncio.wait_for(agent_task, timeout=2.0)
                    except asyncio.TimeoutError:
                        logger.warning(f"Browser task wait timed out for {session_id}")
                    except asyncio.CancelledError:
                        pass  # Expected
                    except Exception as e:
                        logger.warning(f"Error waiting for browser task: {e}")

                    # Remove from active browser tracking
                    self.active_browser.pop(session_id, None)

                # Step 5: Cancel the main task if it exists
                if session_id in self._active_tasks:
                    task = self._active_tasks[session_id]
                    if not task.done():
                        task.cancel()
                        try:
                            await asyncio.wait_for(task, timeout=3.0)
                        except asyncio.TimeoutError:
                            logger.warning(f"Main task wait timed out for {session_id}")
                        except asyncio.CancelledError:
                            pass  # Expected
                        except Exception as e:
                            logger.warning(f"Error waiting for main task: {e}")

                # Step 6: Send completion message if connection is active
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

    async def close_browser_session(self, browser_session) -> bool:
        """Attempt to close browser gracefully using the session's built-in methods.

        Tries multiple cleanup approaches including event bus cleanup,
        standard close methods, and browser instance closure.

        Args:
            browser_session: Browser session instance to close.

        Returns:
            True if closure was successful, False if errors occurred.
        """
        if browser_session is None:
            return True

        try:
            if hasattr(browser_session, "agent"):
                agent = browser_session.agent
                if hasattr(agent, "event_bus"):
                    # Try to stop or clean up the event bus
                    if hasattr(agent.event_bus, "stop"):
                        await agent.event_bus.stop()
                    elif hasattr(agent.event_bus, "close"):
                        await agent.event_bus.close()
                    elif hasattr(agent.event_bus, "cleanup"):
                        await agent.event_bus.cleanup()

            # Also check for global EventBus registry cleanup
            if hasattr(browser_session, "_cleanup_event_system"):
                await browser_session._cleanup_event_system()

            # Try the standard close method first
            if hasattr(browser_session, "close"):
                await browser_session.close()

            # Then try kill method
            if hasattr(browser_session, "kill"):
                await browser_session.kill()

            # Try to close the browser if it has a browser attribute
            if hasattr(browser_session, "browser") and browser_session.browser:
                await browser_session.browser.close()
            browser_session = None
            return True

        except Exception as e:
            print(f"Error during graceful browser closure: {e}")
            return False

    async def terminal_input(self, session_id: str, process_id: str, input_text: str):
        """Handle terminal input request.

        Sends input text to a running terminal process in the active executor.

        Args:
            session_id: Session identifier.
            process_id: Identifier of the terminal process.
            input_text: Text input to send to the terminal.
        """
        if session_id in self.active_executor:
            await self.active_executor[session_id].send_input_to_process(
                process_id, input_text
            )
        elif (
            session_id in self._connections
            and session_id not in self._closed_connections
        ):
            await self._send_message(
                session_id,
                {
                    "type": "terminal_error",
                    "process_id": process_id,
                    "content": f"Session {session_id} is not active for terminal input",
                    "timestamp": dt.now_iso(),
                },
            )
        else:
            logger.warning(f"Received input response for inactive session {session_id}")

    async def terminal_kill(self, session_id: str, process_id: str):
        """Handle terminal process kill request.

        Terminates a running terminal process in the active executor.

        Args:
            session_id: Session identifier.
            process_id: Identifier of the process to kill.
        """
        if session_id in self.active_executor:
            await self.active_executor[session_id].terminate_process(process_id)
        elif (
            session_id in self._connections
            and session_id not in self._closed_connections
        ):
            await self._send_message(
                session_id,
                {
                    "type": "terminal_error",
                    "process_id": process_id,
                    "content": f"Session {session_id} is not active for terminal kill",
                    "timestamp": dt.now_iso(),
                },
            )
        else:
            logger.warning(f"Received kill request for inactive session {session_id}")

    async def disconnect(self, session_id: str) -> None:
        """Clean up connection and associated resources.

        Stops the session, removes connection from tracking,
        and cleans up all associated state.

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

        Raises:
            Exception: If session is closed.
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

        Sends error message to client if session is still active.

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
        """Clean up all active connections and resources.

        Stops all sessions, disconnects all WebSockets with timeout handling,
        and clears all internal state. Called during application shutdown.
        """
        logger.info(f"Cleaning up {len(self.active_connections)} active connections")

        try:
            # Stop all sessions
            for session_id in list(self._active_tasks.keys()):
                self._stop_flags[session_id] = True
                if session_id in self._cancellation_tokens:
                    self._cancellation_tokens[session_id].cancel()

            # Disconnect all websockets with timeout
            async def disconnect_all():
                """Disconnect all active websockets with timeout handling."""
                for session_id in list(self.active_connections):
                    try:
                        await asyncio.wait_for(self.disconnect(session_id), timeout=2)
                    except TimeoutError:
                        logger.warning(f"Timeout disconnecting session {session_id}")
                    except Exception as e:
                        logger.error(f"Error disconnecting session {session_id}: {e}")

            await asyncio.wait_for(disconnect_all(), timeout=10)

        except TimeoutError:
            logger.warning("WebSocketManager cleanup timed out")
        except Exception as e:
            logger.error(f"Error during WebSocketManager cleanup: {e}")
        finally:
            # Clear all internal state
            LLMConfigManager.clear_cache()
            self._connections.clear()
            self._cancellation_tokens.clear()
            self._closed_connections.clear()
            self._input_responses.clear()
            self._active_tasks.clear()
            self._stop_flags.clear()

    @property
    def active_connections(self) -> set[str]:
        """Get set of active session IDs.

        Returns:
            Set of session IDs that are connected and not closed.
        """
        return set(self._connections.keys()) - self._closed_connections

    @property
    def active_sessions(self) -> set[str]:
        """Get set of sessions with active tasks.

        Returns:
            Set of session IDs with running tasks.
        """
        return set(self._active_tasks.keys())

    def is_connected(self, session_id: str) -> bool:
        """Check if a session is actively connected.

        Args:
            session_id: Session identifier to check.

        Returns:
            True if session is connected and not closed.
        """
        return (
            session_id in self._connections
            and session_id not in self._closed_connections
        )

    def is_session_stopped(self, session_id: str) -> bool:
        """Check if a session has been stopped.

        Args:
            session_id: Session identifier to check.

        Returns:
            True if session has been stopped.
        """
        return self._stop_flags.get(session_id, False)

    def get_cancellation_token(self, session_id: str) -> CancellationToken | None:
        """Get the cancellation token for a session.

        Args:
            session_id: Session identifier.

        Returns:
            CancellationToken if session exists, None otherwise.
        """
        return self._cancellation_tokens.get(session_id)

    def get_active_browser(self, session_id: str) -> CancellationToken | None:
        """Get the active browser for a session.

        Args:
            session_id: Session identifier.

        Returns:
            Active browser instance if exists, None otherwise.
        """
        return self.active_browser.get(session_id)
