import asyncio
import json
import os
from collections import defaultdict
from string import Template
from typing import Annotated, Any

import autogen
from autogen import UserProxyAgent
from loguru import logger

from src.capabilities.browser_manager.manager import BrowserManager
from src.capabilities.email_manager.manager import EmailManager
from src.capabilities.file_finder.manager import FileFinder
from src.capabilities.image_generator.manager import ImageGenerator
from src.capabilities.python_developer.manager import PythonDeveloper
from src.configs.datetime_utils import dt
from src.configs.llm_configs_manager import LLMConfigManager
from src.configs.settings import CapabilityType, settings
from src.configs.system_ai_config import GroupchatConfigurationManager
from src.dependencies import get_websocket_manager
from src.omni import prompts
from src.omni.capabilities_descriptions import (
    email_manager_description,
    file_finder_description,
    image_generator_description,
    python_coder_description,
    web_browser_description,
)
from src.omni.capability_manager import CapabilityConfig, CapabilityManager
from src.omni.memory import OmniMemory
from src.omni.response_format import (
    AgentSelectionResponse,
    CapabilityRoutingResponse,
    PlannerResponse,
    QuestionClassification,
)
from src.utilities.async_helpers import async_to_sync
from src.utilities.storage import a_speak, update_chat_history

today_date = dt.now()


