"""Context provider for capability groupchats.

This module generates context messages for capability groupchats using
SimpleMem's adaptive query-aware retrieval. Context is formatted as
AutoGen messages for natural injection into groupchat flows.

Features:
    - Adaptive retrieval depth based on query complexity
    - Capability-specific context (handles repeated calls)
    - Task state awareness (goal, plan, progress)
    - Cross-capability context bridging
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from loguru import logger

from src.memory.models import (
    CapabilityRun,
    MemoryConfig,
    MemoryUnit,
    RetrievalQuery,
    TaskState,
)
from src.memory.processor import MemoryProcessor
from src.memory.store import SimpleMemStore


class ContextProvider:
    """Generates context for capability groupchats.

    Uses SimpleMem's adaptive retrieval to provide relevant context
    formatted as AutoGen messages. Handles:
    - First-time capability calls
    - Repeated capability calls (with prior run context)
    - Cross-capability context (what other capabilities did)

    Attributes:
        store: Memory storage backend.
        processor: Memory processor for embeddings.
        config: Memory configuration.
    """

    def __init__(
        self,
        store: SimpleMemStore,
        processor: MemoryProcessor,
        config: MemoryConfig,
    ):
        """Initialize context provider.

        Args:
            store: Memory storage backend.
            processor: Memory processor.
            config: Memory configuration.
        """
        self.store = store
        self.processor = processor
        self.config = config

    async def get_capability_context(
        self,
        chat_id: str,
        task_id: str | None,
        capability_name: str,
        current_query: str,
        task_state: TaskState | None = None,
    ) -> list[dict[str, Any]]:
        """Get context messages for a capability call.

        Builds a single combined context message including:
        1. Current goal and plan status
        2. Previous runs of this capability (if any)
        3. Relevant memory from other capabilities
        4. Recent relevant facts

        Args:
            chat_id: Chat session identifier.
            task_id: Task identifier.
            capability_name: Name of capability being called.
            current_query: The current task/query for this capability.
            task_state: Optional task state for structured context.

        Returns:
            List with single AutoGen-formatted context message, or empty list.
        """
        context_sections = []

        logger.debug(
            f"Building context for {capability_name}: "
            f"chat={chat_id}, task={task_id}, has_state={task_state is not None}"
        )

        # 1. Goal and plan context (if available)
        if task_state:
            goal_section = self._build_goal_section(task_state)
            if goal_section:
                context_sections.append(goal_section)
                logger.debug(f"Added goal context (goal={bool(task_state.goal)})")

        # 2. Check for previous runs of this capability
        previous_runs = await self.store.get_capability_runs(
            chat_id=chat_id,
            task_id=task_id,
            capability_name=capability_name,
        )

        logger.debug(f"Found {len(previous_runs)} previous runs of {capability_name}")

        if previous_runs:
            runs_section = self._build_previous_runs_section(
                capability_name, previous_runs
            )
            if runs_section:
                context_sections.append(runs_section)

        # 3. Get relevant memory through adaptive retrieval
        relevant_memory = await self._retrieve_relevant_context(
            chat_id=chat_id,
            task_id=task_id,
            capability_name=capability_name,
            query=current_query,
        )

        logger.debug(f"Retrieved {len(relevant_memory)} relevant memory units")

        if relevant_memory:
            memory_section = self._build_memory_section(relevant_memory)
            if memory_section:
                context_sections.append(memory_section)

        # 4. Cross-capability context (what other capabilities did)
        if task_id:
            other_runs = await self.store.get_capability_runs(
                chat_id=chat_id,
                task_id=task_id,
            )
            other_runs = [r for r in other_runs if r.capability_name != capability_name]

            logger.debug(f"Found {len(other_runs)} cross-capability runs")

            if other_runs:
                cross_section = self._build_cross_capability_section(other_runs)
                if cross_section:
                    context_sections.append(cross_section)

        # Combine all sections into a single message
        if not context_sections:
            logger.info(f"ContextProvider: No context available for {capability_name}")
            return []

        combined_content = "\n\n---\n\n".join(context_sections)

        logger.info(
            f"ContextProvider: Generated combined context with {len(context_sections)} sections "
            f"for {capability_name}"
        )

        return [{
            "role": "user",
            "name": "context_keeper",
            "content": f"# Context for {capability_name}\n\n{combined_content}",
        }]

    def _build_goal_section(self, task_state: TaskState) -> str | None:
        """Build goal and plan status section.

        Args:
            task_state: Task state with goal and plan.

        Returns:
            Context section string or None.
        """
        parts = []

        if task_state.goal:
            parts.append(f"## Current Goal\n{task_state.goal}")

        plan_status = task_state.get_plan_status()
        if plan_status:
            parts.append(f"## Task Progress\n{plan_status}")

        if task_state.facts:
            facts_text = "\n".join(
                f"- {key}: {value}"
                for key, value in list(task_state.facts.items())[:10]
            )
            parts.append(f"## Key Facts\n{facts_text}")

        if not parts:
            return None

        return "\n\n".join(parts)

    def _build_previous_runs_section(
        self,
        capability_name: str,
        runs: list[CapabilityRun],
    ) -> str | None:
        """Build context section for previous capability runs.

        Args:
            capability_name: Capability name.
            runs: Previous runs of this capability.

        Returns:
            Context section string or None.
        """
        if not runs:
            return None

        parts = [f"## Previous {capability_name} Runs"]

        for run in runs[:5]:  # Limit to last 5 runs
            run_parts = [f"### Run #{run.sequence}"]
            run_parts.append(f"Task: {run.query}")

            if run.result_summary:
                run_parts.append(f"Result: {run.result_summary}")

            if run.files_affected:
                run_parts.append(f"Files: {', '.join(run.files_affected[:5])}")

            if run.decisions_made:
                run_parts.append(f"Decisions: {'; '.join(run.decisions_made[:3])}")

            if run.errors:
                run_parts.append(f"Errors resolved: {'; '.join(run.errors[:3])}")

            parts.append("\n".join(run_parts))

        return "\n\n".join(parts)

    def _build_memory_section(
        self,
        units: list[MemoryUnit],
    ) -> str | None:
        """Build context section from retrieved memory units.

        Args:
            units: Retrieved memory units.

        Returns:
            Context section string or None.
        """
        if not units:
            return None

        parts = ["## Relevant Context"]

        for unit in units:
            parts.append(f"- {unit.to_context_string()}")

        return "\n".join(parts)

    def _build_cross_capability_section(
        self,
        runs: list[CapabilityRun],
    ) -> str | None:
        """Build context section from other capabilities' runs.

        Args:
            runs: Capability runs from other capabilities.

        Returns:
            Context section string or None.
        """
        if not runs:
            return None

        parts = ["## Other Capabilities Executed"]

        for run in runs[:5]:
            run_text = f"- **{run.capability_name}**: {run.result_summary or run.query}"
            if run.files_affected:
                run_text += f" (files: {', '.join(run.files_affected[:3])})"
            parts.append(run_text)

        return "\n".join(parts)

    async def _retrieve_relevant_context(
        self,
        chat_id: str,
        task_id: str | None,
        capability_name: str,
        query: str,
    ) -> list[MemoryUnit]:
        """Retrieve relevant memory using adaptive retrieval.

        Adjusts retrieval depth based on query complexity.

        Args:
            chat_id: Chat identifier.
            task_id: Task identifier.
            capability_name: Current capability.
            query: Current query.

        Returns:
            List of relevant memory units.
        """
        # Estimate query complexity
        complexity = self._estimate_complexity(query)

        # Adjust k based on complexity
        if complexity == "simple":
            k = 5
        elif complexity == "medium":
            k = 10
        else:  # complex
            k = 15

        # Build retrieval query
        retrieval_query = RetrievalQuery(
            query=f"{capability_name}: {query}",
            chat_id=chat_id,
            task_id=task_id,
            k=k,
            include_consolidated=False,
            time_range_hours=24.0,  # Last 24 hours
        )

        # Get query embedding for semantic search
        query_embedding = await self.processor.get_embedding(retrieval_query.query)

        # Perform search
        results = await self.store.search(
            query=retrieval_query,
            query_embedding=query_embedding,
        )

        return results

    def _estimate_complexity(self, query: str) -> str:
        """Estimate query complexity for adaptive retrieval.

        Args:
            query: Query string.

        Returns:
            Complexity level: "simple", "medium", or "complex".
        """
        # Simple heuristics for complexity estimation
        query_lower = query.lower()

        # Complex indicators
        complex_indicators = [
            "multiple", "several", "all", "each", "every",
            "integrate", "combine", "connect", "based on",
            "previous", "earlier", "before", "after",
            "compare", "analyze", "review",
        ]

        # Simple indicators
        simple_indicators = [
            "create", "make", "add", "remove", "delete",
            "fix", "update", "change", "set",
        ]

        complex_count = sum(1 for ind in complex_indicators if ind in query_lower)
        simple_count = sum(1 for ind in simple_indicators if ind in query_lower)

        # Word count also matters
        word_count = len(query.split())

        if complex_count >= 2 or word_count > 50:
            return "complex"
        elif simple_count >= 2 or word_count < 15:
            return "simple"
        else:
            return "medium"

    async def get_handoff_context(
        self,
        from_capability: str,
        to_capability: str,
        from_run: CapabilityRun,
        chat_id: str,
        task_id: str | None,
    ) -> list[dict[str, Any]]:
        """Get context for handoff between capabilities.

        Used when one capability needs to continue work from another.
        Returns a single combined context message.

        Args:
            from_capability: Source capability name.
            to_capability: Target capability name.
            from_run: The completed run from source capability.
            chat_id: Chat identifier.
            task_id: Task identifier.

        Returns:
            List with single context message.
        """
        sections = []

        # Handoff summary
        handoff_section = f"""## Handoff from {from_capability}

