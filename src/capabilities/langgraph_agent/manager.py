"""LangGraph agent manager for production-grade conversational AI.

This module provides a robust, production-ready LangGraph agent implementation with:
- Configurable LLMs
- MongoDB conversation storage
- WebSocket streaming
- Token tracking
- Context window management
- Error handling and recovery
- Conversation resumability
"""

import asyncio
import os
import uuid
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode
from loguru import logger

from src.capabilities.langgraph_agent.prompts import format_system_prompt
from src.capabilities.langgraph_agent.state import (
    AgentState,
    create_initial_state,
    should_continue,
    trim_messages_to_fit_context,
    update_token_counts,
)
from src.capabilities.langgraph_agent.tools import get_tools
from src.configs.datetime_utils import dt
from src.configs.llm_configs_manager import LLMConfigManager
from src.managers.cancellation_token import CancellationToken
from src.utilities.custom_manager import ChatContext


class LangGraphAgentManager:
    """Production-grade LangGraph agent with full async support.

    This class implements a robust conversational AI agent using LangGraph,
    with support for:
    - Configurable LLMs (OpenAI, Anthropic, etc.)
    - MongoDB conversation persistence
    - WebSocket real-time streaming
    - Token usage tracking
    - Context window management
    - Stop/resume capability
    - Error handling and recovery

    Attributes:
        context: ChatContext with session identifiers and configuration.
        websocket_manager: WebSocket manager for real-time streaming.
        cancellation_token: Token for cancelling operations.
        state: Current agent state.
        graph: Compiled LangGraph workflow.
        llm: Language model instance.
        tools: List of available tools.
    """

    def __init__(self, context: ChatContext):
        """Initialize the LangGraph agent manager.

        Args:
            context: ChatContext with all necessary identifiers and configuration.
        """
        self.context = context
        self.websocket_manager = context.manager_kwargs.get("websocket_manager")
        self.cancellation_token: CancellationToken | None = context.cancellation_token
        self.task_id = context.task_id or str(uuid.uuid4())

        # Set up working directory
        self.working_directory = os.path.abspath(
            os.path.join(context.chat_dir, "workspace")
        )
        os.makedirs(self.working_directory, exist_ok=True)

        # Initialize state
        self.state: AgentState = create_initial_state(
            user_id=context.user_id,
            chat_id=context.chat_id,
            call_id=context.call_id,
            capability_id=context.capability_id,
            task_id=self.task_id,
            max_iterations=25,
            max_context_tokens=100000,
        )

        # Get LLM configuration
        self.llm_config_name = context.manager_kwargs.get("llm_config", "default")
        self.llm_config = LLMConfigManager.get_config(self.llm_config_name)

        # Initialize LLM
        self.llm = self._create_llm()

        # Initialize tools
        self.tools = get_tools()
        self.tool_node = ToolNode(self.tools)

        # Build the graph
        self.graph = self._build_graph()

        # Custom instructions
        self.custom_instructions = ""

        # Create manager wrapper for compatibility
        self.manager = LangGraphAgentManagerWrapper(self)

        logger.info(
            f"LangGraph agent initialized: chat_id={context.chat_id}, "
            f"llm_config={self.llm_config_name}"
        )

    def _create_llm(self) -> ChatOpenAI:
        """Create and configure the language model.

        Returns:
            Configured ChatOpenAI instance.
        """
        config = self.llm_config.get("config_list", [{}])[0]

        # Extract configuration
        model = config.get("model", "gpt-4")
        api_key = config.get("api_key")
        temperature = config.get("temperature", 0.7)
        max_tokens = config.get("max_tokens", 4000)
        base_url = config.get("base_url")

        if not api_key:
            raise ValueError(
                f"API key not found in LLM configuration '{self.llm_config_name}'"
            )

        # Create LLM instance
        llm_kwargs = {
            "model": model,
            "api_key": api_key,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "streaming": True,  # Enable streaming for real-time responses
        }

        if base_url:
            llm_kwargs["base_url"] = base_url

        llm = ChatOpenAI(**llm_kwargs)

        # Bind tools to the LLM
        llm_with_tools = llm.bind_tools(self.tools)

        return llm_with_tools

    def _build_graph(self) -> Any:
        """Build the LangGraph workflow.

        Returns:
            Compiled StateGraph instance.
        """
        # Create a new graph
        workflow = StateGraph(AgentState)

        # Add nodes
        workflow.add_node("agent", self._agent_node)
        workflow.add_node("tools", self.tool_node)

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

    async def _agent_node(self, state: AgentState) -> dict[str, Any]:
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

            # Prepare messages
            messages = state["messages"]

            # Add system message if this is the first interaction
            if not messages or not isinstance(messages[0], SystemMessage):
                system_prompt = format_system_prompt(
                    working_directory=self.working_directory,
                    custom_instructions=self.custom_instructions,
                )
                messages = [SystemMessage(content=system_prompt)] + messages

            # Trim messages if context is too large
            if state["context_window_tokens"] > state["max_context_tokens"] * 0.8:
                messages = trim_messages_to_fit_context(state)

            # Invoke LLM with streaming
            response = None
            accumulated_content = ""

            async for chunk in self.llm.astream(messages):
                # Check cancellation during streaming
                if self._check_cancellation():
                    raise asyncio.CancelledError("Operation cancelled during streaming")

                # Stream content to WebSocket
                if hasattr(chunk, "content") and chunk.content:
                    accumulated_content += chunk.content
                    await self._stream_message(
                        {
                            "type": "stream",
                            "content": chunk.content,
                            "streaming": True,
                        }
                    )

                response = chunk

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
            if hasattr(response, "response_metadata"):
                usage = response.response_metadata.get("token_usage", {})
                prompt_tokens = usage.get("prompt_tokens", 0)
                completion_tokens = usage.get("completion_tokens", 0)

                token_updates = update_token_counts(
                    state, prompt_tokens, completion_tokens
                )

                # Update state with token counts
                state.update(token_updates)

            # Increment iteration count
            state["iteration_count"] += 1

            # Return updated state
            return {"messages": [response], **state}

        except asyncio.CancelledError:
            logger.info(f"Agent node cancelled for session {self.context.chat_id}")
            raise
        except Exception as e:
            logger.error(f"Error in agent node: {e}")
            state["error_message"] = str(e)
            return state

    def _should_continue_routing(self, state: AgentState) -> str:
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
        messages = state["messages"]
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
                "name": "langgraph_agent",
                "content": content,
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

            await api_client.post(
                RoutesConfig.API_UPDATE_OMNI_CHAT,
                params={"capability": self.context.collection_name},
                data={"filter_criteria": filter_criteria, "document": update_document},
            )

        except Exception as e:
            logger.error(f"Failed to update chat history: {e}")

    async def chat(self, user_message: str) -> str:
        """Process a user message and generate a response.

        This method runs the LangGraph workflow with the user's message.

        Args:
            user_message: The user's message to process.

        Returns:
            The final response text from the agent.

        Raises:
            asyncio.CancelledError: If the operation is cancelled.
        """
        # Check for cancellation
        if self._check_cancellation():
            raise asyncio.CancelledError("Operation cancelled before start")

        try:
            # Add user message to state
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

            # Run the graph
            final_state = None
            async for state in self.graph.astream(self.state):
                # Check cancellation during execution
                if self._check_cancellation():
                    raise asyncio.CancelledError("Operation cancelled during execution")

                final_state = state

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
                    final_response = last_message.content
                else:
                    final_response = str(last_message)
            else:
                final_response = "No response generated."

            # Save assistant message to database
            await self._update_chat_history(
                {
                    "role": "assistant",
                    "name": "langgraph_agent",
                    "content": final_response,
                    "raw_message": {
                        "role": "assistant",
                        "content": final_response,
                    },
                    "usage": {
                        "total_tokens": self.state.get("total_tokens", 0),
                        "prompt_tokens": self.state.get("prompt_tokens", 0),
                        "completion_tokens": self.state.get("completion_tokens", 0),
                    },
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

    def reset_conversation(self) -> None:
        """Clear conversation history and reset state."""
        self.state = create_initial_state(
            user_id=self.context.user_id,
            chat_id=self.context.chat_id,
            call_id=self.context.call_id,
            capability_id=self.context.capability_id,
            task_id=self.task_id,
        )

    def get_usage_summary(self) -> dict[str, Any]:
        """Get current usage summary.

        Returns:
            Dictionary with token usage statistics.
        """
        return {
            "total_tokens": self.state.get("total_tokens", 0),
            "prompt_tokens": self.state.get("prompt_tokens", 0),
            "completion_tokens": self.state.get("completion_tokens", 0),
            "iteration_count": self.state.get("iteration_count", 0),
        }


class LangGraphAgentManagerWrapper:
    """Wrapper for compatibility with existing capability pattern.

    This provides the expected manager interface (manager.a_initiate_chat, etc.)
    while wrapping the LangGraph agent.
    """

    def __init__(self, agent: LangGraphAgentManager):
        """Initialize the wrapper.

        Args:
            agent: LangGraphAgentManager instance to wrap.
        """
        self.agent = agent
        self._messages: list[dict[str, Any]] = []

    async def a_initiate_chat(
        self,
        _recipient,
        message: str,
        clear_history: bool = False,
        **kwargs,
    ) -> None:
        """Initiate chat with the agent.

        Args:
            _recipient: Ignored, kept for interface compatibility.
            message: Initial user message to process.
            clear_history: Whether to clear conversation history.
            **kwargs: Additional arguments (ignored).
        """
        if clear_history:
            self.agent.reset_conversation()
            self._messages = []

        await self.agent.chat(message)

    def resume(self, messages: list[dict[str, Any]]) -> None:
        """Resume conversation with previous messages.

        Args:
            messages: List of previous messages to restore.
        """
        self._messages = messages
        self.agent.load_history(messages)
