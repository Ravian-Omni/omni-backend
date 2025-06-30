# from simplegmail import Gmail
# from oauth2client.file import Storage
# from pathlib import Path
# import os
# from autogen import AssistantAgent, UserProxyAgent, GroupChat, GroupChatManager
# from autogen import config_list_from_json
# from typing import Annotated, List, Dict, Any, Union
# from datetime import datetime
# from autogen.agentchat.agent import Agent
# from autogen import register_function
# from autogen.coding import LocalCommandLineCodeExecutor

# today_date = datetime.now()
# import smtplib
# from email.mime.text import MIMEText
# from email.mime.multipart import MIMEMultipart
# from email.mime.base import MIMEBase
# from email import encoders
# import os

# from utilities.external_memory import get_last_entry, get_all_messages
# from configs.settings import settings
# from capabilities.email_manager import prompts
# from configs.llm_configs_manager import LLMConfigManager
# llm_config = LLMConfigManager.get_config("gpt4o")
# # Load configuration

# token_path = os.path.join(settings.ROOT_DIR,"configs","gmail_token.json") 
# secret_path = os.path.join(settings.ROOT_DIR,"configs","client_secret.json")

# gmail = Gmail(client_secret_file=secret_path, creds_file=token_path)
# # gmail = None


# def validate_attachments(file_paths):
#     """Validate if all attachment files exist before sending."""
#     import os
#     invalid_paths = []
#     for path in file_paths:
#         if not os.path.exists(path):
#             invalid_paths.append(path)
#     return invalid_paths


# def send_email_with_attachments(to: Union[List[str], str], subject: str, msg_html: str, msg_plain: str,
#                                 attachments: List[str] = None, sender: str = settings.USER_EMAIL):
#     """
#     Sends an email with optional attachments using simplegmail.

#     :param to: List of recipient email addresses or a single email as a string.
#     :param subject: Subject of the email.
#     :param msg_html: HTML content of the email.
#     :param msg_plain: Plain text content of the email.
#     :param attachments: List of file paths to attach.
#     :param sender: Sender email address (default: codelokiyt@gmail.com).
#     :return: Sent message details.
#     """

#     import os
#     if attachments:
#         invalid_paths = validate_attachments(attachments)
#         if invalid_paths:
#             return f"Error: The following attachment paths are invalid: {invalid_paths}"
#     gmail = Gmail(client_secret_file=secret_path, creds_file=token_path)

#     # The issue is with how we're handling the 'to' parameter
#     # For simplegmail, 'to' should be a single string (for one recipient) 
#     # or a comma-separated string (for multiple recipients)
#     if isinstance(to, list):
#         to = ", ".join(to)  # Convert list to comma-separated string

#     params = {
#         "to": to,
#         "sender": sender,
#         "subject": subject,
#         "msg_html": msg_html,
#         "msg_plain": msg_plain,
#         "attachments": attachments or [],
#         "signature": False  # Use account signature
#         }

#     message = gmail.send_message(**params)
#     return message


# planner_email = AssistantAgent(
#     name="planner_email",
#     llm_config=llm_config,
#     system_message=prompts.planner.format(get_last_entry=get_last_entry,get_all_messages=get_all_messages)
#     )

# content_writer_email = AssistantAgent(
#     name="content_writer_email",
#     llm_config=llm_config,
#     system_message=prompts.content_writer.format(get_last_entry=get_last_entry,get_all_messages=get_all_messages)
#     )

# code_writer_email = AssistantAgent(
#     name="code_writer_email",
#     llm_config=llm_config,
#     system_message=prompts.email_caller.format(get_last_entry=get_last_entry,get_all_messages=get_all_messages,user_email=settings.USER_EMAIL)
#     )
# code_executor_email = UserProxyAgent(
#     name="code_executor_email",
#     human_input_mode="NEVER",
#     code_execution_config=False
#     )
# debugger_email = AssistantAgent(
#     name="debugger_email",
#     max_consecutive_auto_reply=5,
#     llm_config=llm_config,
#     system_message=prompts.debugger
#     )
# process_completion_email = AssistantAgent(
#     name="process_completion_email",
#     llm_config=llm_config,
#     description="Let group manager know that the process is completed. ",
#     system_message=prompts.process_completion
#     )

