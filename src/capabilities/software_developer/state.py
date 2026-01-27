"""LangGraph state definition for Software Developer capability.

This module defines the state structure for the LangGraph-powered software developer agent.
"""

from typing import Annotated, Any, TypedDict

from langgraph.graph.message import add_messages


class SoftwareDeveloperState(TypedDict):
    """State structure for the Software Developer LangGraph agent.

    Attributes:
        messages: List of messages in the conversation (auto-accumulated by LangGraph).
        user_id: Unique identifier for the user.
        chat_id: Unique identifier for the chat session.
        call_id: Unique identifier for the current API call.
        capability_id: Unique identifier for the capability instance.
        task_id: Unique identifier for the current task.
        total_tokens: Total tokens used in the conversation.
        prompt_tokens: Total prompt tokens used.
        completion_tokens: Total completion tokens used.
        iteration_count: Number of agent loop iterations.
        max_iterations: Maximum allowed iterations before stopping.
        error_message: Error message if any error occurred.
        final_response: The final response to return to the user.
        context_window_tokens: Current context window size in tokens.
        max_context_tokens: Maximum allowed context tokens (configurable).
        working_directory: Working directory for file operations.
        metadata: Additional metadata for the session.
    """

    # Messages list - automatically accumulated by LangGraph
    messages: Annotated[list[Any], add_messages]

    # Session identifiers
    user_id: str
    chat_id: str
    call_id: str
    capability_id: str
    task_id: str

    # Token tracking
    total_tokens: int
    prompt_tokens: int
    completion_tokens: int

    # Iteration tracking
    iteration_count: int
    max_iterations: int

    # Error handling
    error_message: str | None

    # Final response
    final_response: str | None

    # Context management
    context_window_tokens: int
    max_context_tokens: int

    # Working directory
    working_directory: str

    # Additional metadata
    metadata: dict[str, Any]


def create_initial_state(
    user_id: str,
    chat_id: str,
    call_id: str,
    capability_id: str,
    task_id: str,
    working_directory: str,
    max_iterations: int = 25,
    max_context_tokens: int = 200000,
) -> SoftwareDeveloperState:
    """Create initial state for a new software developer session.

    Args:
        user_id: User identifier.
        chat_id: Chat session identifier.
        call_id: API call identifier.
        capability_id: Capability instance identifier.
        task_id: Task identifier.
        working_directory: Working directory for file operations.
        max_iterations: Maximum agent loop iterations. Defaults to 25.
        max_context_tokens: Maximum context window size. Defaults to 200000 for Claude.

    Returns:
        Initialized SoftwareDeveloperState with default values.
    """
    return {
        "messages": [],
        "user_id": user_id,
        "chat_id": chat_id,
        "call_id": call_id,
        "capability_id": capability_id,
        "task_id": task_id,
        "total_tokens": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "iteration_count": 0,
        "max_iterations": max_iterations,
        "error_message": None,
        "final_response": None,
        "context_window_tokens": 0,
        "max_context_tokens": max_context_tokens,
        "working_directory": working_directory,
        "metadata": {},
    }


def update_token_counts(
    state: SoftwareDeveloperState,
    input_tokens: int,
    output_tokens: int,
) -> dict[str, int]:
    """Update token counts in the state.

    Args:
        state: Current agent state.
        input_tokens: Tokens used in the input/prompt.
        output_tokens: Tokens generated in output/completion.

    Returns:
        Dictionary with updated token counts.
    """
    # Use .get() for safe access in case state fields aren't initialized yet
    total = input_tokens + output_tokens
    return {
        "total_tokens": state.get("total_tokens", 0) + total,
        "prompt_tokens": state.get("prompt_tokens", 0) + input_tokens,
        "completion_tokens": state.get("completion_tokens", 0) + output_tokens,
        "context_window_tokens": state.get("context_window_tokens", 0) + total,
    }


def should_continue(state: SoftwareDeveloperState) -> bool:
    """Check if the agent should continue processing.

    Args:
        state: Current agent state.

    Returns:
        True if agent should continue, False if it should stop.
    """
    # Use .get() for safe access in case state fields aren't initialized yet
    # Stop if max iterations reached
    iteration_count = state.get("iteration_count", 0)
    max_iterations = state.get("max_iterations", 25)
    if iteration_count >= max_iterations:
        return False

    # Stop if context window exceeded
    context_window_tokens = state.get("context_window_tokens", 0)
    max_context_tokens = state.get("max_context_tokens", 200000)
    if context_window_tokens >= max_context_tokens:
        return False

    # Stop if error occurred
    if state.get("error_message"):
        return False

    # Stop if final response is set
    if state.get("final_response"):
        return False

    return True


def trim_messages_to_fit_context(
    state: SoftwareDeveloperState,
    keep_last_n: int = 30,
) -> list[Any]:
    """Trim messages to fit within context window.

    Keeps the system message and the most recent N messages.

    Args:
        state: Current agent state.
        keep_last_n: Number of recent messages to keep. Defaults to 30.

    Returns:
        Trimmed list of messages.
    """
    # Use .get() for safe access
    messages = state.get("messages", [])

    if len(messages) <= keep_last_n + 1:  # +1 for system message
        return messages

    # Always keep system message (first message) and last N messages
    return [messages[0]] + messages[-(keep_last_n):]
