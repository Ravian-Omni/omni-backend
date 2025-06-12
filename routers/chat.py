from fastapi import Depends
from fastapi import APIRouter
from fastapi import Request
from dependencies import get_mongodb_service
from utilities.mongodb_service import MongoDBService
import uuid
import json
from configs.settings import settings
router = APIRouter(prefix="/chats", tags=["Chat Management"])
from omni.manager import Omni
from fastapi import HTTPException, Depends, status
import datetime
from pydantic import BaseModel

class ChatRequest(BaseModel):
    chat_id: str
    message: str


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
            "chat_id": chat_id,
            "messages": [],
            "raw_messages": [],
            "created_at": datetime.datetime.now(datetime.timezone.utc),
            "updated_at": datetime.datetime.now(datetime.timezone.utc)
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
    messages = history.get("messages",[])
    if messages:
        last_agent, last_message = omni.manager.resume(messages=messages)
    response = omni.manager.initiate_chat(omni.manager,message=chat_request.message,clear_history=False)
    return response
