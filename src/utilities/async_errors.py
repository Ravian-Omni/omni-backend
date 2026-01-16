"""Standardized async error handling module with error codes.

This module provides:
- Standardized error codes for all async-related errors
- User-friendly error messages for end users
- Technical details for the tech team
- Proper async exception handling utilities
"""

import asyncio
import functools
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Coroutine, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class AsyncErrorCode(Enum):
    """Standardized error codes for async operations.

    Error code format: ASYNC-XXXX
    - 1XXX: Connection errors
    - 2XXX: Task/coroutine errors
    - 3XXX: I/O errors (file, network)
    - 4XXX: Resource errors (locks, pools)
    - 5XXX: Timeout errors
    - 6XXX: Cancellation errors
    - 9XXX: Internal/unknown errors
    """

    # Connection errors (1XXX)
    WEBSOCKET_CONNECTION_FAILED = "ASYNC-1001"
    WEBSOCKET_DISCONNECTED = "ASYNC-1002"
    WEBSOCKET_SEND_FAILED = "ASYNC-1003"
    CONNECTION_POOL_EXHAUSTED = "ASYNC-1004"

    # Task errors (2XXX)
    TASK_CREATION_FAILED = "ASYNC-2001"
    TASK_EXECUTION_FAILED = "ASYNC-2002"
    TASK_NOT_FOUND = "ASYNC-2003"
    TASK_ALREADY_RUNNING = "ASYNC-2004"
    COROUTINE_NOT_AWAITED = "ASYNC-2005"

    # I/O errors (3XXX)
    FILE_READ_FAILED = "ASYNC-3001"
    FILE_WRITE_FAILED = "ASYNC-3002"
    NETWORK_REQUEST_FAILED = "ASYNC-3003"
    HTTP_DOWNLOAD_FAILED = "ASYNC-3004"
    EMAIL_SEND_FAILED = "ASYNC-3005"
    EMAIL_READ_FAILED = "ASYNC-3006"

    # Resource errors (4XXX)
    LOCK_ACQUISITION_FAILED = "ASYNC-4001"
    RESOURCE_BUSY = "ASYNC-4002"
    RESOURCE_NOT_AVAILABLE = "ASYNC-4003"
    BROWSER_SESSION_FAILED = "ASYNC-4004"

    # Timeout errors (5XXX)
    OPERATION_TIMEOUT = "ASYNC-5001"
    CONNECTION_TIMEOUT = "ASYNC-5002"
    TASK_TIMEOUT = "ASYNC-5003"
    INPUT_TIMEOUT = "ASYNC-5004"

    # Cancellation errors (6XXX)
    OPERATION_CANCELLED = "ASYNC-6001"
    SESSION_CANCELLED = "ASYNC-6002"
    BROWSER_CANCELLED = "ASYNC-6003"

    # Internal errors (9XXX)
    INTERNAL_ERROR = "ASYNC-9001"
    EVENT_LOOP_ERROR = "ASYNC-9002"
    UNKNOWN_ERROR = "ASYNC-9999"


@dataclass
class AsyncErrorDetails:
    """Detailed error information for async operations."""

    code: AsyncErrorCode
    user_message: str  # User-friendly message
    technical_message: str  # Technical details for dev team
    operation: str  # What operation was being performed
    context: dict[str, Any] | None = None  # Additional context
    original_exception: Exception | None = None  # Original exception if any

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "error_code": self.code.value,
            "message": self.user_message,
            "operation": self.operation,
            "details": {
                "technical_message": self.technical_message,
                "context": self.context or {},
            },
        }

    def to_user_response(self) -> dict[str, Any]:
        """Create a user-friendly error response."""
        return {
            "success": False,
            "error": {
                "code": self.code.value,
                "message": self.user_message,
                "support_reference": f"Please contact support with code: {self.code.value}",
            },
        }


class AsyncOperationError(Exception):
    """Base exception for async operation errors."""

    def __init__(self, details: AsyncErrorDetails):
        self.details = details
        super().__init__(details.user_message)

    @property
    def code(self) -> str:
        return self.details.code.value

    @property
    def user_message(self) -> str:
        return self.details.user_message

    @property
    def technical_message(self) -> str:
        return self.details.technical_message