class OmniGroupChatManager(autogen.GroupChatManager):
    """Enhanced GroupChatManager with memory, WebSocket, and voice capabilities."""

    def __init__(
        self,
        groupchat,
        memory,
        chat_id: str,
        task_id: str = None,
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
        self.memory = memory
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
                source=CapabilityType.OMNI.value.upper(),
            )
        except Exception as e:
            logger.error(f"WebSocket send failed for chat_id {self.chat_id}: {e}")

    async def _handle_voice_alert(self, agent_name: str, content: str) -> None:
        """Handle voice alerts for specific agents."""
        try:
            if agent_name == "manual_verification":
                await a_speak(content)
            elif agent_name == "process_completion_agent":
                await a_speak("Hey there! Ravian finished your task!")
        except Exception as e:
            logger.error(f"Voice alert failed for agent {agent_name}: {e}")

    async def _process_message_async(self, message_data: dict) -> None:
        """Process message asynchronously."""
        await self._handle_voice_alert(message_data["name"], message_data["content"])
        await self._send_websocket_message(message_data)
        await update_chat_history(self.chat_id, message_data, settings.OMNI_COLLECTION)

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

        # Store in memory synchronously
        self.memory.push_main_message(
            {k: message_data[k] for k in ["role", "name", "content"]}
        )

        # Process async operations
        # asyncio.create_task(self._handle_voice_alert(message_data["name"], message_data["content"]))
        async_to_sync(self._send_websocket_message(websocket_message))
        async_to_sync(
            update_chat_history(self.chat_id, message_data, settings.OMNI_COLLECTION)
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


class Omni:
    """Main Omni orchestrator for multi-agent task execution and capability management."""

    def __init__(
        self,
        chat_id: str,
        user_id: str = "default_user",
        chat_dir: str = os.path.join(settings.ROOT_DIR, "ravian"),
    ):
        self.user_id = user_id
        self.chat_id = chat_id
        self.chat_dir = chat_dir
        self.cancellation_token = None
        self.task_id = None
        self.llm_config = LLMConfigManager.get_config("gpt_4_1_mini")
        self.groupchat_config = (
            GroupchatConfigurationManager.get_instance().get_groupchat_configuration(
                "omni"
            )
        )

        # Memory Configuration
        self.memory = OmniMemory()

        self.capability_manager = CapabilityManager(
            user_id=self.user_id,
            chat_id=self.chat_id,
            chat_dir=self.chat_dir,
            memory=self.memory,
        )

        self.agents = self.get_agents()
        self._register_functions()
        self.get_chat_manager()

    def set_input_function(self, input_function):
        """Set the custom input function for user interactions."""
        self.input_function = input_function
        return self.input_function

    def _set_cancellation_token(self, cancellation_token):
        self.cancellation_token = cancellation_token

    def set_task_id(self, task_id):
        """Set the current task ID for tracking."""
        self.task_id = task_id
        self.manager.task_id = task_id

    def _check_cancellation(self):
        """Check if operations should be cancelled."""
        if self.cancellation_token and self.cancellation_token.is_cancelled():
            raise asyncio.CancelledError(
                f"OMNI operation cancelled for session {self.chat_id}"
            )

    def get_last_call_id(self):
        """Get the last tool call IDs from the agent caller."""
        last_speaker = self.groupchat.messages[-1]
        if last_speaker.get("name") == "agent_caller":
            tool_calls = last_speaker.get("tool_calls")
            result = {}

            for index, item in enumerate(tool_calls):
                function_name = item["function"]["name"]
                call_info = {
                    "id": item["id"],
                    "index": index,
                    "arguments": item["function"].get("arguments", {}),
                }

                if function_name in result:
                    result[function_name].append(call_info)
                else:
                    result[function_name] = [call_info]

            return result
        return None

    def find_call_id(self, capability_name: str, query: str) -> str | None:
        """Find matching call ID for any capability.

        Args:
            capability_name: Name of the capability (e.g., "email_sender", "file_finder")
            query: The query string to match against call arguments

        Returns:
            Optional[str]: The matching call ID if found, None otherwise
        """
        try:
            call_ids = self.get_last_call_id().get(capability_name, [])

            for item in call_ids:
                arguments_str = item.get("arguments", "")

                # Try to parse the arguments as JSON first
                try:
                    arguments_dict = json.loads(arguments_str)
                    # Check if query matches any value in the arguments dict
                    if isinstance(arguments_dict, dict):
                        for key, value in arguments_dict.items():
                            if isinstance(value, str) and query in value:
                                return item["id"]
                    elif isinstance(arguments_dict, str) and query in arguments_dict:
                        return item["id"]
                except json.JSONDecodeError:
                    # If not valid JSON, fall back to string comparison
                    if query in arguments_str:
                        return item["id"]

            return None

        except Exception as e:
            logger.error(f"Error finding {capability_name} call ID: {e}")
            return None

    async def get_image_generator(
        self, query: Annotated[str, "The detailed image generation prompt"]
    ):
        """Execute the image generator capability."""
        call_id = self.find_call_id("image_generator", query)
        self.image_gen_config = CapabilityConfig(
            name=CapabilityType.IMAGE_GENERATOR.value,
            collection=settings.IMAGE_GENERATOR_COLLECTION,
            manager_class=ImageGenerator,
            completion_agent_name="process_completion",
            task_id=self.task_id,
            cancellation_token=self.cancellation_token,
        )
        return await self.capability_manager.execute_capability(
            query, self.image_gen_config, call_id
        )

    async def get_web_browser(
        self,
        query: Annotated[
            str,
            "The complete search query with all the details like subject relationship with the message",
        ],
    ) -> Annotated[
        str,
        "The complete search query with all the details like subject relationship with the message",
    ]:
        """Execute the web browser capability."""
        call_id = self.find_call_id("web_browser", query)
        self.web_browser_config = CapabilityConfig(
            name=CapabilityType.BROWSER_MANAGER.value,
            collection=settings.BROWSER_COLLECTION,
            manager_class=BrowserManager,
            completion_agent_name="process_completion",
            task_id=self.task_id,
            cancellation_token=self.cancellation_token,
            use_chat_messages=False,
            manager_kwargs={"input_function": self.input_function},
        )
        return await self.capability_manager.execute_capability(
            query, self.web_browser_config, call_id
        )

    async def get_python_coder(
        self,
        query: Annotated[
            str,
            "The complete  query with all the details, on what work we have to do and what we have to return for other agents to work on",
        ],
    ) -> Annotated[str, "The results"]:
        """Execute the Python coder capability."""
        call_id = self.find_call_id("python_coder", query)
        websocket_manager = await get_websocket_manager()
        self.python_coder_config = CapabilityConfig(
            name=CapabilityType.PYTHON_DEVELOPER.value,
            collection=settings.PYTHON_DEV_COLLECTION,
            manager_class=PythonDeveloper,
            completion_agent_name="process_completion_agent",
            task_id=self.task_id,
            cancellation_token=self.cancellation_token,
            manager_kwargs={"websocket_manager": websocket_manager},
        )
        return await self.capability_manager.execute_capability(
            query, self.python_coder_config, call_id
        )

    async def get_email_sender(
        self, query: Annotated[str, "The complete user query"]
    ) -> dict:
        """Execute the email sender capability."""
        call_id = self.find_call_id("email_sender", query)
        self.email_sender_config = CapabilityConfig(
            name=CapabilityType.EMAIL_MANAGER.value,
            collection=settings.EMAIL_COLLECTION,
            manager_class=EmailManager,
            completion_agent_name="process_completion_agent",
            task_id=self.task_id,
            cancellation_token=self.cancellation_token,
            manager_kwargs={"input_function": self.input_function},
        )
        return await self.capability_manager.execute_capability(
            query, self.email_sender_config, call_id
        )

    async def get_file_finder(self, query: Annotated[str, "The search query"]):
        """Execute the file finder capability."""
        call_id = self.find_call_id("file_finder", query)
        self.file_finder_config = CapabilityConfig(
            name=CapabilityType.FILE_FINDER.value,
            collection=settings.FILE_FINDER_COLLECTION,
            manager_class=FileFinder,
            completion_agent_name="process_completion",
            task_id=self.task_id,
            cancellation_token=self.cancellation_token,
            use_chat_messages=False,
        )
        return await self.capability_manager.execute_capability(
            query, self.file_finder_config, call_id
        )

    def _register_functions(self):

        # Wrapper functions before registring to agents

        async def image_generator_wrapper(
            query: Annotated[str, "The detailed image generation prompt"]
        ):
            return await self.get_image_generator(query)

        async def web_browser_wrapper(
            query: Annotated[
                str,
                "The complete search query with all the details like subject relationship with the message",
            ]
        ) -> Annotated[
            str,
            "The complete search query with all the details like subject relationship with the message",
        ]:
            return await self.get_web_browser(query)

        async def python_coder_wrapper(
            query: Annotated[
                str,
                "The complete search query with all the details what work we have to do and what we have to return for other agents to work on",
            ]
        ) -> Annotated[str, "The results"]:
            return await self.get_python_coder(query)

        async def email_sender_wrapper(
            query: Annotated[str, "The complete user query"]
        ):
            return await self.get_email_sender(query)

        async def file_finder_wrapper(query: Annotated[str, "The search query"]):
            return await self.get_file_finder(query)

        autogen.agentchat.register_function(
            python_coder_wrapper,
            caller=self.agent_caller,
            executor=self.agent_executor,
            name="python_coder",
            # description="This tool will be used to write any sort of python code.",
            description=python_coder_description,
        )

        autogen.agentchat.register_function(
            email_sender_wrapper,
            caller=self.agent_caller,
            executor=self.agent_executor,
            name="email_sender",
            # description="This tool will be used to send emails as per the user's request.",
            description=email_manager_description,
        )

        autogen.agentchat.register_function(
            file_finder_wrapper,
            caller=self.agent_caller,
            executor=self.agent_executor,
            name="file_finder",
            # description="This tool will be used to find any file as per the user's request.",
            description=file_finder_description,
        )

        autogen.agentchat.register_function(
            web_browser_wrapper,
            caller=self.agent_caller,
            executor=self.agent_executor,
            name="web_browser",
            # description="This tool will be used to search the web.",
            description=web_browser_description,
        )

        autogen.agentchat.register_function(
            image_generator_wrapper,
            caller=self.agent_caller,
            executor=self.agent_executor,
            name="image_generator",
            # description="This tool will be used to generate images form textual input.",
            description=image_generator_description,
        )

    def get_judge_question(self):
        """Create and configure the question judge agent."""
        llm_config_name = (
            self.groupchat_config.get_agent_config("judge_question").llm_config
            or "default"
        )
        llm_config_judge_question = LLMConfigManager.get_config(llm_config_name)
        llm_config_judge_question["response_format"] = QuestionClassification
        return autogen.AssistantAgent(
            name="judge_question",
            llm_config=llm_config_judge_question,
            system_message=prompts.judge_question,  # update the prompt and json output format to judge question and add to speaker selection and all the agents list
        )

    def get_conversation_agent(self):
        """Create and configure the conversation agent."""
        llm_config_name = (
            self.groupchat_config.get_agent_config("conversation_agent").llm_config
            or "default"
        )
        llm_conversation_agent = LLMConfigManager.get_config(llm_config_name)
        return autogen.AssistantAgent(
            name="conversation_agent",
            llm_config=llm_conversation_agent,
            system_message=prompts.conversation,  # update the prompt and json output format to judge question
        )

    def get_planner(self):
        """Create and configure the planner agent."""
        llm_config_name = (
            self.groupchat_config.get_agent_config("conversation_agent").llm_config
            or "default"
        )
        llm_planner_agent = LLMConfigManager.get_config(llm_config_name)
        llm_planner_agent["response_format"] = PlannerResponse
        return autogen.AssistantAgent(
            name="planner_agent",
            llm_config=llm_planner_agent,
            system_message=Template(prompts.planner).substitute(today_date=today_date),
        )

    def get_user_acceptance(self):
        """Create and configure the user acceptance agent."""
        return CustomUserProxyAgent(
            name="get_user_acceptance",
            # default_auto_reply="Awaiting for manual verification",
            human_input_mode="ALWAYS",
            code_execution_config=False,
            # system_message=prompts.manual_verification,
        )

    def get_agent_aligner(self):
        """Create and configure the agent aligner."""
        llm_config_name = (
            self.groupchat_config.get_agent_config("agent_aligner").llm_config
            or "default"
        )
        llm_agent_aligner = LLMConfigManager.get_config(llm_config_name)
        llm_agent_aligner["response_format"] = AgentSelectionResponse
        return autogen.AssistantAgent(
            name="agent_aligner",
            llm_config=llm_agent_aligner,
            description="This agent will align the whole process and will share which agent will work next. ",
            system_message=prompts.agent_aligner,
        )

    def get_agent_router(self):
        """Create and configure the agent router."""
        llm_config_name = (
            self.groupchat_config.get_agent_config("agent_router").llm_config
            or "default"
        )
        llm_agent_router = LLMConfigManager.get_config(llm_config_name)
        llm_agent_router["response_format"] = CapabilityRoutingResponse
        return autogen.AssistantAgent(
            name="agent_router",
            llm_config=llm_agent_router,
            description="""From the initial information route to the capability which will solve the user's question.""",
            system_message=prompts.agent_router,
        )

    def get_agent_caller(self):
        """Create and configure the agent caller."""
        llm_config_name = (
            self.groupchat_config.get_agent_config("agent_caller").llm_config
            or "default"
        )
        llm_config_caller = LLMConfigManager.get_config(llm_config_name)
        llm_config_caller["config_list"][0]["tool_choice"] = {"type": "any"}
        return autogen.AssistantAgent(
            name="agent_caller",
            llm_config=llm_config_caller,
            # system_message=prompts.agent_caller,
        )

    def get_agent_executor(self):
        """Create and configure the agent executor."""
        return UserProxyAgent(
            "agent_executor",
            human_input_mode="NEVER",
            # description="""This agent will execute the function which are group chat on their own""",
            code_execution_config=False,
            system_message=prompts.agent_executor.format(today_date=today_date),
            # is_termination_msg=lambda x: x.get("content", "").find("TERMINATE") >= 0,
        )

    def get_problem_status_checker(self):
        """Create and configure the problem status checker agent."""
        llm_config_name = (
            self.groupchat_config.get_agent_config("problem_status_checker").llm_config
            or "default"
        )
        llm_problem_status_checker = LLMConfigManager.get_config(llm_config_name)
        return autogen.AssistantAgent(
            name="problem_status_checker",
            llm_config=llm_problem_status_checker,
            description="""call this agent to check if the Task specified by the user has been completed""",
            system_message=prompts.prob_status_checker,
        )

    def get_manual_verification(self):
        """Create and configure the manual verification agent."""
        llm_config_name = (
            self.groupchat_config.get_agent_config("manual_verification").llm_config
            or "default"
        )
        llm_config_mini = LLMConfigManager.get_config(llm_config_name)
        return autogen.AssistantAgent(
            name="manual_verification",
            llm_config=llm_config_mini,
            system_message="Ask the question to the user and wait for the response. ",
        )

    def get_user_input(self):
        """Create and configure the user input agent."""
        return CustomUserProxyAgent(
            name="user_input",
            default_auto_reply="Awaiting for manual verification",
            human_input_mode="ALWAYS",
            code_execution_config=False,
            system_message=prompts.manual_verification,
        )

    def get_process_completion(self):
        """Create and configure the process completion agent."""
        llm_config_name = (
            self.groupchat_config.get_agent_config(
                "process_completion_agent"
            ).llm_config
            or "default"
        )
        llm_process_completion_agent = LLMConfigManager.get_config(llm_config_name)
        return autogen.AssistantAgent(
            name="process_completion_agent",
            llm_config=llm_process_completion_agent,
            system_message=prompts.process_completion,
        )

    # dynamic, query classification and agent selection  conditional chat routing for task agent and manual verification
    def custom_speaker_selection_func(self, last_speaker: Any, groupchat: Any) -> Any:
        """Select the next speaker based on conversation state and agent responses."""
        try:
            self._check_cancellation()

            messages = groupchat.messages
            try:
                if last_speaker.name in ["planner_agent"]:
                    status = json.loads(messages[-1]["content"]).get("overall_status")
                    if status == "completed":
                        return groupchat.agent_by_name("process_completion_agent")
            except Exception as e:
                logger.error(f"Error parsing planner_agent message: {e}")

            if len(messages) == 1:
                # judge a question and understand if the question is a task or  general conversation
                return groupchat.agent_by_name("judge_question")
            if last_speaker.name in ["judge_question"]:
                if "task_oriented" in messages[-1]["content"]:
                    # if it is a task oriented question then route to planner agent
                    return groupchat.agent_by_name("planner_agent")
                # if it is a general conversation then route to conversation agent
                if "conversation" in messages[-1]["content"]:
                    return groupchat.agent_by_name("conversation_agent")

            # Agent Aligner will align the process and will route to the next agent
            if last_speaker.name == "agent_aligner":
                if "agent_router" in messages[-1]["content"]:
                    return groupchat.agent_by_name("agent_router")
                elif "manual_verification" in messages[-1]["content"]:
                    return groupchat.agent_by_name("manual_verification")
                elif "process_completion" in messages[-1]["content"]:
                    return groupchat.agent_by_name("process_completion_agent")

            # inner loop planner agent will report back to aligner agent
            if last_speaker.name in ["planner_agent"]:
                if len(messages) >= 2 and messages[-2]["name"] == "judge_question":
                    # prompt = json.dumps({"agent":"get_user_acceptance", "prompt":"Please confirm if you want to proceed with the plan generated by the planner agent."})
                    # answer = async_to_sync(self.input_function(prompt))
                    return groupchat.agent_by_name("get_user_acceptance")
                else:
                    return groupchat.agent_by_name("agent_aligner")

            # inner loop planner agent will report back to aligner agent
            if last_speaker.name in ["get_user_acceptance"]:
                return groupchat.agent_by_name("agent_aligner")
            # if last_speaker.name in ["user_input"]:
            #     return groupchat.agent_by_name("agent_aligner")

            # inner loop manual verification agent will report back to aligner agent
            if last_speaker.name in ["manual_verification"]:
                return groupchat.agent_by_name("user_input")
            if last_speaker.name in ["user_input"]:
                return groupchat.agent_by_name("agent_aligner")

            # how the sequential processes will get called
            if last_speaker.name == "agent_router":
                return groupchat.agent_by_name("agent_caller")
            if last_speaker.name == "agent_caller" and messages[-1].get(
                "content", None
            ):
                return groupchat.agent_by_name("conversation_agent")
            if last_speaker.name == "agent_caller":
                return groupchat.agent_by_name("agent_executor")
            if last_speaker.name == "agent_executor":
                return groupchat.agent_by_name("planner_agent")
            if last_speaker.name == "chat_manager":
                return groupchat.agent_by_name("judge_question")

            return None
        except asyncio.CancelledError:
            logger.info(f"Speaker selection cancelled for session {self.chat_id}")
            # Return process_completion to gracefully end the chat
            # return groupchat.agent_by_name("process_completion_agent")
            raise

    def get_agents(self):
        """Initialize and return all agents for the Omni workflow."""
        self.judge_question = self.get_judge_question()
        self.conversation_agent = self.get_conversation_agent()
        self.planner = self.get_planner()
        self.agent_aligner = self.get_agent_aligner()
        self.agent_router = self.get_agent_router()
        self.agent_caller = self.get_agent_caller()
        self.agent_executor = self.get_agent_executor()
        self.manual_verification = self.get_manual_verification()
        self.get_user_acceptance = self.get_user_acceptance()
        self.user_input = self.get_user_input()
        self.process_completion = self.get_process_completion()
        return [
            self.judge_question,
            self.conversation_agent,
            self.planner,
            self.agent_aligner,
            self.agent_router,
            self.agent_caller,
            self.agent_executor,
            self.get_user_acceptance,
            self.manual_verification,
            self.user_input,
            self.process_completion,
        ]

    def get_chat_manager(self):
        """Create and configure the group chat manager."""
        self.groupchat = autogen.GroupChat(
            agents=self.agents,
            messages=[],
            speaker_selection_method=self.custom_speaker_selection_func,
            max_round=500,
        )
        self.manager = OmniGroupChatManager(
            groupchat=self.groupchat,
            memory=self.memory,
            llm_config=self.llm_config,
            human_input_mode="ALWAYS",
            chat_id=self.chat_id,
            task_id=self.task_id,
        )
        return self.manager, self.groupchat
