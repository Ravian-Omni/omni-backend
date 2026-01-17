"""Custom AutoGen group chat manager with enhanced tracking and WebSocket support.

This module provides a custom GroupChatManager implementation that extends AutoGen's
standard manager with chat context tracking, usage monitoring, database persistence,
real-time WebSocket communication, and SimpleMem memory integration.
"""

import asyncio
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

import autogen
from loguru import logger

from src.configs.datetime_utils import dt
from src.configs.routes import RoutesConfig
from src.dependencies import get_websocket_manager
from src.managers.cancellation_token import CancellationToken
from src.memory.integration import mem
from src.omni.memory import OmniMemory
from src.utilities.api_client import api_client
from src.utilities.async_helpers import async_to_sync


@dataclass
class ChatContext:
    """Chat context containing all necessary identifiers and configuration.

    This dataclass encapsulates all the context information needed for a chat
    session, including user identification, chat routing, memory management,
    and capability configuration.

    Attributes:
        user_id: Unique identifier for the user.
        chat_id: Unique identifier for the chat session.
        chat_dir: Directory path for storing chat-related files.
        call_id: Unique identifier for the current API call.
        capability_id: Unique identifier for the capability being used.
        capability_name: Human-readable name of the capability.
        collection_name: MongoDB collection name for storing chat data.
        omni_memory: OmniMemory instance for managing conversation memory.
        cancellation_token: Token for cancelling long-running operations.
        task_id: Optional identifier for tracking specific tasks.
        manager_kwargs: Additional keyword arguments for manager configuration.
    """

    user_id: str
    chat_id: str
    chat_dir: str
    call_id: str
    capability_id: str
    capability_name: str
    collection_name: str
    omni_memory: OmniMemory
    cancellation_token: CancellationToken = None
    task_id: str = None
    manager_kwargs: dict[str, Any] | None = None

    def __post_init__(self):
        """Initialize manager_kwargs to empty dict if not provided."""
        if self.manager_kwargs is None:
            self.manager_kwargs = {}


async def create_capability_chat(context: ChatContext) -> dict[str, str]:
    """Create a new capability chat session in the database.

    Initialize a new chat document with all necessary metadata and store it
    in the database using the capability's collection.

    Args:
        context: ChatContext containing all chat identifiers and configuration.

    Returns:
        Dictionary containing the created chat_id.

    Raises:
        Exception: If database chat creation fails.

    Example:
        >>> context = ChatContext(
        ...     user_id="user123",
        ...     chat_id="chat456",
        ...     capability_name="search"
        ... )
        >>> result = await create_capability_chat(context)
        >>> print(result["chat_id"])
        chat456
    """
    chat_document = {
        "user_id": context.user_id,
        "chat_id": context.chat_id,
        "call_id": context.call_id,
        "capability_id": context.capability_id,
        "messages": [],
        "raw_messages": [],
        "created_at": dt.now(),
        "updated_at": dt.now(),
    }

    # Create database record
    create_chat = await api_client.post(
        RoutesConfig.API_CREATE_OMNI_CHAT,
        params={"capability": context.collection_name},
        data=chat_document,
    )
    create_chat = create_chat.standard_response()
    if not create_chat.get("success"):
        raise Exception(
            f"Failed to create capbility_chat: {create_chat.get('message', 'Unknown error')}"
        )

    create_chat.get("data")
    # await mongodb.insert_one(context.collection_name, chat_document)

    # Return standardized response using Pydantic model
    return {"chat_id": context.chat_id}


async def update_chat_history(context: ChatContext, message: dict[str, Any]) -> bool:
    """Update chat history in MongoDB.

    Args:
        context: Chat context with all identifiers.
        message: Message data to store.

    Returns:
        True if update was successful.
    """
    try:
        # Extract message fields safely
        raw_message = {
            k: message.get(k)
            for k in ["role", "name", "raw_message", "usage", "task_id"]
            if k in message
        }
        content_message = {
            k: message.get(k) for k in ["role", "name", "content"] if k in message
        }

        raw_message["timestamp"] = dt.now_iso()  # Add timestamp to raw message

        # Build push operations
        push_operations = {"raw_messages": raw_message}
        if content_message.get("content"):
            push_operations["messages"] = content_message

        # Prepare update document
        update_document = {
            "$push": push_operations,
            "$set": {"updated_at": dt.now()},
        }

        # Execute update
        filter_criteria = {
            "user_id": context.user_id,
            "chat_id": context.chat_id,
            "call_id": context.call_id,
            "capability_id": context.capability_id,
        }

        update_result = await api_client.post(
            RoutesConfig.API_UPDATE_OMNI_CHAT,
            params={"capability": context.collection_name},
            data={"filter_criteria": filter_criteria, "document": update_document},
        )
        update_result = update_result.standard_response()
        if not update_result.get("success"):
            raise Exception(
                f"Failed to update chat history: {update_result.get('message', 'Unknown error')}"
            )

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
        # return False
        raise e