# user_proxy = UserProxyAgent(
#     name="user_proxy",
#     human_input_mode="NEVER",
#     # is_termination_msg=lambda x: x.get("content", "").find("TERMINATE") >= 0,
#     code_execution_config=False,  # Please set use_docker=True if docker is available to run the generated code. Using docker is safer than running the generated code directly.
# )

# def custom_speaker_selection_func(last_speaker: Any, groupchat: Any) -> Any:
#     messages = groupchat.messages
#     print(len(messages))
#     # Proceed based on the last speaker
#     if len(messages) == 1:
#         print("Initial query received. Starting with user_proxy.")
#         # rint(f"last_agent_msg is --> {get_last_msg()}")
#         return groupchat.agent_by_name("planner_email")
#     if last_speaker.name == "planner_email":
#         return groupchat.agent_by_name("content_writer_email")
#     if last_speaker.name == "content_writer_email":
#         return groupchat.agent_by_name("code_writer_email")
#     elif last_speaker.name == "code_writer_email":
#         return groupchat.agent_by_name("code_executor_email")
#     elif last_speaker.name == "code_executor_email":
#         if "exitcode: 1" in messages[-1]["content"]:
#             return groupchat.agent_by_name("debugger_email")
#         elif "exitcode: 0" in messages[-1]["content"]:
#             return groupchat.agent_by_name("process_completion_email")
#         else:
#             return groupchat.agent_by_name("process_completion_email")
#     elif last_speaker.name == "debugger_email":
#         return groupchat.agent_by_name("code_writer_email")


# register_function(send_email_with_attachments,
#     caller=code_writer_email,
#     executor=code_executor_email,
#     name="send_email_with_attachments",
#     description="This tool will be used to send emails with attachments. It will take input for ",
#     )

# es_groupchat = GroupChat([planner_email,
#                           content_writer_email,
#                           code_writer_email,
#                           code_executor_email,
#                           debugger_email,
#                           process_completion_email,
#                           user_proxy
#                           ],
#     speaker_selection_method=custom_speaker_selection_func,
#     messages=[],
#     max_round=500
#     )

# es_manager = GroupChatManager(es_groupchat, llm_config=llm_config)
# #
# # import sys
# #
# # if len(sys.argv) < 2:
# #     print("[ERROR] No query provided.")
# #     sys.exit(1)
# #
# # query = sys.argv[1]
# #
# # print(f"[INFO] Starting agent with query: {query}")
# #
# # es_manager.initiate_chat(es_manager, message=query)





###NEW CODE WTHOUT CREDENTIALS###



import sys
import os
sys.path.append("/Users/lokesh/Desktop/omni_app/omni_be/omni-backend")
print("PYTHONPATH:", sys.path)


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
llm_config = LLMConfigManager.get_config("gpt_4_1_mini")
# Load configuration

# token_path = os.path.join(settings.ROOT_DIR,"configs","gmail_token.json") 
# secret_path = os.path.join(settings.ROOT_DIR,"configs","client_secret.json")


username = "codelokiyt@gmail.com"
password = "khio xisc nxhv bref"


import os
import smtplib
import re
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import List, Union, Optional
from pydantic import BaseModel, validator
import logging


#last_agent_msg = get_last_agent_msg(outer_memory_df)
#last_agent_msg = outer_memory_df.iloc[-1,1]
# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)



# gmail = Gmail(client_secret_file=secret_path, creds_file=token_path)
# gmail = None


# def validate_attachments(file_paths):
#     """Validate if all attachment files exist before sending."""
#     import os
#     invalid_paths = []
#     for path in file_paths:
#         if not os.path.exists(path):
#             invalid_paths.append(path)
#     return invalid_paths


# def send_email_with_attachments(to: Union[List[str], str], subject: str, msg_html: str, msg_plain: str,
#                                 attachments: List[str] = None, sender: str = settings.USER_EMAIL):
#     """
#     Sends an email with optional attachments using simplegmail.

#     :param to: List of recipient email addresses or a single email as a string.
#     :param subject: Subject of the email.
#     :param msg_html: HTML content of the email.
#     :param msg_plain: Plain text content of the email.
#     :param attachments: List of file paths to attach.
#     :param sender: Sender email address (default: codelokiyt@gmail.com).
#     :return: Sent message details.
#     """

#     import os
#     if attachments:
#         invalid_paths = validate_attachments(attachments)
#         if invalid_paths:
#             return f"Error: The following attachment paths are invalid: {invalid_paths}"
#     gmail = Gmail(client_secret_file=secret_path, creds_file=token_path)

