import os
import autogen
import asyncio
from typing import List, Optional,Dict,Any
from loguru import logger
from datetime import datetime,timezone
from dependencies import get_mongodb_service
from dependencies import get_websocket_manager
from dataclasses import dataclass
from omni.memory import OmniMemory


@dataclass
class ChatContext:
    """Chat context containing all necessary identifiers"""
    user_id: str
    chat_id: str
    call_id: str
    capability_id: str
    capability_name: str
    collection_name: str
    omni_memory: OmniMemory
    manager_kwargs: Optional[Dict[str, Any]] = None
    
    def __post_init__(self):
        if self.manager_kwargs is None:
            self.manager_kwargs = {}

async def create_capability_chat(context: ChatContext) -> Dict[str, str]:
    mongodb = await get_mongodb_service()
    chat_document = {
        "user_id": context.user_id,
        "chat_id": context.chat_id,
        "call_id":context.call_id,
        "capability_id":context.capability_id,
        "messages": [],
        "raw_messages": [],
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc)
    }
    
    # Create database record
    await mongodb.insert_one(context.collection_name, chat_document)
    
    # Return standardized response using Pydantic model
    return {"chat_id":context.chat_id}


async def update_chat_history(context: ChatContext, message: Dict[str, Any]) -> bool:
    """
    Update chat history in MongoDB.
    
    Args:
        context: Chat context with all identifiers
        message: Message data to store
    
    Returns:
        bool: True if update was successful
    """
    try:
        mongodb_service = await get_mongodb_service()
        
        # Extract message fields safely
        raw_message = {k: message.get(k) for k in ['role', 'name', 'raw_message'] if k in message}
        content_message = {k: message.get(k) for k in ['role', 'name', 'content'] if k in message}
        
        raw_message['timestamp'] = datetime.now(timezone.utc).isoformat()  # Add timestamp to raw message
        
        # Build push operations
        push_operations = {"raw_messages": raw_message}
        if content_message.get('content'):
            push_operations["messages"] = content_message
        
        # Prepare update document
        update_document = {
            "$push": push_operations,
            "$set": {"updated_at": datetime.now()}
        }
        
        # Execute update
        filter_criteria = {
            "user_id": context.user_id,
            "chat_id": context.chat_id,
            "call_id": context.call_id,
            "capability_id": context.capability_id
        }
        
        result = await mongodb_service.update_one(
            context.collection_name, 
            filter_criteria, 
            update_document
        )
        
        logger.info(
            f"Chat history updated - chat_id: {context.chat_id}, "
            f"call_id: {context.call_id}, capability: {context.capability_name}, "
            f"modified: {result}"
        )
        
        return result
        
    except Exception as e:
        logger.error(f"Failed to update chat history: {e}")
        return False

class CustomGroupChatManager(autogen.GroupChatManager):
    """Enhanced GroupChatManager with chat context and background processing"""
    
    def __init__(self, groupchat, llm_config, chat_context: ChatContext, 
                 human_input_mode: str = "NEVER"):
        super().__init__(groupchat=groupchat, llm_config=llm_config, human_input_mode=human_input_mode)
        self.context = chat_context
        self.omni_memory = chat_context.omni_memory
        
    async def _send_websocket_message(self, message: Dict[str, Any]) -> None:
        """Send message to WebSocket clients"""
        try:
            websocket_manager = await get_websocket_manager()
            await websocket_manager.send_chat_message(
                session_id=self.context.chat_id, 
                content=message, 
                source=self.context.capability_name
            )
        except Exception as e:
            logger.error(f"WebSocket send failed: {e}")
    
    async def _process_message_background(self, message_data: Dict[str, Any]) -> None:
        """Process message in background (WebSocket + Database)"""
        await asyncio.gather(
            self._send_websocket_message(message_data),
            update_chat_history(self.context, message_data),
            return_exceptions=True
        )
    
    def _print_received_message(self, message: Dict[str, Any], sender: "autogen.Agent") -> None:
        """Override to handle received messages with enhanced processing"""
        logger.info(f"Received from {sender.name}: {message}")
        super()._print_received_message(message, sender)
        
        # Prepare message data
        content = message.get("content", "") if isinstance(message, dict) else str(message)
        message_data = {
            "role": "user",
            "name": sender.name,
            "content": content,
            "raw_message": message
        }
        
        # Store in memory (synchronous)
        memory_data = {k: message_data[k] for k in ['role', 'name', 'content']}
        self.omni_memory.push_capability_message(
            memory_data, 
            self.context.capability_name, 
            self.context.capability_id
        )
        
        # Process background tasks (async)
        asyncio.create_task(self._send_websocket_message(message_data))
        asyncio.create_task(update_chat_history(self.context,message_data))

# async def update_db(chat_id, call_id, message, capability, capability_id):
#     mongodb = await get_mongodb_service()
#     raw_message = {k: message[k] for k in ['role', 'name', 'raw_message']}
#     message = {k: message[k] for k in ['role', 'name', 'content']}
#     # Build the push operations conditionally
#     push_operations = {"raw_messages": raw_message}

#     # Only add to messages if content is not empty/null
#     if message.get('content'):
#         push_operations["messages"] = message

#     mongo_update = {
#         "$push": push_operations,
#         "$set": {
#             "updated_at": datetime.now()
#         }
#     }
#     db_mongo_update = asyncio.create_task(mongodb.update_one(capability,{"chat_id":chat_id, "call_id":call_id, "capability_id": capability_id},mongo_update))
#     logger.info(f"MongoDB updated for {chat_id} having status {db_mongo_update} and details are {call_id} | {capability}")
#     return True

# class CustomGroupChatManager(autogen.GroupChatManager):
#     def __init__(self, groupchat, llm_config, omni_memory, capability_name="default", capability_id=None, chat_id=None, call_id=None, human_input_mode="NEVER", queue: Optional[asyncio.Queue] = None):
#         super().__init__(groupchat=groupchat, llm_config=llm_config, human_input_mode=human_input_mode)
#         self.queue = queue
#         self.capability = capability_name
#         self.chat_id = chat_id
#         self.call_id = call_id
#         self.capability_id = capability_id
#         self.omni_memory = omni_memory
        
#     async def send_websocket(self, message):
#         ws_manager = await get_websocket_manager()
#         await ws_manager.send_chat_message(session_id=self.chat_id, content=message, source=self.capability)
#         return
    
#     def _print_received_message(self, message: Dict[str, Any], sender: "autogen.Agent") -> None:
#         logger.info(f"Received from {sender.name}: {message}")
#         super()._print_received_message(message, sender)
#         content = message.get("content", "") if isinstance(message, dict) else str(message)
#         db_content = {"role":"user","name":sender.name,"content":content}
#         self.omni_memory.push_capability_message(db_content,self.capability,self.capability_id)
#         db_content["raw_message"] = message
#         asyncio.run(self.send_websocket(db_content))
#         asyncio.create_task(update_db(chat_id=self.chat_id, call_id=self.call_id, message=db_content, capability=self.capability, capability_id=self.capability_id))