# Specific exception classes for common error types
class ConnectionError(AsyncOperationError):
    """WebSocket/network connection errors."""

    pass


class TaskError(AsyncOperationError):
    """Task execution errors."""

    pass


class IOError(AsyncOperationError):
    """File/network I/O errors."""

    pass


class ResourceError(AsyncOperationError):
    """Resource management errors."""

    pass


class TimeoutError(AsyncOperationError):
    """Operation timeout errors."""

    pass


class CancellationError(AsyncOperationError):
    """Operation cancellation errors."""

    pass


def create_error(
    code: AsyncErrorCode,
    operation: str,
    user_message: str | None = None,
    technical_message: str | None = None,
    context: dict[str, Any] | None = None,
    original_exception: Exception | None = None,
) -> AsyncErrorDetails:
    """Create a standardized error details object.

    Args:
        code: Error code from AsyncErrorCode enum
        operation: Description of the operation that failed
        user_message: Optional custom user message (defaults to standard message)
        technical_message: Optional technical details
        context: Additional context dictionary
        original_exception: Original exception if any

    Returns:
        AsyncErrorDetails object
    """
    # Default user messages for each error code
    default_user_messages = {
        AsyncErrorCode.WEBSOCKET_CONNECTION_FAILED: "Unable to establish connection. Please check your internet and try again.",
        AsyncErrorCode.WEBSOCKET_DISCONNECTED: "Connection was interrupted. Please refresh and try again.",
        AsyncErrorCode.WEBSOCKET_SEND_FAILED: "Failed to send message. Please try again.",
        AsyncErrorCode.CONNECTION_POOL_EXHAUSTED: "Service is temporarily busy. Please wait a moment and try again.",
        AsyncErrorCode.TASK_CREATION_FAILED: "Unable to start the operation. Please try again.",
        AsyncErrorCode.TASK_EXECUTION_FAILED: "The operation encountered an error. Please try again.",
        AsyncErrorCode.TASK_NOT_FOUND: "The requested task was not found.",
        AsyncErrorCode.TASK_ALREADY_RUNNING: "This operation is already in progress.",
        AsyncErrorCode.COROUTINE_NOT_AWAITED: "Internal processing error. Please try again.",
        AsyncErrorCode.FILE_READ_FAILED: "Unable to read the file. Please check if it exists and try again.",
        AsyncErrorCode.FILE_WRITE_FAILED: "Unable to save the file. Please check permissions and try again.",
        AsyncErrorCode.NETWORK_REQUEST_FAILED: "Network request failed. Please check your connection and try again.",
        AsyncErrorCode.HTTP_DOWNLOAD_FAILED: "Failed to download content. Please try again.",
        AsyncErrorCode.EMAIL_SEND_FAILED: "Failed to send email. Please verify recipients and try again.",
        AsyncErrorCode.EMAIL_READ_FAILED: "Failed to read email. Please check your email settings.",
        AsyncErrorCode.LOCK_ACQUISITION_FAILED: "Resource is currently locked. Please try again.",
        AsyncErrorCode.RESOURCE_BUSY: "Service is busy processing other requests. Please wait.",
        AsyncErrorCode.RESOURCE_NOT_AVAILABLE: "Required resource is not available. Please try again later.",
        AsyncErrorCode.BROWSER_SESSION_FAILED: "Browser session failed. Please try again.",
        AsyncErrorCode.OPERATION_TIMEOUT: "The operation took too long. Please try again with a simpler request.",
        AsyncErrorCode.CONNECTION_TIMEOUT: "Connection timed out. Please check your internet and try again.",
        AsyncErrorCode.TASK_TIMEOUT: "Task timed out. Please try again.",
        AsyncErrorCode.INPUT_TIMEOUT: "Waiting for input timed out. Please respond faster next time.",
        AsyncErrorCode.OPERATION_CANCELLED: "The operation was cancelled.",
        AsyncErrorCode.SESSION_CANCELLED: "Your session was cancelled.",
        AsyncErrorCode.BROWSER_CANCELLED: "Browser operation was cancelled.",
        AsyncErrorCode.INTERNAL_ERROR: "An internal error occurred. Please try again.",
        AsyncErrorCode.EVENT_LOOP_ERROR: "A system error occurred. Please refresh and try again.",
        AsyncErrorCode.UNKNOWN_ERROR: "An unexpected error occurred. Please try again.",
    }

    final_user_message = user_message or default_user_messages.get(
        code, "An error occurred. Please try again."
    )

    final_technical_message = technical_message or (
        str(original_exception) if original_exception else f"{code.name} in {operation}"
    )

    return AsyncErrorDetails(
        code=code,
        user_message=final_user_message,
        technical_message=final_technical_message,
        operation=operation,
        context=context,
        original_exception=original_exception,
    )


