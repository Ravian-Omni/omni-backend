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
    #raw_message = {k: message[k] for k in ['role', 'name', 'raw_message','usage_summary']}
    raw_message_payload = {
        'role': message.get('role'),
        'name': message.get('name'),
        'raw_message': message.get('raw_message'),
        'usage_summary': message.get('usage_summary')
    }
    message = {k: message[k] for k in ['role', 'name', 'content']}
    # Build the push operations conditionally
    push_operations = {"raw_messages": raw_message_payload}

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

    def _get_agent_usage_string(self, agent: autogen.Agent) -> str:
        """
        Retrieves the cumulative usage for an agent and formats it into a readable string.
        """
        # get_total_usage() returns the cumulative usage for the agent instance.
        usage = agent.get_total_usage()
        if not usage:
            return "Agent has no recorded token usage."

        total_cost = usage.get("total_cost", 0)
        # The model key (e.g., 'gpt-4o-mini') is the one that isn't 'total_cost'
        model_key = next((key for key in usage if key != "total_cost"), None)
        
        if not model_key:
            return f"Cumulative Cost: ${total_cost:.6f}"

        model_usage = usage.get(model_key, {})
        return (
            f"Model: {model_key} | "
            f"Prompt Tokens: {model_usage.get('prompt_tokens', 0)} | "
            f"Completion Tokens: {model_usage.get('completion_tokens', 0)} | "
            f"Total Tokens: {model_usage.get('total_tokens', 0)} | "
            f"Cumulative Cost: ${total_cost:.6f}"
        )
        
        
    async def send_websocket(self, message):
        ws_manager = await get_websocket_manager()
        await ws_manager.send_chat_message(session_id=self.chat_id, content=message, source=self.capability)
        return
    
    # def _print_received_message(self, message: Dict[str, Any], sender: "autogen.Agent") -> None:
    #     logger.info(f"Received from {sender.name}: {message}")
    #     super()._print_received_message(message, sender)
    #     content = message.get("content", "") if isinstance(message, dict) else str(message)
    #     db_content = {"role":"user","name":sender.name,"content":content}
    #     self.omni_memory.push_capability_message(db_content,self.capability,self.capability_id)
    #     db_content["raw_message"] = message
    #     asyncio.run(self.send_websocket(db_content))
    #     asyncio.create_task(update_db(chat_id=self.chat_id, call_id=self.call_id, message=db_content, capability=self.capability, capability_id=self.capability_id))
    def _print_received_message(self, message: Dict[str, Any], sender: "autogen.Agent") -> None:
        logger.info(f"Received from {sender.name}: {message}")
        super()._print_received_message(message, sender)
        content = message.get("content", "") if isinstance(message, dict) else str(message)
        
        # 1. Get the formatted usage string for the sender agent
        usage_str = self._get_agent_usage_string(sender)

        # 2. Print to console for real-time visibility
        print("--------------------------------------------------------------------------------")
        print(f"Message from: {sender.name}")
        if content:
             print("Content:\n" + content)
        print("\n" + f">> AGENT USAGE ({sender.name.upper()}): {usage_str}")
        print("--------------------------------------------------------------------------------\n")
        
        # 3. Add the 'usage_summary' key to the dictionary BEFORE it's used. This is the fix.
        db_content = {
            "role": "user",
            "name": sender.name,
            "content": content,
            "raw_message": message,
            "usage_summary": usage_str
        }

        # 4. Now, the rest of your code works because db_content contains the required key.
        self.omni_memory.push_capability_message(db_content, self.capability, self.capability_id)
        asyncio.run(self.send_websocket(db_content))
        asyncio.create_task(update_db(
            chat_id=self.chat_id,
            call_id=self.call_id,
            message=db_content,
            capability=self.capability,
            capability_id=self.capability_id
        ))