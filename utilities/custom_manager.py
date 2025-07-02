import os
import autogen
import asyncio
from typing import List, Optional,Dict,Any
from loguru import logger
from utilities.storage import omni_storage
from utilities.storage import omni_storage
from datetime import datetime,timezone
from dependencies import get_mongodb_service
from dependencies import get_websocket_manager

async def create_capability_chat(chat_id,call_id,capability, capability_id):
    mongodb = await get_mongodb_service()
    chat_document = {
        "chat_id": chat_id,
        "call_id":call_id,
        "capability_id":capability_id,
        "messages": [],
        "raw_messages": [],
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc)
    }
    
    # Create database record
    await mongodb.insert_one(capability, chat_document)
    
    # Return standardized response using Pydantic model
    return {"chat_id":chat_id}

async def update_db(chat_id, call_id, message, capability, capability_id):
    mongodb = await get_mongodb_service()
    raw_message = {k: message[k] for k in ['role', 'name', 'raw_message']}
    message = {k: message[k] for k in ['role', 'name', 'content']}
    # Build the push operations conditionally
    push_operations = {"raw_messages": raw_message}

    # Only add to messages if content is not empty/null
    if message.get('content'):
        push_operations["messages"] = message

    mongo_update = {
        "$push": push_operations,
        "$set": {
            "updated_at": datetime.now()
        }
    }
    db_mongo_update = asyncio.create_task(mongodb.update_one(capability,{"chat_id":chat_id, "call_id":call_id, "capability_id": capability_id},mongo_update))
    logger.info(f"MongoDB updated for {chat_id} having status {db_mongo_update} and details are {call_id} | {capability}")
    return True

class CustomGroupChatManager(autogen.GroupChatManager):
    def __init__(self, groupchat, llm_config, omni_memory, capability_name="default", capability_id=None, chat_id=None, call_id=None, human_input_mode="NEVER", queue: Optional[asyncio.Queue] = None):
        super().__init__(groupchat=groupchat, llm_config=llm_config, human_input_mode=human_input_mode)
        self.queue = queue
        self.capability = capability_name
        self.chat_id = chat_id
        self.call_id = call_id
        self.capability_id = capability_id
        self.omni_memory = omni_memory
        
    async def send_websocket(self, message):
        ws_manager = await get_websocket_manager()
        await ws_manager.send_chat_message(session_id=self.chat_id, content=message, source=self.capability)
        return
    
    def _print_received_message(self, message: Dict[str, Any], sender: "autogen.Agent") -> None:
        logger.info(f"Received from {sender.name}: {message}")
        super()._print_received_message(message, sender)
        content = message.get("content", "") if isinstance(message, dict) else str(message)
        db_content = {"role":"user","name":sender.name,"content":content}
        self.omni_memory.push_capability_message(db_content,self.capability,self.capability_id)
        asyncio.run(self.send_websocket(db_content))
        db_content["raw_message"] = message
        asyncio.create_task(update_db(chat_id=self.chat_id, call_id=self.call_id, message=db_content, capability=self.capability, capability_id=self.capability_id))