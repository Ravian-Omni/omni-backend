from configs.settings import settings
import pandas as pd
import autogen
from autogen import AssistantAgent, UserProxyAgent, GroupChat, GroupChatManager
from autogen import config_list_from_json
import os,json
from typing import List, Dict, Any
from typing import Annotated, List, Dict
from datetime import datetime
from autogen.agentchat.agent import Agent
from autogen import register_function
# from omni_newton import cs_groupchat,cs_manager
from capabilities.file_finder.controller import ff_groupchat, ff_manager
from capabilities.image_generator.controller import ig_groupchat, ig_manager
# from omni_birbal import birbal_groupchat, birbal_manager
from capabilities.python_developer.controller import pcw_groupchat, pcw_manager
from capabilities.email_manager.controller import es_groupchat, es_manager
# from omni_dashboarding import dash_groupchat, dash_manager
from capabilities.browser_manager.controller import browser_gc, browser_manager
from utilities.external_memory import shared_df, add_entry, get_last_entry, get_all_messages,get_raw_dataframe,get_context

from configs.llm_configs_manager import LLMConfigManager
from omni import prompts
today_date = datetime.now()

# Load configuration
config_list_anth = LLMConfigManager.get_config("claude-3-7-sonnet-20250219")
llm_config_reason = LLMConfigManager.get_config("o3-mini-reason-high")
llm_config = LLMConfigManager.get_config("gpt4o")


def image_generator(query: Annotated[str, "The detailed image generation prompt"]):
    context = get_context()
    query = json.dumps({"query":query,"context":context})
    response = ig_manager.initiate_chat(ig_manager, message=query)
    messages = ig_groupchat.messages
    for msg in reversed(messages):
        if msg.get('name') == 'process_completion':
            add_entry("image_generator", msg['content'])
            return msg['content']
    add_entry("image_generator", "No completion message found")
    return f"The image generation process got into a runtime error, please check the logs for more details. . Process that encountered the error > : {query}"


def web_browser(query: Annotated[
    str, "The complete search query with all the details like subject relationship with the message"]) -> \
        Annotated[
            str, "The complete search query with all the details like subject relationship with the message"]:
    context = get_context()
    query = json.dumps({"query":query,"context":context})
    response = browser_manager.initiate_chat(browser_manager, message=query)
    messages = browser_gc.messages
    for msg in reversed(messages):
        if msg.get('name') == 'process_completion':
            add_entry("Web_browser", msg['content'])
            return msg['content']
    add_entry("Web_browser", "No completion message found")
    return f"The web browsing process got into a runtime error, please check the logs for more details. Process that encountered the error > : {query}"


def python_coder(query: Annotated[
    str, "The complete search query with all the details what work we have to do and what we have to return for other agents to work on"]) -> \
        Annotated[str, "The results"]:
    # Initiate the chat
    context = get_context()
    query = json.dumps({"query":query,"context":context})
    response = pcw_manager.initiate_chat(pcw_manager, message=query)
    # Get messages directly from cs_groupchat
    messages = pcw_groupchat.messages
    # Find the last process_completion message
    for msg in reversed(messages):
        if msg.get('name') == 'ProcessCompletion':
            add_entry("python_coder", msg['content'])
            return msg['content']
    add_entry("python_coder", "No completion message found")
    return f"The python coding process got into a runtime error, please check the logs for more details. Process that encountered the error > : {query}"


def email_sender(query: Annotated[str, "The complete user query"]) -> dict:
    context = get_context()
    query = json.dumps({"query":query,"context":context})
    response = es_manager.initiate_chat(es_manager, message=(query))
    messages = es_groupchat.messages
    for msg in reversed(messages):
        if msg.get('name') == 'process_completion_email':  # Make sure there's no extra space
            add_entry("email_sender", msg['content'])
            return msg['content']
    add_entry("email_sender", "No completion message found")
    return f"The email sending process got into a runtime error, please check the logs for more details. Process that encountered the error > : {query}"


def file_finder(query: Annotated[str, "The search query"]):
    context = get_context()
    query = json.dumps({"query":query,"context":context})
    response = ff_manager.initiate_chat(ff_manager, message=query)
    messages = ff_groupchat.messages
    for msg in reversed(messages):
        if msg.get('name') == 'process_completion':
            add_entry("file_finder", msg['content'])
            return msg['content']
    add_entry("email_sender", "No completion message found")
    return f"The file finder  process got into a runtime error, please check the logs for more details. Process that encountered the error > : {query}"


# def dashboard_server(query: Annotated[str, "The search query"]):
#     response = dash_manager.initiate_chat(dash_manager, message=query)
#     messages = dash_groupchat.messages
#     for msg in reversed(messages):
#         if msg.get('name') == 'dashboard_process_completion':
#             add_entry("file_finder", msg['content'])
#             return msg['content']
#     add_entry("email_sender", "No completion message found")
#     return "Operation completed without explicit confirmation"


get_request = AssistantAgent(
    "get_request",
    is_termination_msg=lambda x: x.get("content", "").find("TERMINATE") >= 0,
    llm_config=llm_config,
    description="""
        This agent will get the initial request from the user
        """,
    system_message=prompts.get_request.format(today_date=today_date)
    )

Planner = AssistantAgent(
    "Planner",
    llm_config=llm_config_reason,
    description="""
   Your main task is to plan the complete problem statement

""",
    system_message=prompts.planner.format(today_date=today_date)
    )

