from dotenv import load_dotenv
from fastapi import FastAPI
from starlette.responses import RedirectResponse
# from routers import apis
from routers import chat
from starlette.middleware.cors import CORSMiddleware
from fastapi.middleware import Middleware
from utilities.logging import logger
from contextlib import asynccontextmanager
from dependencies import mongodb_service
from configs.settings import settings
from fastapi.openapi.utils import get_openapi

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
     # Startup: Connect to databases
    logger.info("Connecting to MongoDB...")
    await mongodb_service.connect()
    logger.info("Connected to MongoDB")
    
    yield  # App is running and handling requests here
    
    # Shutdown: Close database connections
    logger.info("Closing database connections...")
    await mongodb_service.close()
    logger.info("MongoDB connection closed")

app = FastAPI(
    title="Autogen FastAPI Backend",
    openapi_url=openapi_url,
    # docs_url=docs_url,
    redoc_url=None,
    lifespan=lifespan,
    middleware=middleware
)


# app.include_router(apis.router)
app.include_router(chat.router)



@app.get("/")
async def root():
    """
    Root endpoint
    """
    return {"message": f"Welcome to {settings.PROJECT_NAME}"}

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

