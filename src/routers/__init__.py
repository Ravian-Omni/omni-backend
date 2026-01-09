"""API routers for the application.

This module exports all router instances for registration with the FastAPI app.

Routers:
- chat: Chat management REST API endpoints
- settings: Settings and configuration management endpoints
- websocket: WebSocket endpoints for real-time AI chat
"""

from src.routers.chat import router as chat_router
from src.routers.settings import router as settings_router
from src.routers.websocket import router as websocket_router

__all__ = [
    "chat_router",
    "settings_router",
    "websocket_router",
]
