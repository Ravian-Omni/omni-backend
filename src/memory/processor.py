"""Async memory processor for compression and indexing.

This module implements the semantic structured compression pipeline from SimpleMem,
adapted for multi-agent conversations. It runs as a background worker that:
1. Buffers incoming messages
2. Compresses them into atomic memory units
3. Generates embeddings
4. Stores in the memory store

All operations are non-blocking and don't impact the main execution flow.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections import defaultdict
from datetime import datetime
from typing import Any, Callable

from loguru import logger

from src.configs.datetime_utils import dt
from src.configs.llm_configs_manager import LLMConfigManager
from src.memory.models import (
    AgentMessage,
    CompressionResult,
    MemoryConfig,
    MemoryUnit,
    SalienceLevel,
    CapabilityRun,
)
from src.memory.store import SimpleMemStore


class MemoryProcessor:
    """Async processor for memory compression and indexing.

    Implements SimpleMem's semantic structured compression:
    - Entropy-aware filtering
    - Coreference resolution
    - Temporal anchoring
    - Entity extraction
    - Embedding generation

    Runs as a background worker with non-blocking message ingestion.

    Attributes:
        config: Memory system configuration.
        store: Storage backend.
        _buffer: Per-task message buffers.
        _sequence_counter: Global sequence counter.
        _processing_task: Background processing task.
        _shutdown: Shutdown flag.
    """

    def __init__(
        self,
        config: MemoryConfig,
        store: SimpleMemStore,
        embedding_func: Callable[[str], list[float]] | None = None,
    ):
        """Initialize the processor.

        Args:
            config: Memory configuration.
            store: Storage backend.
            embedding_func: Optional custom embedding function.
        """
        self.config = config
        self.store = store
        self._embedding_func = embedding_func

        # Per-chat/task message buffers
        self._buffer: dict[str, list[AgentMessage]] = defaultdict(list)
        self._buffer_lock = asyncio.Lock()

        # Global sequence counter for ordering
        self._sequence_counter = 0
        self._sequence_lock = asyncio.Lock()

        # Background processing
        self._processing_queue: asyncio.Queue[tuple[str, str]] = asyncio.Queue()
        self._processing_task: asyncio.Task | None = None
        self._shutdown = False

        # LLM client for compression (lazy init)
        self._llm_client = None

        # Embedding cache to avoid redundant API calls
        self._embedding_cache: dict[str, list[float]] = {}
        self._cache_lock = asyncio.Lock()

        logger.info("MemoryProcessor initialized")

    async def start(self):
        """Start background processing worker."""
        if self._processing_task is None or self._processing_task.done():
            self._shutdown = False
            self._processing_task = asyncio.create_task(self._process_loop())
            logger.info("MemoryProcessor background worker started")

    async def stop(self):
        """Stop background processing gracefully."""
        self._shutdown = True

        # Process remaining items
        if self._processing_task:
            # Signal completion
            await self._processing_queue.put(("__SHUTDOWN__", "__SHUTDOWN__"))

            try:
                await asyncio.wait_for(self._processing_task, timeout=10.0)
            except asyncio.TimeoutError:
                self._processing_task.cancel()
                try:
                    await self._processing_task
                except asyncio.CancelledError:
                    pass

        logger.info("MemoryProcessor stopped")

    async def add_message(self, message: AgentMessage) -> None:
        """Add a message to the processing buffer.

        This method returns immediately - processing happens in background.

        Args:
            message: Agent message to process.
        """
        buffer_key = f"{message.chat_id}:{message.task_id or 'default'}"

        async with self._buffer_lock:
            self._buffer[buffer_key].append(message)
            buffer_size = len(self._buffer[buffer_key])

        # Trigger processing if buffer threshold reached
        if buffer_size >= self.config.buffer_size:
            await self._processing_queue.put((message.chat_id, message.task_id or "default"))

    async def flush(self, chat_id: str, task_id: str | None = None) -> None:
        """Force flush buffer for a chat/task.

        Args:
            chat_id: Chat identifier.
            task_id: Optional task identifier.
        """
        await self._processing_queue.put((chat_id, task_id or "default"))

    async def _process_loop(self):
        """Background processing loop."""
        while not self._shutdown:
            try:
                # Wait for processing signal
                chat_id, task_id = await asyncio.wait_for(
                    self._processing_queue.get(),
                    timeout=5.0,
                )

                if chat_id == "__SHUTDOWN__":
                    break

                # Process the buffer
                await self._process_buffer(chat_id, task_id)

            except asyncio.TimeoutError:
                # Check for any stale buffers to process
                await self._process_stale_buffers()

            except asyncio.CancelledError:
                break

            except Exception as e:
                logger.error(f"Error in processing loop: {e}")
                await asyncio.sleep(1.0)

        # Final flush on shutdown
        await self._flush_all_buffers()

    async def _process_stale_buffers(self):
        """Process buffers that have been waiting too long."""
        async with self._buffer_lock:
            keys_to_process = []
            for key, messages in self._buffer.items():
                if messages:
                    # Process if buffer has any messages (opportunistic)
                    keys_to_process.append(key)

        for key in keys_to_process:
            parts = key.split(":", 1)
            chat_id = parts[0]
            task_id = parts[1] if len(parts) > 1 else "default"
            await self._process_buffer(chat_id, task_id)

    async def _flush_all_buffers(self):
        """Flush all remaining buffers on shutdown."""
        async with self._buffer_lock:
            keys = list(self._buffer.keys())

        for key in keys:
            parts = key.split(":", 1)
            chat_id = parts[0]
            task_id = parts[1] if len(parts) > 1 else "default"
            await self._process_buffer(chat_id, task_id)

    async def _process_buffer(self, chat_id: str, task_id: str) -> CompressionResult:
        """Process buffered messages for a chat/task.

        Args:
            chat_id: Chat identifier.
            task_id: Task identifier.

        Returns:
            Compression result with extracted units.
        """
        buffer_key = f"{chat_id}:{task_id}"
        start_time = time.time()

        # Get and clear buffer atomically
        async with self._buffer_lock:
            messages = self._buffer.pop(buffer_key, [])

        if not messages:
            return CompressionResult(units=[], dropped_count=0)

        logger.debug(f"Processing {len(messages)} messages for {buffer_key}")

        try:
            # Stage 1: Semantic structured compression
            compressed = await self._compress_messages(messages, chat_id, task_id)

            # Stage 2: Generate embeddings
            if compressed.units:
                await self._add_embeddings(compressed.units)

            # Stage 3: Store in database
            if compressed.units:
                await self.store.add_memory_units(compressed.units)

            processing_time = (time.time() - start_time) * 1000
            compressed.processing_time_ms = processing_time

            logger.debug(
                f"Processed {len(messages)} messages → {len(compressed.units)} units "
                f"({compressed.dropped_count} dropped) in {processing_time:.1f}ms"
            )

            return compressed

        except Exception as e:
            logger.error(f"Error processing buffer {buffer_key}: {e}")
            # Re-add messages to buffer on failure
            async with self._buffer_lock:
                self._buffer[buffer_key] = messages + self._buffer.get(buffer_key, [])
            raise

    async def _compress_messages(
        self,
        messages: list[AgentMessage],
        chat_id: str,
        task_id: str,
    ) -> CompressionResult:
        """Compress messages into atomic memory units.

        Applies SimpleMem's semantic structured compression:
        1. Entropy-aware filtering
        2. Coreference resolution
        3. Temporal anchoring
        4. Entity extraction

        Args:
            messages: Messages to compress.
            chat_id: Chat identifier.
            task_id: Task identifier.

        Returns:
            Compression result with memory units.
        """
        # Filter out low-value messages
        filtered_messages = self._entropy_filter(messages)
        dropped_count = len(messages) - len(filtered_messages)

        if not filtered_messages:
            return CompressionResult(units=[], dropped_count=dropped_count)

        # Format messages for LLM compression
        formatted = self._format_messages_for_compression(filtered_messages)

        # Use LLM to extract atomic facts
        try:
            facts = await self._extract_facts_with_llm(formatted, messages[0].timestamp)
        except Exception as e:
            logger.warning(f"LLM extraction failed, using fallback: {e}")
            facts = self._fallback_extraction(filtered_messages)

        # Convert facts to MemoryUnits
        units = []
        for fact in facts:
            async with self._sequence_lock:
                sequence = self._sequence_counter
                self._sequence_counter += 1

            # Find source message for metadata
            source_msg = self._find_source_message(fact, filtered_messages)

            unit = MemoryUnit(
                content=fact["content"],
                entities=fact.get("entities", []),
                topic=fact.get("topic", "general"),
                timestamp=dt.now(),
                salience=SalienceLevel(fact.get("salience", "medium")),
                chat_id=chat_id,
                task_id=task_id if task_id != "default" else None,
                capability_name=source_msg.capability_name if source_msg else None,
                capability_run_id=source_msg.capability_run_id if source_msg else None,
                agent_name=source_msg.speaker if source_msg else None,
                sequence=sequence,
                metadata={"source_count": len(filtered_messages)},
            )
            units.append(unit)

        return CompressionResult(units=units, dropped_count=dropped_count)

    def _entropy_filter(self, messages: list[AgentMessage]) -> list[AgentMessage]:
        """Filter out low-entropy (low-value) messages.

        Removes:
        - Very short messages (< 10 chars)
        - Pure acknowledgments
        - System messages with no content
        - Repetitive content

        Args:
            messages: Messages to filter.

        Returns:
            Filtered messages.
        """
        low_value_patterns = {
            "ok", "okay", "yes", "no", "sure", "got it", "understood",
            "thanks", "thank you", "done", "completed", "finished",
            "starting", "processing", "working on it",
        }

        filtered = []
        seen_content = set()

        for msg in messages:
            content = msg.content.strip().lower()

            # Skip empty or very short
            if len(content) < 10:
                continue

            # Skip pure acknowledgments
            if content in low_value_patterns:
                continue

            # Skip near-duplicates
            content_key = content[:100]  # First 100 chars for dedup
            if content_key in seen_content:
                continue
            seen_content.add(content_key)

            filtered.append(msg)

        return filtered

    def _format_messages_for_compression(self, messages: list[AgentMessage]) -> str:
        """Format messages for LLM compression prompt.

        Args:
            messages: Messages to format.

        Returns:
            Formatted string for LLM.
        """
        lines = []
        for msg in messages:
            timestamp = msg.timestamp.strftime("%Y-%m-%d %H:%M:%S")
            speaker = msg.speaker
            if msg.capability_name:
                speaker = f"{msg.capability_name}/{msg.speaker}"
            lines.append(f"[{timestamp}] {speaker}: {msg.content}")

        return "\n".join(lines)

    async def _extract_facts_with_llm(
        self,
        formatted_messages: str,
        base_timestamp: datetime,
    ) -> list[dict[str, Any]]:
        """Extract atomic facts using LLM.

        Args:
            formatted_messages: Formatted message string.
            base_timestamp: Base timestamp for relative time resolution.

        Returns:
            List of extracted fact dictionaries.
        """
        prompt = f"""Extract atomic, self-contained facts from these agent conversation messages.

