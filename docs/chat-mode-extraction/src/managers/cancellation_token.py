"""Cancellation token for managing task cancellation.

This module provides a thread-safe cancellation token implementation
for gracefully stopping long-running async operations.
"""

import threading
from typing import Callable, List


class CancellationToken:
    """Thread-safe cancellation token for async task management.

    Provides a mechanism to signal cancellation to running tasks and
    register callbacks that are invoked when cancellation occurs.

    Attributes:
        _cancelled: Internal flag indicating cancellation state.
        _lock: Thread lock for synchronization.
        _callbacks: List of registered cancellation callbacks.
    """

    def __init__(self):
        """Initialize a new CancellationToken in non-cancelled state."""
        self._cancelled = False
        self._lock = threading.Lock()
        self._callbacks: List[Callable] = []

    def cancel(self) -> None:
        """Request cancellation of the operation.

        Sets the cancelled flag and invokes all registered callbacks.
        Thread-safe operation.
        """
        with self._lock:
            if not self._cancelled:
                self._cancelled = True
                # Invoke all registered callbacks
                for callback in self._callbacks:
                    try:
                        callback()
                    except Exception:
                        pass  # Ignore callback errors

    def is_cancelled(self) -> bool:
        """Check if cancellation has been requested.

        Returns:
            True if cancel() has been called, False otherwise.
        """
        with self._lock:
            return self._cancelled

    def register_callback(self, callback: Callable) -> None:
        """Register a callback to be invoked on cancellation.

        Args:
            callback: Callable to invoke when cancel() is called.
        """
        with self._lock:
            self._callbacks.append(callback)
            # If already cancelled, invoke immediately
            if self._cancelled:
                try:
                    callback()
                except Exception:
                    pass

    def reset(self) -> None:
        """Reset the token to non-cancelled state.

        Clears the cancelled flag and all registered callbacks.
        """
        with self._lock:
            self._cancelled = False
            self._callbacks.clear()

    def __bool__(self) -> bool:
        """Boolean representation returns cancellation state.

        Returns:
            True if NOT cancelled (operation should continue).
        """
        return not self.is_cancelled()
