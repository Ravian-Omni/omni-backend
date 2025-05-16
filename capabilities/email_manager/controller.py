from simplegmail import Gmail
from oauth2client.file import Storage
from pathlib import Path
import os
from autogen import AssistantAgent, UserProxyAgent, GroupChat, GroupChatManager
from autogen import config_list_from_json
from typing import Annotated, List, Dict, Any, Union
from datetime import datetime
from autogen.agentchat.agent import Agent
from autogen import register_function
from autogen.coding import LocalCommandLineCodeExecutor

today_date = datetime.now()
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
import os

from utilities.external_memory import get_last_entry, get_all_messages
from configs.settings import settings
from capabilities.email_manager import prompts
from configs.llm_configs_manager import LLMConfigManager
llm_config = LLMConfigManager.get_config("gpt4o")
# Load configuration

token_path = os.path.join(settings.ROOT_DIR,"configs","gmail_token.json") 
secret_path = os.path.join(settings.ROOT_DIR,"configs","client_secret.json")

gmail = Gmail(client_secret_file=secret_path, creds_file=token_path)
# gmail = None


def validate_attachments(file_paths):
    """Validate if all attachment files exist before sending."""
    import os
    invalid_paths = []
    for path in file_paths:
        if not os.path.exists(path):
            invalid_paths.append(path)
    return invalid_paths


def send_email_with_attachments(to: Union[List[str], str], subject: str, msg_html: str, msg_plain: str,
                                attachments: List[str] = None, sender: str = settings.USER_EMAIL):
    """
    Sends an email with optional attachments using simplegmail.

    :param to: List of recipient email addresses or a single email as a string.
    :param subject: Subject of the email.
    :param msg_html: HTML content of the email.
    :param msg_plain: Plain text content of the email.
    :param attachments: List of file paths to attach.
    :param sender: Sender email address (default: codelokiyt@gmail.com).
    :return: Sent message details.
    """

    import os
    if attachments:
        invalid_paths = validate_attachments(attachments)
        if invalid_paths:
            return f"Error: The following attachment paths are invalid: {invalid_paths}"
    gmail = Gmail(client_secret_file=secret_path, creds_file=token_path)

    # The issue is with how we're handling the 'to' parameter
    # For simplegmail, 'to' should be a single string (for one recipient) 
    # or a comma-separated string (for multiple recipients)
    if isinstance(to, list):
        to = ", ".join(to)  # Convert list to comma-separated string

    params = {
        "to": to,
        "sender": sender,
        "subject": subject,
        "msg_html": msg_html,
        "msg_plain": msg_plain,
        "attachments": attachments or [],
        "signature": False  # Use account signature
        }

    message = gmail.send_message(**params)
    return message


planner_email = AssistantAgent(
    name="planner_email",
    llm_config=llm_config,
    system_message=prompts.planner.format(get_last_entry=get_last_entry,get_all_messages=get_all_messages)
    )

content_writer_email = AssistantAgent(
    name="content_writer_email",
    llm_config=llm_config,
    system_message=prompts.content_writer.format(get_last_entry=get_last_entry,get_all_messages=get_all_messages)
    )

code_writer_email = AssistantAgent(
    name="code_writer_email",
    llm_config=llm_config,
    system_message=prompts.email_caller.format(get_last_entry=get_last_entry,get_all_messages=get_all_messages,user_email=settings.USER_EMAIL)
    )
code_executor_email = UserProxyAgent(
    name="code_executor_email",
    human_input_mode="NEVER",
    code_execution_config=False
    )
debugger_email = AssistantAgent(
    name="debugger_email",
    max_consecutive_auto_reply=5,
    llm_config=llm_config,
    system_message=prompts.debugger
    )
process_completion_email = AssistantAgent(
    name="process_completion_email",
    llm_config=llm_config,
    description="Let group manager know that the process is completed. ",
    system_message=prompts.process_completion
    )

user_proxy = UserProxyAgent(
    name="user_proxy",
    human_input_mode="NEVER",
    # is_termination_msg=lambda x: x.get("content", "").find("TERMINATE") >= 0,
    code_execution_config=False,  # Please set use_docker=True if docker is available to run the generated code. Using docker is safer than running the generated code directly.
)

def custom_speaker_selection_func(last_speaker: Any, groupchat: Any) -> Any:
    messages = groupchat.messages
    print(len(messages))
    # Proceed based on the last speaker
    if len(messages) == 1:
        print("Initial query received. Starting with user_proxy.")
        # rint(f"last_agent_msg is --> {get_last_msg()}")
        return groupchat.agent_by_name("planner_email")
    if last_speaker.name == "planner_email":
        return groupchat.agent_by_name("content_writer_email")
    if last_speaker.name == "content_writer_email":
        return groupchat.agent_by_name("code_writer_email")
    elif last_speaker.name == "code_writer_email":
        return groupchat.agent_by_name("code_executor_email")
    elif last_speaker.name == "code_executor_email":
        if "exitcode: 1" in messages[-1]["content"]:
            return groupchat.agent_by_name("debugger_email")
        elif "exitcode: 0" in messages[-1]["content"]:
            return groupchat.agent_by_name("process_completion_email")
        else:
            return groupchat.agent_by_name("process_completion_email")
    elif last_speaker.name == "debugger_email":
        return groupchat.agent_by_name("code_writer_email")


register_function(send_email_with_attachments,
    caller=code_writer_email,
    executor=code_executor_email,
    name="send_email_with_attachments",
    description="This tool will be used to send emails with attachments. It will take input for ",
    )

es_groupchat = GroupChat([planner_email,
                          content_writer_email,
                          code_writer_email,
                          code_executor_email,
                          debugger_email,
                          process_completion_email,
                          user_proxy
                          ],
    speaker_selection_method=custom_speaker_selection_func,
    messages=[],
    max_round=500
    )

es_manager = GroupChatManager(es_groupchat, llm_config=llm_config)
#
# import sys
#
# if len(sys.argv) < 2:
#     print("[ERROR] No query provided.")
#     sys.exit(1)
#
# query = sys.argv[1]
#
# print(f"[INFO] Starting agent with query: {query}")
#
# es_manager.initiate_chat(es_manager, message=query)
