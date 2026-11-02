"""FastAPI application entry point for Omni Backend.

This module initializes and configures the FastAPI application with:
- WebSocket and REST API endpoints
- CORS middleware
- Logging configuration
- OpenAPI documentation
"""

import os
from contextlib import asynccontextmanager

import nest_asyncio
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware import Middleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.cors import CORSMiddleware

from src.configs.settings import settings  # loads .env first
from src.auth import SessionGate
from src.dependencies import init_managers
from src.routers.agents import router as agents_router
from src.routers.campaigns import router as campaigns_router
from src.routers import chat
from src.routers import settings as settings_router
from src.routers import auth as auth_router
from src.routers import admin, evals, feedback, handoffs, mcp, share, slack, software_developer, teams, websocket
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
    ),
    Middleware(SessionGate),  # email and password sign-in when DAXAGENT_AUTH=on (the hosted app)
]
# The built frontend, when this server also serves the page (Railway: one service, one domain).
STATIC_DIR = os.getenv("DAXAGENT_STATIC_DIR", "")


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
    title="DAXAGENT",
    lifespan=lifespan,
    middleware=middleware,
)


app.include_router(chat.router, prefix="/chats", tags=["Chat Management"])
app.include_router(
    websocket.router,
    prefix="/ws",
    tags=["WebSocket"],
    responses={404: {"description": "Not found"}},
)
app.include_router(
    settings_router.router,
    prefix="/settings",
    tags=["Settings Management"],
    responses={404: {"description": "Not found"}},
)
app.include_router(
    software_developer.router,
    prefix="/software-developer",
    tags=["Software Developer"],
    responses={404: {"description": "Not found"}},
)
app.include_router(
    mcp.router,
    prefix="/mcp",
    tags=["MCP Servers"],
    responses={404: {"description": "Not found"}},
)
app.include_router(
    share.router,
    prefix="/share",
    tags=["Chat Sharing"],
    responses={404: {"description": "Not found"}},
)
app.include_router(agents_router, prefix="/agents", tags=["Agent Runtime"])
app.include_router(campaigns_router, prefix="/campaigns", tags=["Campaigns"])
app.include_router(feedback.router, prefix="/feedback", tags=["Feedback"])
app.include_router(admin.router, prefix="/admin", tags=["Admin"])
app.include_router(evals.router, prefix="/admin/evals", tags=["Evaluation"])
app.include_router(handoffs.router, prefix="/handoffs", tags=["Handoffs"])
app.include_router(teams.router, prefix="/teams", tags=["Teams bot"])
app.include_router(slack.router, prefix="/slack", tags=["Slack bot"])
app.include_router(auth_router.router, prefix="/auth", tags=["Sign-in"])


# @app.get("/")
# async def root():
#     """
#     Root endpoint
#     """
#     return {"message": f"Welcome to {settings.PROJECT_NAME}"}


    # OpenAPI schema uses default FastAPI generation (no Bearer auth)

# WEBSOCKET Swagger Docs


@app.get("/", response_class=HTMLResponse)
async def serve_html(request: Request):
    """Serve the main HTML page with backend URL.

    Args:
        request: FastAPI request object.

    Returns:
        HTMLResponse: The main index.html page content with template variables.
    """
    if STATIC_DIR:
        return FileResponse(os.path.join(STATIC_DIR, "index.html"))
    return templates.TemplateResponse(
        "index.html",
        {"request": request},
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
        {"request": request},
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
        {"request": request},
    )


@app.get("/software-developer", response_class=HTMLResponse)
async def serve_software_developer_html(request: Request):
    """Serve the Software Developer AI coding assistant HTML page.

    Args:
        request: FastAPI request object.

    Returns:
        HTMLResponse: The software_developer.html page.
    """
    return templates.TemplateResponse("software_developer.html", {"request": request})


@app.get("/omni", response_class=HTMLResponse)
async def serve_omni_chat(request: Request):
    """Serve the Omni chat UI.

    Args:
        request: FastAPI request object.

    Returns:
        HTMLResponse: The omni_chat.html page.
    """
    return templates.TemplateResponse("omni_chat.html", {"request": request})


@app.get("/health")
async def health_check():
    """Check application health status.

    Returns:
        dict: Health status containing 'status' (ok) and descriptive message.
    """
    return {"status": "ok", "message": "Service is running"}


if STATIC_DIR and os.path.isdir(STATIC_DIR):
    app.mount("/", StaticFiles(directory=STATIC_DIR), name="frontend")  # after every API route


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(settings.PORT), reload=False)
