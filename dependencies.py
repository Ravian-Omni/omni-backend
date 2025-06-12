from fastapi import Depends
from typing import Annotated
from configs.settings import settings
from utilities.mongodb_service import MongoDBService


# Singleton instance of MongoDB service
mongodb_service = MongoDBService(
    connection_string=settings.MONGODB_URI,
    database_name=settings.DATABASE_NAME
)


# Dependencies
async def get_mongodb_service():
    """
    Get MongoDB service dependency
    This allows us to mock the database service in tests
    """
    return mongodb_service
