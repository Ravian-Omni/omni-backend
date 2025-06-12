import autogen
import types
from autogen.code_utils import content_str
from termcolor import colored
from autogen.io import IOStream

# import autogen.coding
import json
import os
import datetime
import subprocess
import time
import uuid
from typing import List, Dict, Any, Union
from capabilities.email_manager import prompts
from configs.llm_configs_manager import LLMConfigManager
from configs.settings import settings
from simplegmail import Gmail



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
from typing import Optional
import asyncio
from utilities.logging import logger

llm_config = LLMConfigManager.get_config("gpt_4_1_mini")


token_path = os.path.join(settings.ROOT_DIR,"configs","gmail_token.json") 
secret_path = os.path.join(settings.ROOT_DIR,"configs","client_secret.json")

def validate_attachments(file_paths):
    """Validate if all attachment files exist before sending."""
    import os
    invalid_paths = []
    for path in file_paths:
        if not os.path.exists(path):
            invalid_paths.append(path)
    return invalid_paths

class EmailGroupChatManager(autogen.GroupChatManager):
    def __init__(self, groupchat, llm_config, human_input_mode="NEVER", queue: Optional[asyncio.Queue] = None, capability_name = "default"):
        super().__init__(groupchat=groupchat, llm_config=llm_config, human_input_mode=human_input_mode)
        self.queue = queue
        self.capability_name = capability_name
    
    def _print_received_message(self, message: Dict[str, Any], sender: "autogen.Agent") -> None:
        logger.info(f"Received from {sender.name}: {message}")
        super()._print_received_message(message, sender)
        content = message.get("content", "") if isinstance(message, dict) else str(message)
        try:
            # omni_storage.add_capability_message(capability_name=self.capability_name,role="user",agent_name=sender.name,content=content)
            logger.debug(f"Queued from {sender.name}: {content}")
        except asyncio.QueueFull:
            logger.error(f"Queue full, could not queue message from {sender.name}: {content}")



class EmailManager:
    def __init__(self):
        self.llm_config = LLMConfigManager.get_config("gpt4o")
        self.agents = self.get_agents()
        autogen.register_function(
            self.send_email_with_attachments,
            caller=self.email_caller,
            executor=self.code_executor,
            name="send_email_with_attachments",
            description="Sends an email with HTML and plain text content to one or more recipients, optionally including file attachments.",
        )
        self.get_chat_manager()
        

    @staticmethod
    def send_email_with_attachments(to: Union[List[str], str], subject: str, msg_html: str, msg_plain: str,
                                attachments: Union[List[str], None] = None, sender: str = settings.USER_EMAIL):
        """
        Sends an email with optional attachments using simplegmail.

        :param to: List of recipient email addresses or a single email as a string.
        :param subject: Subject of the email.
        :param msg_html: HTML content of the email.
        :param msg_plain: Plain text content of the email.
        :param attachments: List of file paths to attach or None.
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

    def get_planner(self):
        return autogen.AssistantAgent(
            name="planner_agent",
            llm_config=self.llm_config,
            system_message=prompts.planner
        )

    def get_content_writer(self):
        return autogen.AssistantAgent(
            name="content_writer_agent",
            llm_config=self.llm_config,
            system_message=prompts.content_writer,
        )

    def get_email_caller(self):
        return autogen.AssistantAgent(
            name="email_caller_agent",
            llm_config=self.llm_config,
            system_message=prompts.email_caller,
        )

    def get_code_executor(self):
        return autogen.UserProxyAgent(
            name="code_executor_agent",
            human_input_mode="NEVER",
            code_execution_config=False,
        )

    def get_debugger(self):
        return autogen.AssistantAgent(
            name="debugger_agent",
            max_consecutive_auto_reply=5,
            llm_config=self.llm_config,
            system_message=prompts.debugger,
        )

    def get_process_completion(self):
        return autogen.AssistantAgent(
            name="process_completion_agent",
            llm_config=self.llm_config,
            system_message=prompts.process_completion,
        )

    def custom_speaker_selection_func(self,last_speaker: Any, groupchat: Any) -> Any:
        messages = groupchat.messages
        # Proceed based on the last speaker
        if last_speaker.name == "chat_manager":
            print("Initial query received. Starting with user_proxy.")
            # rint(f"last_agent_msg is --> {get_last_msg()}")
            return groupchat.agent_by_name("planner_agent")
        if last_speaker.name == "planner_agent":
            return groupchat.agent_by_name("content_writer_agent")
        if last_speaker.name == "content_writer_agent":
            return groupchat.agent_by_name("email_caller_agent")
        elif last_speaker.name == "email_caller_agent":
            return groupchat.agent_by_name("code_executor_agent")
        elif last_speaker.name == "code_executor_agent":
            if "exitcode: 1" in messages[-1]["content"]:
                return groupchat.agent_by_name("debugger_agent")
            elif "exitcode: 0" in messages[-1]["content"]:
                return groupchat.agent_by_name("process_completion_agent")
            else:
                return groupchat.agent_by_name("process_completion_agent")
        elif last_speaker.name == "debugger_agent":
            return groupchat.agent_by_name("email_caller_agent")

    def get_agents(self):
        self.planner = self.get_planner()
        self.content_writer = self.get_content_writer()
        self.email_caller = self.get_email_caller()
        self.code_executor = self.get_code_executor()
        self.debugger = self.get_debugger()
        self.process_completion = self.get_process_completion()
        return [
            self.planner,
            self.content_writer,
            self.email_caller,
            self.code_executor,
            self.debugger,
            self.process_completion
        ]

    def get_chat_manager(self):
        self.groupchat = autogen.GroupChat(
            agents=self.agents,
            messages=[],
            speaker_selection_method=self.custom_speaker_selection_func,
            max_round=500,
        )
        self.manager = EmailGroupChatManager(
            groupchat=self.groupchat,
            llm_config=self.llm_config,
            human_input_mode="ALWAYS",
            capability_name="email_sender"
        )
        return