RULES:
1. Each fact must be completely self-contained (no pronouns like "it", "they", "the file")
2. Replace all pronouns with actual names/entities
3. Convert relative times ("tomorrow", "in 2 hours") to absolute times (base: {base_timestamp.isoformat()})
4. Skip acknowledgments, greetings, and low-value messages
5. Combine related sequential messages into single facts
6. Extract key decisions, actions taken, files created/modified, errors encountered

MESSAGES:
{formatted_messages}

OUTPUT FORMAT (JSON array):
[
  {{
    "content": "Self-contained factual statement",
    "entities": ["entity1", "entity2"],
    "topic": "category (e.g., code, email, file, decision, error)",
    "salience": "high" or "medium" or "low"
  }}
]

Return ONLY the JSON array, no other text."""

        # Get LLM config
        try:
            llm_config = LLMConfigManager.get_config("gpt_4_1_mini")
            config_data = llm_config["config_list"][0]

            import openai
            client = openai.AsyncOpenAI(
                api_key=config_data.get("api_key"),
                base_url=config_data.get("base_url"),
            )

            response = await client.chat.completions.create(
                model=config_data.get("model", "gpt-4.1-mini"),
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=2000,
            )

            result_text = response.choices[0].message.content.strip()

            # Parse JSON from response
            # Handle potential markdown code blocks
            if result_text.startswith("```"):
                result_text = result_text.split("```")[1]
                if result_text.startswith("json"):
                    result_text = result_text[4:]

            return json.loads(result_text)

        except Exception as e:
            logger.error(f"LLM fact extraction failed: {e}")
            raise

    def _fallback_extraction(self, messages: list[AgentMessage]) -> list[dict[str, Any]]:
        """Fallback fact extraction without LLM.

        Used when LLM extraction fails. Creates simple memory units
        from messages directly.

        Args:
            messages: Messages to process.

        Returns:
            List of extracted facts.
        """
        facts = []
        for msg in messages:
            # Extract basic entities (words starting with capital letters)
            words = msg.content.split()
            entities = [
                w.strip(".,!?:;\"'()[]{}") for w in words
                if w and w[0].isupper() and len(w) > 2
            ]

            # Determine topic from content keywords
            content_lower = msg.content.lower()
            if any(kw in content_lower for kw in ["file", "created", "saved", "wrote"]):
                topic = "file"
            elif any(kw in content_lower for kw in ["error", "failed", "exception"]):
                topic = "error"
            elif any(kw in content_lower for kw in ["code", "function", "class", "def "]):
                topic = "code"
            elif any(kw in content_lower for kw in ["email", "sent", "message"]):
                topic = "email"
            elif any(kw in content_lower for kw in ["decided", "will", "should", "plan"]):
                topic = "decision"
            else:
                topic = "general"

            # Determine salience
            salience = "medium"
            if any(kw in content_lower for kw in ["error", "failed", "important", "critical"]):
                salience = "high"
            elif any(kw in content_lower for kw in ["note", "fyi", "minor"]):
                salience = "low"

            facts.append({
                "content": f"{msg.speaker}: {msg.content[:500]}",
                "entities": entities[:10],  # Limit entities
                "topic": topic,
                "salience": salience,
            })

        return facts

    def _find_source_message(
        self,
        fact: dict[str, Any],
        messages: list[AgentMessage],
    ) -> AgentMessage | None:
        """Find the source message for a fact.

        Args:
            fact: Extracted fact.
            messages: Original messages.

        Returns:
            Source message if found.
        """
        # Simple heuristic: find message with most entity overlap
        fact_entities = set(e.lower() for e in fact.get("entities", []))

        best_match = None
        best_score = 0

        for msg in messages:
            msg_words = set(w.lower() for w in msg.content.split())
            overlap = len(fact_entities & msg_words)
            if overlap > best_score:
                best_score = overlap
                best_match = msg

        return best_match

    async def _add_embeddings(self, units: list[MemoryUnit]) -> None:
        """Add embeddings to memory units.

        Args:
            units: Memory units to embed.
        """
        if self._embedding_func:
            # Use custom embedding function
            for unit in units:
                try:
                    unit.embedding = self._embedding_func(unit.content)
                except Exception as e:
                    logger.warning(f"Custom embedding failed: {e}")
        else:
            # Use OpenAI embeddings
            await self._add_openai_embeddings(units)

    async def _add_openai_embeddings(self, units: list[MemoryUnit]) -> None:
        """Add embeddings using OpenAI API.

        Args:
            units: Memory units to embed.
        """
        try:
            llm_config = LLMConfigManager.get_config("gpt_4_1_mini")
            config_data = llm_config["config_list"][0]

            import openai
            client = openai.AsyncOpenAI(
                api_key=config_data.get("api_key"),
                base_url=config_data.get("base_url"),
            )

            # Batch embedding request
            contents = [unit.content for unit in units]

            # Check cache first
            uncached_indices = []
            uncached_contents = []
            for i, content in enumerate(contents):
                cache_key = content[:200]  # Use prefix as cache key
                async with self._cache_lock:
                    if cache_key in self._embedding_cache:
                        units[i].embedding = self._embedding_cache[cache_key]
                    else:
                        uncached_indices.append(i)
                        uncached_contents.append(content)

            if not uncached_contents:
                return

            # Get embeddings for uncached content
            response = await client.embeddings.create(
                model=self.config.embedding_model,
                input=uncached_contents,
            )

            # Assign embeddings to units and cache
            for idx, embedding_data in zip(uncached_indices, response.data):
                embedding = embedding_data.embedding
                units[idx].embedding = embedding

                # Cache the embedding
                cache_key = contents[idx][:200]
                async with self._cache_lock:
                    self._embedding_cache[cache_key] = embedding
                    # Limit cache size
                    if len(self._embedding_cache) > 1000:
                        # Remove oldest entries
                        keys = list(self._embedding_cache.keys())[:100]
                        for key in keys:
                            del self._embedding_cache[key]

        except Exception as e:
            logger.warning(f"OpenAI embedding failed: {e}")
            # Continue without embeddings - search will still work via FTS

    async def extract_capability_result(
        self,
        capability_name: str,
        raw_result: str,
        query: str,
        task_id: str | None = None,
    ) -> CapabilityRun:
        """Extract structured result from capability output.

        Args:
            capability_name: Name of the capability.
            raw_result: Raw result string.
            query: Original query.
            task_id: Task identifier.

        Returns:
            Structured capability run record.
        """
        try:
            # Use LLM to extract structured info
            extraction = await self._extract_result_with_llm(
                capability_name, raw_result, query
            )
        except Exception as e:
            logger.warning(f"LLM result extraction failed: {e}")
            extraction = self._fallback_result_extraction(raw_result)

        run = CapabilityRun(
            capability_name=capability_name,
            query=query,
            task_id=task_id,
            result_summary=extraction.get("summary", raw_result[:200]),
            files_affected=extraction.get("files", []),
            decisions_made=extraction.get("decisions", []),
            errors=extraction.get("errors", []),
            completed_at=dt.now(),
        )

        return run

    async def _extract_result_with_llm(
        self,
        capability_name: str,
        raw_result: str,
        query: str,
    ) -> dict[str, Any]:
        """Extract structured result info using LLM.

        Args:
            capability_name: Capability name.
            raw_result: Raw result text.
            query: Original query.

        Returns:
            Extracted information.
        """
        prompt = f"""Extract structured information from this {capability_name} capability result.

