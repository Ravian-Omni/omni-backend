from fastapi.staticfiles import StaticFiles
from pathlib import Path
from fastapi.responses import HTMLResponse
from dotenv import load_dotenv
from fastapi import FastAPI
from starlette.responses import RedirectResponse
# from routers import apis
from routers import chat
from starlette.middleware.cors import CORSMiddleware
from fastapi.middleware import Middleware
from utilities.logging import setup_logging, cleanup_logging
from contextlib import asynccontextmanager
from dependencies import mongodb_service, init_managers
from configs.settings import settings
from fastapi.openapi.utils import get_openapi
import os
from initialization import AppInitializer
import nest_asyncio
from routers import ws
# Initialize application
app_file_path = os.path.dirname(os.path.abspath(__file__))
initializer = AppInitializer(settings, app_file_path)

load_dotenv()

base = "/autogen/"
prefix = base + "api/v1"
openapi_url = prefix + "/openapi.json"
docs_url = prefix + "/docs"

middleware = [Middleware(CORSMiddleware, allow_origins=[
                         '*'], allow_credentials=True, allow_methods=['*'], allow_headers=['*'])]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for the FastAPI application
    Handles startup and shutdown events
    """

    nest_asyncio.apply()  # 🧠 Patch the loop here

    # Startup: Setup logging first
    logger = setup_logging(log_file="app.log")
    logger.info("🚀 Starting FastAPI application...")

    try:
        # Startup: Connect to databases
        logger.info("📊 Connecting to MongoDB...")
        await mongodb_service.connect()
        logger.info("✅ MongoDB connection established")

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
        logger.info("📊 Closing MongoDB connections...")
        await mongodb_service.close()
        logger.info("✅ MongoDB connections closed")

        # Add any other cleanup tasks here
        logger.info("🧹 Application shutdown completed successfully")

    except Exception as e:
        logger.error(f"❌ Error during shutdown: {e}")
    finally:
        # Cleanup logging resources
        cleanup_logging()

app = FastAPI(
    title="Autogen FastAPI Backend",
    openapi_url=openapi_url,
    # docs_url=docs_url,
    redoc_url=None,
    lifespan=lifespan,
    middleware=middleware
)


# app.include_router(apis.router)
app.include_router(
    chat.router,
    prefix="/chats",
    tags=["Chat Management"]
)
app.include_router(
    ws.router,
    prefix="/ws",
    tags=["websocket"],
    responses={404: {"description": "Not found"}},
)


# @app.get("/")
# async def root():
#     """
#     Root endpoint
#     """
#     return {"message": f"Welcome to {settings.PROJECT_NAME}"}

@app.get(path=base, include_in_schema=False)
async def docs_redirect():
    return RedirectResponse(url=docs_url)


def custom_openapi():
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
            "description": "Enter your AWS Cognito JWT token in the format 'Bearer <token>'."
        }
    }
    # Apply security to all endpoints
    for path in openapi_schema["paths"]:
        for method in openapi_schema["paths"][path]:
            openapi_schema["paths"][path][method]["security"] = [
                {"BearerAuth": []}]
    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi

# WEBSOCKET Swagger Docs


app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/", response_class=HTMLResponse)
async def serve_html():
    html_content = Path("templates/index.html").read_text(encoding="utf-8")
    return HTMLResponse(content=html_content)

if __name__ == "__main__":
    import uvicorn
    import socket

    def is_port_available(port: int, host: str = "0.0.0.0") -> bool:
        """Check if a port is available for binding"""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                # Try binding to both 0.0.0.0 and localhost
                sock.bind((host, port))
                sock.close()

                # Double check with localhost
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock2:
                    sock2.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    sock2.bind(("127.0.0.1", port))
                    return True
        except OSError as e:
            print(f"⚠️  Port {port} check failed: {e}")
            return False

    def find_available_port(start_port: int, max_attempts: int = 10) -> int:
        """Find an available port starting from start_port"""
        for i in range(max_attempts):
            port = start_port + i
            if is_port_available(port):
                return port
        raise RuntimeError(
            f"No available port found in range {start_port}-{start_port + max_attempts - 1}")

    # Get the appropriate port based on execution mode
    preferred_port = initializer.get_port()

    try:
        # Check if preferred port is available
        if is_port_available(preferred_port):
            port = preferred_port
        else:
            print(
                f"⚠️  Port {preferred_port} is not available, finding alternative...")
            port = find_available_port(preferred_port)
            print(f"✅ Using port {port} instead")

        print(f"🚀 Starting server on port {port}")
        print(f"📁 App directory: {initializer.app_root}")
        print(f"🔧 Running as executable: {initializer.is_executable}")

        if initializer.is_executable:
            # For executable, pass the app object directly with no restart capability
            uvicorn.run(
                app,
                host="0.0.0.0",
                port=port,
                log_level="info",
                reload=False,
                access_log=False
            )
        else:
            # For development, use module string for hot reload
            uvicorn.run(
                "main:app",
                host="0.0.0.0",
                port=port,
                reload=True,
                log_level="info"
            )
    except Exception as e:
        print(f"❌ Failed to start server: {e}")
        print("💡 Tip: Check if the port is already in use or try a different port")
        exit(1)
