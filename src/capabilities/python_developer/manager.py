import asyncio
import os

import autogen
from autogen import GroupChat, UserProxyAgent
from autogen.agentchat.agent import Agent
from loguru import logger

from src.capabilities.python_developer import prompts
from src.capabilities.python_developer.executor import (
    InteractiveLocalCommandLineCodeExecutor,
)
from src.capabilities.python_developer.response_format import (
    PlannerResponseFormat,
    ProblemStatusResponse,
)
from src.configs.llm_configs_manager import LLMConfigManager
from src.configs.system_ai_config import GroupchatConfigurationManager
from src.utilities.custom_manager import ChatContext, CustomGroupChatManager
from src.utilities.storage import ensure_path
from src.utilities.venv_config import AG2AIVirtualEnvContext


class LoopDetector:
    """Detects repetitive patterns in conversation messages."""

    def __init__(self, window_size=3):
        self.recent_messages = []
        self.window_size = window_size

    def update(self, message: str) -> bool:
        """Update the detector with a new message and check for loops."""
        if message in self.recent_messages:
            return True
        self.recent_messages.append(message)
        if len(self.recent_messages) > self.window_size:
            self.recent_messages.pop(0)
        return False


loop_detector = LoopDetector()


class PythonDeveloper:
    """Manager for Python code development and execution capabilities."""

    def __init__(self, context: ChatContext):
        self.context = context
        self.groupchat_config = (
            GroupchatConfigurationManager.get_instance().get_groupchat_configuration(
                "python_coder"
            )
        )
        self.websocket_manager = context.manager_kwargs["websocket_manager"]
        self.llm_config = LLMConfigManager.get_config("default")
        self.coding_language = "python"
        self.results_dir = ensure_path(os.path.join(self.context.chat_dir, ".code"))
        self.file_location = ensure_path(os.path.join(self.context.chat_dir, "files"))
        venv_context = AG2AIVirtualEnvContext()
        self.executor = InteractiveLocalCommandLineCodeExecutor(
            session_id=self.context.chat_id,
            virtual_env_context=venv_context.get_context(),
            timeout=120,
            work_dir=self.results_dir,
        )
        self.websocket_manager.active_executor[self.context.chat_id] = self.executor
        self.agents = self.get_agents()
        self.get_chat_manager()

    def _check_cancellation(self):
        """Check if the chat should be cancelled."""
        if (
            self.context.cancellation_token
            and self.context.cancellation_token.is_cancelled()
        ):
            raise asyncio.CancelledError(
                f"Group chat cancelled for session {self.context.chat_id}"
            )

    def get_planner(self):
        """Get the planner agent."""
        llm_config_name = (
            self.groupchat_config.get_agent_config("planner_agent").llm_config
            or "default"
        )
        llm_planner_agent = LLMConfigManager.get_config(llm_config_name)
        llm_planner_agent["response_format"] = PlannerResponseFormat
        return autogen.AssistantAgent(
            name="planner_agent",
            llm_config=llm_planner_agent,
            system_message=prompts.planner.format(
                file_location=self.file_location, coding_language=self.coding_language
            ),
        )

    def get_context_keeper(self):
        """Get the context keeper agent."""
        return autogen.AssistantAgent(name="context_keeper", llm_config=self.llm_config)

    def get_code_writer(self):
        """Get the code writer agent."""
        llm_config_name = (
            self.groupchat_config.get_agent_config("code_writer_agent").llm_config
            or "default"
        )
        llm_code_writer_agent = LLMConfigManager.get_config(llm_config_name)
        llm_code_writer_agent["max_tokens"] = 16384
        return autogen.AssistantAgent(
            name="code_writer_agent",
            llm_config=llm_code_writer_agent,
            system_message=prompts.code_writer.format(file_location=self.file_location),
        )

    def get_code_executor(self):
        """Get the code executor agent."""
        return UserProxyAgent(
            name="code_executor_agent",
            human_input_mode="NEVER",
            code_execution_config={"executor": self.executor},
            llm_config=self.llm_config,
        )

    def get_code_debugger(self):
        """Get the code debugger agent."""
        llm_config_name = (
            self.groupchat_config.get_agent_config("code_debugger_agent").llm_config
            or "default"
        )
        llm_code_debugger_agent = LLMConfigManager.get_config(llm_config_name)
        return autogen.AssistantAgent(
            name="code_debugger_agent",
            llm_config=llm_code_debugger_agent,
            max_consecutive_auto_reply=5,
            system_message=prompts.debugger.format(
                file_location=self.file_location, coding_language=self.coding_language
            ),
        )

    def problem_status_checker(self):
        """Get the problem status checker agent."""
        llm_config_name = (
            self.groupchat_config.get_agent_config(
                "problem_status_checker_agent"
            ).llm_config
            or "default"
        )
        llm_problem_status_checker_agent = LLMConfigManager.get_config(llm_config_name)
        llm_problem_status_checker_agent["response_format"] = ProblemStatusResponse
        return autogen.AssistantAgent(
            name="problem_status_checker_agent",
            system_message=prompts.prob_status_checker,
            llm_config=llm_problem_status_checker_agent,
        )

    def get_process_completion(self):
        """Get the process completion agent."""
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

    def get_stop_agent(self):
        """Get the stop agent for terminating conversations."""
        return autogen.ConversableAgent(
            name="stop_agent",
            llm_config=self.llm_config,
            system_message="I am the fallback agent. My only task is to terminate the conversation.",
        )

    def is_termination_msg(msg: str) -> bool:
        """Check if the message indicates termination."""
        return "terminate" in msg.lower() or "exit" in msg.lower()

    def custom_speaker_selection_func(self, last_speaker: Agent, groupchat: GroupChat):
        """Select the next speaker based on conversation state and last speaker."""
        try:
            self._check_cancellation()

            messages = groupchat.messages
            last_msg = messages[-1]["content"] if messages else ""

            if loop_detector.update(last_msg):
                return groupchat.agent_by_name("stop_agent")

            if len(messages) <= 1 or last_speaker.name == "chat_manager":

                return groupchat.agent_by_name("planner_agent")
            if last_speaker.name == "planner_agent":
                return groupchat.agent_by_name("code_writer_agent")
            elif last_speaker.name == "code_writer_agent":
                return groupchat.agent_by_name("code_executor_agent")
            elif last_speaker.name == "code_executor_agent":
                if "exitcode: 0" in messages[-1]["content"].lower():
                    return groupchat.agent_by_name("problem_status_checker_agent")
                else:
                    return groupchat.agent_by_name("code_debugger_agent")
            elif last_speaker.name == "problem_status_checker_agent":
                if "yes" in messages[-1]["content"].lower():
                    return groupchat.agent_by_name("process_completion_agent")
                else:
                    return groupchat.agent_by_name("code_writer_agent")
            elif last_speaker.name == "code_debugger_agent":
                return groupchat.agent_by_name("code_writer_agent")

        except asyncio.CancelledError:
            logger.info(
                f"Speaker selection cancelled for session {self.context.chat_id}"
            )
            # Return process_completion to gracefully end the chat
            raise

        # return groupchat.agent_by_name("stop_agent")

    def get_agents(self) -> list[Agent]:
        """Initialize and return all agents for the Python development workflow."""
        self.planner = self.get_planner()
        self.context_keeper = self.get_context_keeper()
        self.code_writer = self.get_code_writer()
        self.code_executor = self.get_code_executor()
        self.code_debugger = self.get_code_debugger()
        self.stop_agent = self.get_stop_agent()
        self.problem_status_checker = self.problem_status_checker()
        self.process_completion = self.get_process_completion()

        return [
            self.planner,
            self.context_keeper,
            self.code_writer,
            self.code_executor,
            self.code_debugger,
            self.stop_agent,
            self.problem_status_checker,
            self.process_completion,
        ]

    def get_chat_manager(self):
        """Initialize and return the group chat manager."""
        self.groupchat = autogen.GroupChat(
            agents=self.agents,
            messages=[],
            speaker_selection_method=self.custom_speaker_selection_func,
            max_round=500,
        )
        self.manager = CustomGroupChatManager(
            groupchat=self.groupchat,
            llm_config=self.llm_config,
            chat_context=self.context,
            human_input_mode="ALWAYS",
        )
        return self.groupchat, self.manager
