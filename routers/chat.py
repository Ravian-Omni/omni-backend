from fastapi import Depends
from fastapi import APIRouter
from fastapi import Request
from dependencies import get_mongodb_service
from utilities.mongodb_service import MongoDBService
from utilities.storage import ensure_path
import uuid
import json
from configs.settings import settings, CapabilityType
from omni.manager import Omni
from fastapi import HTTPException, Depends, status
from datetime import datetime, timezone
from pydantic import BaseModel
from fastapi import FastAPI, HTTPException, Query, Path
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from bson import ObjectId
import time
import os


router = APIRouter()

class ChatRequest(BaseModel):
    chat_id: str
    message: str
    
class Message(BaseModel):
    role: str
    name: str
    content: str

@router.post("/new_chat")
async def create_new_chat(request:Request, user_id:str = "default_user", chat_dir = os.path.join(settings.ROOT_DIR, "ravian"), mongodb: MongoDBService = Depends(get_mongodb_service)):
    try:
        chat_dir = ensure_path(chat_dir)
        # Generate unique chat identifier
        chat_id = str(uuid.uuid4())
        
        
        # Check if the chat_id already exists for this user
        existing_chat = await mongodb.find_one(
            settings.OMNI_COLLECTION,
            {"user_id": user_id, "chat_id": chat_id}
        )
        
        if existing_chat:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, 
                detail="Chat already exists for this user with the generated ID"
            )
        
        # Prepare chat document
        chat_document = {
            "user_id": user_id,  # Placeholder for user_id, can be replaced with actual user ID logic
            "chat_id": chat_id,
            "chat_dir": chat_dir,
            "messages": [],
            "raw_messages": [],
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc)
        }
        
        # Create database record
        await mongodb.insert_one(settings.OMNI_COLLECTION, chat_document)
        
        
        # Return standardized response using Pydantic model
        return {"chat_id":chat_id}
    
    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, 
            detail=f"Chat creation failed due to server error: {e}"
        )

@router.post("capability/new-chat")
async def create_new_chat(request:Request, capability_name: str = Query(..., description="Capability name"), user_id:str = "default_user", chat_dir = os.path.join(settings.ROOT_DIR, "ravian"), mongodb: MongoDBService = Depends(get_mongodb_service)):
    try:
        chat_dir = ensure_path(chat_dir)
        # Generate unique chat identifier
        chat_id = str(uuid.uuid4())
        
        capability = CapabilityType.from_string(capability_name)
        collection_name = capability.collection
        # Check if the chat_id already exists for this user
        existing_chat = await mongodb.find_one(
            collection_name,
            {"user_id": user_id, "chat_id": chat_id}
        )
        
        if existing_chat:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, 
                detail="Chat already exists for this user with the generated ID"
            )
        
        # Prepare chat document
        chat_document = {
            "user_id": user_id,  # Placeholder for user_id, can be replaced with actual user ID logic
            "chat_id": chat_id,
            "chat_dir": chat_dir,
            "call_id": "Individual",
            "capability_id": chat_id,
            "messages": [],
            "raw_messages": [],
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc)
        }
        
        # Create database record
        await mongodb.insert_one(collection_name, chat_document)
        
        
        # Return standardized response using Pydantic model
        return {"capability_name": capability_name,"chat_id":chat_id}
    
    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, 
            detail=f"Chat creation failed due to server error: {e}"
        )

# FastAPI endpoint
@router.post("/chat")
async def chat_endpoint(request:Request, chat_request: ChatRequest, mongodb: MongoDBService = Depends(get_mongodb_service)):
    omni = Omni(chat_request.chat_id)
    history = await mongodb.find_one(settings.OMNI_COLLECTION,{"chat_id":chat_request.chat_id})
    # messages = history.get("messages",[])
    # if messages:
    #     last_agent, last_message = omni.manager.resume(messages=messages)
    #     omni.memory.load_main_messages(messages)
    response = await omni.manager.a_initiate_chat(omni.manager,message=chat_request.message,clear_history=False)
    return omni.groupchat.messages[-1]


