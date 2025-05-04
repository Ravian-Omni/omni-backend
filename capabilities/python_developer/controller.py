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
from autogen import config_list_from_json
from utilities.external_memory import get_last_entry, get_all_messages
from configs.settings import settings
from configs.llm_configs_manager import LLMConfigManager
llm_config = LLMConfigManager.get_config("gpt4o")

file_path = None  # Replace with your data file path

results_dir = os.path.join(settings.ROOT_DIR, "code")
os.makedirs(results_dir, exist_ok=True)

file_location = os.path.join(settings.ROOT_DIR, "code","output")
coding_language = "python"
question = None


Planner = AssistantAgent(
    name="Planner",
    llm_config=llm_config,
    system_message=prompts.planner.format(get_last_entry=get_last_entry,get_all_messages=get_all_messages,file_location=file_location,coding_language=coding_language)
    )

CodeWriter = autogen.AssistantAgent(
    name="CodeWriter",
    llm_config=llm_config,
    system_message=prompts.code_writer.format(file_location=file_location,coding_language=coding_language)
    )


CodeExecutor = UserProxyAgent(
    name="CodeExecutor",
    human_input_mode="NEVER",
    code_execution_config={
        "work_dir": results_dir,
        "use_docker": False,
        },
    llm_config=llm_config
    )

CodeDebugger = AssistantAgent(
    name="CodeDebugger",
    max_consecutive_auto_reply=5,
    llm_config=llm_config,
    system_message=prompts.debugger.format(file_location=file_location,coding_language=coding_language)
    )

ProblemStatusChecker = AssistantAgent(
    name="ProblemStatusChecker",
    system_message=prompts.prob_status_checker.format(question=question),
    llm_config=llm_config
    )

ProcessCompletion = AssistantAgent(
    name="ProcessCompletion",
    llm_config=llm_config,
    system_message=prompts.process_completion)


def custom_speaker_selection_func(last_speaker: Agent, groupchat: GroupChat):
    messages = groupchat.messages
    if len(messages) <= 1:
        # st.spinner("User has asked me a question lets try to solve the question. Bur for this I need better understanding of the question.")
        return groupchat.agent_by_name("Planner")
    if last_speaker.name == "Planner":
        return groupchat.agent_by_name("CodeWriter")
    elif last_speaker.name == "CodeWriter":
        return groupchat.agent_by_name("CodeExecutor")
    elif last_speaker.name == "CodeExecutor":
        if "exitcode: 0" in messages[-1]["content"].lower():
            return groupchat.agent_by_name("ProblemStatusChecker")
        else:
            return groupchat.agent_by_name("CodeDebugger")
    elif last_speaker.name == "ProblemStatusChecker":
        if 'yes' in messages[-1]["content"].lower():
            return groupchat.agent_by_name("ProcessCompletion")
        else:
            return groupchat.agent_by_name("CodeWriter")
    elif last_speaker.name == "CodeDebugger":
        return groupchat.agent_by_name("CodeWriter")


pcw_groupchat = GroupChat(
    agents=[Planner, CodeWriter, CodeExecutor, ProblemStatusChecker, CodeDebugger, ProcessCompletion],
    enable_clear_history=True,
    speaker_selection_method=custom_speaker_selection_func,
    messages=[],
    allow_repeat_speaker=False,
    max_round=75,
    )

pcw_manager = GroupChatManager(
    groupchat=pcw_groupchat,
    llm_config=llm_config
    )

