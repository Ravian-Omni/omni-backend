import asyncio
import json
import os
from collections import defaultdict
from typing import Annotated, Any

import autogen
from autogen import UserProxyAgent
from loguru import logger

from src.chat import prompts
from src.chat.tools.brave import BraveSearchClient, BraveSearchTool
from src.chat.tools.composio import ComposioToolCache, ComposioToolManager
from src.chat.tools.together_image import FluxImageGenerator
from src.configs.datetime_utils import dt
from src.configs.llm_configs_manager import LLMConfigManager
from src.configs.routes import RoutesConfig
from src.configs.settings import CapabilityType, settings
from src.configs.system_ai_config import GroupchatConfigurationManager
from src.dependencies import get_websocket_manager
from src.utilities.api_client import api_client
from src.utilities.async_helpers import async_to_sync

# Import tool registration functions


async def update_chat_history(
    chat_id: str, message: dict, collection_name: str
) -> bool:
    """Update chat history in MongoDB with message data.

    Args:
        chat_id: Unique identifier for the chat session
        message: Message dictionary containing role, name, content, and raw_message
        collection_name: MongoDB collection name for the capability

    Returns:
        bool: True if update was successful

    Raises:
        Exception: If MongoDB operation fails
    """
    try:

        # Extract required fields for different message types
        required_fields = ["role", "name", "raw_message", "usage", "task_id"]
        content_fields = ["role", "name", "content"]

        raw_message_data = {
            field: message[field] for field in required_fields if field in message
        }
        content_message_data = {
            field: message[field] for field in content_fields if field in message
        }

        raw_message_data["timestamp"] = dt.now_iso()  # Add timestamp to raw message
        # Build push operations
        push_operations = {"raw_messages": raw_message_data}

        # Only add to messages if content exists and is not empty
        if content_message_data.get("content"):
            push_operations["messages"] = content_message_data

        # Prepare update document
        update_document = {
            "$push": push_operations,
            "$set": {"updated_at": dt.now()},
        }

        # Execute update operation
        filter_criteria = {"chat_id": chat_id}
        update_result = await api_client.post(
            RoutesConfig.API_UPDATE_CHAT,
            params={"capability": collection_name},
            data={"filter_criteria": filter_criteria, "document": update_document},
        )
        update_result = update_result.standard_response()
        if not update_result.get("success"):
            raise Exception(f"Failed: {update_result.get('message', 'Unknown error')}")

        update_result = update_result.get("data")

        # Log the actual result, not the task object
        logger.info(f"MongoDB update completed for chat_id: {chat_id}")

        return update_result

    except Exception as e:
        logger.error(f"Failed to update chat history for chat_id {chat_id}: {str(e)}")
        raise


