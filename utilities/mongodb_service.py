# src/services/mongodb_service.py
from pymongo import MongoClient
from pymongo.errors import PyMongoError
from configs.settings import settings
from loguru import logger
import asyncio
from datetime import datetime
from typing import List, Dict, Optional

from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId
from typing import List, Dict, Any, Optional, Union
import logging
from pydantic import BaseModel


class PyObjectId(ObjectId):
    """Custom ObjectId class that works with Pydantic models"""
    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, v):
        if not ObjectId.is_valid(v):
            raise ValueError("Invalid ObjectId")
        return ObjectId(v)

    @classmethod
    def __modify_schema__(cls, field_schema):
        field_schema.update(type="string")


class MongoDBService:
    """
    MongoDB database handler for FastAPI applications.
    Provides methods for all database operations.
    """
    def __init__(self, connection_string: str = settings.MONGODB_URI, database_name: str = "OMNI-DB"):
        """
        Initialize MongoDB connection
        
        Args:
            connection_string: MongoDB connection URI
            database_name: Name of the database to use
        """
        self.client = None
        self.db = None
        self.connection_string = connection_string
        self.database_name = database_name
        self.logger = logging.getLogger("mongodb")

    async def connect(self):
        """Connect to MongoDB database"""
        try:
            # Enhanced SSL configuration for PyInstaller executables
            import sys
            import ssl
            import certifi
            
            # Check if running as PyInstaller executable
            is_executable = getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS')
            
            if is_executable:
                # For executables, try multiple connection approaches
                connection_approaches = [
                    # Approach 1: Use connection string as-is (safest for Atlas URIs)
                    {
                        'description': 'URI as-is',
                        'client_params': {}
                    },
                    # Approach 2: Use TLS CA file with bundled certificates
                    {
                        'description': 'with bundled TLS certificates',
                        'client_params': {
                            'tls': True,
                            'tlsCAFile': certifi.where()
                        }
                    },
                    # Approach 3: Disable TLS certificate verification
                    {
                        'description': 'with disabled TLS verification',
                        'client_params': {
                            'tls': True,
                            'tlsAllowInvalidCertificates': True
                        }
                    }
                ]
                
                connection_error = None
                for i, approach in enumerate(connection_approaches):
                    try:
                        self.logger.info(f"Attempting MongoDB connection {approach['description']} (attempt {i+1})")
                        self.client = AsyncIOMotorClient(self.connection_string, **approach['client_params'])
                        self.db = self.client[self.database_name]
                        # Ping the database to verify connection
                        await self.client.admin.command('ping')
                        self.logger.info(f"Connected to MongoDB using approach {i+1}: {approach['description']}")
                        return  # Success, exit the function
                    except Exception as e:
                        connection_error = e
                        self.logger.warning(f"Approach {i+1} failed: {e}")
                        if self.client:
                            self.client.close()
                            self.client = None
                        continue
                
                # If all approaches failed, raise the last error
                if connection_error:
                    raise connection_error
            else:
                # For development, use standard connection
                self.client = AsyncIOMotorClient(self.connection_string)
                self.db = self.client[self.database_name]
                # Ping the database to verify connection
                await self.client.admin.command('ping')
                self.logger.info("Connected to MongoDB")
                
        except Exception as e:
            self.logger.error(f"Error connecting to MongoDB: {e}")
            raise

    async def close(self):
        """Close MongoDB connection"""
        if self.client:
            self.client.close()
            self.logger.info("MongoDB connection closed")

    async def get_collection(self, collection_name: str):
        """Get a collection by name"""
        return self.db[collection_name]

    # CREATE operations
    async def insert_one(self, collection_name: str, document: Dict) -> str:
        """
        Insert a single document into a collection
        
        Args:
            collection_name: Name of the collection
            document: Document to insert
            
        Returns:
            Inserted document's ID as string
        """
        try:
            collection = self.db[collection_name]
            result = await collection.insert_one(document)
            return str(result.inserted_id)
        except Exception as e:
            self.logger.error(f"Error inserting document: {e}")
            raise

    async def insert_many(self, collection_name: str, documents: List[Dict]) -> List[str]:
        """
        Insert multiple documents into a collection
        
        Args:
            collection_name: Name of the collection
            documents: List of documents to insert
            
        Returns:
            List of inserted document IDs as strings
        """
        try:
            collection = self.db[collection_name]
            result = await collection.insert_many(documents)
            return [str(id) for id in result.inserted_ids]
        except Exception as e:
            self.logger.error(f"Error inserting multiple documents: {e}")
            raise

    # READ operations
    async def find_one(self, collection_name: str, query: Dict) -> Optional[Dict]:
        """
        Find a single document in a collection
        
        Args:
            collection_name: Name of the collection
            query: Query filter
            
        Returns:
            Document if found, None otherwise
        """
        try:
            collection = self.db[collection_name]
            result = await collection.find_one(query)
            return result
        except Exception as e:
            self.logger.error(f"Error finding document: {e}")
            raise

    async def find_by_id(self, collection_name: str, id: Union[str, ObjectId]) -> Optional[Dict]:
        """
        Find a document by its ID
        
        Args:
            collection_name: Name of the collection
            id: Document ID as string or ObjectId
            
        Returns:
            Document if found, None otherwise
        """
        if isinstance(id, str):
            id = ObjectId(id)
        return await self.find_one(collection_name, {"_id": id})

    async def find_many(self, 
                        collection_name: str, 
                        query: Dict = None, 
                        sort: List = None, 
                        limit: int = 0, 
                        skip: int = 0) -> List[Dict]:
        """
        Find multiple documents in a collection
        
        Args:
            collection_name: Name of the collection
            query: Query filter
            sort: Sort specifications [(field, direction)]
            limit: Maximum number of documents to return (0 for all)
            skip: Number of documents to skip
            
        Returns:
            List of documents
        """
        try:
            collection = self.db[collection_name]
            cursor = collection.find(query or {})
            
            if sort:
                cursor = cursor.sort(sort)
            
            if skip:
                cursor = cursor.skip(skip)
                
            if limit:
                cursor = cursor.limit(limit)
                
            return await cursor.to_list(length=limit if limit else None)
        except Exception as e:
            self.logger.error(f"Error finding documents: {e}")
            raise

    async def count_documents(self, collection_name: str, query: Dict = None) -> int:
        """
        Count documents in a collection
        
        Args:
            collection_name: Name of the collection
            query: Query filter
            
        Returns:
            Document count
        """
        try:
            collection = self.db[collection_name]
            return await collection.count_documents(query or {})
        except Exception as e:
            self.logger.error(f"Error counting documents: {e}")
            raise

    # UPDATE operations
    async def update_one(self, 
                          collection_name: str, 
                          query: Dict, 
                          update: Dict,
                          upsert: bool = False) -> bool:
        """
        Update a single document in a collection
        
        Args:
            collection_name: Name of the collection
            query: Query filter
            update: Update operations
            upsert: Insert if document doesn't exist
            
        Returns:
            True if a document was updated, False otherwise
        """
        try:
            collection = self.db[collection_name]
            result = await collection.update_one(query, update, upsert=upsert)
            return result.modified_count > 0 or (upsert and result.upserted_id is not None)
        except Exception as e:
            self.logger.error(f"Error updating document: {e}")
            raise

    async def update_by_id(self, 
                           collection_name: str, 
                           id: Union[str, ObjectId], 
                           update: Dict,
                           upsert: bool = False) -> bool:
        """
        Update a document by its ID
        
        Args:
            collection_name: Name of the collection
            id: Document ID as string or ObjectId
            update: Update operations
            upsert: Insert if document doesn't exist
            
        Returns:
            True if the document was updated, False otherwise
        """
        if isinstance(id, str):
            id = ObjectId(id)
        return await self.update_one(collection_name, {"_id": id}, update, upsert)

    async def update_many(self, 
                          collection_name: str, 
                          query: Dict, 
                          update: Dict,
                          upsert: bool = False) -> int:
        """
        Update multiple documents in a collection
        
        Args:
            collection_name: Name of the collection
            query: Query filter
            update: Update operations
            upsert: Insert if documents don't exist
            
        Returns:
            Number of documents updated
        """
        try:
            collection = self.db[collection_name]
            result = await collection.update_many(query, update, upsert=upsert)
            return result.modified_count
        except Exception as e:
            self.logger.error(f"Error updating multiple documents: {e}")
            raise

    # DELETE operations
    async def delete_one(self, collection_name: str, query: Dict) -> bool:
        """
        Delete a single document from a collection
        
        Args:
            collection_name: Name of the collection
            query: Query filter
            
        Returns:
            True if a document was deleted, False otherwise
        """
        try:
            collection = self.db[collection_name]
            result = await collection.delete_one(query)
            return result.deleted_count > 0
        except Exception as e:
            self.logger.error(f"Error deleting document: {e}")
            raise

    async def delete_by_id(self, collection_name: str, id: Union[str, ObjectId]) -> bool:
        """
        Delete a document by its ID
        
        Args:
            collection_name: Name of the collection
            id: Document ID as string or ObjectId
            
        Returns:
            True if the document was deleted, False otherwise
        """
        if isinstance(id, str):
            id = ObjectId(id)
        return await self.delete_one(collection_name, {"_id": id})

    async def delete_many(self, collection_name: str, query: Dict) -> int:
        """
        Delete multiple documents from a collection
        
        Args:
            collection_name: Name of the collection
            query: Query filter
            
        Returns:
            Number of documents deleted
        """
        try:
            collection = self.db[collection_name]
            result = await collection.delete_many(query)
            return result.deleted_count
        except Exception as e:
            self.logger.error(f"Error deleting multiple documents: {e}")
            raise

    # AGGREGATION operations
    async def aggregate(self, 
                        collection_name: str, 
                        pipeline: List[Dict]) -> List[Dict]:
        """
        Perform an aggregation pipeline on a collection
        
        Args:
            collection_name: Name of the collection
            pipeline: Aggregation pipeline stages
            
        Returns:
            Aggregation results
        """
        try:
            collection = self.db[collection_name]
            cursor = collection.aggregate(pipeline)
            return await cursor.to_list(length=None)
        except Exception as e:
            self.logger.error(f"Error performing aggregation: {e}")
            raise

    # UTILITY operations
    async def create_index(self, 
                          collection_name: str, 
                          keys: Union[str, List, Dict],
                          unique: bool = False) -> str:
        """
        Create an index on a collection
        
        Args:
            collection_name: Name of the collection
            keys: Index specification
            unique: Whether the index should enforce uniqueness
            
        Returns:
            Index name
        """
        try:
            collection = self.db[collection_name]
            return await collection.create_index(keys, unique=unique)
        except Exception as e:
            self.logger.error(f"Error creating index: {e}")
            raise

    async def drop_index(self, collection_name: str, index_name: str) -> None:
        """
        Drop an index from a collection
        
        Args:
            collection_name: Name of the collection
            index_name: Name of the index to drop
        """
        try:
            collection = self.db[collection_name]
            await collection.drop_index(index_name)
        except Exception as e:
            self.logger.error(f"Error dropping index: {e}")
            raise

    async def drop_collection(self, collection_name: str) -> None:
        """
        Drop a collection
        
        Args:
            collection_name: Name of the collection to drop
        """
        try:
            await self.db.drop_collection(collection_name)
        except Exception as e:
            self.logger.error(f"Error dropping collection: {e}")
            raise


