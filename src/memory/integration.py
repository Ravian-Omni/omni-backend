"""SimpleMem integration helpers for AutoGen managers.

This module provides a clean, centralized interface for integrating SimpleMem
with AutoGen groupchats. All memory operations are non-blocking and fail silently.

Usage:
    from src.memory.integration import mem

    # In any async context:
    await mem.add_message(chat_id, speaker, content, task_id, capability)
    await mem.init_task(chat_id, task_id)
    await mem.set_goal(chat_id, task_id, goal)
    await mem.set_plan(chat_id, task_id, plan_items)
    context = await mem.get_context(chat_id, task_id, capability, query)

    # Non-blocking fire-and-forget (for use in sync code):
    mem.fire(mem.add_message(chat_id, speaker, content))
    mem.fire(mem.set_goal(chat_id, task_id, goal))
"""

from __future__ import annotations

from typing import Any

from loguru import logger


class MemoryIntegration:
    """Centralized SimpleMem integration with lazy initialization.

    All methods are safe to call - they fail silently if SimpleMem
    is not available or encounters errors.
    """

    _bridge = None
    _init_attempted = False

    @classmethod
    async def _get_bridge(cls):
        """Get SimpleMem bridge with lazy initialization."""
        if cls._init_attempted:
            return cls._bridge

        cls._init_attempted = True
        try:
            from src.memory.bridge import get_memory_bridge

            cls._bridge = await get_memory_bridge()
            logger.info("SimpleMem bridge initialized successfully")
        except Exception as e:
            logger.error(f"SimpleMem initialization failed: {e}")
            cls._bridge = None

        return cls._bridge

    @classmethod
    def fire(cls, coro) -> None:
        """Fire-and-forget async operation for sync code.

        Uses async_to_sync to properly execute coroutines from sync callbacks.
        This is the correct way to call async memory operations from
        synchronous code like AutoGen's _print_received_message.

        Args:
            coro: Coroutine to execute
        """
        try:
            from src.utilities.async_helpers import async_to_sync

            async_to_sync(coro)
        except Exception as e:
            # Log at debug to avoid spamming logs
            logger.debug(f"Memory fire operation skipped: {e}")

    # =========================================================================
    # Message Operations
    # =========================================================================

    @classmethod
    async def add_message(
        cls,
        chat_id: str,
        speaker: str,
        content: str,
        task_id: str | None = None,
        capability: str | None = None,
        capability_run_id: str | None = None,
        raw_message: dict | None = None,
    ) -> None:
        """Add a message to memory (non-blocking, fails silently).

        Args:
            chat_id: Chat session ID
            speaker: Agent/user name
            content: Message content
            task_id: Optional task ID
            capability: Optional capability name
            capability_run_id: Optional capability run ID
            raw_message: Optional raw message dict
        """
        try:
            bridge = await cls._get_bridge()
            if bridge:
                await bridge.add_message(
                    speaker=speaker,
                    content=content,
                    chat_id=chat_id,
                    task_id=task_id,
                    capability_name=capability,
                    capability_run_id=capability_run_id,
                    raw_message=raw_message,
                )
                logger.debug(f"SimpleMem: Added message from {speaker} ({capability})")
            else:
                logger.warning("SimpleMem: Bridge not available for add_message")
        except Exception as e:
            logger.warning(f"SimpleMem add_message failed: {e}")

    # =========================================================================
    # Task State Operations
    # =========================================================================

    @classmethod
    async def init_task(cls, chat_id: str, task_id: str) -> None:
        """Initialize task state (non-blocking, fails silently).

        Args:
            chat_id: Chat session ID
            task_id: Task ID
        """
        try:
            bridge = await cls._get_bridge()
            if bridge:
                await bridge.get_or_create_task_state(chat_id, task_id)
                logger.info(f"SimpleMem: Initialized task {task_id}")
            else:
                logger.warning("SimpleMem: Bridge not available for init_task")
        except Exception as e:
            logger.warning(f"SimpleMem init_task failed: {e}")

    @classmethod
    async def set_goal(cls, chat_id: str, task_id: str, goal: str) -> None:
        """Set task goal (non-blocking, fails silently).

        Args:
            chat_id: Chat session ID
            task_id: Task ID
            goal: User's goal/request
        """
        try:
            bridge = await cls._get_bridge()
            if bridge and task_id:
                await bridge.set_task_goal(chat_id, task_id, goal)
                logger.info(f"SimpleMem: Set goal for task {task_id}")
            elif not task_id:
                logger.debug("SimpleMem: No task_id provided for set_goal")
        except Exception as e:
            logger.warning(f"SimpleMem set_goal failed: {e}")

    @classmethod
    async def set_plan(
        cls,
        chat_id: str,
        task_id: str,
        plan_items: list[dict | str],
    ) -> None:
        """Set task plan (non-blocking, fails silently).

        Args:
            chat_id: Chat session ID
            task_id: Task ID
            plan_items: List of plan items (dicts or strings)
        """
        try:
            bridge = await cls._get_bridge()
            if bridge and task_id:
                # Normalize plan items
                normalized = []
                for item in plan_items:
                    if isinstance(item, str):
                        normalized.append({"description": item})
                    else:
                        normalized.append(item)
                await bridge.set_task_plan(chat_id, task_id, normalized)
        except Exception as e:
            logger.debug(f"Memory set_plan skipped: {e}")

    # =========================================================================
    # Capability Run Operations
    # =========================================================================

    @classmethod
    async def start_run(
        cls,
        chat_id: str,
        task_id: str | None,
        capability: str,
        query: str,
    ):
        """Start tracking a capability run.

        Args:
            chat_id: Chat session ID
            task_id: Task ID
            capability: Capability name
            query: The query/task

        Returns:
            CapabilityRun object or None
        """
        try:
            bridge = await cls._get_bridge()
            if bridge:
                run = await bridge.start_capability_run(
                    chat_id, task_id, capability, query
                )
                logger.info(f"SimpleMem: Started {capability} run #{run.sequence}")
                return run
            else:
                logger.warning("SimpleMem: Bridge not available for start_run")
        except Exception as e:
            logger.warning(f"SimpleMem start_run failed: {e}")
        return None

    @classmethod
    async def complete_run(
        cls,
        run,
        chat_id: str,
        raw_result: str | None = None,
    ) -> None:
        """Complete a capability run.

        Args:
            run: CapabilityRun object from start_run
            chat_id: Chat session ID
            raw_result: Optional raw result to extract info from
        """
        try:
            bridge = await cls._get_bridge()
            if bridge and run:
                await bridge.complete_capability_run(run, chat_id, raw_result)
        except Exception as e:
            logger.debug(f"Memory complete_run skipped: {e}")

    # =========================================================================
    # Context Operations
    # =========================================================================

    @classmethod
    async def get_context(
        cls,
        chat_id: str,
        task_id: str | None,
        capability: str,
        query: str,
    ) -> list[dict[str, Any]]:
        """Get context messages for capability injection.

        Args:
            chat_id: Chat session ID
            task_id: Task ID
            capability: Capability name
            query: Current query

        Returns:
            List of AutoGen message dicts (empty if unavailable)
        """
        try:
            bridge = await cls._get_bridge()
            if bridge:
                context = await bridge.get_capability_context(
                    chat_id, task_id, capability, query
                )
                logger.info(
                    f"SimpleMem: Retrieved {len(context)} context messages "
                    f"for {capability} (task={task_id})"
                )
                return context
            else:
                logger.warning("SimpleMem: Bridge not available for get_context")
        except Exception as e:
            logger.warning(f"SimpleMem get_context failed: {e}")
        return []

    @classmethod
    async def flush(cls, chat_id: str, task_id: str | None = None) -> None:
        """Flush pending messages.

        Args:
            chat_id: Chat session ID
            task_id: Task ID
        """
        try:
            bridge = await cls._get_bridge()
            if bridge:
                await bridge.flush_messages(chat_id, task_id)
        except Exception as e:
            logger.debug(f"Memory flush skipped: {e}")


# Global instance for easy access
mem = MemoryIntegration()