**What was done:** {from_run.result_summary or from_run.query}

**Files affected:** {', '.join(from_run.files_affected) if from_run.files_affected else 'None'}

**Decisions made:** {'; '.join(from_run.decisions_made) if from_run.decisions_made else 'None'}

**Continue with:** {to_capability}"""
        sections.append(handoff_section)

        # Get recent memory from source capability
        retrieval_query = RetrievalQuery(
            query=f"{from_capability} {from_run.query}",
            chat_id=chat_id,
            task_id=task_id,
            capability_name=from_capability,
            k=5,
        )

        query_embedding = await self.processor.get_embedding(retrieval_query.query)
        recent_memory = await self.store.search(
            query=retrieval_query,
            query_embedding=query_embedding,
        )

        if recent_memory:
            memory_section = self._build_memory_section(recent_memory)
            if memory_section:
                sections.append(memory_section)

        return [{
            "role": "user",
            "name": "context_keeper",
            "content": f"# Handoff Context\n\n" + "\n\n---\n\n".join(sections),
        }]

    async def get_continuation_context(
        self,
        chat_id: str,
        task_id: str,
        capability_name: str,
    ) -> list[dict[str, Any]]:
        """Get full context for continuing a task after interruption.

        Reconstructs the complete state for resuming work.
        Returns a single combined context message.

        Args:
            chat_id: Chat identifier.
            task_id: Task identifier.
            capability_name: Capability to continue in.

        Returns:
            List with single context message.
        """
        sections = []

        # Get task state
        task_state = await self.store.get_task_state(task_id)

        if task_state:
            # Full goal and plan context
            goal_section = self._build_goal_section(task_state)
            if goal_section:
                sections.append(goal_section)

            # All previous runs summary
            if task_state.capability_runs:
                runs_section = self._build_runs_summary_section(task_state.capability_runs)
                if runs_section:
                    sections.append(runs_section)

        # Get all recent memory for this task
        retrieval_query = RetrievalQuery(
            query=f"task {task_id} continuation",
            chat_id=chat_id,
            task_id=task_id,
            k=15,
        )

        query_embedding = await self.processor.get_embedding(retrieval_query.query)
        all_memory = await self.store.search(
            query=retrieval_query,
            query_embedding=query_embedding,
        )

        if all_memory:
            memory_section = self._build_memory_section(all_memory)
            if memory_section:
                sections.append(memory_section)

        if not sections:
            return []

        return [{
            "role": "user",
            "name": "context_keeper",
            "content": f"# Continuation Context for {capability_name}\n\n" + "\n\n---\n\n".join(sections),
        }]

    def _build_runs_summary_section(
        self,
        runs: list[CapabilityRun],
    ) -> str | None:
        """Build summary section of all capability runs.

        Args:
            runs: All capability runs.

        Returns:
            Summary section string or None.
        """
        if not runs:
            return None

        parts = ["## Execution History"]

        # Group by capability
        by_capability: dict[str, list[CapabilityRun]] = {}
        for run in runs:
            if run.capability_name not in by_capability:
                by_capability[run.capability_name] = []
            by_capability[run.capability_name].append(run)

        for cap_name, cap_runs in by_capability.items():
            parts.append(f"\n### {cap_name} ({len(cap_runs)} runs)")
            for run in cap_runs:
                status = "completed" if run.completed_at else "in progress"
                parts.append(
                    f"- Run #{run.sequence}: {run.result_summary or run.query} [{status}]"
                )

        return "\n".join(parts)

    async def get_quick_context(
        self,
        chat_id: str,
        task_id: str | None,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Get minimal quick context for simple operations.

        Returns just the most recent memory units without
        full retrieval pipeline.

        Args:
            chat_id: Chat identifier.
            task_id: Task identifier.
            limit: Maximum units to include.

        Returns:
            List of context messages.
        """
        recent = await self.store.get_recent_units(
            chat_id=chat_id,
            task_id=task_id,
            limit=limit,
        )

        if not recent:
            return []

        memory_section = self._build_memory_section(recent)
        if not memory_section:
            return []

        return [{
            "role": "user",
            "name": "context_keeper",
            "content": f"# Recent Context\n\n{memory_section}",
        }]