# class MongoDBService:
#     def __init__(self):
#         self.client = MongoClient(settings.MONGODB_URI)
#         self.db = self.client.get_database("users-management")
#         self.collection = self.db.chats

#     async def create_chat(self, user_id: str, chat_id: str, initial_messages: List[Dict] = None) -> bool:
#         """Create a new chat entry if it doesn't exist."""
#         try:
#             key = {"user_id": user_id, "chat_id": chat_id}
#             if await asyncio.to_thread(self.collection.find_one, key):
#                 logger.info(f"Chat {user_id}/{chat_id} already exists, skipping creation")
#                 return False
#             now = datetime.utcnow()
#             doc = {
#                 "user_id": user_id,
#                 "chat_id": chat_id,
#                 "messages": initial_messages or [],
#                 "created_at": now,
#                 "updated_at": now
#             }
#             await asyncio.to_thread(self.collection.insert_one, doc)
#             logger.info(f"Created chat {user_id}/{chat_id}")
#             return True
#         except PyMongoError as e:
#             logger.error(f"MongoDB create error for {user_id}/{chat_id}: {e}")
#             return False

#     async def read_chat(self, user_id: str, chat_id: str) -> Optional[List[Dict]]:
#         """Read chat messages for a given user_id and chat_id."""
#         try:
#             key = {"user_id": user_id, "chat_id": chat_id}
#             doc = await asyncio.to_thread(self.collection.find_one, key)
#             if doc and "messages" in doc:
#                 return doc["messages"]
#             logger.info(f"No chat messages found for {user_id}/{chat_id}")
#             return []
#         except PyMongoError as e:
#             logger.error(f"MongoDB read error for {user_id}/{chat_id}: {e}")
#             return []

