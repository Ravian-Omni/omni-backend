import os
import autogen
import asyncio
from typing import List, Optional,Dict,Any
from utilities.logging import logger
from utilities.storage import omni_storage
# Load OpenAI API key

class CustomGroupChatManager(autogen.GroupChatManager):
    def __init__(self, groupchat, llm_config, human_input_mode="NEVER", queue: Optional[asyncio.Queue] = None, capability_name = "default"):
        super().__init__(groupchat=groupchat, llm_config=llm_config, human_input_mode=human_input_mode)
        self.queue = queue
        self.capability_name = capability_name
    
    def _print_received_message(self, message: Dict[str, Any], sender: "autogen.Agent") -> None:
        logger.info(f"Received from {sender.name}: {message}")
        super()._print_received_message(message, sender)
        content = message.get("content", "") if isinstance(message, dict) else str(message)
        try:
            omni_storage.add_capability_message(capability_name=self.capability_name,role="user",agent_name=sender.name,content=content)
            logger.debug(f"Queued from {sender.name}: {content}")
        except asyncio.QueueFull:
            logger.error(f"Queue full, could not queue message from {sender.name}: {content}")