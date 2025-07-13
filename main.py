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
from routers import ws, config
# Initialize application
app_file_path = os.path.dirname(os.path.abspath(__file__))
initializer = AppInitializer(settings, app_file_path)

load_dotenv()

base = "/autogen/"
prefix = base + "api/v1"
openapi_url = prefix + "/openapi.json"
docs_url = prefix + "/docs"

middleware = [Middleware(CORSMiddleware, allow_origins=['*'], allow_credentials=True, allow_methods=['*'], allow_headers=['*'])]

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
            openapi_schema["paths"][path][method]["security"] = [{"BearerAuth": []}]
    app.openapi_schema = openapi_schema
    return app.openapi_schema

app.openapi = custom_openapi

#WEBSOCKET Swagger Docs


from fastapi.responses import HTMLResponse
from pathlib import Path
from fastapi.staticfiles import StaticFiles

app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/", response_class=HTMLResponse)
async def serve_html():
    html_content = Path("templates/index.html").read_text(encoding="utf-8")
    return HTMLResponse(content=html_content)