import autogen
# from typing import List, Dict, Any, Union
# from omni import prompts
# from configs.llm_configs_manager import LLMConfigManager
# from configs.settings import settings
# from simplegmail import Gmail
# from configs.settings import settings
# import pandas as pd
# import autogen
# from autogen import AssistantAgent, UserProxyAgent, GroupChat, GroupChatManager
# from autogen import config_list_from_json
# import os,json
# from typing import List, Dict, Any
from typing import Annotated, List, Dict
from datetime import datetime
# from autogen.agentchat.agent import Agent
# from autogen import register_function
# # from omni_newton import cs_groupchat,cs_manager
# from capabilities.file_finder.controller import ff_groupchat, ff_manager
from capabilities.image_generator.manager import ImageGenerator
# from omni_birbal import birbal_groupchat, birbal_manager
# from capabilities.python_developer.controller import pcw_groupchat, pcw_manager
# from capabilities.email_manager.manager import EmailManager
# from omni_dashboarding import dash_groupchat, dash_manager
from capabilities.browser_manager.controller import browser_gc, browser_manager
from configs.llm_configs_manager import LLMConfigManager
from omni import prompts
from utilities.logging import logger
from utilities.storage import omni_storage
import asyncio
from typing import List, Optional,Dict,Any
today_date = datetime.now()
from omni.response_format import AgentSelectionResponse , QuestionClassification , PlannerResponse , CapabilityRoutingResponse
# from omni.response_format import PlannerResponse
# from omni.response_format import CapabilityRoutingResponse

# Load configuration
config_list_anth = LLMConfigManager.get_config("claude-3-7-sonnet-20250219")
llm_config_reason = LLMConfigManager.get_config("o3-mini-reason-high")
llm_config = LLMConfigManager.get_config("deepseek")
llm_config_mini_planner = LLMConfigManager.get_config("gpt_4_1_mini")
llm_config_mini_planner["response_format"] = PlannerResponse
llm_config_mini_aligner = LLMConfigManager.get_config("gpt_4_1_mini")
llm_config_mini_aligner["response_format"] = AgentSelectionResponse
llm_config_mini_router = LLMConfigManager.get_config("gpt_4_1_mini")
llm_config_mini_router["response_format"] = CapabilityRoutingResponse

llm_config_question_class = LLMConfigManager.get_config("gpt_4_1_mini")
llm_config_question_class["response_format"] = QuestionClassification

llm_config_mini = LLMConfigManager.get_config("gpt_4_1_mini")


def image_generator(query: Annotated[str, "The detailed image generation prompt"]):
    omni_storage.start_new_iteration("image_generator")
    image_generator = ImageGenerator()
    response = image_generator.manager.initiate_chat(image_generator.manager, message=query)
    messages = image_generator.groupchat.messages
    for msg in reversed(messages):
        if msg.get("name") == "process_completion":
            # add_entry("image_generator", msg["content"])
            return msg["content"]
    # add_entry("image_generator", "No completion message found")
    return f"The image generation process got into a runtime error, please check the logs for more details. . Process that encountered the error > : {query}"



# def email_sender(query: Annotated[str, "The complete user query"]) -> dict:
#     omni_storage.start_new_iteration("email_sender")
#     print("%^%^%^%^%^%^%^%^%^%^%^%^%^%^%^%^%^%^%^%^%^%^%^%^%^%^%")
#     recent_capability = omni_storage.get_most_recently_updated_capability()
#     print(recent_capability)
#     print(omni_storage.get_latest_iteration_agent_messages(capability_name=recent_capability,agent_name="process_completion_agent"))
#     print("%^%^%^%^%^%^%^%^%^%^%^%^%^%^%^%^%^%^%^%^%^%^%^%^%^%^%")
#     emailer = EmailManager()
#     response = emailer.manager.initiate_chat(emailer.manager, message=query)
#     messages = emailer.groupchat.messages
#     for msg in reversed(messages):
#         if (
#             msg.get("name") == "process_completion_agent"
#         ):  # Make sure there's no extra space
#             # add_entry("email_sender", msg["content"])
#             return msg["content"]
#     # add_entry("email_sender", "No completion message found")
#     return f"The email sending process got into a runtime error, please check the logs for more details. Process that encountered the error > : {query}"



image_generator(query="The image fo a cat playing with a ball in a garden, the image should be very clear and high quality, the cat should be fluffy and cute, the ball should be colorful and the garden should have flowers and grass")