agent_aligner = AssistantAgent(name="agent_aligner",
    llm_config=llm_config_reason,
    description="This agent will align the whole process and will share which agent will work next . ",
    system_message=prompts.agent_aligner)

agent_router = AssistantAgent(
    "agent_router",
    llm_config=llm_config,
    description="""
   From the initial information route to the capability which will solve the user's question.

""",
    system_message=prompts.agent_router
    )

# if we have to call one capability at a time that is necessary as per the priority.
# ONLY CALL ONE CAPABILITY AT  A TIME

agent_caller = AssistantAgent(
    "agent_caller",
    llm_config=llm_config,
    description="""
   From the initial information route to the capability which will solve the user's question.

""",
    system_message=prompts.agent_caller
    )

agent_caller_exe = UserProxyAgent(
    "agent_caller_exe",
    human_input_mode="NEVER",
    description="""
        This agent will execute the function which are group chat on their own
        """,
    code_execution_config=False,
    system_message=prompts.agent_caller_exe.format(today_date=today_date),
    is_termination_msg=lambda x: x.get("content", "").find("TERMINATE") >= 0,
    )

prob_status_checker = AssistantAgent(
    name="prob_status_checker",
    description="""call this agent to check if the Task specified by the user has been completed""",
    system_message=prompts.prob_status_checker,

    llm_config=llm_config
    )

manual_verfication = UserProxyAgent(
    name="manual_verfication",
    llm_config=llm_config,
    human_input_mode="ALWAYS",
    code_execution_config=False,
    description="You will take input from user if needed for any manual intervention or verification ",
    system_message=prompts.manual_verification
    )

process_completion = AssistantAgent(
    name="process_completion",
    description="""When this agent will be called upon -->To answer the questions posed by question generator agent
                         What this agent will do --> This agent will try to answer the question""",
    system_message=prompts.process_completion,
    llm_config=llm_config
    )

question_gen = AssistantAgent(
    "question_gen",
    is_termination_msg=lambda x: x.get("content", "").find("TERMINATE") >= 0,
    llm_config=llm_config_reason,
    system_message=prompts.questions_generator.format(today_date=today_date)
    )




autogen.agentchat.register_function(
    python_coder,
    caller=agent_caller,
    executor=agent_caller_exe,
    name="python_coder",
    description="This tool will be used to write any sort of python code.",
    )

autogen.agentchat.register_function(
    email_sender,
    caller=agent_caller,
    executor=agent_caller_exe,
    name="email_sender",
    description="This tool will be used to send emails as per the user's request.",
    )

autogen.agentchat.register_function(
    file_finder,
    caller=agent_caller,
    executor=agent_caller_exe,
    name="file_finder",
    description="This tool will be used to find any file as per the user's request.",
    )

# autogen.agentchat.register_function(
#     dashboard_server,
#     caller=agent_caller,
#     executor=agent_caller_exe,
#     name="dashboard_server",
#     description="This tool will be used to start or spin up the dashboard server.",
#     )

autogen.agentchat.register_function(
    web_browser,
    caller=agent_caller,
    executor=agent_caller_exe,
    name="web_browser",
    description="This tool will be used to search the web.",
    )

autogen.agentchat.register_function(
    image_generator,
    caller=agent_caller,
    executor=agent_caller_exe,
    name="image_generator",
    description="This tool will be used to generate images form textual input.",
    )


def custom_speaker_selection_func(last_speaker: Any, groupchat: Any) -> Any:
    messages = groupchat.messages
    # file_path_provided = any("file path" in msg["content"].lower() for msg in messages)

    if len(messages) == 1:
        return groupchat.agent_by_name("question_gen")
    if last_speaker.name in ["question_gen"]:
        return groupchat.agent_by_name("Planner")
    if last_speaker.name == "agent_aligner":
        if "agent_router" in messages[-1]["content"]:
            return groupchat.agent_by_name("agent_router")
        # elif "manual_verfication" in messages[-1]["content"]:
        #     return groupchat.agent_by_name("manual_verfication")
        elif "Proccesscompletion_Agent" in messages[-1]["content"]:
            return groupchat.agent_by_name("process_completion")

    # if last_speaker.name in ["manual_verfication"]:
    #     return groupchat.agent_by_name("Planner")

    if last_speaker.name in ["Planner"]:
        return groupchat.agent_by_name("agent_aligner")

    if last_speaker.name == "agent_router":
        return groupchat.agent_by_name("agent_caller")
    if last_speaker.name == "agent_caller":
        return groupchat.agent_by_name("agent_caller_exe")
    if last_speaker.name == "agent_caller_exe":
        return groupchat.agent_by_name("Planner")
    if last_speaker.name == "process_completion":
        return "Process Completed"

    return None


omni_groupchat = GroupChat([question_gen, get_request,
                            agent_aligner,
                            agent_router,
                            Planner,
                            agent_caller,
                            agent_caller_exe,
                            prob_status_checker,
                            process_completion,
                            #manual_verfication
                            ],
    speaker_selection_method=custom_speaker_selection_func,
    messages=[],
    max_round=5000
    )

omni_manager = GroupChatManager(omni_groupchat, llm_config=llm_config, )

import sys

if len(sys.argv) < 2:
    print("[ERROR] No query provided.")
    sys.exit(1)

query = sys.argv[1]

print(f"[INFO] Starting agent with query: {query}")

omni_manager.initiate_chat(omni_manager, message=query)
