"""Asynchronous helper utilities for bridging async/sync code.

This module provides utility functions to bridge between asynchronous and
synchronous code execution contexts, with proper safeguards and error handling.

IMPORTANT: These utilities rely on nest_asyncio being applied at application
startup (in main.py) to allow nested event loops. Without nest_asyncio,
calling async_to_sync from within an async context will deadlock.

Error Codes:
- ASYNC-9002: Event loop related errors
"""

import asyncio
import functools
import logging
from typing import Any, Awaitable, Callable, TypeVar

from src.utilities.async_errors import AsyncErrorCode, create_error

logger = logging.getLogger(__name__)

T = TypeVar("T")


def async_to_sync(awaitable: Awaitable[T]) -> T:
    """Convert an awaitable to synchronous execution.

    Execute an async function or coroutine synchronously. This function
    relies on nest_asyncio being applied at application startup to allow
    nested event loops safely.

    Args:
        awaitable: An awaitable object (coroutine, task, or future) to execute.

    Returns:
        The result of the awaitable execution.

    Raises:
        RuntimeError: If no event loop is available and one cannot be created.

    Example:
        >>> async def fetch_data():
        ...     return {"status": "success"}
        >>> result = async_to_sync(fetch_data())
        >>> print(result)
        {'status': 'success'}

    Warning:
        This function requires nest_asyncio.apply() to be called at application
        startup. It is primarily intended for use in synchronous callback
        methods that need to call async code (e.g., autogen agent callbacks).
    """
    try:
        # Try to get the running loop first
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No running loop, get or create one
            loop = asyncio.get_event_loop()

        # If loop is already running, nest_asyncio should handle it
        if loop.is_running():
            # This relies on nest_asyncio being applied at startup
            return loop.run_until_complete(awaitable)
        else:
            return loop.run_until_complete(awaitable)

    except RuntimeError as e:
        error = create_error(
            AsyncErrorCode.EVENT_LOOP_ERROR,
            "async_to_sync",
            user_message="A system error occurred. Please try again.",
            technical_message=str(e),
            context={"error_type": "event_loop"},
        )
        logger.error(f"[{error.code.value}] Event loop error in async_to_sync: {e}")
        raise RuntimeError(f"[{error.code.value}] {str(e)}") from e


def run_async(coro: Awaitable[T], timeout: float | None = None) -> T:
    """Run an async coroutine with optional timeout.

    Safer alternative to async_to_sync that includes timeout handling.

    Args:
        coro: Coroutine to execute.
        timeout: Optional timeout in seconds.

    Returns:
        Result of the coroutine.

    Raises:
        asyncio.TimeoutError: If timeout is exceeded.
        RuntimeError: If event loop issues occur.
    """
    async def wrapped():
        if timeout:
            return await asyncio.wait_for(coro, timeout=timeout)
        return await coro

    return async_to_sync(wrapped())


def make_sync(func: Callable[..., Awaitable[T]]) -> Callable[..., T]:
    """Decorator to create a synchronous version of an async function.

    Wraps an async function to make it callable synchronously.
    Useful for creating sync wrappers around async APIs.

    Args:
        func: Async function to wrap.

    Returns:
        Synchronous wrapper function.

    Example:
        >>> @make_sync
        ... async def fetch_data(url: str) -> dict:
        ...     async with httpx.AsyncClient() as client:
        ...         response = await client.get(url)
        ...         return response.json()
        >>> data = fetch_data("https://api.example.com")  # Runs synchronously
    """

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> T:
        return async_to_sync(func(*args, **kwargs))

    return wrapper


async def safe_gather(
    *coros: Awaitable[T],
    return_exceptions: bool = True,
) -> list[T | BaseException]:
    """Safely gather multiple coroutines with error handling.

    Like asyncio.gather but with additional logging and error context.

    Args:
        *coros: Coroutines to execute concurrently.
        return_exceptions: If True, exceptions are returned in results list.

    Returns:
        List of results (or exceptions if return_exceptions=True).
    """
    results = await asyncio.gather(*coros, return_exceptions=return_exceptions)

    # Log any exceptions that occurred
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            error = create_error(
                AsyncErrorCode.TASK_EXECUTION_FAILED,
                f"gather_task_{i}",
                technical_message=str(result),
            )
            logger.warning(f"[{error.code.value}] Task {i} failed: {result}")

    return results


async def with_timeout(
    coro: Awaitable[T],
    timeout: float,
    operation_name: str = "operation",
) -> T:
    """Execute a coroutine with timeout and proper error handling.

    Args:
        coro: Coroutine to execute.
        timeout: Timeout in seconds.
        operation_name: Name for error reporting.

    Returns:
        Result of the coroutine.

    Raises:
        asyncio.TimeoutError: With enhanced error context if timeout exceeded.
    """
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except asyncio.TimeoutError:
        error = create_error(
            AsyncErrorCode.OPERATION_TIMEOUT,
            operation_name,
            user_message=f"The operation timed out after {timeout} seconds. Please try again.",
            context={"timeout_seconds": timeout, "operation": operation_name},
        )
        logger.error(f"[{error.code.value}] {operation_name} timed out after {timeout}s")
        raise asyncio.TimeoutError(
            f"[{error.code.value}] {operation_name} timed out after {timeout} seconds"
        )


class AsyncContextManager:
    """Helper for creating async context managers with proper cleanup.

    Ensures resources are properly cleaned up even on errors.

    Example:
        >>> async with AsyncContextManager(setup_resource, cleanup_resource) as resource:
        ...     await use_resource(resource)
    """

    def __init__(
        self,
        setup: Callable[[], Awaitable[T]],
        cleanup: Callable[[T], Awaitable[None]],
    ):
        self._setup = setup
        self._cleanup = cleanup
        self._resource: T | None = None

    async def __aenter__(self) -> T:
        self._resource = await self._setup()
        return self._resource

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> bool:
        if self._resource is not None:
            try:
                await self._cleanup(self._resource)
            except Exception as e:
                error = create_error(
                    AsyncErrorCode.RESOURCE_BUSY,
                    "context_manager_cleanup",
                    technical_message=str(e),
                )
                logger.warning(f"[{error.code.value}] Cleanup error: {e}")
        return False  # Don't suppress exceptions
