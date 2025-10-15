"""Dependency injection and manager initialization for FastAPI application.

This module provides:
- WebSocket manager singleton instances
- Dependency providers for FastAPI routes
- Manager initialization and cleanup functions
- Custom exception handling for manager operations
"""

from fastapi import HTTPException, status
from loguru import logger

from src.managers.connection import WebSocketManager

# Global manager instances


_websocket_manager: WebSocketManager | None = None

# Singleton instance of MongoDB service


async def get_websocket_manager() -> WebSocketManager:
    """Get the global WebSocket manager instance.

    Dependency provider for FastAPI routes that need access to the WebSocket manager.

    Returns:
        WebSocketManager: The initialized WebSocket manager instance.

    Raises:
        HTTPException: If the manager has not been initialized at startup.
    """
    if not _websocket_manager:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Connection manager not initialized",
        )
    return _websocket_manager


# Manager initialization and cleanup


async def init_managers() -> None:
    """Initialize all manager instances at application startup.

    Creates and configures the global WebSocket manager singleton.
    If initialization fails, performs cleanup and re-raises the exception.

    Raises:
        Exception: If manager initialization fails.
    """
    global _websocket_manager

    logger.info("Initializing managers...")

    try:
        # Initialize connection manager
        _websocket_manager = WebSocketManager()
        logger.info("Connection manager initialized")

    except Exception as e:
        logger.error(f"Failed to initialize managers: {str(e)}")
        await cleanup_managers()  # Cleanup any partially initialized managers
        raise


async def cleanup_managers() -> None:
    """Cleanup and shutdown all manager instances at application shutdown.

    Ensures all active WebSocket connections are properly closed and
    manager resources are released. Logs any errors but continues cleanup.
    """
    global _websocket_manager

    logger.info("Cleaning up managers...")

    # Cleanup connection manager first to ensure all active connections are closed
    if _websocket_manager:
        try:
            await _websocket_manager.cleanup()
        except Exception as e:
            logger.error(f"Error cleaning up connection manager: {str(e)}")
        finally:
            _websocket_manager = None

    logger.info("All managers cleaned up")


# Utility functions for dependency management


# Error handling for manager operations


class ManagerOperationError(Exception):
    """Custom exception for manager operation errors.

    Used to provide detailed context when a manager operation fails.

    Attributes:
        manager_name: Name of the manager that encountered the error.
        operation: The operation being performed when the error occurred.
        detail: Detailed error message or description.
    """

    def __init__(self, manager_name: str, operation: str, detail: str):
        """Initialize a ManagerOperationError.

        Args:
            manager_name: Name of the manager that encountered the error.
            operation: The operation being performed when the error occurred.
            detail: Detailed error message or description.
        """
        self.manager_name = manager_name
        self.operation = operation
        self.detail = detail
        super().__init__(f"{manager_name} failed during {operation}: {detail}")