class CustomGroupChatManager(autogen.GroupChatManager):
    """Enhanced GroupChatManager with chat context and background processing.

    Extends AutoGen's GroupChatManager to provide additional functionality including:
    - Chat context tracking for database persistence
    - Per-agent token usage monitoring and delta calculation
    - WebSocket integration for real-time message streaming
    - Memory management integration with OmniMemory
    - Background task processing for non-blocking operations

    Attributes:
        context: ChatContext with all chat identifiers and configuration.
        omni_memory: OmniMemory instance for managing conversation memory.
        _agent_previous_usage: Tracks previous token usage for delta calculation.

    Example:
        >>> chat_context = ChatContext(user_id="user123", chat_id="chat456")
        >>> manager = CustomGroupChatManager(
        ...     groupchat=group_chat,
        ...     chat_context=chat_context,
        ...     llm_config=llm_config
        ... )
    """

    def __init__(
        self,
        groupchat,
        chat_context: ChatContext,
        llm_config=None,
        human_input_mode: str = "NEVER",
    ):
        """Initialize CustomGroupChatManager with enhanced tracking.

        Args:
            groupchat: AutoGen GroupChat instance.
            chat_context: ChatContext with all necessary identifiers.
            llm_config: LLM configuration dictionary. Defaults to None.
            human_input_mode: Human input mode setting. Defaults to "NEVER".
        """
        super().__init__(
            groupchat=groupchat,
            llm_config=llm_config,
            human_input_mode=human_input_mode,
        )
        self.context = chat_context
        self.omni_memory = chat_context.omni_memory
        # Track previous usage state for each agent to calculate deltas
        self._agent_previous_usage = defaultdict(
            lambda: {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "cost": 0.0,
            }
        )

        # Initialize tracking for all agents
        self._initialize_agent_tracking()

    def _initialize_agent_tracking(self):
        """Initialize usage tracking for all agents."""
        for agent in self.groupchat.agents:
            # Initialize with current usage if any
            current_usage = self._get_agent_current_usage(agent)
            self._agent_previous_usage[agent.name] = current_usage.copy()

    def _get_agent_current_usage(self, agent) -> dict[str, Any]:
        """Get current usage for a specific agent.

        Retrieve the current token usage statistics from an agent's client,
        including model information, token counts, and cost.

        Args:
            agent: AutoGen agent instance.

        Returns:
            Dictionary containing:
                - model (str): Model name or "unknown"
                - prompt_tokens (int): Number of prompt tokens used
                - completion_tokens (int): Number of completion tokens used
                - total_tokens (int): Total tokens used
                - cost (float): Estimated cost in dollars
        """
        default_usage = {
            "model": "unknown",
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "cost": 0.0,
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
            "cost": model_usage.get("cost", 0.0),
        }

    def _calculate_agent_usage_delta(self, agent, agent_name: str) -> dict[str, Any]:
        """Calculate usage delta for a specific agent since last check.

        Compute the difference in token usage between the current state and
        the previously recorded state, then update the tracking.

        Args:
            agent: AutoGen agent instance.
            agent_name: Name of the agent.

        Returns:
            Dictionary containing:
                - current_total (dict): Current cumulative usage statistics
                - message_delta (dict): Usage for just this message
                - agent_name (str): Name of the agent
        """
        current_usage = self._get_agent_current_usage(agent)
        previous_usage = self._agent_previous_usage[agent_name]

        # Calculate the delta (what changed since last check)
        usage_delta = {
            "prompt_tokens": current_usage["prompt_tokens"]
            - previous_usage["prompt_tokens"],
            "completion_tokens": current_usage["completion_tokens"]
            - previous_usage["completion_tokens"],
            "total_tokens": current_usage["total_tokens"]
            - previous_usage["total_tokens"],
            "cost": current_usage["cost"] - previous_usage["cost"],
        }

        # Update the previous usage for next calculation
        self._agent_previous_usage[agent_name] = current_usage.copy()

        # Return both current total and delta for this message
        return {
            "current_total": current_usage,
            "message_delta": usage_delta,
            "agent_name": agent_name,
        }

    def _get_sender_agent_usage(self, sender) -> dict[str, Any]:
        """Get usage details for the sender agent when message is received.

        Args:
            sender: AutoGen agent that sent the message.

        Returns:
            Usage delta dictionary with current total and message delta.
        """
        return self._calculate_agent_usage_delta(sender, sender.name)

    async def _send_websocket_message(self, message: dict[str, Any]) -> None:
        """Send message to WebSocket clients.

        Broadcast a message to all connected WebSocket clients for the current
        chat session in real-time.

        Args:
            message: Message data to send.

        Raises:
            Exception: If WebSocket send operation fails.
        """
        try:
            websocket_manager = await get_websocket_manager()
            await websocket_manager.send_chat_message(
                session_id=self.context.chat_id,
                content=message,
                source=self.context.capability_name,
            )
        except Exception as e:
            logger.error(f"WebSocket send failed: {e}")
            raise e

    async def _process_message_background(self, message_data: dict[str, Any]) -> None:
        """Process message in background (WebSocket + Database).

        Execute WebSocket broadcasting and database persistence concurrently
        without blocking the main conversation flow.

        Args:
            message_data: Message data to process.
        """
        await asyncio.gather(
            self._send_websocket_message(message_data),
            update_chat_history(self.context, message_data),
            return_exceptions=True,
        )

    def _print_received_message(
        self, message: dict[str, Any], sender: "autogen.Agent"
    ) -> None:
        """Override to handle received messages with enhanced processing.

        Process incoming messages from agents with additional features:
        - Track token usage and calculate deltas
        - Store messages in OmniMemory
        - Persist to database
        - Broadcast via WebSocket

        Args:
            message: Message dictionary or string content.
            sender: AutoGen agent that sent the message.

        Note:
            This method overrides the parent class method to add custom
            processing while maintaining the original behavior.
        """
        logger.info(f"Received from {sender.name}: {message}")
        super()._print_received_message(message, sender)

        # Get the sender's usage details (current total + delta for this message)
        sender_usage = self._get_sender_agent_usage(sender)

        # Prepare message data
        content = (
            message.get("content", "") if isinstance(message, dict) else str(message)
        )
        message_data = {
            "role": "user",
            "name": sender.name,
            "content": content,
            "raw_message": message,
            "usage": sender_usage,
            "task_id": self.context.task_id,
        }
        websocket_message = {
            "role": "user",
            "name": sender.name,
            "content": content,
            "raw_message": message,
            "call_id": self.context.call_id,
            "capability_id": self.context.capability_id,
            "task_id": self.context.task_id,
        }
        # Store in memory (synchronous - OmniMemory for backward compatibility)
        memory_data = {k: message_data[k] for k in ["role", "name", "content"]}
        self.omni_memory.push_capability_message(
            memory_data, self.context.capability_name, self.context.capability_id
        )

        # Process background tasks (async)
        async_to_sync(update_chat_history(self.context, message_data))
        async_to_sync(self._send_websocket_message(websocket_message))

        # Feed to SimpleMem (non-blocking, fire-and-forget)
        mem.fire(mem.add_message(
            chat_id=self.context.chat_id,
            speaker=sender.name,
            content=content,
            task_id=self.context.task_id,
            capability=self.context.capability_name,
            capability_run_id=self.context.capability_id,
            raw_message=message,
        ))

    # Additional utility methods for comprehensive usage tracking

    def get_all_agents_current_usage(self) -> dict[str, dict[str, Any]]:
        """Get current usage for all agents in the group."""
        all_usage = {}
        for agent in self.groupchat.agents:
            all_usage[agent.name] = self._get_agent_current_usage(agent)
        return all_usage

    def get_group_usage_summary(self) -> dict[str, Any]:
        """Get aggregated usage summary for the entire group.

        Calculate total token usage and costs across all agents in the group.

        Returns:
            Dictionary containing:
                - total_prompt_tokens (int): Total prompt tokens across all agents
                - total_completion_tokens (int): Total completion tokens
                - total_tokens (int): Total tokens used
                - total_cost (float): Total estimated cost
                - agents_count (int): Number of agents in the group
                - models_used (list): List of unique models used
                - per_agent (dict): Individual agent usage statistics
        """
        all_usage = self.get_all_agents_current_usage()

        total_summary = {
            "total_prompt_tokens": 0,
            "total_completion_tokens": 0,
            "total_tokens": 0,
            "total_cost": 0.0,
            "agents_count": len(all_usage),
            "models_used": set(),
            "per_agent": all_usage,
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
        """Reset usage tracking."""
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
#         async_to_sync(self.send_websocket(db_content))
#         asyncio.create_task(update_db(chat_id=self.chat_id, call_id=self.call_id, message=db_content, capability=self.capability, capability_id=self.capability_id))
