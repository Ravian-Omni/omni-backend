"""LangGraph Agent Capability.

A production-grade conversational AI agent built with LangGraph, featuring:
- Configurable LLMs (OpenAI, Anthropic, etc.)
- MongoDB conversation persistence
- WebSocket real-time streaming
- Token usage tracking
- Context window management
- Stop/resume capability
- Error handling and recovery
- Easy tool integration

Usage:
    from src.capabilities.langgraph_agent import LangGraphAgentManager
    from src.utilities.custom_manager import ChatContext

    context = ChatContext(
        user_id="user123",
        chat_id="chat456",
        ...
    )

    agent = LangGraphAgentManager(context)
    response = await agent.chat("Hello, how can you help me?")
"""

from src.capabilities.langgraph_agent.manager import (
    LangGraphAgentManager,
    LangGraphAgentManagerWrapper,
)
from src.capabilities.langgraph_agent.response_format import (
    AgentResponse,
    ConversationState,
    ErrorResponse,
    ToolExecutionResult,
    UsageSummary,
)
from src.capabilities.langgraph_agent.state import AgentState, create_initial_state
from src.capabilities.langgraph_agent.tools import get_tool_names, get_tools

__all__ = [
    # Main manager
    "LangGraphAgentManager",
    "LangGraphAgentManagerWrapper",
    # State management
    "AgentState",
    "create_initial_state",
    # Tools
    "get_tools",
    "get_tool_names",
    # Response formats
    "AgentResponse",
    "ConversationState",
    "ErrorResponse",
    "ToolExecutionResult",
    "UsageSummary",
]

__version__ = "1.0.0"
