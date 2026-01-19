"""Context provider for capability groupchats.

This module generates context messages for capability groupchats using
SimpleMem's adaptive query-aware retrieval. Context is formatted as
AutoGen messages for natural injection into groupchat flows.

Follows the SimpleMem paper (arxiv:2601.02553) approach:
    - Semantic structured compression into compact facts
    - Dependency-aware context for subtask chains
    - Adaptive retrieval based on query complexity
    - No noise - only relevant factual information
"""

from __future__ import annotations

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
    """Generates dependency-aware context for capability groupchats.

    Implements SimpleMem's approach to context generation:
    - Retrieves facts from predecessor capabilities (dependency chain)
    - Filters noise and provides only relevant factual information
    - No verbose metadata (no goal/progress sections)
    - Compact, self-contained facts for efficient context use

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
        task_id: str | None,  # noqa: ARG002
        capability_name: str,
        current_query: str,
        task_state: TaskState | None = None,  # noqa: ARG002
    ) -> list[dict[str, Any]]:
        """Get query-relevant context for a capability call.

        Retrieves only facts relevant to the current query using:
        1. Semantic similarity search (chat-wide)
        2. Lexical matching
        3. Facts from other capabilities in the chat

        No metadata, no task descriptions - just relevant facts.

        Args:
            chat_id: Chat session identifier.
            task_id: Task identifier (unused - search is chat-wide).
            capability_name: Name of capability being called.
            current_query: The current task/query for this capability.
            task_state: Optional task state (unused).

        Returns:
            List with single AutoGen-formatted context message, or empty list.
        """
        logger.debug(
            f"Retrieving query-relevant context for {capability_name}: "
            f"chat={chat_id}, query={current_query[:50]}..."
        )

        # Get query-relevant memory via semantic + lexical search (chat-wide)
        # This filters facts by relevance to the current query
        all_facts = await self._retrieve_query_relevant_context(
            chat_id=chat_id,
            query=current_query,
        )

        if not all_facts:
            logger.info(
                f"ContextProvider: No relevant context found for {capability_name}"
            )
            return []

        # Format facts as compact content
        content = self._format_facts_from_units(all_facts)

        if not content:
            return []

        logger.info(
            f"ContextProvider: Retrieved {len(all_facts)} relevant facts for {capability_name}"
        )

        return [
            {
                "role": "user",
                "name": "context_keeper",
                "content": content,
            }
        ]

    async def _get_all_chat_facts(
        self,
        chat_id: str,
        limit: int = 100,
    ) -> list[MemoryUnit]:
        """Get all facts from the chat.

        Simply retrieves all memory units for the chat without filtering
        by capability_run_id (many units have NULL capability_run_id).

        Args:
            chat_id: Chat identifier.
            limit: Maximum units to return.

        Returns:
            List of all memory units in the chat.
        """
        return await self.store.get_recent_units(
            chat_id=chat_id,
            task_id=None,  # Chat-wide
            limit=limit,
        )

    def _format_facts_from_units(self, units: list[MemoryUnit]) -> str:
        """Format memory units as compact factual statements.

        Just the facts - no headers, no metadata, no grouping.

        Args:
            units: Memory units to format.

        Returns:
            Formatted facts as bullet points.
        """
        if not units:
            return ""

        # Deduplicate by content (in case same fact appears multiple times)
        seen_content: set[str] = set()
        facts: list[str] = []

        for unit in units:
            content_key = unit.content.strip().lower()[:100]
            if content_key not in seen_content:
                seen_content.add(content_key)
                facts.append(f"- {unit.content}")

        return "\n".join(facts)

    async def _retrieve_query_relevant_context(
        self,
        chat_id: str,
        query: str,
    ) -> list[MemoryUnit]:
        """Retrieve query-relevant memory using adaptive retrieval.

        Searches across the entire chat (not task-specific) to find
        relevant facts using semantic + lexical search.

        Args:
            chat_id: Chat identifier.
            query: Current query.

        Returns:
            List of relevant memory units.
        """
        # Estimate query complexity for adaptive k
        complexity = self._estimate_complexity(query)

        if complexity == "simple":
            k = 5
        elif complexity == "medium":
            k = 10
        else:  # complex
            k = 15

        # Build retrieval query - chat-wide search (task_id=None)
        retrieval_query = RetrievalQuery(
            query=query,
            chat_id=chat_id,
            task_id=None,  # Search entire chat, not just current task
            k=k,
            include_consolidated=False,
            time_range_hours=None,  # No time limit - search all history
        )

        # Get query embedding for semantic search
        query_embedding = await self.processor.get_embedding(query)

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
        query_lower = query.lower()

        # Complex indicators
        complex_indicators = [
            "multiple",
            "several",
            "all",
            "each",
            "every",
            "integrate",
            "combine",
            "connect",
            "based on",
            "previous",
            "earlier",
            "before",
            "after",
            "compare",
            "analyze",
            "review",
            "comprehensive",
            "summarize",
            "report",
        ]

        # Simple indicators
        simple_indicators = [
            "create",
            "make",
            "add",
            "remove",
            "delete",
            "fix",
            "update",
            "change",
            "set",
            "get",
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
        """Get context for explicit handoff between capabilities.

        Returns just the facts from the source capability.

        Args:
            from_capability: Source capability name.
            to_capability: Target capability name.
            from_run: The completed run from source capability.
            chat_id: Chat identifier.
            task_id: Task identifier.

        Returns:
            List with single context message containing facts.
        """
        memory_units = await self.store.get_capability_memory_units(
            chat_id=chat_id,
            task_id=task_id,
            capability_name=from_capability,
            capability_run_id=from_run.id,
            limit=100,
        )

        if memory_units:
            content = self._format_facts_from_units(memory_units)
        elif from_run.result_summary:
            content = f"- {from_run.result_summary}"
        else:
            return []

        if not content:
            return []

        return [
            {
                "role": "user",
                "name": "context_keeper",
                "content": content,
            }
        ]

    async def get_continuation_context(
        self,
        chat_id: str,
        task_id: str,
        capability_name: str,
    ) -> list[dict[str, Any]]:
        """Get context for continuing a task after interruption.

        Returns all relevant facts for the task.

        Args:
            chat_id: Chat identifier.
            task_id: Task identifier.
            capability_name: Capability to continue in.

        Returns:
            List with single context message containing facts.
        """
        # Get all memory for this task
        retrieval_query = RetrievalQuery(
            query=f"task {task_id}",
            chat_id=chat_id,
            task_id=task_id,
            k=30,
        )

        query_embedding = await self.processor.get_embedding(retrieval_query.query)
        all_memory = await self.store.search(
            query=retrieval_query,
            query_embedding=query_embedding,
        )

        if not all_memory:
            return []

        content = self._format_facts_from_units(all_memory)
        if not content:
            return []

        return [
            {
                "role": "user",
                "name": "context_keeper",
                "content": content,
            }
        ]

    async def get_quick_context(
        self,
        chat_id: str,
        task_id: str | None,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Get minimal quick context.

        Returns just the most recent facts.

        Args:
            chat_id: Chat identifier.
            task_id: Task identifier.
            limit: Maximum units to include.

        Returns:
            List with context message containing facts.
        """
        recent = await self.store.get_recent_units(
            chat_id=chat_id,
            task_id=task_id,
            limit=limit,
        )

        if not recent:
            return []

        content = self._format_facts_from_units(recent)
        if not content:
            return []

        return [
            {
                "role": "user",
                "name": "context_keeper",
                "content": content,
            }
        ]
