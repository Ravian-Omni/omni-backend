import autogen
import requests
import openai
import re
import os
import time
import asyncio
import pandas as pd
from autogen.agentchat.agent import Agent
from typing import List, Dict, Any
from autogen import AssistantAgent, UserProxyAgent, GroupChat, GroupChatManager, ConversableAgent
import logging
import json
from datetime import datetime

current_datetime = datetime.now()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
import uuid
import io
from PIL import Image
from typing_extensions import Annotated
from huggingface_hub import InferenceClient
from capabilities.python_developer import prompts
from capabilities.python_developer.response_format import ProblemStatusResponse
from autogen import config_list_from_json
from utilities.external_memory import get_last_entry, get_all_messages
from configs.settings import settings
from configs.llm_configs_manager import LLMConfigManager
import autogen
import asyncio
from typing import List, Optional,Dict,Any
from utilities.logging import logger
from utilities.storage import omni_storage, update_db
from utilities.custom_manager import CustomGroupChatManager




class PythonDeveloper:
    def __init__(self, chat_id, call_id, capability_id, omni_memory):
        self.chat_id = chat_id
        self.call_id = call_id
        self.capability_id = capability_id
        self.omni_memory = omni_memory
        self.llm_config = LLMConfigManager.get_config("gpt_4_1_mini")
        self.llm_config_psc = LLMConfigManager.get_config("gpt_4_1_mini")
        self.llm_config_psc["response_format"] = ProblemStatusResponse
        self.file_location = os.path.join(settings.ROOT_DIR, "code", "output")
        self.coding_language = "python"
        self.results_dir = os.path.join(settings.ROOT_DIR, "code")
        self.agents = self.get_agents()
        self.get_chat_manager()
        
    def get_planner(self):
        return autogen.AssistantAgent(
            name="planner_agent",
            llm_config=self.llm_config,
            system_message=prompts.planner.format(get_last_entry=get_last_entry,get_all_messages=get_all_messages,file_location=self.file_location,coding_language=self.coding_language)
        )
    
    def get_code_writer(self):
        return autogen.AssistantAgent(
            name="code_writer_agent",
            llm_config=self.llm_config,
            system_message=prompts.code_writer.format(file_location=self.file_location, coding_language=self.coding_language)
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
        
    # static custom speaker selection, no dynamic agent selection or conditional chat routing
    def custom_speaker_selection_func(self, last_speaker: Agent, groupchat: GroupChat):
        messages = groupchat.messages
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



    def get_agents(self) -> List[Agent]:
        self.planner = self.get_planner()
        self.code_writer = self.get_code_writer()
        self.code_executor = self.get_code_executor()
        self.code_debugger = self.get_code_debugger()
        self.problem_status_checker = self.problem_status_checker()
        self.process_completion = self.get_process_completion()

        return [
            self.planner,
            self.code_writer,
            self.code_executor,
            self.code_debugger,
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
            omni_memory=self.omni_memory,
            capability_name=settings.PYTHON_DEV_COLLECTION,
            capability_id=self.capability_id,
            chat_id=self.chat_id,
            call_id=self.call_id,
            human_input_mode="ALWAYS"
        )
        return self.groupchat , self.manager
    

