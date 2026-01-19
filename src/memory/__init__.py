"""SimpleMem-based memory system for AutoGen multi-agent orchestration.

This module provides a non-blocking, async memory system based on the SimpleMem
architecture (arxiv:2601.02553) adapted for multi-agent groupchat workflows.

Key Components:
    - SimpleMemStore: SQLite-backed vector storage with hybrid retrieval
    - MemoryProcessor: Async compression and indexing pipeline
    - ContextProvider: Query-aware context generation for capabilities
    - SimpleMemBridge: Main interface integrating all components
    - mem: Integration helper for easy use in AutoGen managers

Features:
    - Non-blocking memory operations via async queues
    - Chat & task specific memory partitioning
    - Parallel capability support
    - Semantic structured compression
    - Hybrid retrieval (semantic + lexical + recency)
    - Nuitka-compatible local storage (SQLite + numpy)

Quick Start:
    from src.memory import mem

    # Add message (fire-and-forget from sync code)
    mem.fire(mem.add_message(chat_id, speaker, content))

    # In async code
    await mem.add_message(chat_id, speaker, content, task_id, capability)
    context = await mem.get_context(chat_id, task_id, capability, query)
"""

from src.memory.bridge import SimpleMemBridge
from src.memory.context_provider import ContextProvider
from src.memory.integration import mem
from src.memory.models import (
    CapabilityRun,
    CompressionResult,
    MemoryConfig,
    MemoryUnit,
    RetrievalQuery,
    TaskState,
)
from src.memory.processor import MemoryProcessor
from src.memory.store import SimpleMemStore

__all__ = [
    # Integration helper (recommended for most uses)
    "mem",
    # Core components
    "MemoryUnit",
    "TaskState",
    "CapabilityRun",
    "CompressionResult",
    "RetrievalQuery",
    "MemoryConfig",
    "SimpleMemStore",
    "MemoryProcessor",
    "ContextProvider",
    "SimpleMemBridge",
]
