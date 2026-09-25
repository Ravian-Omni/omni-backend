"""FastAPI application entry point for Chat Service.

This module initializes and configures a lightweight FastAPI application
specifically for Chat Mode functionality, optimized for AWS ECS deployment.
"""

import os
from contextlib import asynccontextmanager

import nest_asyncio
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware import Middleware
from fastapi.responses import JSONResponse
from starlette.middleware.cors import CORSMiddleware

from src.configs.settings import settings
from src.dependencies import init_managers, cleanup_managers
from src.routers import chat, websocket
from src.utilities.logging import setup_logging, cleanup_logging

# Load environment variables
load_dotenv()

# CORS Middleware configuration
middleware = [
    Middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Configure appropriately for production
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage FastAPI application lifespan.

    Handles startup and shutdown events including:
    - Logging initialization
    - WebSocket manager setup
    - Resource cleanup on shutdown

    Args:
        app: FastAPI application instance.

    Yields:
        None: Control during application runtime.
    """
    nest_asyncio.apply()

    # Startup
    logger = setup_logging(log_file="chat-service.log")
    logger.info("🚀 Starting Chat Service...")
    
    os.environ["HOME"] = os.path.expanduser("~")
    
    try:
        logger.info("📊 Initializing WebSocket Manager...")
        await init_managers()
        logger.info("✅ WebSocket Manager initialized")
        logger.info("🎯 Chat Service startup completed successfully")
    except Exception as e:
        logger.error(f"❌ Failed to start Chat Service: {e}")
        raise

    yield  # Application is running

    # Shutdown
    logger.info("🛑 Shutting down Chat Service...")
    try:
        await cleanup_managers()
        logger.info("🧹 Chat Service shutdown completed successfully")
    except Exception as e:
        logger.error(f"❌ Error during shutdown: {e}")
    finally:
        cleanup_logging()


# Create FastAPI application
app = FastAPI(
    title="Chat Service",
    description="Lightweight chat service with AI capabilities",
    version="1.0.0",
    lifespan=lifespan,
    middleware=middleware,
)

# Include routers
app.include_router(
    chat.router,
    prefix="/chats",
    tags=["Chat Management"],
)
app.include_router(
    websocket.router,
    prefix="/ws",
    tags=["WebSocket"],
)


@app.get("/health")
async def health_check():
    """Health check endpoint for load balancer and container orchestration.

    Returns:
        dict: Health status with service name and status indicator.
    """
    return {
        "status": "healthy",
        "service": "chat-service",
        "version": "1.0.0"
    }


@app.get("/")
async def root():
    """Root endpoint with service information.

    Returns:
        dict: Service name, version, and available endpoints.
    """
    return {
        "service": "Chat Service",
        "version": "1.0.0",
        "endpoints": {
            "health": "/health",
            "create_chat": "POST /chats/new",
            "get_history": "GET /chats/history/{user_id}/{chat_id}",
            "websocket": "WS /ws/chat/{chat_id}"
        }
    }


# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """Handle unhandled exceptions globally.

    Args:
        request: The incoming request.
        exc: The exception that was raised.

    Returns:
        JSONResponse: Error response with status code 500.
    """
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "detail": str(exc) if settings.DEBUG else "An unexpected error occurred"
        }
    )


if __name__ == "__main__":
    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=int(settings.PORT),
        reload=settings.DEBUG,
    )
