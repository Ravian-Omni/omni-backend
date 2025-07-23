import os
import autogen
import asyncio
from typing import List, Optional,Dict,Any
from loguru import logger
from datetime import datetime,timezone
from dependencies import get_websocket_manager
from dataclasses import dataclass
from omni.memory import OmniMemory
from collections import defaultdict
from utilities.api_client import api_client
from managers.cancellation_token import CancellationToken
@dataclass
class ChatContext:
    """Chat context containing all necessary identifiers"""
    user_id: str
    chat_id: str
    chat_dir: str
    call_id: str
    capability_id: str
    capability_name: str
    collection_name: str
    omni_memory: OmniMemory
    cancellation_token: CancellationToken = None
    manager_kwargs: Optional[Dict[str, Any]] = None
    
    def __post_init__(self):
        if self.manager_kwargs is None:
            self.manager_kwargs = {}

async def create_capability_chat(context: ChatContext) -> Dict[str, str]:
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
    create_chat = await api_client.post("/chats/new", params={"capability": context.collection_name}, data=chat_document)
    create_chat = create_chat.standard_response()
    if not create_chat.get("success"):
        raise Exception(f"Failed to create capbility_chat: {create_chat.get('message', 'Unknown error')}")
    
    result = create_chat.get("data")
    # await mongodb.insert_one(context.collection_name, chat_document)
    
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
        # Extract message fields safely
        raw_message = {k: message.get(k) for k in ['role', 'name', 'raw_message', 'usage'] if k in message}
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

        update_result = await api_client.post("/chats/chat_update", params={"capability": context.collection_name}, data={"filter_criteria":filter_criteria,"document":update_document})
        update_result = update_result.standard_response()
        if not update_result.get("success"):
            raise Exception(f"Failed to update chat history: {update_result.get('message', 'Unknown error')}")
        
        result = update_result.get("data")
        # result = await mongodb_service.update_one(
        #     context.collection_name, 
        #     filter_criteria, 
        #     update_document
        # )
        
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
        # Track previous usage state for each agent to calculate deltas
        self._agent_previous_usage = defaultdict(lambda: {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "cost": 0.0
        })
        
        # Initialize tracking for all agents
        self._initialize_agent_tracking()
    
    def _initialize_agent_tracking(self):
        """Initialize usage tracking for all agents"""
        for agent in self.groupchat.agents:
            # Initialize with current usage if any
            current_usage = self._get_agent_current_usage(agent)
            self._agent_previous_usage[agent.name] = current_usage.copy()
    
    def _get_agent_current_usage(self, agent) -> Dict[str, Any]:
        """Get current usage for a specific agent"""
        default_usage = {
            "model": "unknown",
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "cost": 0.0
        }
        
        # Check if agent has client and usage summary
        if not hasattr(agent, "client") or not agent.client:
            return default_usage
        
        usage_summary = getattr(agent.client, "total_usage_summary", None)
        if not usage_summary:
            return default_usage
        
        # Find the model key (first key that's not 'total_cost')
        model_keys = [k for k in usage_summary.keys() if k != "total_cost"]
        if not model_keys:
            return default_usage
        
        model_key = model_keys[0]
        model_usage = usage_summary.get(model_key, {})
        
        return {
            "model": model_key,
            "prompt_tokens": model_usage.get("prompt_tokens", 0),
            "completion_tokens": model_usage.get("completion_tokens", 0),
            "total_tokens": model_usage.get("total_tokens", 0),
            "cost": model_usage.get("cost", 0.0)
        }
    
    def _calculate_agent_usage_delta(self, agent, agent_name: str) -> Dict[str, Any]:
        """Calculate usage delta for a specific agent since last check"""
        current_usage = self._get_agent_current_usage(agent)
        previous_usage = self._agent_previous_usage[agent_name]
        
        # Calculate the delta (what changed since last check)
        usage_delta = {
            "prompt_tokens": current_usage["prompt_tokens"] - previous_usage["prompt_tokens"],
            "completion_tokens": current_usage["completion_tokens"] - previous_usage["completion_tokens"],
            "total_tokens": current_usage["total_tokens"] - previous_usage["total_tokens"],
            "cost": current_usage["cost"] - previous_usage["cost"]
        }
        
        # Update the previous usage for next calculation
        self._agent_previous_usage[agent_name] = current_usage.copy()
        
        # Return both current total and delta for this message
        return {
            "current_total": current_usage,
            "message_delta": usage_delta,
            "agent_name": agent_name
        }
    
    def _get_sender_agent_usage(self, sender) -> Dict[str, Any]:
        """Get usage details for the sender agent when message is received"""
        return self._calculate_agent_usage_delta(sender, sender.name)
        
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
        
        # Get the sender's usage details (current total + delta for this message)
        sender_usage = self._get_sender_agent_usage(sender)
        
        # Prepare message data
        content = message.get("content", "") if isinstance(message, dict) else str(message)
        message_data = {
            "role": "user",
            "name": sender.name,
            "content": content,
            "raw_message": message,
            "usage": sender_usage
        }
        websocket_message = {
            "role": "user",
            "name": sender.name,
            "content": content,
            "raw_message": message,
            "call_id": self.context.call_id,
        }
        # Store in memory (synchronous)
        memory_data = {k: message_data[k] for k in ['role', 'name', 'content']}
        self.omni_memory.push_capability_message(
            memory_data, 
            self.context.capability_name, 
            self.context.capability_id
        )
        
        # Process background tasks (async)
        asyncio.run(self._send_websocket_message(websocket_message))
        asyncio.run(update_chat_history(self.context,message_data))
        
    # Additional utility methods for comprehensive usage tracking
    
    def get_all_agents_current_usage(self) -> Dict[str, Dict[str, Any]]:
        """Get current usage for all agents in the group"""
        all_usage = {}
        for agent in self.groupchat.agents:
            all_usage[agent.name] = self._get_agent_current_usage(agent)
        return all_usage
    
    def get_group_usage_summary(self) -> Dict[str, Any]:
        """Get aggregated usage summary for the entire group"""
        all_usage = self.get_all_agents_current_usage()
        
        total_summary = {
            "total_prompt_tokens": 0,
            "total_completion_tokens": 0,
            "total_tokens": 0,
            "total_cost": 0.0,
            "agents_count": len(all_usage),
            "models_used": set(),
            "per_agent": all_usage
        }
        
        for agent_name, usage in all_usage.items():
            total_summary["total_prompt_tokens"] += usage["prompt_tokens"]
            total_summary["total_completion_tokens"] += usage["completion_tokens"]
            total_summary["total_tokens"] += usage["total_tokens"]
            total_summary["total_cost"] += usage["cost"]
            if usage["model"] != "unknown":
                total_summary["models_used"].add(usage["model"])
        
        total_summary["models_used"] = list(total_summary["models_used"])
        return total_summary
    
    def reset_usage_tracking(self):
        """Reset usage tracking (useful for starting fresh tracking mid-conversation)"""
        for agent in self.groupchat.agents:
            current_usage = self._get_agent_current_usage(agent)
            self._agent_previous_usage[agent.name] = current_usage.copy()

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