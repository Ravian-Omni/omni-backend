"""Dependency injection and manager initialization for FastAPI application.

This module provides:
- WebSocket manager singleton instances
- Dependency providers for FastAPI routes
- Manager initialization and cleanup functions
- Custom exception handling for manager operations
"""

import asyncio
from fastapi import HTTPException, status
from loguru import logger

from src.configs.settings import settings
from src.database.connection import close_db, init_db
from src.database import load_all_api_keys, load_user_profile
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

        # Initialize SQLite database
        await init_db()
        from src.mcp_client.config import refresh as refresh_mcp_servers

        await refresh_mcp_servers()
        try:
            from src.agent_runtime import specialists

            await specialists.refresh()
        except Exception as e:
            logger.warning(f"MCP specialists not built at startup: {e}")
        logger.info("SQLite database initialized")

        # Restore persisted API keys into settings
        saved_keys = await load_all_api_keys()
        from src.services.settings_service import _PROVIDER_ATTR_MAP
        for provider, key in saved_keys.items():
            attr = _PROVIDER_ATTR_MAP.get(provider)
            if attr:
                settings.update_setting(attr, key)
        if saved_keys:
            logger.info(f"Restored API keys for: {', '.join(saved_keys.keys())}")
            # Clear LLM config cache so it rebuilds with the restored keys
            from src.configs.llm_configs_manager import LLMConfigManager
            LLMConfigManager.clear_cache()

        # Connections made or renewed in Composio since the last run (in the background: network)
        async def _sync_composio():
            try:
                from src.routers.mcp import sync_composio_servers

                await sync_composio_servers()
            except Exception as e:
                logger.warning(f"Composio connection sync skipped: {e}")

        asyncio.create_task(_sync_composio())

        async def _prefetch_tools():  # the first chat then skips the ~3 s tool listing
            from src.mcp_client import is_connected, list_tools, server_names

            for name in server_names():
                try:
                    if await is_connected(name):
                        await list_tools(name)
                except Exception as e:
                    logger.debug(f"Tool prefetch for {name} skipped: {e}")

        asyncio.create_task(_prefetch_tools())

        from src.agent_runtime import watcher

        asyncio.create_task(watcher.run_forever())  # the reply watcher; idle until switched on in Settings

        # Restore persisted user profile into settings
        _PROFILE_ATTR_MAP = {
            "first_name": "USER_FIRST_NAME",
            "last_name": "USER_LAST_NAME",
            "email": "USER_EMAIL",
            "dob": "USER_DOB",
            "gender": "USER_GENDER",
            "country": "USER_COUNTRY",
        }
        saved_profile = await load_user_profile()
        for field, value in saved_profile.items():
            attr = _PROFILE_ATTR_MAP.get(field)
            if attr and value:
                settings.update_setting(attr, value)
        if saved_profile:
            logger.info("Restored user profile from database")

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

    # Close SQLite database
    try:
        await close_db()
    except Exception as e:
        logger.error(f"Error closing SQLite database: {str(e)}")

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
