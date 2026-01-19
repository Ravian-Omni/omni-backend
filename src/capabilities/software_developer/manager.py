"""Software Developer capability manager.

This module provides the SoftwareDeveloper class that implements an AI-powered
coding assistant using Claude's API with native async streaming support.
"""

import asyncio
import os
import uuid
from typing import Any

import anthropic
from loguru import logger

from src.capabilities.software_developer.prompts import SYSTEM_PROMPT
from src.capabilities.software_developer.tools import (
    TOOL_DEFINITIONS,
    AsyncToolRegistry,
)
from src.configs.datetime_utils import dt
from src.configs.llm_configs_manager import LLMConfigManager
from src.managers.cancellation_token import CancellationToken
from src.utilities.custom_manager import ChatContext
from src.utilities.storage import ensure_path


class SoftwareDeveloperManager:
    """Async-compatible manager wrapper for SoftwareDeveloper.

    This class provides compatibility with the existing capability pattern
    by wrapping the SoftwareDeveloper instance and providing the expected
    interface (manager.a_initiate_chat, manager.resume).
    """

    def __init__(self, software_dev: "SoftwareDeveloper"):
        """Initialize the manager wrapper.

        Args:
            software_dev: SoftwareDeveloper instance to wrap.
        """
        self.software_dev = software_dev
        self._messages: list[dict[str, Any]] = []

    async def a_initiate_chat(
        self,
        _recipient,
        message: str,
        clear_history: bool = False,
        **kwargs,
    ) -> None:
        """Initiate chat with the software developer agent.

        Args:
            _recipient: Ignored, kept for interface compatibility.
            message: Initial user message to process.
            clear_history: Whether to clear conversation history.
            **kwargs: Additional arguments (ignored).
        """
        if clear_history:
            self.software_dev.conversation_history = []
            self._messages = []

        await self.software_dev.chat(message)

    def resume(self, messages: list[dict[str, Any]]) -> None:
        """Resume conversation with previous messages.

        Args:
            messages: List of previous messages to restore.
        """
        self._messages = messages
        self.software_dev.load_history(messages)