def handle_async_errors(
    operation_name: str,
    default_error_code: AsyncErrorCode = AsyncErrorCode.TASK_EXECUTION_FAILED,
):
    """Decorator for handling async errors with standardized error codes.

    Args:
        operation_name: Name of the operation for error reporting
        default_error_code: Default error code if no specific mapping exists

    Usage:
        @handle_async_errors("image_download")
        async def download_image(url: str) -> bytes:
            ...
    """

    def decorator(
        func: Callable[..., Coroutine[Any, Any, T]],
    ) -> Callable[..., Coroutine[Any, Any, T]]:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> T:
            try:
                return await func(*args, **kwargs)
            except AsyncOperationError:
                # Re-raise our custom errors
                raise
            except asyncio.CancelledError as e:
                error = create_error(
                    AsyncErrorCode.OPERATION_CANCELLED,
                    operation_name,
                    original_exception=e,
                )
                logger.warning(
                    f"[{error.code.value}] {operation_name} cancelled: {error.technical_message}"
                )
                raise CancellationError(error) from e
            except asyncio.TimeoutError as e:
                error = create_error(
                    AsyncErrorCode.OPERATION_TIMEOUT,
                    operation_name,
                    original_exception=e,
                )
                logger.error(
                    f"[{error.code.value}] {operation_name} timeout: {error.technical_message}"
                )
                raise TimeoutError(error) from e
            except OSError as e:
                # File I/O errors
                error_code = (
                    AsyncErrorCode.FILE_READ_FAILED
                    if "read" in operation_name.lower()
                    else AsyncErrorCode.FILE_WRITE_FAILED
                )
                error = create_error(
                    error_code,
                    operation_name,
                    original_exception=e,
                )
                logger.error(
                    f"[{error.code.value}] {operation_name} I/O error: {error.technical_message}"
                )
                raise IOError(error) from e
            except Exception as e:
                error = create_error(
                    default_error_code,
                    operation_name,
                    original_exception=e,
                    context={"exception_type": type(e).__name__},
                )
                logger.error(
                    f"[{error.code.value}] {operation_name} error: {error.technical_message}"
                )
                raise TaskError(error) from e

        return wrapper

    return decorator


async def safe_task_execution(
    coro: Coroutine[Any, Any, T],
    operation_name: str,
    timeout: float | None = None,
    on_error: Callable[[AsyncErrorDetails], Any] | None = None,
    on_cancel: Callable[[], Any] | None = None,
) -> T | None:
    """Execute a coroutine with comprehensive error handling.

    Args:
        coro: Coroutine to execute
        operation_name: Name for error reporting
        timeout: Optional timeout in seconds
        on_error: Optional callback for error handling
        on_cancel: Optional callback for cancellation

    Returns:
        Result of coroutine or None on error
    """
    try:
        if timeout:
            return await asyncio.wait_for(coro, timeout=timeout)
        return await coro
    except asyncio.CancelledError:
        logger.info(f"Task cancelled: {operation_name}")
        if on_cancel:
            on_cancel()
        return None
    except asyncio.TimeoutError:
        error = create_error(
            AsyncErrorCode.TASK_TIMEOUT,
            operation_name,
            context={"timeout_seconds": timeout},
        )
        logger.error(f"[{error.code.value}] Task timeout: {operation_name}")
        if on_error:
            on_error(error)
        return None
    except AsyncOperationError as e:
        logger.error(f"[{e.code}] {operation_name}: {e.technical_message}")
        if on_error:
            on_error(e.details)
        return None
    except Exception as e:
        error = create_error(
            AsyncErrorCode.TASK_EXECUTION_FAILED,
            operation_name,
            original_exception=e,
        )
        logger.error(f"[{error.code.value}] {operation_name} failed: {str(e)}")
        if on_error:
            on_error(error)
        return None


