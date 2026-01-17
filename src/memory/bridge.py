"""SimpleMemBridge - Main interface for the SimpleMem memory system.

This module provides the primary API for integrating SimpleMem with AutoGen
groupchats. It orchestrates all memory components and provides a simple,
non-blocking interface for the rest of the application.

Key Features:
    - Non-blocking message ingestion
    - Automatic background processing
    - Context generation for capabilities
    - Task state management
    - Thread-safe singleton pattern

Usage:
    # Get the bridge instance
    bridge = await SimpleMemBridge.get_instance()

    # Add messages (non-blocking)
    await bridge.add_message(speaker, content, chat_id, task_id, ...)

    # Get context for capability
    context = await bridge.get_capability_context(chat_id, task_id, capability_name, query)

    # Track capability execution
    run = await bridge.start_capability_run(chat_id, task_id, capability_name, query)
    await bridge.complete_capability_run(run, result)
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from loguru import logger

from src.configs.datetime_utils import dt
from src.configs.settings import settings
from src.memory.context_provider import ContextProvider
from src.memory.models import (
    AgentMessage,
    CapabilityRun,
    MemoryConfig,
    TaskItem,
    TaskState,
    TaskStatus,
)
from src.memory.processor import MemoryProcessor
from src.memory.store import SimpleMemStore


class SimpleMemBridge:
    """Main interface for the SimpleMem memory system.

    Provides a unified, non-blocking API for all memory operations.
    Implements singleton pattern for global access.

    Attributes:
        config: Memory configuration.
        store: Storage backend.
        processor: Compression and indexing processor.
        context_provider: Context generation for capabilities.
    """

    _instance: SimpleMemBridge | None = None
    _lock = asyncio.Lock()
    _initialized = False

    def __init__(self, config: MemoryConfig | None = None):
        """Initialize the bridge.

        Note: Use get_instance() for singleton access.

        Args:
            config: Memory configuration. Uses defaults if not provided.
        """
        self.config = config or MemoryConfig(
            db_path=Path(settings.ROOT_DIR) / "memory"
        )
        self.store = SimpleMemStore(self.config)
        self.processor = MemoryProcessor(self.config, self.store)
        self.context_provider = ContextProvider(
            self.store, self.processor, self.config
        )

        # Task state cache (in-memory for fast access)
        self._task_states: dict[str, TaskState] = {}
        self._task_state_lock = asyncio.Lock()

        # Capability run counters per task
        self._capability_counters: dict[str, dict[str, int]] = defaultdict(
            lambda: defaultdict(int)
        )

        # Active capability runs (for tracking in-progress work)
        self._active_runs: dict[str, CapabilityRun] = {}

    @classmethod
    async def get_instance(cls, config: MemoryConfig | None = None) -> SimpleMemBridge:
        """Get or create the singleton instance.

        Args:
            config: Optional configuration (only used on first call).

        Returns:
            The SimpleMemBridge singleton instance.
        """
        if cls._instance is None:
            async with cls._lock:
                if cls._instance is None:
                    cls._instance = cls(config)
                    await cls._instance._initialize()

        return cls._instance

    async def _initialize(self):
        """Initialize async components."""
        if self._initialized:
            return

        # Start background processor
        await self.processor.start()
        self._initialized = True
        logger.info("SimpleMemBridge initialized and ready")

    async def shutdown(self):
        """Shutdown the bridge gracefully."""
        await self.processor.stop()
        self.store.close()
        SimpleMemBridge._instance = None
        self._initialized = False
        logger.info("SimpleMemBridge shutdown complete")

    # =========================================================================
    # Message Ingestion (Non-blocking)
    # =========================================================================

    async def add_message(
        self,
        speaker: str,
        content: str,
        chat_id: str,
        task_id: str | None = None,
        capability_name: str | None = None,
        capability_run_id: str | None = None,
        timestamp: datetime | None = None,
        raw_message: dict[str, Any] | None = None,
    ) -> None:
        """Add a message to memory processing queue.

        This method returns immediately - processing happens in background.

        Args:
            speaker: Agent/user name.
            content: Message content.
            chat_id: Chat session identifier.
            task_id: Task identifier within chat.
            capability_name: Capability name (if from capability).
            capability_run_id: Capability run identifier.
            timestamp: Message timestamp (defaults to now).
            raw_message: Original raw message dict.
        """
        if not content or not content.strip():
            return

        message = AgentMessage(
            speaker=speaker,
            content=content,
            timestamp=timestamp or dt.now(),
            chat_id=chat_id,
            task_id=task_id,
            capability_name=capability_name,
            capability_run_id=capability_run_id,
            raw_message=raw_message,
        )

        await self.processor.add_message(message)

    async def flush_messages(
        self,
        chat_id: str,
        task_id: str | None = None,
    ) -> None:
        """Force flush buffered messages for a chat/task.

        Useful before capability execution to ensure context is current.

        Args:
            chat_id: Chat identifier.
            task_id: Task identifier.
        """
        await self.processor.flush(chat_id, task_id)

    # =========================================================================
    # Task State Management
    # =========================================================================

    async def get_or_create_task_state(
        self,
        chat_id: str,
        task_id: str,
    ) -> TaskState:
        """Get or create task state for a task.

        Args:
            chat_id: Chat identifier.
            task_id: Task identifier.

        Returns:
            TaskState for the task.
        """
        cache_key = f"{chat_id}:{task_id}"

        async with self._task_state_lock:
            # Check cache first
            if cache_key in self._task_states:
                return self._task_states[cache_key]

            # Check database
            state = await self.store.get_task_state(task_id)

            if state is None:
                # Create new state
                state = TaskState(
                    task_id=task_id,
                    chat_id=chat_id,
                )
                await self.store.save_task_state(state)

            self._task_states[cache_key] = state
            return state

    async def set_task_goal(
        self,
        chat_id: str,
        task_id: str,
        goal: str,
    ) -> TaskState:
        """Set the goal for a task.

        Args:
            chat_id: Chat identifier.
            task_id: Task identifier.
            goal: User's goal/request.

        Returns:
            Updated TaskState.
        """
        state = await self.get_or_create_task_state(chat_id, task_id)
        state.goal = goal
        state.updated_at = dt.now()

        await self.store.save_task_state(state)
        return state

    async def set_task_plan(
        self,
        chat_id: str,
        task_id: str,
        plan_items: list[dict[str, Any]],
    ) -> TaskState:
        """Set the plan for a task.

        Args:
            chat_id: Chat identifier.
            task_id: Task identifier.
            plan_items: List of plan item dicts with 'description' key.

        Returns:
            Updated TaskState.
        """
        state = await self.get_or_create_task_state(chat_id, task_id)

        state.plan = [
            TaskItem(
                description=item.get("description", str(item)),
                capability=item.get("capability"),
                sequence=i,
            )
            for i, item in enumerate(plan_items)
        ]
        state.updated_at = dt.now()

        await self.store.save_task_state(state)
        return state

    async def update_task_item_status(
        self,
        chat_id: str,
        task_id: str,
        item_index: int,
        status: TaskStatus,
        result_summary: str | None = None,
    ) -> TaskState:
        """Update status of a plan item.

        Args:
            chat_id: Chat identifier.
            task_id: Task identifier.
            item_index: Index of the plan item.
            status: New status.
            result_summary: Optional result summary.

        Returns:
            Updated TaskState.
        """
        state = await self.get_or_create_task_state(chat_id, task_id)

        if 0 <= item_index < len(state.plan):
            state.plan[item_index].status = status
            if result_summary:
                state.plan[item_index].result_summary = result_summary
            state.updated_at = dt.now()

            await self.store.save_task_state(state)

        return state

    async def add_task_fact(
        self,
        chat_id: str,
        task_id: str,
        key: str,
        value: Any,
    ) -> TaskState:
        """Add a fact to task state.

        Args:
            chat_id: Chat identifier.
            task_id: Task identifier.
            key: Fact key.
            value: Fact value.

        Returns:
            Updated TaskState.
        """
        state = await self.get_or_create_task_state(chat_id, task_id)
        state.facts[key] = value
        state.updated_at = dt.now()

        await self.store.save_task_state(state)
        return state

    # =========================================================================
    # Capability Run Tracking
    # =========================================================================

    async def start_capability_run(
        self,
        chat_id: str,
        task_id: str | None,
        capability_name: str,
        query: str,
    ) -> CapabilityRun:
        """Start tracking a capability run.

        Call this when a capability execution begins.

        Args:
            chat_id: Chat identifier.
            task_id: Task identifier.
            capability_name: Name of the capability.
            query: The query/task for this run.

        Returns:
            CapabilityRun record for tracking.
        """
        # Get sequence number for this capability in this task
        counter_key = f"{chat_id}:{task_id or 'default'}"
        self._capability_counters[counter_key][capability_name] += 1
        sequence = self._capability_counters[counter_key][capability_name]

        run = CapabilityRun(
            capability_name=capability_name,
            query=query,
            sequence=sequence,
            task_id=task_id,
            started_at=dt.now(),
        )

        # Track as active
        self._active_runs[run.id] = run

        # Store in database
        await self.store.add_capability_run(run, chat_id)

        # Update task state if available
        if task_id:
            state = await self.get_or_create_task_state(chat_id, task_id)
            state.add_capability_run(run)
            await self.store.save_task_state(state)

        logger.debug(f"Started {capability_name} run #{sequence} for task {task_id}")
        return run

    async def complete_capability_run(
        self,
        run: CapabilityRun,
        chat_id: str,
        raw_result: str | None = None,
    ) -> CapabilityRun:
        """Complete a capability run with results.

        Call this when capability execution completes.

        Args:
            run: The CapabilityRun to complete.
            chat_id: Chat identifier.
            raw_result: Raw result string to extract info from.

        Returns:
            Updated CapabilityRun with extracted results.
        """
        run.completed_at = dt.now()

        # Extract structured result if raw_result provided
        if raw_result:
            extracted = await self.processor.extract_capability_result(
                capability_name=run.capability_name,
                raw_result=raw_result,
                query=run.query,
                task_id=run.task_id,
            )
            run.result_summary = extracted.result_summary
            run.files_affected = extracted.files_affected
            run.decisions_made = extracted.decisions_made
            run.errors = extracted.errors

        # Update in database
        await self.store.add_capability_run(run, chat_id)

        # Update task state
        if run.task_id:
            state = await self.get_or_create_task_state(chat_id, run.task_id)
            # Update the run in state
            for i, r in enumerate(state.capability_runs):
                if r.id == run.id:
                    state.capability_runs[i] = run
                    break
            await self.store.save_task_state(state)

        # Remove from active
        self._active_runs.pop(run.id, None)

        logger.debug(
            f"Completed {run.capability_name} run #{run.sequence}: {run.result_summary}"
        )
        return run

    async def get_capability_run_count(
        self,
        chat_id: str,
        task_id: str | None,
        capability_name: str,
    ) -> int:
        """Get number of times a capability has been run.

        Args:
            chat_id: Chat identifier.
            task_id: Task identifier.
            capability_name: Capability name.

        Returns:
            Number of runs.
        """
        counter_key = f"{chat_id}:{task_id or 'default'}"
        return self._capability_counters[counter_key].get(capability_name, 0)

    # =========================================================================
    # Context Generation
    # =========================================================================

    async def get_capability_context(
        self,
        chat_id: str,
        task_id: str | None,
        capability_name: str,
        query: str,
    ) -> list[dict[str, Any]]:
        """Get context messages for a capability call.

        This is the main method to call before starting a capability.
        Returns AutoGen-formatted messages for injection.

        Args:
            chat_id: Chat identifier.
            task_id: Task identifier.
            capability_name: Capability to get context for.
            query: The current query/task.

        Returns:
            List of AutoGen message dicts.
        """
        # Ensure pending messages are processed
        await self.flush_messages(chat_id, task_id)

        # Get task state if available
        task_state = None
        if task_id:
            task_state = await self.get_or_create_task_state(chat_id, task_id)

        # Generate context
        context = await self.context_provider.get_capability_context(
            chat_id=chat_id,
            task_id=task_id,
            capability_name=capability_name,
            current_query=query,
            task_state=task_state,
        )

        return context

    async def get_handoff_context(
        self,
        from_capability: str,
        to_capability: str,
        from_run: CapabilityRun,
        chat_id: str,
        task_id: str | None,
    ) -> list[dict[str, Any]]:
        """Get context for capability handoff.

        Args:
            from_capability: Source capability.
            to_capability: Target capability.
            from_run: Completed run from source.
            chat_id: Chat identifier.
            task_id: Task identifier.

        Returns:
            List of AutoGen message dicts.
        """
        return await self.context_provider.get_handoff_context(
            from_capability=from_capability,
            to_capability=to_capability,
            from_run=from_run,
            chat_id=chat_id,
            task_id=task_id,
        )

    async def get_quick_context(
        self,
        chat_id: str,
        task_id: str | None = None,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Get minimal quick context.

        Args:
            chat_id: Chat identifier.
            task_id: Task identifier.
            limit: Maximum items.

        Returns:
            List of AutoGen message dicts.
        """
        return await self.context_provider.get_quick_context(
            chat_id=chat_id,
            task_id=task_id,
            limit=limit,
        )

    # =========================================================================
    # Utility Methods
    # =========================================================================

    async def get_memory_stats(
        self,
        chat_id: str | None = None,
        task_id: str | None = None,
    ) -> dict[str, Any]:
        """Get memory statistics.

        Args:
            chat_id: Optional chat filter.
            task_id: Optional task filter.

        Returns:
            Statistics dictionary.
        """
        count = await self.store.get_memory_count(chat_id, task_id)

        stats = {
            "memory_units": count,
            "active_runs": len(self._active_runs),
            "cached_task_states": len(self._task_states),
        }

        if task_id:
            state = await self.store.get_task_state(task_id)
            if state:
                stats["task_goal"] = state.goal
                stats["plan_items"] = len(state.plan)
                stats["capability_runs"] = len(state.capability_runs)
                stats["facts_count"] = len(state.facts)

        return stats

    async def clear_chat_memory(self, chat_id: str) -> int:
        """Clear all memory for a chat.

        Args:
            chat_id: Chat to clear.

        Returns:
            Number of items deleted.
        """
        # Clear cache entries for this chat
        async with self._task_state_lock:
            keys_to_remove = [
                k for k in self._task_states if k.startswith(f"{chat_id}:")
            ]
            for key in keys_to_remove:
                del self._task_states[key]

        # Clear counter entries
        keys_to_remove = [
            k for k in self._capability_counters if k.startswith(f"{chat_id}:")
        ]
        for key in keys_to_remove:
            del self._capability_counters[key]

        # Clear from database
        deleted = await self.store.clear_chat_memory(chat_id)

        logger.info(f"Cleared {deleted} memory items for chat {chat_id}")
        return deleted

    async def get_task_summary(
        self,
        chat_id: str,
        task_id: str,
    ) -> dict[str, Any]:
        """Get a summary of task execution.

        Args:
            chat_id: Chat identifier.
            task_id: Task identifier.

        Returns:
            Task summary dictionary.
        """
        state = await self.store.get_task_state(task_id)

        if not state:
            return {"task_id": task_id, "status": "not_found"}

        completed_items = sum(
            1 for item in state.plan if item.status == TaskStatus.COMPLETED
        )

        return {
            "task_id": task_id,
            "goal": state.goal,
            "plan_progress": f"{completed_items}/{len(state.plan)}",
            "capability_runs": [
                {
                    "capability": run.capability_name,
                    "sequence": run.sequence,
                    "summary": run.result_summary,
                }
                for run in state.capability_runs
            ],
            "facts": state.facts,
            "decisions": state.decisions,
        }


# Convenience function for getting the bridge
async def get_memory_bridge(config: MemoryConfig | None = None) -> SimpleMemBridge:
    """Get the SimpleMemBridge singleton instance.

    Args:
        config: Optional configuration.

    Returns:
        SimpleMemBridge instance.
    """
    return await SimpleMemBridge.get_instance(config)
