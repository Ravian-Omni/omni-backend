"""Storage backend for SimpleMem memory system.

This module provides the storage layer using SQLite with numpy for vector
operations. Designed to be Nuitka-compatible without external vector DB
dependencies.

Features:
    - SQLite for metadata storage (built-in, no dependencies)
    - Numpy for vector similarity (lightweight, Nuitka-friendly)
    - Hybrid retrieval (semantic + lexical + symbolic)
    - Async-safe operations
    - Automatic schema management
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
from collections.abc import Sequence
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
from loguru import logger

from src.memory.models import (
    MemoryConfig,
    MemoryUnit,
    RetrievalQuery,
    TaskState,
    CapabilityRun,
)


class SimpleMemStore:
    """SQLite-based storage for memory units with vector search.

    Provides persistent storage for memory units with support for:
    - Vector similarity search using numpy
    - Metadata filtering (chat_id, task_id, capability)
    - Full-text search on content
    - Task state persistence

    Thread-safe and async-compatible through connection pooling.

    Attributes:
        config: Memory system configuration.
        db_path: Path to SQLite database file.
    """

    # Schema version for migrations
    SCHEMA_VERSION = 1

    def __init__(self, config: MemoryConfig):
        """Initialize the store.

        Args:
            config: Memory configuration with db_path and other settings.
        """
        self.config = config
        self.db_path = config.db_path / "simplemem.db"
        self._local = threading.local()
        self._lock = asyncio.Lock()
        self._write_lock = threading.Lock()

        # Ensure directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        # Initialize schema
        self._init_schema()

        logger.info(f"SimpleMemStore initialized at {self.db_path}")

    @contextmanager
    def _get_connection(self):
        """Get a thread-local database connection.

        Yields:
            SQLite connection for the current thread.
        """
        if not hasattr(self._local, "connection") or self._local.connection is None:
            self._local.connection = sqlite3.connect(
                str(self.db_path),
                check_same_thread=False,
                timeout=30.0,
            )
            self._local.connection.row_factory = sqlite3.Row
            # Enable WAL mode for better concurrent access
            self._local.connection.execute("PRAGMA journal_mode=WAL")
            self._local.connection.execute("PRAGMA synchronous=NORMAL")

        try:
            yield self._local.connection
        except Exception:
            self._local.connection.rollback()
            raise

    def _init_schema(self):
        """Initialize database schema."""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Memory units table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS memory_units (
                    id TEXT PRIMARY KEY,
                    content TEXT NOT NULL,
                    entities TEXT NOT NULL,
                    topic TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    salience TEXT NOT NULL,
                    chat_id TEXT NOT NULL,
                    task_id TEXT,
                    capability_name TEXT,
                    capability_run_id TEXT,
                    agent_name TEXT,
                    sequence INTEGER NOT NULL,
                    embedding BLOB,
                    metadata TEXT,
                    consolidated INTEGER DEFAULT 0,
                    consolidated_into TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Task state table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS task_states (
                    task_id TEXT PRIMARY KEY,
                    chat_id TEXT NOT NULL,
                    goal TEXT,
                    plan TEXT,
                    capability_runs TEXT,
                    facts TEXT,
                    decisions TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

            # Capability runs table (for quick lookup)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS capability_runs (
                    id TEXT PRIMARY KEY,
                    capability_name TEXT NOT NULL,
                    query TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    task_id TEXT,
                    chat_id TEXT NOT NULL,
                    result_summary TEXT,
                    files_affected TEXT,
                    decisions_made TEXT,
                    errors TEXT,
                    started_at TEXT NOT NULL,
                    completed_at TEXT
                )
            """)

            # Indexes for fast filtering
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_memory_chat_id
                ON memory_units(chat_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_memory_task_id
                ON memory_units(task_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_memory_capability
                ON memory_units(capability_name)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_memory_timestamp
                ON memory_units(timestamp)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_memory_consolidated
                ON memory_units(consolidated)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_task_chat_id
                ON task_states(chat_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_capruns_task_id
                ON capability_runs(task_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_capruns_capability
                ON capability_runs(capability_name, task_id)
            """)

            # Full-text search on content
            cursor.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts
                USING fts5(id, content, entities, topic)
            """)

            conn.commit()

    async def add_memory_unit(self, unit: MemoryUnit) -> str:
        """Add a single memory unit to storage.

        Args:
            unit: Memory unit to store.

        Returns:
            ID of the stored unit.
        """
        async with self._lock:
            return await asyncio.to_thread(self._add_memory_unit_sync, unit)

    def _add_memory_unit_sync(self, unit: MemoryUnit) -> str:
        """Synchronous implementation of add_memory_unit."""
        with self._write_lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()

                # Serialize embedding as bytes
                embedding_bytes = None
                if unit.embedding:
                    embedding_bytes = np.array(unit.embedding, dtype=np.float32).tobytes()

                cursor.execute(
                    """
                    INSERT OR REPLACE INTO memory_units
                    (id, content, entities, topic, timestamp, salience, chat_id,
                     task_id, capability_name, capability_run_id, agent_name,
                     sequence, embedding, metadata, consolidated, consolidated_into)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        unit.id,
                        unit.content,
                        json.dumps(unit.entities),
                        unit.topic,
                        unit.timestamp.isoformat() if isinstance(unit.timestamp, datetime) else unit.timestamp,
                        unit.salience.value if hasattr(unit.salience, "value") else unit.salience,
                        unit.chat_id,
                        unit.task_id,
                        unit.capability_name,
                        unit.capability_run_id,
                        unit.agent_name,
                        unit.sequence,
                        embedding_bytes,
                        json.dumps(unit.metadata),
                        1 if unit.consolidated else 0,
                        unit.consolidated_into,
                    ),
                )

                # Update FTS index
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO memory_fts (id, content, entities, topic)
                    VALUES (?, ?, ?, ?)
                    """,
                    (unit.id, unit.content, " ".join(unit.entities), unit.topic),
                )

                conn.commit()
                return unit.id

    async def add_memory_units(self, units: Sequence[MemoryUnit]) -> list[str]:
        """Add multiple memory units in batch.

        Args:
            units: Memory units to store.

        Returns:
            List of stored unit IDs.
        """
        if not units:
            return []

        async with self._lock:
            return await asyncio.to_thread(self._add_memory_units_sync, units)

    def _add_memory_units_sync(self, units: Sequence[MemoryUnit]) -> list[str]:
        """Synchronous batch insert."""
        ids = []
        with self._write_lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()

                for unit in units:
                    embedding_bytes = None
                    if unit.embedding:
                        embedding_bytes = np.array(unit.embedding, dtype=np.float32).tobytes()

                    cursor.execute(
                        """
                        INSERT OR REPLACE INTO memory_units
                        (id, content, entities, topic, timestamp, salience, chat_id,
                         task_id, capability_name, capability_run_id, agent_name,
                         sequence, embedding, metadata, consolidated, consolidated_into)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            unit.id,
                            unit.content,
                            json.dumps(unit.entities),
                            unit.topic,
                            unit.timestamp.isoformat() if isinstance(unit.timestamp, datetime) else unit.timestamp,
                            unit.salience.value if hasattr(unit.salience, "value") else unit.salience,
                            unit.chat_id,
                            unit.task_id,
                            unit.capability_name,
                            unit.capability_run_id,
                            unit.agent_name,
                            unit.sequence,
                            embedding_bytes,
                            json.dumps(unit.metadata),
                            1 if unit.consolidated else 0,
                            unit.consolidated_into,
                        ),
                    )

                    cursor.execute(
                        """
                        INSERT OR REPLACE INTO memory_fts (id, content, entities, topic)
                        VALUES (?, ?, ?, ?)
                        """,
                        (unit.id, unit.content, " ".join(unit.entities), unit.topic),
                    )

                    ids.append(unit.id)

                conn.commit()

        return ids

    async def search(
        self,
        query: RetrievalQuery,
        query_embedding: list[float] | None = None,
    ) -> list[MemoryUnit]:
        """Search for relevant memory units.

        Performs hybrid search combining:
        - Semantic similarity (if embedding provided)
        - Lexical matching (FTS5)
        - Metadata filtering

        Args:
            query: Retrieval query with filters.
            query_embedding: Optional query embedding for semantic search.

        Returns:
            List of relevant memory units, ranked by combined score.
        """
        return await asyncio.to_thread(
            self._search_sync, query, query_embedding
        )

    def _search_sync(
        self,
        query: RetrievalQuery,
        query_embedding: list[float] | None = None,
    ) -> list[MemoryUnit]:
        """Synchronous search implementation."""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Build base query with filters
            conditions = []
            params = []

            if query.chat_id:
                conditions.append("chat_id = ?")
                params.append(query.chat_id)

            if query.task_id:
                conditions.append("task_id = ?")
                params.append(query.task_id)

            if query.capability_name:
                conditions.append("capability_name = ?")
                params.append(query.capability_name)

            if not query.include_consolidated:
                conditions.append("consolidated = 0")

            if query.time_range_hours:
                cutoff = (datetime.now() - timedelta(hours=query.time_range_hours)).isoformat()
                conditions.append("timestamp >= ?")
                params.append(cutoff)

            where_clause = " AND ".join(conditions) if conditions else "1=1"

            # Sanitize FTS query - extract only alphanumeric words for safe matching
            fts_query = self._sanitize_fts_query(query.query)

            # Build SQL - only use FTS if we have valid search terms
            if fts_query:
                sql = f"""
                    SELECT m.*,
                           COALESCE(
                               (SELECT rank FROM memory_fts
                                WHERE memory_fts.id = m.id
                                AND memory_fts MATCH ?),
                               0
                           ) as fts_score
                    FROM memory_units m
                    WHERE {where_clause}
                    ORDER BY m.sequence DESC
                    LIMIT ?
                """
                params.insert(0, fts_query)  # FTS query param first
            else:
                # Skip FTS if query can't be sanitized
                sql = f"""
                    SELECT m.*, 0 as fts_score
                    FROM memory_units m
                    WHERE {where_clause}
                    ORDER BY m.sequence DESC
                    LIMIT ?
                """

            params.append(query.k * 3)  # Get more candidates for reranking

            cursor.execute(sql, params)
            rows = cursor.fetchall()

            if not rows:
                return []

            # Convert to MemoryUnits and compute scores
            candidates = []
            for row in rows:
                unit = self._row_to_memory_unit(row)
                fts_score = row["fts_score"] if row["fts_score"] else 0

                # Compute semantic score if embedding available
                semantic_score = 0.0
                if query_embedding and unit.embedding:
                    semantic_score = self._cosine_similarity(
                        query_embedding, unit.embedding
                    )

                # Combined score (weighted)
                # Semantic: 0.6, Lexical: 0.3, Recency: 0.1
                recency_score = 1.0 / (1 + (len(rows) - candidates.__len__()) * 0.1)
                combined_score = (
                    0.6 * semantic_score
                    + 0.3 * min(abs(fts_score) / 100, 1.0)
                    + 0.1 * recency_score
                )

                candidates.append((unit, combined_score))

            # Sort by combined score and return top k
            candidates.sort(key=lambda x: x[1], reverse=True)
            return [unit for unit, _ in candidates[: query.k]]

    def _row_to_memory_unit(self, row: sqlite3.Row) -> MemoryUnit:
        """Convert database row to MemoryUnit."""
        embedding = None
        if row["embedding"]:
            embedding = np.frombuffer(row["embedding"], dtype=np.float32).tolist()

        return MemoryUnit(
            id=row["id"],
            content=row["content"],
            entities=json.loads(row["entities"]),
            topic=row["topic"],
            timestamp=row["timestamp"],
            salience=row["salience"],
            chat_id=row["chat_id"],
            task_id=row["task_id"],
            capability_name=row["capability_name"],
            capability_run_id=row["capability_run_id"],
            agent_name=row["agent_name"],
            sequence=row["sequence"],
            embedding=embedding,
            metadata=json.loads(row["metadata"]) if row["metadata"] else {},
            consolidated=bool(row["consolidated"]),
            consolidated_into=row["consolidated_into"],
        )

    @staticmethod
    def _sanitize_fts_query(query_text: str) -> str | None:
        """Sanitize a query string for FTS5 MATCH.

        FTS5 has special syntax characters that can cause syntax errors.
        This method extracts only safe alphanumeric words and creates
        a valid FTS5 query.

        Args:
            query_text: Raw query string.

        Returns:
            Sanitized FTS5 query string, or None if no valid terms.
        """
        import re

        # Extract alphanumeric words (letters, numbers, underscores)
        words = re.findall(r'\b[a-zA-Z0-9_]+\b', query_text)

        # Filter out very short words and common stop words
        stop_words = {'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'to', 'of', 'and', 'or', 'in', 'on', 'at', 'for'}
        words = [w for w in words if len(w) > 2 and w.lower() not in stop_words]

        if not words:
            return None

        # Take first 10 words max to avoid overly long queries
        words = words[:10]

        # Create an OR query with each word quoted for safety
        # Format: "word1" OR "word2" OR "word3"
        fts_terms = ' OR '.join(f'"{w}"' for w in words)

        return fts_terms

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        """Compute cosine similarity between two vectors."""
        a_arr = np.array(a, dtype=np.float32)
        b_arr = np.array(b, dtype=np.float32)

        dot = np.dot(a_arr, b_arr)
        norm_a = np.linalg.norm(a_arr)
        norm_b = np.linalg.norm(b_arr)

        if norm_a == 0 or norm_b == 0:
            return 0.0

        return float(dot / (norm_a * norm_b))

    # Task State Operations

    async def save_task_state(self, state: TaskState) -> None:
        """Save or update task state.

        Args:
            state: Task state to persist.
        """
        async with self._lock:
            await asyncio.to_thread(self._save_task_state_sync, state)

    def _save_task_state_sync(self, state: TaskState) -> None:
        """Synchronous task state save."""
        with self._write_lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()

                cursor.execute(
                    """
                    INSERT OR REPLACE INTO task_states
                    (task_id, chat_id, goal, plan, capability_runs, facts,
                     decisions, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        state.task_id,
                        state.chat_id,
                        state.goal,
                        json.dumps([item.to_dict() for item in state.plan]),
                        json.dumps([run.to_dict() for run in state.capability_runs]),
                        json.dumps(state.facts),
                        json.dumps(state.decisions),
                        state.created_at.isoformat(),
                        state.updated_at.isoformat(),
                    ),
                )

                conn.commit()

    async def get_task_state(self, task_id: str) -> TaskState | None:
        """Get task state by ID.

        Args:
            task_id: Task identifier.

        Returns:
            TaskState if found, None otherwise.
        """
        return await asyncio.to_thread(self._get_task_state_sync, task_id)

    def _get_task_state_sync(self, task_id: str) -> TaskState | None:
        """Synchronous task state retrieval."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM task_states WHERE task_id = ?",
                (task_id,),
            )
            row = cursor.fetchone()

            if not row:
                return None

            from src.memory.models import TaskItem, TaskStatus

            plan_data = json.loads(row["plan"]) if row["plan"] else []
            plan = [
                TaskItem(
                    id=item.get("id", ""),
                    description=item["description"],
                    status=TaskStatus(item.get("status", "pending")),
                    capability=item.get("capability"),
                    result_summary=item.get("result_summary"),
                    sequence=item.get("sequence", 0),
                )
                for item in plan_data
            ]

            runs_data = json.loads(row["capability_runs"]) if row["capability_runs"] else []
            capability_runs = []
            for run_data in runs_data:
                run = CapabilityRun(
                    id=run_data.get("id", ""),
                    capability_name=run_data["capability_name"],
                    query=run_data["query"],
                    sequence=run_data.get("sequence", 1),
                    task_id=run_data.get("task_id"),
                    result_summary=run_data.get("result_summary"),
                    files_affected=run_data.get("files_affected", []),
                    decisions_made=run_data.get("decisions_made", []),
                    errors=run_data.get("errors", []),
                )
                capability_runs.append(run)

            return TaskState(
                task_id=row["task_id"],
                chat_id=row["chat_id"],
                goal=row["goal"],
                plan=plan,
                capability_runs=capability_runs,
                facts=json.loads(row["facts"]) if row["facts"] else {},
                decisions=json.loads(row["decisions"]) if row["decisions"] else [],
                created_at=datetime.fromisoformat(row["created_at"]),
                updated_at=datetime.fromisoformat(row["updated_at"]),
            )

    async def get_chat_task_states(self, chat_id: str) -> list[TaskState]:
        """Get all task states for a chat.

        Args:
            chat_id: Chat identifier.

        Returns:
            List of task states for the chat.
        """
        return await asyncio.to_thread(self._get_chat_task_states_sync, chat_id)

    def _get_chat_task_states_sync(self, chat_id: str) -> list[TaskState]:
        """Synchronous chat task states retrieval."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT task_id FROM task_states WHERE chat_id = ? ORDER BY created_at DESC",
                (chat_id,),
            )
            rows = cursor.fetchall()

            states = []
            for row in rows:
                state = self._get_task_state_sync(row["task_id"])
                if state:
                    states.append(state)

            return states

    # Capability Run Operations

    async def add_capability_run(self, run: CapabilityRun, chat_id: str) -> str:
        """Add a capability run record.

        Args:
            run: Capability run to store.
            chat_id: Parent chat ID.

        Returns:
            Run ID.
        """
        async with self._lock:
            return await asyncio.to_thread(self._add_capability_run_sync, run, chat_id)

    def _add_capability_run_sync(self, run: CapabilityRun, chat_id: str) -> str:
        """Synchronous capability run insert."""
        with self._write_lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()

                cursor.execute(
                    """
                    INSERT OR REPLACE INTO capability_runs
                    (id, capability_name, query, sequence, task_id, chat_id,
                     result_summary, files_affected, decisions_made, errors,
                     started_at, completed_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run.id,
                        run.capability_name,
                        run.query,
                        run.sequence,
                        run.task_id,
                        chat_id,
                        run.result_summary,
                        json.dumps(run.files_affected),
                        json.dumps(run.decisions_made),
                        json.dumps(run.errors),
                        run.started_at.isoformat(),
                        run.completed_at.isoformat() if run.completed_at else None,
                    ),
                )

                conn.commit()
                return run.id

    async def get_capability_runs(
        self,
        chat_id: str,
        task_id: str | None = None,
        capability_name: str | None = None,
    ) -> list[CapabilityRun]:
        """Get capability runs with optional filters.

        Args:
            chat_id: Chat identifier.
            task_id: Optional task filter.
            capability_name: Optional capability filter.

        Returns:
            List of matching capability runs.
        """
        return await asyncio.to_thread(
            self._get_capability_runs_sync, chat_id, task_id, capability_name
        )

    def _get_capability_runs_sync(
        self,
        chat_id: str,
        task_id: str | None = None,
        capability_name: str | None = None,
    ) -> list[CapabilityRun]:
        """Synchronous capability runs retrieval."""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            conditions = ["chat_id = ?"]
            params = [chat_id]

            if task_id:
                conditions.append("task_id = ?")
                params.append(task_id)

            if capability_name:
                conditions.append("capability_name = ?")
                params.append(capability_name)

            where_clause = " AND ".join(conditions)

            cursor.execute(
                f"""
                SELECT * FROM capability_runs
                WHERE {where_clause}
                ORDER BY started_at DESC
                """,
                params,
            )
            rows = cursor.fetchall()

            runs = []
            for row in rows:
                run = CapabilityRun(
                    id=row["id"],
                    capability_name=row["capability_name"],
                    query=row["query"],
                    sequence=row["sequence"],
                    task_id=row["task_id"],
                    result_summary=row["result_summary"],
                    files_affected=json.loads(row["files_affected"]) if row["files_affected"] else [],
                    decisions_made=json.loads(row["decisions_made"]) if row["decisions_made"] else [],
                    errors=json.loads(row["errors"]) if row["errors"] else [],
                    started_at=datetime.fromisoformat(row["started_at"]),
                    completed_at=datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None,
                )
                runs.append(run)

            return runs

    # Utility Methods

    async def get_memory_count(
        self,
        chat_id: str | None = None,
        task_id: str | None = None,
    ) -> int:
        """Get count of memory units.

        Args:
            chat_id: Optional chat filter.
            task_id: Optional task filter.

        Returns:
            Number of memory units matching filters.
        """
        return await asyncio.to_thread(
            self._get_memory_count_sync, chat_id, task_id
        )

    def _get_memory_count_sync(
        self,
        chat_id: str | None = None,
        task_id: str | None = None,
    ) -> int:
        """Synchronous count."""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            conditions = []
            params = []

            if chat_id:
                conditions.append("chat_id = ?")
                params.append(chat_id)

            if task_id:
                conditions.append("task_id = ?")
                params.append(task_id)

            where_clause = " AND ".join(conditions) if conditions else "1=1"

            cursor.execute(
                f"SELECT COUNT(*) FROM memory_units WHERE {where_clause}",
                params,
            )

            return cursor.fetchone()[0]

    async def clear_chat_memory(self, chat_id: str) -> int:
        """Clear all memory for a chat.

        Args:
            chat_id: Chat to clear.

        Returns:
            Number of units deleted.
        """
        async with self._lock:
            return await asyncio.to_thread(self._clear_chat_memory_sync, chat_id)

    def _clear_chat_memory_sync(self, chat_id: str) -> int:
        """Synchronous chat memory clear."""
        with self._write_lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()

                # Delete from FTS first
                cursor.execute(
                    """
                    DELETE FROM memory_fts
                    WHERE id IN (SELECT id FROM memory_units WHERE chat_id = ?)
                    """,
                    (chat_id,),
                )

                # Delete memory units
                cursor.execute(
                    "DELETE FROM memory_units WHERE chat_id = ?",
                    (chat_id,),
                )
                deleted = cursor.rowcount

                # Delete task states
                cursor.execute(
                    "DELETE FROM task_states WHERE chat_id = ?",
                    (chat_id,),
                )

                # Delete capability runs
                cursor.execute(
                    "DELETE FROM capability_runs WHERE chat_id = ?",
                    (chat_id,),
                )

                conn.commit()
                return deleted

    async def get_recent_units(
        self,
        chat_id: str,
        task_id: str | None = None,
        limit: int = 10,
    ) -> list[MemoryUnit]:
        """Get most recent memory units.

        Args:
            chat_id: Chat identifier.
            task_id: Optional task filter.
            limit: Maximum units to return.

        Returns:
            List of recent memory units.
        """
        return await asyncio.to_thread(
            self._get_recent_units_sync, chat_id, task_id, limit
        )

    def _get_recent_units_sync(
        self,
        chat_id: str,
        task_id: str | None = None,
        limit: int = 10,
    ) -> list[MemoryUnit]:
        """Synchronous recent units retrieval."""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            if task_id:
                cursor.execute(
                    """
                    SELECT * FROM memory_units
                    WHERE chat_id = ? AND task_id = ? AND consolidated = 0
                    ORDER BY sequence DESC
                    LIMIT ?
                    """,
                    (chat_id, task_id, limit),
                )
            else:
                cursor.execute(
                    """
                    SELECT * FROM memory_units
                    WHERE chat_id = ? AND consolidated = 0
                    ORDER BY sequence DESC
                    LIMIT ?
                    """,
                    (chat_id, limit),
                )

            rows = cursor.fetchall()
            return [self._row_to_memory_unit(row) for row in rows]

    def close(self):
        """Close database connections."""
        if hasattr(self._local, "connection") and self._local.connection:
            self._local.connection.close()
            self._local.connection = None
