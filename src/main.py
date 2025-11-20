"""FastAPI application entry point for Omni Backend.

This module initializes and configures the FastAPI application with:
- WebSocket and REST API endpoints
- CORS middleware
- Logging configuration
- Authentication via AWS Cognito
- OpenAPI documentation
"""

import os
from contextlib import asynccontextmanager

import nest_asyncio
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware import Middleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.cors import CORSMiddleware

from src.configs.routes import RoutesConfig
from src.configs.settings import settings
from src.dependencies import init_managers

# from src.routers import apis
from src.routers import chat, config, ws
from src.utilities.logging import cleanup_logging, setup_logging

# Initialize application
load_dotenv()

# Initialize Jinja2 templates
templates = Jinja2Templates(directory="templates")

middleware = [
    Middleware(
        CORSMiddleware,
        allow_origins=["*"],
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
    nest_asyncio.apply()  # 🧠 Patch the loop here

    # Startup: Setup logging first
    logger = setup_logging(log_file="app.log")
    logger.info("🚀 Starting FastAPI application...")
    os.environ["HOME"] = os.path.expanduser("~")
    try:
        # Startup: Connect to databases
        logger.info("📊 Websocket Manager...")
        await init_managers()
        logger.info("✅ Websocket Manager established")
        # Add any other startup tasks here
        logger.info("🎯 Application startup completed successfully")

    except Exception as e:
        logger.error(f"❌ Failed to start application: {e}")
        raise

    yield  # App is running and handling requests here

    # Shutdown: Close database connections and cleanup
    logger.info("🛑 Shutting down FastAPI application...")

    try:
        # Add any other cleanup tasks here
        logger.info("🧹 Application shutdown completed successfully")

    except Exception as e:
        logger.error(f"❌ Error during shutdown: {e}")
    finally:
        # Cleanup logging resources
        cleanup_logging()


app = FastAPI(
    title="RAVIAN AI",
    lifespan=lifespan,
    middleware=middleware,
)


# app.include_router(apis.router)
app.include_router(chat.router, prefix="/chats", tags=["Chat Management"])
app.include_router(
    ws.router,
    prefix="/ws",
    tags=["websocket"],
    responses={404: {"description": "Not found"}},
)
app.include_router(
    config.router,
    prefix="/settings",
    tags=["Settings Management"],
    responses={404: {"description": "Not found"}},
)


# @app.get("/")
# async def root():
#     """
#     Root endpoint
#     """
#     return {"message": f"Welcome to {settings.PROJECT_NAME}"}


def custom_openapi():
    """Generate custom OpenAPI schema with Bearer authentication.

    Customizes the OpenAPI schema by adding AWS Cognito JWT Bearer token
    authentication to all endpoints.

    Returns:
        dict: The customized OpenAPI schema with security configurations.
    """
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    # Add BearerAuth security scheme
    openapi_schema["components"]["securitySchemes"] = {
        "BearerAuth": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": "Enter your AWS Cognito JWT token in the format 'Bearer <token>'.",
        }
    }
    # Apply security to all endpoints
    for path in openapi_schema["paths"]:
        for method in openapi_schema["paths"][path]:
            openapi_schema["paths"][path][method]["security"] = [{"BearerAuth": []}]
    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi

# WEBSOCKET Swagger Docs


@app.get("/", response_class=HTMLResponse)
async def serve_html(request: Request):
    """Serve the main HTML page with backend URL.

    Args:
        request: FastAPI request object.

    Returns:
        HTMLResponse: The main index.html page content with template variables.
    """
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "backend_url": RoutesConfig.BACKEND_URL_FALLBACK},
    )


@app.get("/chatbot", response_class=HTMLResponse)
async def serve_chat_html(request: Request):
    """Serve the chat HTML page with backend URL.

    Args:
        request: FastAPI request object.

    Returns:
        HTMLResponse: The chat.html page content with template variables.
    """
    return templates.TemplateResponse(
        "chat.html",
        {"request": request, "backend_url": RoutesConfig.BACKEND_URL_FALLBACK},
    )


@app.get("/capability", response_class=HTMLResponse)
async def serve_capability_html(request: Request):
    """Serve the capability demonstration HTML page with backend URL.

    Args:
        request: FastAPI request object.

    Returns:
        HTMLResponse: The capability.html page content with template variables.
    """
    return templates.TemplateResponse(
        "capability.html",
        {"request": request, "backend_url": RoutesConfig.BACKEND_URL_FALLBACK},
    )


@app.get("/health")
async def health_check():
    """Check application health status.

    Returns:
        dict: Health status containing 'status' (ok) and descriptive message.
    """
    return {"status": "ok", "message": "Service is running"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(settings.PORT), reload=False)
