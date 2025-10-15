"""Asynchronous helper utilities for converting async functions to synchronous.

This module provides utility functions to bridge between asynchronous and
synchronous code execution contexts, primarily for compatibility purposes.
"""

import asyncio


def async_to_sync(awaitable):
    """Convert an awaitable to synchronous execution.

    Execute an async function or coroutine synchronously using the current
    event loop. This is useful when you need to call async code from a
    synchronous context.

    Args:
        awaitable: An awaitable object (coroutine, task, or future) to execute.

    Returns:
        The result of the awaitable execution.

    Example:
        >>> async def fetch_data():
        ...     return {"status": "success"}
        >>> result = async_to_sync(fetch_data())
        >>> print(result)
        {'status': 'success'}

    Note:
        This function uses the current event loop and blocks until completion.
        Use with caution in async contexts as it may cause deadlocks.
    """
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(awaitable)
