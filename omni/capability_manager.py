import uuid
from loguru import logger
from typing import Annotated, Dict, Any, Optional, List, Type, Union
from dataclasses import dataclass
from utilities.custom_manager import create_capability_chat, ChatContext


@dataclass
class CapabilityConfig:
    """Configuration for a capability"""
    name: str
    collection: str
    manager_class: Type
    completion_agent_name: str = "process_completion"
    use_chat_messages: bool = True
    manager_kwargs: Optional[Dict[str, Any]] = None  # Additional arguments for manager class
    
    def __post_init__(self):
        if self.manager_kwargs is None:
            self.manager_kwargs = {}

class CapabilityManager:
    """Generic manager for handling capability operations"""
    
    def __init__(self, user_id: str, chat_id: str, chat_dir: str, memory):
        self.user_id = user_id
        self.chat_id = chat_id
        self.chat_dir = chat_dir
        self.memory = memory
    
    async def execute_capability(
        self, 
        query: str, 
        config: CapabilityConfig,
        call_id: str
    ) -> Dict[str, Any]:
        """
        Execute a capability with the given configuration
        
        Args:
            query: The complete user query
            config: Configuration for the capability
            call_id: The call ID to use for this capability
            
        Returns:
            Dict containing the result or error message
        """
        try:
            # Validate call_id
            if not call_id:
                logger.warning(f"No call_id provided for {config.name}: {query}")
                return {
                    "error": f"No call_id provided for {config.name}", 
                    "query": query
                }
            
            # Create chat context with manager kwargs
            context = ChatContext(
                user_id=self.user_id,
                chat_id=self.chat_id,
                chat_dir=self.chat_dir,
                call_id=call_id,
                capability_id=str(uuid.uuid4()),
                capability_name=config.name,
                collection_name=config.collection,
                omni_memory=self.memory,
                manager_kwargs=config.manager_kwargs
            )
            
            # Initialize capability chat
            await create_capability_chat(context=context)
            
            # Create capability manager instance
            capability_instance = config.manager_class(context)
            
            # Prepare and execute chat
            if config.use_chat_messages:
                messages = self._prepare_chat_messages() or []
                if messages:
                    last_agent, last_message = capability_instance.manager.resume(messages=messages)
            capability_instance.groupchat.max_round = 5
            response = capability_instance.manager.initiate_chat(
                capability_instance.manager, 
                message=query, 
                clear_history=False
            )
            
            # Extract result from messages
            result = self._extract_completion_result(
                capability_instance.groupchat.messages,
                config.completion_agent_name
            )
            
            return result if result else f"error: {config.name} process encountered runtime error: {query}"
            
        except Exception as e:
            logger.error(f"{config.name} process failed for query '{query}': {e}")
            return {
                "error": f"{config.name} process failed: {str(e)}",
                "query": query
            }
    

    
    def _prepare_chat_messages(self) -> List[Dict[str, Any]]:
        """Prepare messages for capability manager chat"""
        # messages = self.memory.pull_recent_from_chat_manager()
        messages = []
        
        # Add last capability messages if available
        if self.memory.get_last_capability():
            last_content_list = self._get_last_completion_content()
            if last_content_list:
                for agent_message in last_content_list:
                    messages.append({
                        "role": "user",
                        "name": f"context_keeper",
                        "content": agent_message['content']
                    })
        
        return messages
    
    def _get_last_completion_content(self) -> Optional[list]:
        """Get last completion content from capability messages for all specified agents"""
        try:
            capability_messages = self.memory.pull_last_capability_messages()
            agent_messages = []
            
            for msg in capability_messages:
                if msg.get('name') in ('process_completion', 'code_executor_agent', 'process_completion_agent'):
                    agent_messages.append({
                        'name': msg.get('name'),
                        'content': msg.get('content')
                    })
            
            return agent_messages if agent_messages else None
            
        except Exception as e:
            logger.error(f"Error getting last completion content: {e}")
            return None
    
    def _extract_completion_result(
        self, 
        messages: List[Dict[str, Any]], 
        completion_agent_name: str
    ) -> Optional[str]:
        """Extract completion result from chat messages"""
        try:
            # Search from most recent messages
            for msg in reversed(messages):
                if msg.get("name") == completion_agent_name:
                    return msg.get("content")
            return None
        except Exception as e:
            logger.error(f"Error extracting completion result: {e}")
            return None


# Usage example - How to use the generic manager
# class YourMainClass:
#     def __init__(self):
#         self.capability_manager = CapabilityManager(
#             chat_id=self.chat_id,
#             memory=self.memory
#         )
        
        # # Define configurations for different capabilities
        # self.email_config = CapabilityConfig(
        #     name="email_sender",
        #     collection=settings.EMAIL_COLLECTION,
        #     manager_class=EmailManager,
        #     call_id_key="email_sender",
        #     completion_agent_name="process_completion_agent"
        # )
        
        # self.file_finder_config = CapabilityConfig(
        #     name="file_finder",
        #     collection=settings.FILE_FINDER_COLLECTION,
        #     manager_class=FileFinder,
        #     call_id_key="file_finder",
        #     completion_agent_name="process_completion",
        #     use_chat_messages=False  # file_finder doesn't use chat messages
#         )
    
#     async def get_email_sender(self, query: Annotated[str, "The complete user query"]) -> Dict[str, Any]:
#         """Process email sending request using EmailManager."""
#         # Get call ID for email sender
#         call_ids = self.get_last_call_id().get("email_sender", [])
#         call_id = next(
#             (item['id'] for item in call_ids if query in item.get('arguments', '')), 
#             None
#         )
#         return await self.capability_manager.execute_capability(query, self.email_config, call_id)
    
#     async def get_file_finder(self, query: Annotated[str, "The search query"]) -> Union[str, Dict[str, Any]]:
#         """Process file finding request using FileFinder."""
#         # Get call ID for file finder
#         call_ids = self.get_last_call_id().get("file_finder", [])
#         call_id = next(
#             (item['id'] for item in call_ids if query in item.get('arguments', '')), 
#             None
#         )
        
#         result = await self.capability_manager.execute_capability(query, self.file_finder_config, call_id)
        
#         # Return just the content for backward compatibility
#         if result.get("success"):
#             return result["content"]
#         else:
#             return f"The file finder process got into a runtime error, please check the logs for more details. Process that encountered the error > : {query}"
    
#     # Add more capabilities easily
#     async def get_some_other_capability(self, query: str):
#         other_config = CapabilityConfig(
#             name="other_capability",
#             collection=settings.OTHER_COLLECTION,
#             manager_class=OtherManager,
#             call_id_key="other_capability"
#         )
#         # Get call ID for other capability
#         call_ids = self.get_last_call_id().get("other_capability", [])
#         call_id = next(
#             (item['id'] for item in call_ids if query in item.get('arguments', '')), 
#             None
#         )
#         return await self.capability_manager.execute_capability(query, other_config, call_id)