class TaskTracker:
    """Track and manage async tasks with error handling.

    Provides centralized task management with:
    - Task creation with automatic error callbacks
    - Task cancellation
    - Task status monitoring
    """

    def __init__(self, name: str = "default"):
        self.name = name
        self._tasks: dict[str, asyncio.Task] = {}
        self._lock = asyncio.Lock()

    async def create_task(
        self,
        coro: Coroutine[Any, Any, T],
        task_id: str,
        on_complete: Callable[[T], Any] | None = None,
        on_error: Callable[[AsyncErrorDetails], Any] | None = None,
    ) -> asyncio.Task[T]:
        """Create and track an async task with error handling.

        Args:
            coro: Coroutine to run
            task_id: Unique identifier for the task
            on_complete: Optional callback on successful completion
            on_error: Optional callback on error

        Returns:
            The created asyncio.Task
        """
        async with self._lock:
            if task_id in self._tasks and not self._tasks[task_id].done():
                error = create_error(
                    AsyncErrorCode.TASK_ALREADY_RUNNING,
                    f"create_task({task_id})",
                    context={"task_id": task_id},
                )
                raise TaskError(error)

            async def wrapped_coro():
                try:
                    result = await coro
                    if on_complete:
                        on_complete(result)
                    return result
                except asyncio.CancelledError:
                    logger.info(f"Task {task_id} was cancelled")
                    raise
                except Exception as e:
                    error = create_error(
                        AsyncErrorCode.TASK_EXECUTION_FAILED,
                        f"task:{task_id}",
                        original_exception=e,
                        context={"task_id": task_id},
                    )
                    logger.error(f"[{error.code.value}] Task {task_id} failed: {str(e)}")
                    if on_error:
                        on_error(error)
                    raise

            task = asyncio.create_task(wrapped_coro())
            self._tasks[task_id] = task

            # Add done callback for cleanup
            task.add_done_callback(lambda t: self._on_task_done(task_id, t))

            return task

    def _on_task_done(self, task_id: str, task: asyncio.Task) -> None:
        """Handle task completion."""
        if task.cancelled():
            logger.debug(f"Task {task_id} completed (cancelled)")
        elif task.exception():
            logger.debug(f"Task {task_id} completed (error)")
        else:
            logger.debug(f"Task {task_id} completed (success)")

    async def cancel_task(self, task_id: str) -> bool:
        """Cancel a tracked task.

        Args:
            task_id: ID of task to cancel

        Returns:
            True if task was cancelled, False if not found or already done
        """
        async with self._lock:
            if task_id not in self._tasks:
                return False

            task = self._tasks[task_id]
            if task.done():
                return False

            task.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=2.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass

            return True

    async def cancel_all(self) -> None:
        """Cancel all tracked tasks."""
        async with self._lock:
            for task_id in list(self._tasks.keys()):
                task = self._tasks[task_id]
                if not task.done():
                    task.cancel()

            # Wait for all tasks to complete
            if self._tasks:
                await asyncio.gather(
                    *self._tasks.values(),
                    return_exceptions=True,
                )
            self._tasks.clear()

    def get_active_tasks(self) -> list[str]:
        """Get list of active task IDs."""
        return [tid for tid, task in self._tasks.items() if not task.done()]

    async def cleanup(self) -> None:
        """Clean up completed tasks."""
        async with self._lock:
            completed = [tid for tid, task in self._tasks.items() if task.done()]
            for task_id in completed:
                del self._tasks[task_id]
