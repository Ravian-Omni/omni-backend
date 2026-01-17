"""Data models for the SimpleMem memory system.

This module defines all data structures used throughout the memory system,
including memory units, task state, capability runs, and configuration.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from src.configs.datetime_utils import dt


class SalienceLevel(str, Enum):
    """Importance level for memory units."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class TaskStatus(str, Enum):
    """Status of a task in the plan."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class MemoryUnit:
    """Atomic, self-contained memory unit with resolved references.

    Represents a single fact extracted from agent conversations with
    coreference resolution and temporal anchoring applied.

    Attributes:
        id: Unique identifier for the memory unit.
        content: Self-contained factual statement.
        entities: Named entities referenced in the content.
        topic: Categorical topic label.
        timestamp: Absolute timestamp (ISO format).
        salience: Importance level (high/medium/low).
        chat_id: Parent chat session identifier.
        task_id: Task identifier within the chat.
        capability_name: Source capability (if from capability).
        capability_run_id: Specific capability run identifier.
        agent_name: Agent that produced the original message.
        sequence: Global sequence number for ordering.
        embedding: Dense vector embedding (set during indexing).
        metadata: Additional flexible metadata.
        consolidated: Whether this unit has been consolidated.
        consolidated_into: ID of parent unit if consolidated.
    """

    content: str
    entities: list[str]
    topic: str
    timestamp: datetime
    salience: SalienceLevel = SalienceLevel.MEDIUM
    chat_id: str = ""
    task_id: str | None = None
    capability_name: str | None = None
    capability_run_id: str | None = None
    agent_name: str | None = None
    sequence: int = 0
    embedding: list[float] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    consolidated: bool = False
    consolidated_into: str | None = None
    id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "id": self.id,
            "content": self.content,
            "entities": self.entities,
            "topic": self.topic,
            "timestamp": (
                self.timestamp.isoformat()
                if isinstance(self.timestamp, datetime)
                else self.timestamp
            ),
            "salience": self.salience.value if isinstance(self.salience, SalienceLevel) else self.salience,
            "chat_id": self.chat_id,
            "task_id": self.task_id,
            "capability_name": self.capability_name,
            "capability_run_id": self.capability_run_id,
            "agent_name": self.agent_name,
            "sequence": self.sequence,
            "embedding": self.embedding,
            "metadata": self.metadata,
            "consolidated": self.consolidated,
            "consolidated_into": self.consolidated_into,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MemoryUnit:
        """Create from dictionary."""
        timestamp = data.get("timestamp")
        if isinstance(timestamp, str):
            timestamp = dt.iso_to_datetime(timestamp)

        salience = data.get("salience", "medium")
        if isinstance(salience, str):
            salience = SalienceLevel(salience)

        return cls(
            id=data.get("id", str(uuid.uuid4())),
            content=data["content"],
            entities=data.get("entities", []),
            topic=data.get("topic", "general"),
            timestamp=timestamp or dt.now(),
            salience=salience,
            chat_id=data.get("chat_id", ""),
            task_id=data.get("task_id"),
            capability_name=data.get("capability_name"),
            capability_run_id=data.get("capability_run_id"),
            agent_name=data.get("agent_name"),
            sequence=data.get("sequence", 0),
            embedding=data.get("embedding"),
            metadata=data.get("metadata", {}),
            consolidated=data.get("consolidated", False),
            consolidated_into=data.get("consolidated_into"),
        )

    def to_context_string(self) -> str:
        """Format as context string for injection."""
        prefix = ""
        if self.capability_name:
            prefix = f"[{self.capability_name}] "
        elif self.agent_name:
            prefix = f"[{self.agent_name}] "

        return f"{prefix}{self.content}"


@dataclass
class TaskItem:
    """Single task item in a plan.

    Attributes:
        id: Unique task identifier.
        description: What needs to be done.
        status: Current task status.
        capability: Capability to execute this task (if known).
        result_summary: Summary of result after completion.
        sequence: Order in the plan.
    """

    description: str
    status: TaskStatus = TaskStatus.PENDING
    capability: str | None = None
    result_summary: str | None = None
    sequence: int = 0
    id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "description": self.description,
            "status": self.status.value,
            "capability": self.capability,
            "result_summary": self.result_summary,
            "sequence": self.sequence,
        }


@dataclass
class CapabilityRun:
    """Record of a single capability execution.

    Attributes:
        id: Unique run identifier.
        capability_name: Name of the capability.
        query: Original query/task.
        result_summary: Summarized result.
        files_affected: List of files created/modified.
        decisions_made: Key decisions during execution.
        errors: Any errors encountered.
        sequence: Order in the task (1st, 2nd call, etc.).
        task_id: Parent task identifier.
        started_at: Start timestamp.
        completed_at: Completion timestamp.
    """

    capability_name: str
    query: str
    sequence: int = 1
    task_id: str | None = None
    result_summary: str | None = None
    files_affected: list[str] = field(default_factory=list)
    decisions_made: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    started_at: datetime = field(default_factory=dt.now)
    completed_at: datetime | None = None
    id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "capability_name": self.capability_name,
            "query": self.query,
            "sequence": self.sequence,
            "task_id": self.task_id,
            "result_summary": self.result_summary,
            "files_affected": self.files_affected,
            "decisions_made": self.decisions_made,
            "errors": self.errors,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }

    def to_context_message(self) -> dict[str, Any]:
        """Format as AutoGen message for context injection."""
        parts = [f"[{self.capability_name} run #{self.sequence}]"]
        parts.append(f"Task: {self.query}")

        if self.result_summary:
            parts.append(f"Result: {self.result_summary}")

        if self.files_affected:
            parts.append(f"Files: {', '.join(self.files_affected)}")

        if self.decisions_made:
            parts.append(f"Decisions: {'; '.join(self.decisions_made)}")

        if self.errors:
            parts.append(f"Errors resolved: {'; '.join(self.errors)}")

        return {
            "role": "user",
            "name": "memory",
            "content": "\n".join(parts),
        }


@dataclass
class TaskState:
    """Complete state for a single task execution.

    Tracks the goal, plan, capability runs, and extracted facts
    for a single user task (identified by task_id).

    Attributes:
        task_id: Unique task identifier.
        chat_id: Parent chat session.
        goal: User's original goal/request.
        plan: List of planned task items.
        capability_runs: Record of all capability executions.
        facts: Extracted key facts (key-value pairs).
        decisions: Key decisions made during execution.
        created_at: Task creation timestamp.
        updated_at: Last update timestamp.
    """

    task_id: str
    chat_id: str
    goal: str | None = None
    plan: list[TaskItem] = field(default_factory=list)
    capability_runs: list[CapabilityRun] = field(default_factory=list)
    facts: dict[str, Any] = field(default_factory=dict)
    decisions: list[dict[str, Any]] = field(default_factory=list)
    created_at: datetime = field(default_factory=dt.now)
    updated_at: datetime = field(default_factory=dt.now)

    def get_plan_status(self) -> str:
        """Get formatted plan status."""
        if not self.plan:
            return ""

        lines = []
        for item in self.plan:
            status_icon = {
                TaskStatus.PENDING: "[ ]",
                TaskStatus.IN_PROGRESS: "[~]",
                TaskStatus.COMPLETED: "[x]",
                TaskStatus.FAILED: "[!]",
                TaskStatus.CANCELLED: "[-]",
            }.get(item.status, "[ ]")
            lines.append(f"{status_icon} {item.description}")

        return "\n".join(lines)

    def get_capability_run_count(self, capability_name: str) -> int:
        """Get number of times a capability has been run."""
        return sum(1 for run in self.capability_runs if run.capability_name == capability_name)

    def get_last_capability_run(self, capability_name: str) -> CapabilityRun | None:
        """Get the most recent run of a capability."""
        runs = [r for r in self.capability_runs if r.capability_name == capability_name]
        return runs[-1] if runs else None

    def add_capability_run(self, run: CapabilityRun) -> None:
        """Add a capability run and update sequence."""
        run.sequence = self.get_capability_run_count(run.capability_name) + 1
        run.task_id = self.task_id
        self.capability_runs.append(run)
        self.updated_at = dt.now()

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "task_id": self.task_id,
            "chat_id": self.chat_id,
            "goal": self.goal,
            "plan": [item.to_dict() for item in self.plan],
            "capability_runs": [run.to_dict() for run in self.capability_runs],
            "facts": self.facts,
            "decisions": self.decisions,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


@dataclass
class CompressionResult:
    """Result of compressing messages into memory units.

    Attributes:
        units: Extracted memory units.
        dropped_count: Number of messages filtered out.
        processing_time_ms: Time taken to process.
    """

    units: list[MemoryUnit]
    dropped_count: int = 0
    processing_time_ms: float = 0.0


@dataclass
class RetrievalQuery:
    """Query for memory retrieval.

    Attributes:
        query: Natural language query.
        chat_id: Filter by chat.
        task_id: Filter by task.
        capability_name: Filter by capability.
        k: Number of results to return.
        include_consolidated: Include consolidated units.
        time_range_hours: Only include units from last N hours.
    """

    query: str
    chat_id: str | None = None
    task_id: str | None = None
    capability_name: str | None = None
    k: int = 10
    include_consolidated: bool = False
    time_range_hours: float | None = None


@dataclass
class MemoryConfig:
    """Configuration for the memory system.

    Attributes:
        db_path: Path to LanceDB storage.
        buffer_size: Messages to buffer before compression.
        compression_threshold: Entropy threshold for filtering.
        consolidation_threshold: Affinity threshold for merging.
        embedding_model: Model name for embeddings.
        embedding_dimension: Dimension of embeddings.
        max_retrieval_k: Maximum retrieval results.
        enable_background_processing: Run compression in background.
        enable_consolidation: Enable memory consolidation.
    """

    db_path: Path = field(default_factory=lambda: Path.home() / ".ravian" / "memory")
    buffer_size: int = 5
    compression_threshold: float = 0.35
    consolidation_threshold: float = 0.85
    embedding_model: str = "text-embedding-3-small"
    embedding_dimension: int = 1536
    max_retrieval_k: int = 20
    enable_background_processing: bool = True
    enable_consolidation: bool = True

    def __post_init__(self):
        """Ensure db_path is a Path object."""
        if isinstance(self.db_path, str):
            self.db_path = Path(self.db_path)


@dataclass
class AgentMessage:
    """Raw agent message before compression.

    Attributes:
        speaker: Agent name.
        content: Message content.
        timestamp: Message timestamp.
        chat_id: Chat session ID.
        task_id: Task ID.
        capability_name: Capability name (if from capability).
        capability_run_id: Capability run ID.
        role: Message role.
        raw_message: Original raw message dict.
    """

    speaker: str
    content: str
    timestamp: datetime
    chat_id: str
    task_id: str | None = None
    capability_name: str | None = None
    capability_run_id: str | None = None
    role: str = "user"
    raw_message: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "speaker": self.speaker,
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
            "chat_id": self.chat_id,
            "task_id": self.task_id,
            "capability_name": self.capability_name,
            "capability_run_id": self.capability_run_id,
            "role": self.role,
        }
