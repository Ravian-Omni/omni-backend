"""Software Developer capability manager with LangGraph.

This module provides the SoftwareDeveloper class that implements an AI-powered
coding assistant using LangGraph with native async streaming support, PTY terminals,
and comprehensive tool support.
"""

import asyncio
import os
import uuid
from typing import Any

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode
from loguru import logger

from src.capabilities.software_developer.prompts import SYSTEM_PROMPT
from src.capabilities.software_developer.pty_terminal import PtyTerminalManager
from src.capabilities.software_developer.state import (
    SoftwareDeveloperState,
    create_initial_state,
    should_continue,
    trim_messages_to_fit_context,
    update_token_counts,
)
from src.capabilities.software_developer.tools import (
    AsyncToolRegistry,
    create_langgraph_tools,
)
from src.configs.datetime_utils import dt
from src.configs.llm_configs_manager import LLMConfigManager
from src.managers.cancellation_token import CancellationToken
from src.utilities.custom_manager import ChatContext
from src.utilities.storage import ensure_path


class SoftwareDeveloperManager:
    """Manager wrapper for SoftwareDeveloper (compatibility with existing capability pattern).

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
            self.software_dev.reset_conversation()
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
    """AI-powered software developer assistant using LangGraph + Anthropic Claude.

    This class implements an agentic coding assistant with:
    - LangGraph workflow for robust tool use
    - Native async support
    - Real-time WebSocket streaming
    - PTY-based interactive terminals
    - Full file system and git operations
    - Code analysis and execution

    Attributes:
        context: ChatContext with session identifiers and configuration.
        state: Current LangGraph agent state.
        graph: Compiled LangGraph workflow.
        llm: Anthropic Claude LLM instance.
        tool_registry: Registry of available tools.
        terminal_manager: PTY terminal manager.
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

        # Initialize state
        self.state: SoftwareDeveloperState = create_initial_state(
            user_id=context.user_id,
            chat_id=context.chat_id,
            call_id=context.call_id,
            capability_id=context.capability_id,
            task_id=self.task_id,
            working_directory=self.working_directory,
            max_iterations=25,
            max_context_tokens=200000,  # Claude's context window
        )

        # Custom instructions
        self.custom_instructions = ""

        # Get LLM config and initialize
        self.llm_config_name = "claude-sonnet-4-20250514"  # Use Claude by default
        self.llm_config = LLMConfigManager.get_config(self.llm_config_name)

        # Initialize LLM
        self.llm = self._create_llm()

        # Initialize tool registry with PTY command executor
        self.tool_registry = AsyncToolRegistry(
            working_directory=self.working_directory,
            session_id=self.context.chat_id,
            websocket_manager=self.websocket_manager,
        )

        # Create LangGraph tools from registry
        self.tools = create_langgraph_tools(self.tool_registry)
        self.tool_node = ToolNode(self.tools)

        # Initialize PTY terminal manager for native terminal support
        self.terminal_manager = PtyTerminalManager(
            websocket_manager=self.websocket_manager,
        )

        # Build the LangGraph workflow
        self.graph = self._build_graph()

        # Create manager wrapper for compatibility
        self.manager = SoftwareDeveloperManager(self)

        # Usage tracking
        self._total_usage = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }

        logger.info(
            f"Software Developer initialized with LangGraph: chat_id={context.chat_id}, "
            f"tools_count={len(self.tools)}"
        )
        logger.info(f"Available tools: {[tool.name for tool in self.tools]}")

    @staticmethod
    def _extract_text_content(content: Any) -> str:
        """Extract text content from Claude's response format.

        Claude can return content as either a string or a list of content blocks.
        This method handles both cases and extracts the text.

        Args:
            content: Content from Claude's response (string or list of blocks).

        Returns:
            Extracted text content as a string.
        """
        if isinstance(content, str):
            return content
        elif isinstance(content, list):
            # Extract text from content blocks
            text = ""
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text += block.get("text", "")
                elif hasattr(block, "text"):
                    text += block.text
            return text
        else:
            return str(content)

    def _create_llm(self) -> ChatAnthropic:
        """Create and configure the Anthropic Claude LLM.

        Returns:
            Configured ChatAnthropic instance with tools bound.
        """
        config = self.llm_config.get("config_list", [{}])[0]

        # Extract configuration
        api_key = config.get("api_key")
        model = config.get("model", "claude-sonnet-4-20250514")
        temperature = config.get("temperature", 0.7)
        max_tokens = config.get("max_tokens", 8000)

        if not api_key:
            raise ValueError("Anthropic API key not found in LLM configuration")

        # Create Claude instance
        llm = ChatAnthropic(
            api_key=api_key,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            streaming=True,  # Enable streaming
        )

        return llm

    def _build_graph(self) -> Any:
        """Build the LangGraph workflow for the software developer agent.

        Returns:
            Compiled StateGraph instance.
        """
        # Create a new graph
        workflow = StateGraph(SoftwareDeveloperState)

        # Add nodes
        workflow.add_node("agent", self._agent_node)
        workflow.add_node("tools", self._tools_node)

        # Add edges
        workflow.add_edge(START, "agent")
        workflow.add_conditional_edges(
            "agent",
            self._should_continue_routing,
            {
                "continue": "tools",
                "end": END,
            },
        )
        workflow.add_edge("tools", "agent")

        # Compile the graph
        compiled_graph = workflow.compile()

        return compiled_graph

    async def _agent_node(self, state: SoftwareDeveloperState) -> dict[str, Any]:
        """Agent node: invokes the LLM with current state.

        Args:
            state: Current agent state.

        Returns:
            Updated state with LLM response.
        """
        try:
            # Check for cancellation
            if self._check_cancellation():
                raise asyncio.CancelledError("Operation cancelled")

            # Prepare messages (safe access)
            messages = state.get("messages", [])

            # Filter out any messages with empty content (Claude requirement)
            # Keep ToolMessages even if empty as they're needed for the conversation flow
            filtered_messages = []
            for msg in messages:
                # Skip messages with no content or empty string content
                if hasattr(msg, "content"):
                    # For ToolMessage, content might be empty which is OK
                    from langchain_core.messages import ToolMessage
                    if isinstance(msg, ToolMessage):
                        filtered_messages.append(msg)
                    elif msg.content and (isinstance(msg.content, str) and msg.content.strip() or isinstance(msg.content, list) and msg.content):
                        filtered_messages.append(msg)
                    # Skip messages with empty content
                else:
                    filtered_messages.append(msg)

            messages = filtered_messages

            # Add system message if this is the first interaction
            if not messages or not isinstance(messages[0], SystemMessage):
                system_prompt = SYSTEM_PROMPT.format(
                    working_directory=self.working_directory,
                    file_location=self.file_location,
                    custom_instructions=self.custom_instructions,
                )
                messages = [SystemMessage(content=system_prompt)] + messages

            # Trim messages if context is too large
            context_window_tokens = state.get("context_window_tokens", 0)
            max_context_tokens = state.get("max_context_tokens", 200000)
            if context_window_tokens > max_context_tokens * 0.8:
                messages = trim_messages_to_fit_context(state)

            # Bind tools to LLM
            llm_with_tools = self.llm.bind_tools(self.tools)
            logger.info(f"Bound {len(self.tools)} tools to LLM")

            # Invoke LLM with streaming
            response = None
            accumulated_content = ""

            # Accumulate chunks to properly collect tool calls
            async for chunk in llm_with_tools.astream(messages):
                # Check cancellation during streaming
                if self._check_cancellation():
                    raise asyncio.CancelledError("Operation cancelled during streaming")

                # Stream content to WebSocket
                if hasattr(chunk, "content") and chunk.content:
                    content_to_add = self._extract_text_content(chunk.content)

                    if content_to_add:
                        accumulated_content += content_to_add
                        await self._stream_message(
                            {
                                "type": "stream",
                                "content": content_to_add,
                                "streaming": True,
                            }
                        )

                # Merge chunks to accumulate tool calls
                if response is None:
                    response = chunk
                else:
                    response = response + chunk

            # Log response details for debugging
            if response:
                logger.info(f"Response type: {type(response)}")
                logger.info(f"Response has tool_calls: {hasattr(response, 'tool_calls')}")
                if hasattr(response, "tool_calls"):
                    logger.info(f"Number of tool_calls: {len(response.tool_calls) if response.tool_calls else 0}")
                    if response.tool_calls:
                        for tc in response.tool_calls:
                            logger.info(f"Tool call: {tc}")

            # Send final message
            if accumulated_content:
                await self._stream_message(
                    {
                        "type": "message",
                        "content": accumulated_content,
                        "streaming": False,
                    }
                )

            # Track token usage
            token_updates = {}
            if hasattr(response, "usage_metadata"):
                usage = response.usage_metadata
                input_tokens = usage.get("input_tokens", 0)
                output_tokens = usage.get("output_tokens", 0)

                token_updates = update_token_counts(
                    state, input_tokens, output_tokens
                )

                # Update internal tracking
                self._total_usage["prompt_tokens"] += input_tokens
                self._total_usage["completion_tokens"] += output_tokens
                self._total_usage["total_tokens"] += (input_tokens + output_tokens)

            # Return ONLY the fields we want to update (don't spread entire state)
            return {
                "messages": [response],
                "iteration_count": state.get("iteration_count", 0) + 1,
                **token_updates,  # Only token fields
            }

        except asyncio.CancelledError:
            logger.info(f"Agent node cancelled for session {self.context.chat_id}")
            raise
        except Exception as e:
            logger.error("Error in agent node", exc_info=True)
            return {"error_message": str(e)}

    async def _tools_node(self, state: SoftwareDeveloperState) -> dict[str, Any]:
        """Tools node: executes tools and returns results.

        Args:
            state: Current agent state.

        Returns:
            Updated state with tool results.
        """
        try:
            # Check for cancellation
            if self._check_cancellation():
                raise asyncio.CancelledError("Operation cancelled")

            # Get the last message (should contain tool calls)
            messages = state.get("messages", [])
            if not messages:
                return {}  # No updates needed

            last_message = messages[-1]

            # Check if there are tool calls to execute
            has_tool_calls = False
            if isinstance(last_message, AIMessage) and hasattr(last_message, "tool_calls"):
                if last_message.tool_calls:
                    has_tool_calls = True
                    logger.info(f"Executing {len(last_message.tool_calls)} tool call(s)")
                    # Notify about tool execution
                    for tool_call in last_message.tool_calls:
                        tool_name = tool_call.get("name", "unknown")
                        logger.info(f"Tool: {tool_name}, Args: {tool_call.get('args', {})}")
                        await self._stream_message(
                            {
                                "type": "tool_use",
                                "tool_name": tool_name,
                                "tool_input": tool_call.get("args", {}),
                                "status": "executing",
                            }
                        )

            if not has_tool_calls:
                logger.info("No tool calls to execute")
                return {}  # No tools to execute

            # Execute the tool node
            logger.info("Invoking LangGraph ToolNode...")
            tool_result = await self.tool_node.ainvoke(state)
            logger.info(f"Tool execution complete, result type: {type(tool_result)}")

            # Notify about tool completion
            for tool_call in last_message.tool_calls:
                await self._stream_message(
                    {
                        "type": "tool_result",
                        "tool_name": tool_call.get("name", "unknown"),
                        "status": "completed",
                    }
                )

            return tool_result

        except asyncio.CancelledError:
            logger.info(f"Tools node cancelled for session {self.context.chat_id}")
            raise
        except Exception as e:
            logger.error("Error in tools node", exc_info=True)
            return {"error_message": str(e)}

    def _should_continue_routing(self, state: SoftwareDeveloperState) -> str:
        """Determine if the agent should continue or end.

        Args:
            state: Current agent state.

        Returns:
            "continue" to use tools, "end" to finish.
        """
        # Check if we should stop
        if not should_continue(state):
            return "end"

        # Check if the last message has tool calls
        messages = state.get("messages", [])
        if not messages:
            return "end"

        last_message = messages[-1]

        # If the last message is an AI message with tool calls, continue
        if isinstance(last_message, AIMessage) and hasattr(last_message, "tool_calls"):
            if last_message.tool_calls:
                return "continue"

        return "end"

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
        self.state["task_id"] = task_id

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

    def provide_input(self, process_id: str | None, user_input: str) -> bool:
        """Provide input to a waiting process from the tool registry.

        Args:
            process_id: Process identifier (or None to use current).
            user_input: The input text to provide to the process.

        Returns:
            True if input was successfully provided, False otherwise.
        """
        return self.tool_registry.provide_input(process_id, user_input)

    def has_pending_input(self) -> bool:
        """Check if any process is waiting for user input.

        Returns:
            True if a process is waiting for input.
        """
        return self.tool_registry.has_pending_input()

    def resize_command_pty(self, process_id: str | None, cols: int, rows: int) -> bool:
        """Resize a command's PTY terminal.

        Args:
            process_id: Process identifier (or None to use current).
            cols: New width in columns.
            rows: New height in rows.

        Returns:
            True if resize was successful.
        """
        target_id = (
            process_id or self.tool_registry.command_executor.get_current_process_id()
        )
        if target_id:
            return self.tool_registry.command_executor.resize_pty(target_id, cols, rows)
        return False

    async def cleanup(self) -> None:
        """Clean up all resources including running processes and terminals."""
        await self.tool_registry.cleanup()
        await self.terminal_manager.cleanup_all()

    # =========================================================================
    # PTY Terminal Methods
    # =========================================================================

    async def start_terminal(
        self,
        cols: int | None = None,
        rows: int | None = None,
        shell: str | None = None,
    ) -> bool:
        """Start a PTY terminal session.

        Args:
            cols: Terminal width in columns.
            rows: Terminal height in rows.
            shell: Shell to use (defaults to system shell).

        Returns:
            True if terminal started successfully.
        """
        terminal = await self.terminal_manager.create_terminal(
            session_id=self.context.chat_id,
            working_directory=self.working_directory,
            cols=cols,
            rows=rows,
            shell=shell,  # nosec B604
        )
        return terminal is not None

    async def write_to_terminal(self, data: str | bytes) -> bool:
        """Write data to the terminal (keyboard input).

        Args:
            data: Data to write (raw keystrokes).

        Returns:
            True if data was written successfully.
        """
        terminal = self.terminal_manager.get_terminal(self.context.chat_id)
        if terminal:
            return await terminal.write(data)
        return False

    async def resize_terminal(self, cols: int, rows: int) -> None:
        """Resize the terminal.

        Args:
            cols: New width in columns.
            rows: New height in rows.
        """
        terminal = self.terminal_manager.get_terminal(self.context.chat_id)
        if terminal:
            await terminal.resize(cols, rows)

    async def terminate_terminal(self, force: bool = False) -> bool:
        """Terminate the terminal session.

        Args:
            force: If True, force kill the terminal.

        Returns:
            True if terminal was terminated.
        """
        return await self.terminal_manager.terminate_terminal(
            self.context.chat_id, force=force
        )

    def is_terminal_running(self) -> bool:
        """Check if the terminal is running.

        Returns:
            True if terminal is active.
        """
        terminal = self.terminal_manager.get_terminal(self.context.chat_id)
        return terminal is not None and terminal.is_running

    def get_terminal_status(self) -> dict[str, Any] | None:
        """Get terminal status information.

        Returns:
            Status dict or None if no terminal.
        """
        terminal = self.terminal_manager.get_terminal(self.context.chat_id)
        if terminal:
            return terminal.get_status()
        return None

    # =========================================================================
    # Conversation Management
    # =========================================================================

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
        self.state["messages"] = []

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            if role == "user":
                self.state["messages"].append(HumanMessage(content=content))
            elif role == "assistant":
                self.state["messages"].append(AIMessage(content=content))

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

    async def _stream_message(self, content: dict[str, Any]) -> None:
        """Stream a message through WebSocket.

        Args:
            content: Message content to send.
        """
        if self.websocket_manager is None:
            return

        try:
            message_data = {
                "role": "assistant",
                "name": "software_developer",
                "content": content,
                "type": content.get("type", "message"),
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
            from src.configs.routes import RoutesConfig
            from src.utilities.api_client import api_client

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

            # await api_client.post(
            #     RoutesConfig.API_UPDATE_OMNI_CHAT,
            #     params={"capability": self.context.collection_name},
            #     data={"filter_criteria": filter_criteria, "document": update_document},
            # )
            # print("Simulated chat history update:", filter_criteria, update_document)

        except Exception as e:
            logger.error(f"Failed to update chat history: {e}")

    async def chat(self, user_message: str) -> str:
        """Process a user message and generate a response using LangGraph.

        This method runs the LangGraph workflow with the user's message.

        Args:
            user_message: The user's message to process.

        Returns:
            The final response text from Claude.

        Raises:
            asyncio.CancelledError: If the operation is cancelled.
        """
        # Check for cancellation
        if self._check_cancellation():
            raise asyncio.CancelledError("Operation cancelled before start")

        try:
            # Add user message to state (ensure messages list exists)
            if "messages" not in self.state:
                self.state["messages"] = []
            self.state["messages"].append(HumanMessage(content=user_message))

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

            # Run the LangGraph workflow
            final_state = None
            async for state_update in self.graph.astream(self.state):
                # Check cancellation during execution
                if self._check_cancellation():
                    raise asyncio.CancelledError("Operation cancelled during execution")

                final_state = state_update

            # Update internal state
            if final_state:
                # Extract the actual state from the graph output
                if isinstance(final_state, dict):
                    # Get the last key (which is the last node executed)
                    last_node = list(final_state.keys())[-1]
                    self.state = final_state[last_node]
                else:
                    self.state = final_state

            # Extract final response
            messages = self.state.get("messages", [])
            if messages:
                last_message = messages[-1]
                if isinstance(last_message, AIMessage):
                    final_response = self._extract_text_content(last_message.content)
                else:
                    final_response = str(last_message)
            else:
                final_response = "No response generated."

            # Save assistant message to database
            await self._update_chat_history(
                {
                    "role": "assistant",
                    "name": "software_developer",
                    "content": final_response,
                    "raw_message": {
                        "role": "assistant",
                        "content": final_response,
                    },
                    "usage": self._total_usage.copy(),
                    "task_id": self.task_id,
                }
            )

            return final_response

        except asyncio.CancelledError:
            logger.info(f"Chat cancelled for session {self.context.chat_id}")
            raise
        except Exception as e:
            logger.error(f"Error in chat: {e}")
            raise

    def reset_conversation(self) -> None:
        """Clear conversation history."""
        self.state = create_initial_state(
            user_id=self.context.user_id,
            chat_id=self.context.chat_id,
            call_id=self.context.call_id,
            capability_id=self.context.capability_id,
            task_id=self.task_id,
            working_directory=self.working_directory,
        )
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