#     async def update_chat(self, user_id: str, chat_id: str, messages: List[Dict]) -> bool:
#         """Update entire chat messages for a given user_id and chat_id."""
#         try:
#             key = {"user_id": user_id, "chat_id": chat_id}
#             update = {
#                 "$set": {
#                     "messages": messages,
#                     "updated_at": datetime.utcnow()
#                 }
#             }
#             result = await asyncio.to_thread(
#                 self.collection.update_one, key, update, upsert=True
#             )
#             if result.modified_count > 0 or result.upserted_id:
#                 logger.info(f"Updated chat {user_id}/{chat_id}")
#                 return True
#             logger.info(f"No update needed for {user_id}/{chat_id}")
#             return False
#         except PyMongoError as e:
#             logger.error(f"MongoDB update error for {user_id}/{chat_id}: {e}")
#             return False

#     async def update_one(self, user_id: str, chat_id: str, message: Dict) -> bool:
#         """Push a single message into the messages array."""
#         try:
#             key = {"user_id": user_id, "chat_id": chat_id}
#             update = {
#                 "$push": {"messages": message},
#                 "$set": {"updated_at": datetime.utcnow()}
#             }
#             result = await asyncio.to_thread(
#                 self.collection.update_one, key, update, upsert=True
#             )
#             if result.modified_count > 0 or result.upserted_id:
#                 logger.info(f"Pushed message to chat {user_id}/{chat_id}")
#                 return True
#             logger.info(f"No update needed for {user_id}/{chat_id}")
#             return False
#         except PyMongoError as e:
#             logger.error(f"MongoDB update_one error for {user_id}/{chat_id}: {e}")
#             return False

#     async def delete_chat(self, user_id: str, chat_id: str) -> bool:
#         """Delete chat for a given user_id and chat_id."""
#         try:
#             key = {"user_id": user_id, "chat_id": chat_id}
#             result = await asyncio.to_thread(self.collection.delete_one, key)
#             if result.deleted_count > 0:
#                 logger.info(f"Deleted chat {user_id}/{chat_id}")
#                 return True
#             logger.info(f"No chat found to delete for {user_id}/{chat_id}")
#             return False
#         except PyMongoError as e:
#             logger.error(f"MongoDB delete error for {user_id}/{chat_id}: {e}")
#             return False

#     async def close(self):
#         """Close the MongoDB connection."""
#         self.client.close()
#         logger.info("MongoDB connection closed")

# mongo_service = MongoDBService()