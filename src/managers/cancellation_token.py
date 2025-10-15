"""Cancellation token for managing async task cancellation.

This module provides a thread-safe cancellation token implementation
for coordinating cancellation of async operations and futures.
"""

import threading
from asyncio import Future
from collections.abc import Callable
from typing import Any


class CancellationToken:
    """A token used to cancel pending async calls.

    Provides thread-safe cancellation mechanism for async operations
    with callback support. Can be linked to asyncio Futures to
    automatically cancel them when the token is cancelled.

    Attributes:
        _cancelled: Boolean flag indicating if token has been cancelled.
        _lock: Thread lock for ensuring thread-safe operations.
        _callbacks: List of callbacks to execute on cancellation.
    """

    def __init__(self) -> None:
        """Initialize CancellationToken with default uncancelled state."""
        self._cancelled: bool = False
        self._lock: threading.Lock = threading.Lock()
        self._callbacks: list[Callable[[], None]] = []

    def cancel(self) -> None:
        """Cancel pending async calls linked to this cancellation token.

        Executes all registered callbacks in a thread-safe manner.
        Once cancelled, the token remains cancelled.
        """
        with self._lock:
            if not self._cancelled:
                self._cancelled = True
                for callback in self._callbacks:
                    callback()

    def is_cancelled(self) -> bool:
        """Check if the CancellationToken has been cancelled.

        Returns:
            True if token has been cancelled, False otherwise.
        """
        with self._lock:
            return self._cancelled

    def add_callback(self, callback: Callable[[], None]) -> None:
        """Attach a callback that will be called when cancel is invoked.

        If the token is already cancelled, the callback is executed immediately.
        Otherwise, it is stored and will be called when cancel() is invoked.

        Args:
            callback: Function to call on cancellation (takes no arguments).
        """
        with self._lock:
            if self._cancelled:
                callback()
            else:
                self._callbacks.append(callback)

    def link_future(self, future: Future[Any]) -> Future[Any]:
        """Link a pending async call to a token to allow its cancellation.

        If the token is already cancelled, the future is cancelled immediately.
        Otherwise, a callback is registered to cancel the future when this
        token is cancelled.

        Args:
            future: asyncio Future to link to this token.

        Returns:
            The same future that was passed in (for chaining).
        """
        with self._lock:
            if self._cancelled:
                future.cancel()
            else:

                def _cancel() -> None:
                    """Cancel the linked future."""
                    future.cancel()

                self._callbacks.append(_cancel)
        return future