class GroupChatManager(autogen.GroupChatManager):
    """Enhanced GroupChatManager with memory, WebSocket, and voice capabilities."""

    def __init__(
        self,
        groupchat,
        chat_id: str,
        task_id=None,
        llm_config=None,
        human_input_mode: str = "NEVER",
    ):
        super().__init__(
            groupchat=groupchat,
            llm_config=llm_config,
            human_input_mode=human_input_mode,
        )
        self.chat_id = chat_id
        self.task_id = task_id
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
        """Get current usage for a specific agent."""
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
        """Calculate usage delta for a specific agent since last check."""
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
        """Get usage details for the sender agent when message is received."""
        return self._calculate_agent_usage_delta(sender, sender.name)

    async def _send_websocket_message(self, message_data: dict) -> None:
        """Send message to WebSocket clients."""
        try:
            websocket_manager = await get_websocket_manager()
            await websocket_manager.send_chat_message(
                session_id=self.chat_id,
                content=message_data,
                source=CapabilityType.CHAT.value.upper(),
            )
        except Exception as e:
            logger.error(f"WebSocket send failed for chat_id {self.chat_id}: {e}")

    async def _process_message_async(self, message_data: dict) -> None:
        """Process message asynchronously."""
        await self._handle_voice_alert(message_data["name"], message_data["content"])
        await self._send_websocket_message(message_data)
        await update_chat_history(self.chat_id, message_data, settings.CHAT_COLLECTION)

    def _print_received_message(
        self, message: dict[str, Any], sender: "autogen.Agent"
    ) -> None:
        """Override to handle received messages with enhanced processing."""
        logger.info(f"Received from {sender.name}: {message}")
        super()._print_received_message(message, sender)

        # Get the sender's usage details (current total + delta for this message)
        sender_usage = self._get_sender_agent_usage(sender)

        content = (
            message.get("content", "") if isinstance(message, dict) else str(message)
        )
        message_data = {
            "role": "user",
            "name": sender.name,
            "content": content,
            "raw_message": message,
            "usage": sender_usage,
            "task_id": self.task_id,
        }
        websocket_message = {
            "role": "user",
            "name": sender.name,
            "content": content,
            "raw_message": message,
            "task_id": self.task_id,
        }
        # Log the usage information for debugging
        logger.info(
            f"Agent {sender.name} usage - "
            f"Delta: {sender_usage['message_delta']['total_tokens']} tokens, "
            f"${sender_usage['message_delta']['cost']:.4f} | "
            f"Total: {sender_usage['current_total']['total_tokens']} tokens, "
            f"${sender_usage['current_total']['cost']:.4f}"
        )

        # Process async operations
        # asyncio.create_task(self._handle_voice_alert(message_data["name"], message_data["content"]))
        async_to_sync(self._send_websocket_message(websocket_message))
        async_to_sync(
            update_chat_history(self.chat_id, message_data, settings.CHAT_COLLECTION)
        )

    # Additional utility methods for comprehensive usage tracking

    def get_all_agents_current_usage(self) -> dict[str, dict[str, Any]]:
        """Get current usage for all agents in the group."""
        all_usage = {}
        for agent in self.groupchat.agents:
            all_usage[agent.name] = self._get_agent_current_usage(agent)
        return all_usage

    def get_group_usage_summary(self) -> dict[str, Any]:
        """Get aggregated usage summary for the entire group."""
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
        """Reset usage tracking (useful for starting fresh tracking mid-conversation)."""
        for agent in self.groupchat.agents:
            current_usage = self._get_agent_current_usage(agent)
            self._agent_previous_usage[agent.name] = current_usage.copy()