class SoftwareDeveloper:
    """AI-powered software developer assistant using Claude's API.

    This class implements an agentic coding assistant with native async support,
    real-time WebSocket streaming, and full tool use capabilities.

    Attributes:
        context: ChatContext with session identifiers and configuration.
        conversation_history: List of conversation messages.
        tool_registry: Registry of available tools.
        client: Async Anthropic client.
        model: Claude model to use.
    """

    def __init__(self, context: ChatContext):
        """Initialize the Software Developer capability.

        Args:
            context: ChatContext with all necessary identifiers and configuration.
        """
        self.context = context
        self.websocket_manager = context.manager_kwargs.get("websocket_manager")
        self.cancellation_token: CancellationToken | None = context.cancellation_token
        self.task_id = context.task_id or str(uuid.uuid4())

        # Set up working directory
        self.working_directory = ensure_path(
            os.path.join(context.chat_dir, "workspace")
        )
        self.file_location = ensure_path(os.path.join(context.chat_dir, "files"))

        # Initialize conversation state
        self.conversation_history: list[dict[str, Any]] = []
        self.custom_instructions = ""

        # Get LLM config and API key
        self.llm_config = LLMConfigManager.get_config("claude-sonnet-4-20250514")
        api_key = self.llm_config.get("config_list")[0].get("api_key")

        if not api_key:
            raise ValueError("Anthropic API key not found in LLM configuration")

        # Initialize async Anthropic client
        self.client = anthropic.AsyncAnthropic(api_key=api_key)
        self.model = self.llm_config.get("model", "claude-opus-4-5-20251101")

        # Initialize tool registry
        self.tool_registry = AsyncToolRegistry(working_directory=self.working_directory)

        # Create manager wrapper for compatibility
        self.manager = SoftwareDeveloperManager(self)

        # Usage tracking
        self._total_usage = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }

    def _check_cancellation(self) -> bool:
        """Check if the operation should be cancelled.

        Returns:
            True if cancelled, False otherwise.
        """
        if self.cancellation_token and self.cancellation_token.is_cancelled():
            return True
        return False

    def set_task_id(self, task_id: str) -> None:
        """Set the task ID for tracking.

        Args:
            task_id: Unique task identifier.
        """
        self.task_id = task_id
        self.context.task_id = task_id

    def _set_cancellation_token(self, token: CancellationToken | None) -> None:
        """Set the cancellation token.

        Args:
            token: CancellationToken instance or None.
        """
        self.cancellation_token = token
        self.context.cancellation_token = token

    def set_input_function(self, input_func) -> None:
        """Set the input function for user interaction.

        Args:
            input_func: Async function to request user input.
        """
        self._input_func = input_func

    def load_custom_instructions(self, instructions: str) -> None:
        """Load custom instructions for the agent.

        Args:
            instructions: Custom instructions text.
        """
        self.custom_instructions = instructions

    def load_history(self, messages: list[dict[str, Any]]) -> None:
        """Load conversation history from previous messages.

        Args:
            messages: List of previous message dictionaries.
        """
        self.conversation_history = []
        for msg in messages:
            raw_message = msg.get("raw_message", {})
            if raw_message:
                # Convert from storage format to Anthropic format
                role = raw_message.get("role", "user")
                content = raw_message.get("content", "")
                if role in ("user", "assistant") and content:
                    self.conversation_history.append(
                        {
                            "role": role,
                            "content": content if isinstance(content, str) else content,
                        }
                    )

    def _build_system_prompt(self) -> str:
        """Build the system prompt for Claude.

        Returns:
            Formatted system prompt string.
        """
        return SYSTEM_PROMPT.format(
            working_directory=self.working_directory,
            file_location=self.file_location,
            custom_instructions=self.custom_instructions,
        )

    async def _send_websocket_message(
        self,
        content: Any,
        message_type: str = "message",
        agent_name: str = "software_developer",
    ) -> None:
        """Send a message through WebSocket.

        Args:
            content: Message content to send.
            message_type: Type of message (message, tool_use, etc.).
            agent_name: Name of the sending agent.
        """
        if self.websocket_manager is None:
            return

        try:
            message_data = {
                "role": "assistant",
                "name": agent_name,
                "content": content,
                "type": message_type,
                "call_id": self.context.call_id,
                "capability_id": self.context.capability_id,
                "task_id": self.task_id,
            }
            await self.websocket_manager.send_chat_message(
                session_id=self.context.chat_id,
                content=message_data,
                source=self.context.capability_name,
            )
        except Exception as e:
            logger.error(f"WebSocket send failed: {e}")

    async def _update_chat_history(self, message_data: dict[str, Any]) -> None:
        """Update chat history in the database.

        Args:
            message_data: Message data to persist.
        """
        try:
            raw_message = {
                k: message_data.get(k)
                for k in ["role", "name", "raw_message", "usage", "task_id"]
                if k in message_data
            }
            content_message = {
                k: message_data.get(k)
                for k in ["role", "name", "content"]
                if k in message_data
            }

            raw_message["timestamp"] = dt.now_iso()

            push_operations = {"raw_messages": raw_message}
            if content_message.get("content"):
                push_operations["messages"] = content_message

            update_document = {
                "$push": push_operations,
                "$set": {"updated_at": dt.now()},
            }

            filter_criteria = {
                "user_id": self.context.user_id,
                "chat_id": self.context.chat_id,
                "call_id": self.context.call_id,
                "capability_id": self.context.capability_id,
            }
            print(filter_criteria, update_document)

            # await api_client.post(
            #     RoutesConfig.API_UPDATE_OMNI_CHAT,
            #     params={"capability": self.context.collection_name},
            #     data={"filter_criteria": filter_criteria, "document": update_document},
            # )

        except Exception as e:
            logger.error(f"Failed to update chat history: {e}")

    async def chat(
        self,
        user_message: str,
        max_turns: int = 25,
    ) -> str:
        """Process a user message and generate a response.

        This method implements the agentic loop with tool use support,
        streaming responses through WebSocket in real-time.

        Args:
            user_message: The user's message to process.
            max_turns: Maximum number of tool-use turns before stopping.

        Returns:
            The final response text from Claude.

        Raises:
            asyncio.CancelledError: If the operation is cancelled.
        """
        # Check for cancellation
        if self._check_cancellation():
            raise asyncio.CancelledError("Operation cancelled before start")

        # Add user message to history
        self.conversation_history.append(
            {
                "role": "user",
                "content": user_message,
            }
        )

        # Save user message to database
        await self._update_chat_history(
            {
                "role": "user",
                "name": "user",
                "content": user_message,
                "raw_message": {"role": "user", "content": user_message},
                "task_id": self.task_id,
            }
        )

        turn = 0
        final_response = ""

        while turn < max_turns:
            turn += 1

            # Check cancellation at each turn
            if self._check_cancellation():
                raise asyncio.CancelledError(f"Operation cancelled at turn {turn}")

            # Stream response from Claude
            response, accumulated_text = await self._stream_response()

            # Update usage tracking
            if hasattr(response, "usage"):
                self._total_usage["prompt_tokens"] += response.usage.input_tokens
                self._total_usage["completion_tokens"] += response.usage.output_tokens
                self._total_usage["total_tokens"] += (
                    response.usage.input_tokens + response.usage.output_tokens
                )

            # Process response for tool use
            assistant_content = []
            has_tool_use = False
            tool_uses = []

            for block in response.content:
                if block.type == "text":
                    final_response = block.text
                    assistant_content.append(
                        {
                            "type": "text",
                            "text": block.text,
                        }
                    )
                elif block.type == "tool_use":
                    has_tool_use = True
                    tool_uses.append(block)
                    assistant_content.append(
                        {
                            "type": "tool_use",
                            "id": block.id,
                            "name": block.name,
                            "input": block.input,
                        }
                    )

            # Add assistant message to history
            self.conversation_history.append(
                {
                    "role": "assistant",
                    "content": assistant_content,
                }
            )

            # Save assistant message to database
            await self._update_chat_history(
                {
                    "role": "assistant",
                    "name": "software_developer",
                    "content": accumulated_text,
                    "raw_message": {
                        "role": "assistant",
                        "content": assistant_content,
                    },
                    "usage": self._total_usage.copy(),
                    "task_id": self.task_id,
                }
            )

            if not has_tool_use:
                # No tool use, conversation complete
                break

            # Execute tools and add results
            tool_results = []
            for tool_block in tool_uses:
                # Check cancellation before each tool execution
                if self._check_cancellation():
                    raise asyncio.CancelledError(
                        "Operation cancelled during tool execution"
                    )

                # Send tool use notification
                await self._send_websocket_message(
                    content={
                        "tool_name": tool_block.name,
                        "tool_input": tool_block.input,
                        "status": "executing",
                    },
                    message_type="tool_use",
                )

                # Execute tool
                tool_result = await self.tool_registry.execute(
                    tool_block.name, **tool_block.input
                )

                # Send tool result notification
                await self._send_websocket_message(
                    content={
                        "tool_name": tool_block.name,
                        "tool_result": (
                            tool_result[:2000]
                            if len(tool_result) > 2000
                            else tool_result
                        ),
                        "status": "completed",
                    },
                    message_type="tool_result",
                )

                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_block.id,
                        "content": tool_result,
                    }
                )

            # Add tool results to conversation
            self.conversation_history.append(
                {
                    "role": "user",
                    "content": tool_results,
                }
            )

            # Check stop reason
            if response.stop_reason == "end_turn":
                break

        return final_response

    async def _stream_response(self) -> tuple[Any, str]:
        """Stream response from Claude with real-time WebSocket updates.

        Returns:
            Tuple of (final response object, accumulated text).
        """
        accumulated_text = ""
        tool_input_json = ""

        async with self.client.messages.stream(
            model=self.model,
            max_tokens=16000,
            system=self._build_system_prompt(),
            messages=self.conversation_history,
            tools=TOOL_DEFINITIONS,
        ) as stream:
            async for event in stream:
                # Check cancellation during streaming
                if self._check_cancellation():
                    raise asyncio.CancelledError("Operation cancelled during streaming")

                if event.type == "content_block_start":
                    if hasattr(event, "content_block"):
                        block_type = getattr(event.content_block, "type", None)
                        if block_type == "tool_use":
                            getattr(event.content_block, "name", "")
                            tool_input_json = ""

                elif event.type == "content_block_delta":
                    if hasattr(event.delta, "text"):
                        text_chunk = event.delta.text
                        accumulated_text += text_chunk

                        # Stream text to WebSocket
                        await self._send_websocket_message(
                            content={
                                "text": text_chunk,
                                "streaming": True,
                            },
                            message_type="stream",
                        )

                    elif hasattr(event.delta, "partial_json"):
                        tool_input_json += event.delta.partial_json

            # Get the final message
            response = await stream.get_final_message()

        # Send final accumulated text if any
        if accumulated_text:
            await self._send_websocket_message(
                content=accumulated_text,
                message_type="message",
            )

        return response, accumulated_text

    def reset_conversation(self) -> None:
        """Clear conversation history."""
        self.conversation_history = []
        self._total_usage = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }

    def get_usage_summary(self) -> dict[str, Any]:
        """Get current usage summary.

        Returns:
            Dictionary with token usage statistics.
        """
        return self._total_usage.copy()
