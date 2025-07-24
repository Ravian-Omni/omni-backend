import autogen
import os
from autogen.agentchat.agent import Agent
from typing import List, Dict, Any
from autogen import UserProxyAgent, GroupChat
from capabilities.python_developer import prompts
from capabilities.python_developer.response_format import ProblemStatusResponse
from configs.llm_configs_manager import LLMConfigManager
import autogen
import asyncio
from typing import List, Optional,Dict,Any
from loguru import logger
from utilities.storage import ensure_path
from utilities.custom_manager import CustomGroupChatManager, ChatContext

class LoopDetector:
        def __init__(self, window_size=3):
            self.recent_messages = []
            self.window_size = window_size

        def update(self, message: str) -> bool:
            if message in self.recent_messages:
                return True
            self.recent_messages.append(message)
            if len(self.recent_messages) > self.window_size:
                self.recent_messages.pop(0)
            return False
loop_detector = LoopDetector()

class PythonDeveloper:
    def __init__(self, context: ChatContext):
        self.context = context
        self.llm_config = LLMConfigManager.get_config("gpt_4_1_mini")
        self.llm_code_writer = LLMConfigManager.get_config("claude-3-7-sonnet-20250219")
        self.llm_config_psc = LLMConfigManager.get_config("gpt_4_1_mini")
        self.llm_config_psc["response_format"] = ProblemStatusResponse
        self.coding_language = "python"
        self.results_dir = ensure_path(os.path.join(self.context.chat_dir, ".code"))
        self.file_location = ensure_path(os.path.join(self.context.chat_dir, "files"))
        self.agents = self.get_agents()
        self.get_chat_manager()
    
    def _check_cancellation(self):
        """Check if the chat should be cancelled"""
        if self.context.cancellation_token and self.context.cancellation_token.is_cancelled():
            raise asyncio.CancelledError(f"Group chat cancelled for session {self.context.chat_id}")
        
    def get_planner(self):
        return autogen.AssistantAgent(
            name="planner_agent",
            llm_config=self.llm_config,
            system_message=prompts.planner.format(file_location=self.file_location,coding_language=self.coding_language)
        )
    
    def get_context_keeper(self):
        return autogen.AssistantAgent(
            name="context_keeper",
            llm_config=self.llm_config
        )
    
    def get_code_writer(self):
        return autogen.AssistantAgent(
            name="code_writer_agent",
            llm_config=self.llm_code_writer,
            system_message=prompts.code_writer.format(file_location=self.file_location)
        )
    def get_code_executor(self):
        return UserProxyAgent(
            name="code_executor_agent",
            human_input_mode="NEVER",
            code_execution_config={
                "work_dir": self.results_dir,
                "use_docker": False,
            },
            llm_config=self.llm_config
        )
    def get_code_debugger(self):
        return autogen.AssistantAgent(
            name="code_debugger_agent",
            llm_config=self.llm_config,
            system_message=prompts.debugger.format(file_location=self.file_location,coding_language=self.coding_language)
        )
    def problem_status_checker(self):
        return autogen.AssistantAgent(
            name="problem_status_checker_agent",
            system_message=prompts.prob_status_checker,
            llm_config=self.llm_config_psc
        )
    def get_process_completion(self):
        return autogen.AssistantAgent(
            name="process_completion_agent",
            llm_config=self.llm_config,
            system_message=prompts.process_completion
        )
    
    def get_stop_agent(self):
        return autogen.ConversableAgent(
            name="stop_agent",
            llm_config=self.llm_config,
            system_message="I am the fallback agent. My only task is to terminate the conversation."
        )
    
    

        
    def is_termination_msg(msg: str) -> bool:
        return "terminate" in msg.lower() or "exit" in msg.lower()
    
        
    # static custom speaker selection, no dynamic agent selection or conditional chat routing
    def custom_speaker_selection_func(self, last_speaker: Agent, groupchat: GroupChat):
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
                if 'yes' in messages[-1]["content"].lower():
                    return groupchat.agent_by_name("process_completion_agent")
                else:
                    return groupchat.agent_by_name("code_writer_agent")
            elif last_speaker.name == "code_debugger_agent":
                return groupchat.agent_by_name("code_writer_agent")
            
        except asyncio.CancelledError:
            logger.info(f"Speaker selection cancelled for session {self.context.chat_id}")
            # Return process_completion to gracefully end the chat
            raise
        
        # return groupchat.agent_by_name("stop_agent")



    def get_agents(self) -> List[Agent]:
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
            self.process_completion
        ]


    def get_chat_manager(self):
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
            human_input_mode="ALWAYS"
        )
        return self.groupchat , self.manager
    