ORIGINAL QUERY: {query}

RESULT:
{raw_result[:3000]}

Extract and return JSON:
{{
  "summary": "One sentence summary of what was accomplished",
  "files": ["list of files created or modified"],
  "decisions": ["key decisions made during execution"],
  "errors": ["any errors encountered and how they were resolved"]
}}

Return ONLY the JSON, no other text."""

        llm_config = LLMConfigManager.get_config("gpt_4_1_mini")
        config_data = llm_config["config_list"][0]

        import openai
        client = openai.AsyncOpenAI(
            api_key=config_data.get("api_key"),
            base_url=config_data.get("base_url"),
        )

        response = await client.chat.completions.create(
            model=config_data.get("model", "gpt-4.1-mini"),
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=500,
        )

        result_text = response.choices[0].message.content.strip()

        # Handle markdown code blocks
        if result_text.startswith("```"):
            result_text = result_text.split("```")[1]
            if result_text.startswith("json"):
                result_text = result_text[4:]

        return json.loads(result_text)

    def _fallback_result_extraction(self, raw_result: str) -> dict[str, Any]:
        """Fallback result extraction without LLM.

        Args:
            raw_result: Raw result text.

        Returns:
            Extracted information.
        """
        # Extract file paths (simple pattern matching)
        import re
        file_patterns = re.findall(r'[\w./\\]+\.\w{1,5}', raw_result)
        files = list(set(f for f in file_patterns if len(f) > 5))[:10]

        # Check for error indicators
        errors = []
        if "error" in raw_result.lower() or "failed" in raw_result.lower():
            error_lines = [
                line.strip() for line in raw_result.split("\n")
                if "error" in line.lower() or "failed" in line.lower()
            ]
            errors = error_lines[:5]

        return {
            "summary": raw_result[:200],
            "files": files,
            "decisions": [],
            "errors": errors,
        }

    async def get_embedding(self, text: str) -> list[float] | None:
        """Get embedding for a text string.

        Args:
            text: Text to embed.

        Returns:
            Embedding vector or None on failure.
        """
        if self._embedding_func:
            try:
                return self._embedding_func(text)
            except Exception:
                pass

        # Check cache
        cache_key = text[:200]
        async with self._cache_lock:
            if cache_key in self._embedding_cache:
                return self._embedding_cache[cache_key]

        try:
            llm_config = LLMConfigManager.get_config("gpt_4_1_mini")
            config_data = llm_config["config_list"][0]

            import openai
            client = openai.AsyncOpenAI(
                api_key=config_data.get("api_key"),
                base_url=config_data.get("base_url"),
            )

            response = await client.embeddings.create(
                model=self.config.embedding_model,
                input=[text],
            )

            embedding = response.data[0].embedding

            # Cache it
            async with self._cache_lock:
                self._embedding_cache[cache_key] = embedding

            return embedding

        except Exception as e:
            logger.warning(f"Embedding generation failed: {e}")
            return None
