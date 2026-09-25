"""API routers for Chat Service.

This module exports all router instances for registration with the FastAPI app.
"""

from src.routers.chat import router as chat_router
from src.routers.websocket import router as websocket_router

__all__ = [
    "chat_router",
    "websocket_router",
]
