from fastapi import Depends
from fastapi import APIRouter
from fastapi import Request
from dependencies import get_mongodb_service
from utilities.mongodb_service import MongoDBService
import uuid
import json
from configs.settings import settings
from omni.manager import Omni
from fastapi import HTTPException, Depends, status
from datetime import datetime, timezone
from pydantic import BaseModel
from fastapi import FastAPI, HTTPException, Query, Path
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from bson import ObjectId

router = APIRouter()

class ChatRequest(BaseModel):
    chat_id: str
    message: str
    
class Message(BaseModel):
    role: str
    name: str
    content: str

class RawMessage(BaseModel):
    role: str
    name: str
    raw_message: Any

class ChatHistory(BaseModel):
    id: str = Field(alias="_id")
    chat_id: str
    messages: List[Message]
    raw_messages: List[RawMessage]
    created_at: datetime
    updated_at: datetime
    user_id: str

    class Config:
        populate_by_name = True
        json_encoders = {
            ObjectId: str,
            datetime: lambda v: v.isoformat()
        }

@router.post("/new_chat")
async def create_new_chat(request:Request, mongodb: MongoDBService = Depends(get_mongodb_service)):
    try:
        # Generate unique chat identifier
        chat_id = str(uuid.uuid4())
        
        # Check if the chat_id already exists for this user
        existing_chat = await mongodb.find_one(
            settings.OMNI_COLLECTION,
            {"chat_id": chat_id}
        )
        
        if existing_chat:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, 
                detail="Chat already exists for this user with the generated ID"
            )
        
        # Prepare chat document
        chat_document = {
            "user_id": "default_user",  # Placeholder for user_id, can be replaced with actual user ID logic
            "chat_id": chat_id,
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

@router.get("/chat-history/{user_id}/{chat_id}", response_model=ChatHistory)
async def get_specific_chat(
    user_id: str = Path(..., description="User ID"),
    chat_id: str = Path(..., description="Chat ID"),
    mongodb: MongoDBService = Depends(get_mongodb_service)
):
    """Get a specific chat by user_id and chat_id"""
    try:
        query = {"user_id": user_id, "chat_id": chat_id}
        document = await mongodb.find_one(settings.OMNI_COLLECTION, query)
        
        if not document:
            raise HTTPException(
                status_code=404,
                detail=f"Chat not found for user_id: {user_id} and chat_id: {chat_id}"
            )
        
        return serialize_document(document)
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch chat: {str(e)}")