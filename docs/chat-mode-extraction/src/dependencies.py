"""Dependency injection for Chat Service.

This module provides:
- WebSocket manager singleton instance
- Dependency providers for FastAPI routes
- Manager initialization and cleanup functions
"""

from fastapi import HTTPException, status
from loguru import logger

from src.managers.connection import WebSocketManager

# Global manager instance
_websocket_manager: WebSocketManager | None = None


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
            detail="WebSocket manager not initialized",
        )
    return _websocket_manager


async def init_managers() -> None:
    """Initialize all manager instances at application startup.

    Creates and configures the global WebSocket manager singleton.

    Raises:
        Exception: If manager initialization fails.
    """
    global _websocket_manager

    logger.info("Initializing managers...")

    try:
        _websocket_manager = WebSocketManager()
        logger.info("WebSocket manager initialized")
    except Exception as e:
        logger.error(f"Failed to initialize managers: {str(e)}")
        await cleanup_managers()
        raise


async def cleanup_managers() -> None:
    """Cleanup and shutdown all manager instances at application shutdown.

    Ensures all active WebSocket connections are properly closed and
    manager resources are released.
    """
    global _websocket_manager

    logger.info("Cleaning up managers...")

    if _websocket_manager:
        try:
            await _websocket_manager.cleanup()
        except Exception as e:
            logger.error(f"Error cleaning up WebSocket manager: {str(e)}")
        finally:
            _websocket_manager = None

    logger.info("All managers cleaned up")
