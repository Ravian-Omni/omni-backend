# To install required packages:
# pip install pyautogen==0.2.9 panel==1.3.8
import autogen
# import panel as pn
import requests
import openai
import re
import os
import time
import asyncio
# from langchain.chat_models.azure_openai import AzureChatOpenAI
# from langchain_community.chat_models.azure_openai import AzureChatOpenAI
# from langchain_openai import AzureChatOpenAI
# from autogen.coding import LocalCommandLineCodeExecutor
# import LocalCommandLineCodeExecutor
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
from utilities.custom_manager import CustomGroupChatManager



llm_config_psc = LLMConfigManager.get_config("gpt_4_1_mini")
llm_config_psc["response_format"] = ProblemStatusResponse

llm_config = LLMConfigManager.get_config("gpt_4_1_mini")

file_path = None  # Replace with your data file path

results_dir = os.path.join(settings.ROOT_DIR, "code")
os.makedirs(results_dir, exist_ok=True)

file_location = os.path.join(settings.ROOT_DIR, "code","output")#
#file_location ="/Users/lokesh/Desktop/omni_app/omni_be/omni-backend/code/output"
coding_language = "python"
question = None


class pythondeveloper:
    def __init__(self):
        self.llm_config = LLMConfigManager.get_config("gpt_4_1_mini")
        self.llm_config_psc = LLMConfigManager.get_config("gpt_4_1_mini")
        self.llm_config_psc["response_format"] = ProblemStatusResponse
        self.question = question
        self.file_location = file_location
        self.coding_language = coding_language
        self.results_dir = results_dir
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
            system_message=prompts.prob_status_checker.format(question=self.question),
            llm_config=self.llm_config_psc
        )
    def get_process_completion(self):
        return autogen.AssistantAgent(
            name="process_completion_agent",
            llm_config=self.llm_config,
            system_message=prompts.process_completion
        )
        

    def custom_speaker_selection_func(self, last_speaker: Agent, groupchat: GroupChat):
        messages = groupchat.messages
        if len(messages) <= 1:
            # st.spinner("User has asked me a question lets try to solve the question. Bur for this I need better understanding of the question.")
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
            human_input_mode="ALWAYS",
            capability_name="python_coder"
        )
        return self.groupchat , self.manager
    