def serialize_document(doc: Dict[Any, Any]) -> Dict[str, Any]:
    """Convert MongoDB document to JSON serializable format"""
    if doc is None:
        return None
    
    # Convert ObjectId to string
    if "_id" in doc:
        doc["_id"] = str(doc["_id"])
    
    # Convert datetime objects to ISO format
    for key, value in doc.items():
        if isinstance(value, datetime):
            doc[key] = value.isoformat()
        elif isinstance(value, ObjectId):
            doc[key] = str(value)
    
    return doc

class RawMessage(BaseModel):
    role: str
    name: str
    raw_message: Any
    timestamp: str


# Modified response model to only include chat_id and raw_messages
class SimplifiedChatHistory(BaseModel):
    chat_id: str
    chat_dir: Optional[str] = None
    raw_messages: List[RawMessage]


@router.get("/chat-history/{user_id}/{chat_id}", response_model=SimplifiedChatHistory)
async def get_specific_chat(
    user_id: str = Path(..., description="User ID"),
    chat_id: str = Path(..., description="Chat ID"),
    mongodb: MongoDBService = Depends(get_mongodb_service)
):
    """Get a specific chat by user_id and chat_id - returns only chat_id and raw_messages"""
    try:
        query = {"user_id": user_id, "chat_id": chat_id}
        document = await mongodb.find_one(settings.OMNI_COLLECTION, query)
        
        if not document:
            raise HTTPException(
                status_code=404,
                detail=f"Chat not found for user_id: {user_id} and chat_id: {chat_id}"
            )
        
        # Serialize the full document first
        serialized_doc = serialize_document(document)
        
        # Transform messages to raw_messages format
        raw_messages = []
        if "raw_messages" in serialized_doc:
            for message in serialized_doc["raw_messages"]:
                raw_messages.append({
                    "role": message.get("role", ""),
                    "name": message.get("name", ""),
                    "raw_message": message.get("raw_message", ""),  # Using content as raw_message
                    "timestamp": message.get("timestamp", "")  # Using content as raw_message
                })
        
        # Return only chat_id and raw_messages
        return {
            "chat_id": serialized_doc.get("chat_id", ""),
            "chat_dir": serialized_doc.get("chat_dir", ""),
            "raw_messages": raw_messages
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch chat: {str(e)}")

class EnhancedChatHistory(BaseModel):
    call_id: str
    capability_name: str
    chat_id: str
    raw_messages: List[RawMessage]

@router.get("/chat-history/capability/{user_id}/{chat_id}", response_model=EnhancedChatHistory)
async def get_specific_chat(
    user_id: str = Path(..., description="User ID"),
    chat_id: str = Path(..., description="Chat ID"),
    call_id: str = Query(..., description="Call ID"),
    capability_name: str = Query(..., description="Capability name"),
    mongodb: MongoDBService = Depends(get_mongodb_service)
):
    """Get a specific chat by user_id and chat_id - returns call_id, capability_name, chat_id and raw_messages"""
    try:
        query = {"user_id": user_id, "chat_id": chat_id, "call_id": call_id}
        if capability_name not in CapabilityType._value2member_map_:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid capability name: {capability_name}. Must be one of the valid capability names"
            )
        capability = CapabilityType._value2member_map_.get(capability_name)
        collection_name = capability.collection 
        document = await mongodb.find_one(collection_name, query)
        
        if not document:
            raise HTTPException(
                status_code=404,
                detail=f"Chat not found for user_id: {user_id} and chat_id: {chat_id}"
            )
        
        # Serialize the full document first
        serialized_doc = serialize_document(document)
        
        # Transform messages to raw_messages format
        raw_messages = []
        if "raw_messages" in serialized_doc:
            for message in serialized_doc["raw_messages"]:
                raw_messages.append({
                    "role": message.get("role", ""),
                    "name": message.get("name", ""),
                    "raw_message": message.get("raw_message", ""),
                    "timestamp": message.get("timestamp", "")
                })
        
        # Return call_id, capability_name, chat_id and raw_messages
        return {
            "call_id": call_id,
            "capability_name": capability_name,
            "chat_id": serialized_doc.get("chat_id", ""),
            "raw_messages": raw_messages
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch chat: {str(e)}")