class CustomUserProxyAgent(UserProxyAgent):
    """Custom user proxy agent with WebSocket input support."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def set_input_function(self, input_function):
        """Set the custom input function for WebSocket communication."""
        self.input_function = input_function
        return self.input_function

    def get_human_input(self, prompt: str) -> str:
        """Override the default input method to use websocket."""
        print("🔄 Waiting for user input via websocket...")

        # Send input request to websocket client
        # self._send_input_request(prompt)

        # Wait for response from websocket
        return super().get_human_input(prompt)

    async def a_get_human_input(self, prompt: str) -> str:
        """Asynchronously get human input via WebSocket."""
        print("🔁 Custom logic before input...")

        # Safely call super, assuming you have registered an async input
        # result = await super().a_get_human_input(prompt)
        prompt = json.dumps({"agent": self.name, "prompt": prompt})
        return await self.input_function(prompt)

        # print(f"✅ Got input: {result}")
        # return await aioconsole.ainput(prompt)


class Chat:
    """Main Chat orchestrator for task execution and capability management."""

    def __init__(
        self,
        chat_id: str,
        user_id: str = "default_user",
        chat_dir: str = os.path.join(settings.ROOT_DIR, "ravian"),
    ):
        self.user_id = user_id
        self.chat_id = chat_id
        self.task_id = None
        self.chat_dir = chat_dir
        self.cancellation_token = None
        self._initialized = False
        self.llm_config = LLMConfigManager.get_config("default")
        self.groupchat_config = (
            GroupchatConfigurationManager.get_instance().get_groupchat_configuration(
                "chat"
            )
        )

        # Initialize agents synchronously (fast operation)
        self.agents = self.get_agents()
        # Register non-composio tools synchronously (fast operation)
        self._register_local_functions()
        self.get_chat_manager()

    @classmethod
    async def create(
        cls,
        chat_id: str,
        user_id: str = "default_user",
        chat_dir: str = None,
    ) -> "Chat":
        """Async factory method for creating a fully initialized Chat instance.

        This is the preferred way to create a Chat instance as it handles
        async tool registration without blocking.

        Args:
            chat_id: Unique identifier for the chat session
            user_id: User identifier for tool access
            chat_dir: Directory for chat files

        Returns:
            Fully initialized Chat instance with all tools registered
        """
        if chat_dir is None:
            chat_dir = os.path.join(settings.ROOT_DIR, "ravian")

        instance = cls(chat_id=chat_id, user_id=user_id, chat_dir=chat_dir)
        await instance.initialize_tools_async()
        return instance

    async def initialize_tools_async(self) -> int:
        """Initialize Composio tools asynchronously.

        This method registers all Composio tools using async operations
        with parallel fetching for optimal performance.

        Returns:
            Number of tools registered
        """
        if self._initialized:
            logger.debug(f"Chat {self.chat_id} already initialized, skipping")
            return 0

        logger.info(f"Initializing Composio tools for chat {self.chat_id}")

        composio_tool_manager = ComposioToolManager(
            user_id=self.user_id,
            chat_agent=self.chat_agent,
            agent_executor=self.agent_executor,
        )

        tool_count = await composio_tool_manager.register_all_tools_async()
        self._initialized = True

        logger.info(f"Registered {tool_count} Composio tools for chat {self.chat_id}")
        return tool_count

    @staticmethod
    def invalidate_tool_cache(user_id: str) -> None:
        """Invalidate cached tools for a user.

        Call this when a user's connected apps change.

        Args:
            user_id: User identifier to invalidate cache for
        """
        ComposioToolCache.get_instance().invalidate(user_id)

    def set_input_function(self, input_function):
        """Set the custom input function for user interactions."""
        self.input_function = input_function
        return self.input_function

    def set_task_id(self, task_id):
        """Set the current task ID for tracking."""
        self.task_id = task_id
        self.manager.task_id = task_id

    def _set_cancellation_token(self, cancellation_token):
        self.cancellation_token = cancellation_token

    def _check_cancellation(self):
        """Check if operations should be cancelled."""
        if self.cancellation_token and self.cancellation_token.is_cancelled():
            raise asyncio.CancelledError(
                f"OMNI operation cancelled for session {self.chat_id}"
            )

    def get_chat_agent(self):
        """Create and configure the main chat agent.

        Initializes an Autogen AssistantAgent with appropriate LLM configuration,
        termination conditions, and system prompts for conversational interactions.

        Returns:
            autogen.AssistantAgent: Configured chat agent for handling user conversations.
        """
        llm_config_name = (
            self.groupchat_config.get_agent_config("chat_agent").llm_config or "default"
        )
        llm_chat_agent = LLMConfigManager.get_config(llm_config_name)
        agent_config = self.groupchat_config.get_agent_config("chat_agent")
        chat_prompt = agent_config.system_message
        if agent_config.custom_properties.get("max_tokens"):
            llm_chat_agent["max_tokens"] = agent_config.custom_properties.get(
                "max_tokens"
            )
        return autogen.AssistantAgent(
            name="chat_agent",
            llm_config=llm_chat_agent,
            is_termination_msg=lambda msg: msg.get("content", "").strip().upper()
            == "TERMINATE",
            system_message=chat_prompt if chat_prompt else prompts.chat_agent,
            # system_message=prompts.chat_agent,
            # .format(
            #     today=today_date.strftime("%Y-%m-%d")
            # ),
        )

    def get_agent_executor(self):
        """Create and configure the agent executor.

        Initializes a CustomUserProxyAgent that serves as the execution agent
        for running registered tools and functions without human intervention.

        Returns:
            CustomUserProxyAgent: Configured executor agent for tool execution.
        """
        return CustomUserProxyAgent(
            "agent_executor",
            human_input_mode="NEVER",
            # description="""This agent will execute the function which are group chat on their own""",
            code_execution_config=False,
            # is_termination_msg=lambda x: x.get("content", "").find("TERMINATE") >= 0,
        )

    def _register_local_functions(self):
        """Register local tools (image generation, web search) for the chat manager."""

        def flux_image_generator_wrapper(
            query: Annotated[str, "The image generation prompt"],
            filename: Annotated[str, "The filename to save the image as"],
            width: Annotated[int, "Width of the image"] = 512,
            height: Annotated[int, "Height of the image"] = 512,
        ):
            generator = FluxImageGenerator(output_dir=self.chat_dir)
            return generator.generate_image(
                prompt=query, filename=filename, width=width, height=height
            )

        async def search_tool_wrapper(
            query: Annotated[
                str,
                "The search query string - be specific and descriptive for better results. Include relevant keywords, context, and relationships to the topic being searched",
            ],
            search_type: Annotated[
                str,
                "Search mode: 'comprehensive' (detailed results with extra snippets), 'quick' (fast basic results), 'recent' (time-filtered results)",
            ] = "comprehensive",
        ):
            """Brave Search API tool with comprehensive result formatting.

            Args:
                query: Search query
                search_type: "quick" (basic), "comprehensive" (detailed), "recent" (with freshness filter)
                count: Number of results (1-20)
                freshness: Time filter - "pd", "pw", "pm", "py"
                country: Country code
                safesearch: Safe search level
            """
            # Initialize client with SSL verification enabled by default
            # If you encounter SSL certificate errors, you can disable verification with verify_ssl=False
            # However, this is NOT recommended for production environments
            client = BraveSearchClient(verify_ssl=True)
            search_tool = BraveSearchTool(client)

            # Perform search
            return await search_tool.search(query=query, search_type=search_type)

        if self.groupchat_config.function_descriptions:
            if "image_generator" in self.groupchat_config.function_descriptions.keys():
                image_generator = self.groupchat_config.function_descriptions.get(
                    "image_generator"
                )
                autogen.agentchat.register_function(
                    flux_image_generator_wrapper,
                    caller=self.chat_agent,
                    executor=self.agent_executor,
                    name="image_generator",
                    description=(
                        image_generator.get("description")
                        if image_generator.get("description")
                        else "This tool will be used to generate images based on the information."
                    ),
                )
            if "web_api_search" in self.groupchat_config.function_descriptions.keys():
                web_api_search = self.groupchat_config.function_descriptions.get(
                    "web_api_search"
                )
                autogen.register_function(
                    search_tool_wrapper,
                    caller=self.chat_agent,
                    executor=self.agent_executor,
                    name="web_api_search",
                    description=(
                        web_api_search.get("description")
                        if web_api_search.get("description")
                        else (
                            "Search the web using Brave Search API to find current information, "
                            "news, articles, videos, images, and other content. This tool provides "
                            "comprehensive search results including web pages, videos, images, news "
                            "articles, forum discussions, FAQs, and local business information. "
                            "Use this when you need to find real-time information, verify facts, "
                            "research topics, or gather current data from the internet."
                        )
                    ),
                )

    def custom_speaker_selection_func(self, last_speaker: Any, groupchat: Any) -> Any:
        """Determine the next speaker in the group chat conversation flow.

        Implements custom logic for speaker selection based on conversation state,
        enabling smooth transitions between chat agent and executor agent.

        Args:
            last_speaker: The agent that spoke last in the conversation.
            groupchat: The group chat instance containing all agents and messages.

        Returns:
            The next agent to speak, or None if no valid transition exists.

        Raises:
            asyncio.CancelledError: If the operation is cancelled via cancellation token.
        """
        try:
            self._check_cancellation()

            messages = groupchat.messages

            if len(messages) == 1 or last_speaker.name == "chat_manager":
                return groupchat.agent_by_name("chat_agent")
            if (
                last_speaker.name == "chat_agent"
                and len(messages[-1].get("tool_calls", [])) > 0
            ):
                return groupchat.agent_by_name("agent_executor")
            if last_speaker.name == "agent_executor":
                return groupchat.agent_by_name("chat_agent")
            return None
        except asyncio.CancelledError:
            raise

    def get_agents(self):
        """Initialize and return all agents for the chat system.

        Creates both the chat agent and executor agent, storing them as
        instance attributes and returning them as a list for group chat setup.

        Returns:
            list: List containing the chat agent and executor agent instances.
        """
        self.chat_agent = self.get_chat_agent()
        self.agent_executor = self.get_agent_executor()
        return [
            self.chat_agent,
            self.agent_executor,
        ]

    def get_chat_manager(self):
        """Create and configure the group chat manager."""
        self.groupchat = autogen.GroupChat(
            agents=self.agents,
            messages=[],
            speaker_selection_method=self.custom_speaker_selection_func,
            max_round=self.groupchat_config.groupchat_settings.get("max_round", 500),
        )
        self.manager = GroupChatManager(
            groupchat=self.groupchat,
            llm_config=self.llm_config,
            human_input_mode="ALWAYS",
            chat_id=self.chat_id,
            task_id=self.task_id,
        )
        return self.manager, self.groupchat