#     # The issue is with how we're handling the 'to' parameter
#     # For simplegmail, 'to' should be a single string (for one recipient) 
#     # or a comma-separated string (for multiple recipients)
#     if isinstance(to, list):
#         to = ", ".join(to)  # Convert list to comma-separated string

#     params = {
#         "to": to,
#         "sender": sender,
#         "subject": subject,
#         "msg_html": msg_html,
#         "msg_plain": msg_plain,
#         "attachments": attachments or [],
#         "signature": False  # Use account signature
#         }

#     message = gmail.send_message(**params)
#     return message


class EmailConfig(BaseModel):
    """Pydantic model for email configuration and validation"""
    sender_email: str
    app_password: str
    receiver_email: Union[str, List[str]]
    subject: str
    body: str
    absolute_file_paths: Optional[List[str]] = []

    @validator('sender_email', 'receiver_email')
    def validate_email(cls, v):
        """Validate email format using regex"""
        email_regex = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if isinstance(v, str):
            if not re.match(email_regex, v):
                raise ValueError(f'Invalid email format: {v}')
            return v
        elif isinstance(v, list):
            for email in v:
                if not re.match(email_regex, email):
                    raise ValueError(f'Invalid email format: {email}')
            return v
        raise ValueError('Email must be string or list of strings')

    @validator('absolute_file_paths')
    def validate_file_paths(cls, v):
        """Validate file paths exist"""
        if v is None:
            return []
        
        invalid_paths = [path for path in v if not os.path.exists(path)]
        if invalid_paths:
            raise ValueError(f"Following files do not exist: {', '.join(invalid_paths)}")
        return v

def send_email_with_attachments(
    receiver_email: Union[str, List[str]] = "",
    subject: str = "",
    body: str = "",
    absolute_file_paths: Optional[List[str]] = None
) -> dict:
    """
    Send email with attachments using Gmail SMTP server.
    
    Args:
        sender_email (str): Sender's email address
        app_password (str): Gmail app password
        receiver_email (Union[str, List[str]]): Recipient email(s)
        subject (str): Email subject
        body (str): Email body content
        absolute_file_paths (Optional[List[str]]): List of file paths
        
    Returns:
        dict: Response containing status and message
    """
    try:
        # Validate input parameters
        email_config = EmailConfig(
            sender_email=username,
            app_password=password,
            receiver_email=receiver_email,
            subject=subject,
            body=body,
            absolute_file_paths=absolute_file_paths if absolute_file_paths is not None else []
        )

        # Create email message
        message = MIMEMultipart()
        message["From"] = email_config.sender_email
        
        # Handle multiple recipients
        if isinstance(email_config.receiver_email, list):
            message["To"] = ", ".join(email_config.receiver_email)
        else:
            message["To"] = email_config.receiver_email
            
        message["Subject"] = email_config.subject
        
        # Add body
        message.attach(MIMEText(email_config.body, "plain"))
        
        # Process attachments
        if email_config.absolute_file_paths:
            for file_path in email_config.absolute_file_paths:
                try:
                    with open(file_path, "rb") as attachment:
                        part = MIMEBase("application", "octet-stream")
                        part.set_payload(attachment.read())
                    
                    encoders.encode_base64(part)
                    
                    filename = os.path.basename(file_path)
                    part.add_header(
                        "Content-Disposition",
                        f"attachment; filename= {filename}",
                    )
                    
                    message.attach(part)
                    logger.info(f"Attached file: {filename}")
                    
                except Exception as e:
                    error_msg = f"Error attaching file {file_path}: {str(e)}"
                    logger.error(error_msg)
                    return {"status": "error", "message": error_msg}
        
        # Send email
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(email_config.sender_email, email_config.app_password)
            
            # Handle multiple recipients for sending
            recipients = (
                email_config.receiver_email 
                if isinstance(email_config.receiver_email, list) 
                else [email_config.receiver_email]
            )
            
            server.sendmail(
                email_config.sender_email,
                recipients,
                message.as_string()
            )
            
        success_msg = "Email sent successfully!"
        logger.info(success_msg)
        return {"status": "success", "message": success_msg}
        
    except Exception as e:
        error_msg = f"Failed to send email: {str(e)}"
        logger.error(error_msg)
        return {"status": "error", "message": error_msg}
    


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
query = "Send an email to lokesh@ravian.ai and say hi to him"
es_manager.initiate_chat(es_manager, message=query)

