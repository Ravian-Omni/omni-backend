"""Pydantic response format models for structured outputs.

This module defines Pydantic models for validating and structuring
agent responses and tool outputs.
"""

from typing import Any

from pydantic import BaseModel, Field, field_validator


class ToolExecutionResult(BaseModel):
    """Result of a tool execution.

    Attributes:
        tool_name: Name of the tool that was executed.
        success: Whether the tool execution was successful.
        result: The result returned by the tool.
        error_message: Error message if execution failed.
        execution_time_ms: Time taken to execute the tool in milliseconds.
    """

    tool_name: str = Field(..., description="Name of the tool executed")
    success: bool = Field(..., description="Whether execution was successful")
    result: str | None = Field(None, description="Tool execution result")
    error_message: str | None = Field(None, description="Error message if failed")
    execution_time_ms: float | None = Field(
        None, description="Execution time in milliseconds"
    )

    @field_validator("result")
    @classmethod
    def validate_result(cls, value: str | None) -> str | None:
        """Validate that result is present if success is True."""
        return value


class AgentResponse(BaseModel):
    """Structured response from the agent.

    Attributes:
        content: The main response content.
        tool_calls: List of tools called during this response.
        reasoning: Optional reasoning or thought process.
        confidence: Confidence score (0.0 to 1.0).
        requires_followup: Whether this response requires user followup.
        suggested_actions: List of suggested next actions.
    """

    content: str = Field(..., description="Main response content")
    tool_calls: list[str] = Field(
        default=[], description="List of tools called during this response"
    )
    reasoning: str | None = Field(
        None, description="Reasoning or thought process behind the response"
    )
    confidence: float = Field(
        default=1.0, description="Confidence score (0.0 to 1.0)", ge=0.0, le=1.0
    )
    requires_followup: bool = Field(
        default=False, description="Whether this response requires user followup"
    )
    suggested_actions: list[str] = Field(
        default=[], description="List of suggested next actions"
    )


class UsageSummary(BaseModel):
    """Token usage summary for a conversation.

    Attributes:
        total_tokens: Total tokens used.
        prompt_tokens: Tokens used in prompts.
        completion_tokens: Tokens used in completions.
        iteration_count: Number of agent iterations.
        estimated_cost: Estimated cost in USD.
    """

    total_tokens: int = Field(..., description="Total tokens used")
    prompt_tokens: int = Field(..., description="Tokens used in prompts")
    completion_tokens: int = Field(..., description="Tokens used in completions")
    iteration_count: int = Field(default=0, description="Number of agent iterations")
    estimated_cost: float | None = Field(
        None, description="Estimated cost in USD", ge=0.0
    )

    @field_validator("total_tokens")
    @classmethod
    def validate_total(cls, value: int, info) -> int:
        """Validate that total equals prompt + completion."""
        data = info.data
        if "prompt_tokens" in data and "completion_tokens" in data:
            expected = data["prompt_tokens"] + data["completion_tokens"]
            if value != expected:
                raise ValueError(
                    f"Total tokens ({value}) doesn't match prompt + completion ({expected})"
                )
        return value


class ConversationState(BaseModel):
    """Current state of a conversation.

    Attributes:
        chat_id: Chat session identifier.
        user_id: User identifier.
        message_count: Number of messages in conversation.
        is_active: Whether conversation is currently active.
        last_activity: Timestamp of last activity.
        usage: Usage summary for the conversation.
        metadata: Additional metadata.
    """

    chat_id: str = Field(..., description="Chat session identifier")
    user_id: str = Field(..., description="User identifier")
    message_count: int = Field(default=0, description="Number of messages", ge=0)
    is_active: bool = Field(
        default=True, description="Whether conversation is active"
    )
    last_activity: str | None = Field(None, description="Last activity timestamp")
    usage: UsageSummary | None = Field(None, description="Usage summary")
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Additional metadata"
    )


class ErrorResponse(BaseModel):
    """Structured error response.

    Attributes:
        error_code: Error code identifier.
        error_message: Human-readable error message.
        error_details: Additional error details.
        recovery_suggestion: Suggestion for recovering from the error.
        timestamp: When the error occurred.
    """

    error_code: str = Field(..., description="Error code identifier")
    error_message: str = Field(..., description="Human-readable error message")
    error_details: str | None = Field(None, description="Additional error details")
    recovery_suggestion: str | None = Field(
        None, description="Suggestion for recovering from error"
    )
    timestamp: str | None = Field(None, description="When the error occurred")
