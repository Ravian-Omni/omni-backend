import sys
import os
# Add the project root directory to Python path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
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
from utilities.custom_manager import CustomGroupChatManager
from utilities.external_memory import get_last_entry, get_all_messages
from configs.settings import settings
from capabilities.email_manager import prompts
from configs.llm_configs_manager import LLMConfigManager
from typing import Optional
import asyncio
import logging
logger = logging.getLogger(__name__)

#new imports
import imaplib
import email
from email.header import decode_header
from email.message import EmailMessage
llm_config = LLMConfigManager.get_config("gpt_4_1_mini")
from langchain_openai import AzureChatOpenAI


# token_path = os.path.join(settings.ROOT_DIR,"configs","gmail_token.json") 
# secret_path = os.path.join(settings.ROOT_DIR,"configs","client_secret.json")
username = settings.USER_EMAIL
password = settings.USER_EMAIL_PASSWORD
# print(f"username is {username} and password is {password}")


llm = AzureChatOpenAI(
    azure_deployment="gpt-4o-mini",
    api_version="2023-06-01-preview",
    temperature=0,
    azure_endpoint="https://newton-aoi.openai.azure.com/",
    api_key="Cq3mVjQS5sBySSyMhRTGkoI8okh0HbOjB4UxuV4txdBkB4ANUCflJQQJ99BCACYeBjFXJ3w3AAABACOG2GEt",
)


def validate_attachments(file_paths):
    """Validate if all attachment files exist before sending."""
    import os
    invalid_paths = []
    for path in file_paths:
        if not os.path.exists(path):
            invalid_paths.append(path)
    return invalid_paths



class EmailManager:
    def __init__(self, chat_id, call_id, capability_id, omni_memory):
        self.chat_id = chat_id
        self.call_id = call_id
        self.capability_id = capability_id
        self.omni_memory = omni_memory
        self.llm_config = LLMConfigManager.get_config("gpt_4_1_mini")
        self.agents = self.get_agents()
        
        autogen.register_function(
            self.send_email_with_attachments,
            caller=self.email_caller,
            executor=self.code_executor,
            name="send_email_with_attachments",
            description="Sends an email with HTML and plain text content to one or more recipients, optionally including file attachments.",
        )
        autogen.register_function(
            self.read_latest_email_with_attachments,
            caller=self.email_reader_agent,
            executor=self.code_executor,
            name="read_latest_email_with_attachments",
            description="Search emails by criteria,  read the email content  and save attachments to local if needed."
        )
        autogen.register_function(
            self.send_reply_to_email,
            caller=self.email_reply_agent,
            executor=self.code_executor,
            name="send_reply_to_email",
            description="Send reply to a specific email"
        )

        autogen.register_function(
            self.search_emails_by_criteria,
            caller=self.email_search_agent,
            executor=self.code_executor,
            name="search_emails_by_criteria",
            description="Search emails by criteria"
        )

        self.get_chat_manager()
        

    # @staticmethod
    # def send_email_with_attachments(to: Union[List[str], str], subject: str, msg_html: str, msg_plain: str,
    #                             attachments: Union[List[str], None] = None, sender: str = settings.USER_EMAIL):
    #     """
    #     Sends an email with optional attachments using simplegmail.

    #     :param to: List of recipient email addresses or a single email as a string.
    #     :param subject: Subject of the email.
    #     :param msg_html: HTML content of the email.
    #     :param msg_plain: Plain text content of the email.
    #     :param attachments: List of file paths to attach or None.
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



    @staticmethod
    def send_email_with_attachments(to: Union[List[str], str], subject: str, msg_html: str, msg_plain: str,
                                    attachments: List[str] = None, sender: str = None):

        if sender is None:
            sender = username
            
        if attachments:
            invalid_paths = validate_attachments(attachments)
            if invalid_paths:
                return f"Error: The following attachment paths are invalid: {invalid_paths}"
        
        try:
            # Create message
            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = sender
            
            # Handle multiple recipients
            if isinstance(to, list):
                msg['To'] = ", ".join(to)
                recipients = to
            else:
                msg['To'] = to
                recipients = [to]
            
            # Add body parts
            if msg_plain:
                part1 = MIMEText(msg_plain, 'plain')
                msg.attach(part1)
                
            if msg_html:
                part2 = MIMEText(msg_html, 'html')
                msg.attach(part2)
            
            # Add attachments
            if attachments:
                for file_path in attachments:
                    if os.path.exists(file_path):
                        with open(file_path, "rb") as attachment:
                            part = MIMEBase('application', 'octet-stream')
                            part.set_payload(attachment.read())
                        
                        encoders.encode_base64(part)
                        part.add_header(
                            'Content-Disposition',
                            f'attachment; filename= {os.path.basename(file_path)}'
                        )
                        msg.attach(part)
            
            # Send email using SMTP
            with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
                server.login(username, password)
                server.send_message(msg, from_addr=sender, to_addrs=recipients)
            
            return f"Email sent successfully to {msg['To']}"
            
        except Exception as e:
            return f"Error sending email: {e}"
        

    @staticmethod
    def read_latest_email_with_attachments( username=username, password=password, sender_details=str, attachment_dir="attachments"):

        try:
            # Connect and login
            imap = imaplib.IMAP4_SSL("imap.gmail.com")
            imap.login(username, password)
            imap.select("inbox")
        except Exception as e:
            return f"Error connecting to email: {e}"

        # Search for emails from a specific sender
        status, messages = imap.search(None, f'FROM "{sender_details}"')
        email_ids = messages[0].split()

        if not email_ids:
            imap.logout()
            return "No emails found from the specified sender."

        # Fetch the latest email
        latest_email_id = email_ids[-1]
        status, msg_data = imap.fetch(latest_email_id, "(RFC822)")

        # Create folder to save attachments
        os.makedirs(attachment_dir, exist_ok=True)

        # Initialize variables
        subject = ""
        from_ = ""
        message_id = ""
        body = ""
        attachment_paths = []

        # Parse the email
        for response_part in msg_data:
            if isinstance(response_part, tuple):
                msg = email.message_from_bytes(response_part[1])

                # Extract headers
                subject_header = msg.get("Subject")
                if subject_header:
                    subject, encoding = decode_header(subject_header)[0]
                    if isinstance(subject, bytes):
                        subject = subject.decode(encoding if encoding else "utf-8")
                
                from_ = msg.get("From")
                message_id = msg.get("Message-ID")

                # Extract the email body and attachments
                if msg.is_multipart():
                    for part in msg.walk():
                        content_disposition = str(part.get("Content-Disposition"))

                        # Extract plain text body
                        if part.get_content_type() == "text/plain" and "attachment" not in content_disposition:
                            try:
                                body = part.get_payload(decode=True).decode('utf-8')
                            except UnicodeDecodeError:
                                try:
                                    body = part.get_payload(decode=True).decode('latin-1')
                                except:
                                    body = "Could not decode email body"

                        # Download attachment
                        if "attachment" in content_disposition:
                            filename = part.get_filename()
                            if filename:
                                decoded_filename, encoding = decode_header(filename)[0]
                                if isinstance(decoded_filename, bytes):
                                    decoded_filename = decoded_filename.decode(encoding if encoding else "utf-8")

                                filepath = os.path.join(attachment_dir, decoded_filename)
                                full_path = os.path.abspath(filepath)
                                
                                try:
                                    with open(full_path, "wb") as f:
                                        f.write(part.get_payload(decode=True))
                                    attachment_paths.append(full_path)
                                except Exception as e:
                                    print(f"Error saving attachment {decoded_filename}: {e}")
                else:
                    # Single-part email
                    try:
                        body = msg.get_payload(decode=True).decode('utf-8')
                    except UnicodeDecodeError:
                        try:
                            body = msg.get_payload(decode=True).decode('latin-1')
                        except:
                            body = "Could not decode email body"

        imap.logout()
        
        # Return structured data that can be easily parsed by agents
        return f"""EMAIL_DETAILS:
    message_id: {message_id}
    subject: {subject}
    from: {from_}
    body: {body}
    attachments_count: {len(attachment_paths)}
    attachment_paths: {attachment_paths}
    STATUS: Email read successfully"""



    @staticmethod
    def send_reply_to_email(message_id: str, subject: str, from_: str, body: str, reply_content: str = None):
        """
        Send a reply to a specific email.
        """
        if not all([message_id, subject, from_, body]):
            return "Error: Missing required email information"
        
        try:
            original_message_id = message_id
            msg = EmailMessage()
            msg["Subject"] = "Re: " + subject
            msg["From"] = username
            msg["To"] = from_
            msg["In-Reply-To"] = original_message_id
            msg["References"] = original_message_id
            
            if reply_content:
                msg.set_content(reply_content)
            else:
                # Use LLM to generate reply
                response = llm.invoke(f"reply to the email with a short message to the user,--> {body}")
                msg.set_content(response.content)

            # Send via Gmail SMTP
            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
                smtp.login(username, password)
                smtp.send_message(msg)

            return "Reply sent successfully."
        except Exception as e:
            return f"Error sending reply: {e}"


    @staticmethod
    def search_emails_by_criteria(search_criteria: str, limit: int = 5):
        """
        Search emails based on criteria (sender, subject, etc.)
        """
        try:
            imap = imaplib.IMAP4_SSL("imap.gmail.com")
            imap.login(username, password)
            imap.select("inbox")
            
            status, messages = imap.search(None, search_criteria)
            email_ids = messages[0].split()
            
            if not email_ids:
                imap.logout()
                return "No emails found matching the criteria."
            
            # Limit results
            email_ids = email_ids[-limit:]
            
            results = []
            for email_id in email_ids:
                status, msg_data = imap.fetch(email_id, "(RFC822)")
                for response_part in msg_data:
                    if isinstance(response_part, tuple):
                        msg = email.message_from_bytes(response_part[1])
                        
                        subject_header = msg.get("Subject")
                        subject = ""
                        if subject_header:
                            subject, encoding = decode_header(subject_header)[0]
                            if isinstance(subject, bytes):
                                subject = subject.decode(encoding if encoding else "utf-8")
                        
                        from_ = msg.get("From")
                        date = msg.get("Date")


                        body = ""
                        if msg.is_multipart():
                            for part in msg.walk():
                                content_disposition = str(part.get("Content-Disposition"))
                                if part.get_content_type() == "text/plain" and "attachment" not in content_disposition:
                                    try:
                                        body = part.get_payload(decode=True).decode('utf-8')
                                    except UnicodeDecodeError:
                                        try:
                                            body = part.get_payload(decode=True).decode('latin-1')
                                        except:
                                            body = "Could not decode email body"
                                    break  # only first plain-text part
                        else:
                            try:
                                body = msg.get_payload(decode=True).decode('utf-8')
                            except UnicodeDecodeError:
                                try:
                                    body = msg.get_payload(decode=True).decode('latin-1')
                                except:
                                    body = "Could not decode email body"
                        
                        results.append({
                            "subject": subject,
                            "from": from_,
                            "date": date,
                            "body": body,
                            "message_id": msg.get("Message-ID")
                        })
            
            imap.logout()
            return f"Found {len(results)} emails matching criteria: {results}"
            
        except Exception as e:
            return f"Error searching emails: {e}"  




    
    def get_intent_classifier(self):
        return autogen.AssistantAgent(
            name="intent_classifier_agent",
            llm_config=self.llm_config,
            system_message=prompts.intent_classifier,
        )
    def get_email_reader(self):
        return autogen.AssistantAgent(
            name="email_reader_agent",
            llm_config=self.llm_config,
            system_message=prompts.email_reader,
        )
    def get_email_search(self):
        return autogen.AssistantAgent(
            name="email_search_agent",
            llm_config=self.llm_config,
            system_message=prompts.email_search,
        )
    def get_email_reply(self):
        return autogen.AssistantAgent(
            name="email_reply_agent",
            llm_config=self.llm_config,
            system_message=prompts.email_reply,
        )


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
    # static custom speaker selection, no dynamic agent selection or conditional chat routing
    # def custom_speaker_selection_func(self,last_speaker: Any, groupchat: Any) -> Any:
    #     messages = groupchat.messages
    #     # Proceed based on the last speaker
    #     if last_speaker.name == "chat_manager":
    #         print("Initial query received. Starting with user_proxy.")
    #         # rint(f"last_agent_msg is --> {get_last_msg()}")
    #         return groupchat.agent_by_name("planner_agent")
    #     if last_speaker.name == "planner_agent":
    #         return groupchat.agent_by_name("content_writer_agent")
    #     if last_speaker.name == "content_writer_agent":
    #         return groupchat.agent_by_name("email_caller_agent")
    #     elif last_speaker.name == "email_caller_agent":
    #         return groupchat.agent_by_name("code_executor_agent")
    #     elif last_speaker.name == "code_executor_agent":
    #         if "exitcode: 1" in messages[-1]["content"]:
    #             return groupchat.agent_by_name("debugger_agent")
    #         elif "exitcode: 0" in messages[-1]["content"]:
    #             return groupchat.agent_by_name("process_completion_agent")
    #         else:
    #             return groupchat.agent_by_name("process_completion_agent")
    #     elif last_speaker.name == "debugger_agent":
    #         return groupchat.agent_by_name("email_caller_agent")
        

    def custom_speaker_selection_func(self,last_speaker: Any, groupchat: Any) -> Any:
        messages = groupchat.messages
        if len(messages) == 1:
            print("Initial query received. Starting with intent_classifier.")
            return groupchat.agent_by_name("intent_classifier_agent")
        if last_speaker.name == "intent_classifier_agent":
            last_message = messages[-1]["content"]
            if "INTENT: SEND_EMAIL" in last_message:
                return groupchat.agent_by_name("planner_agent")
            elif "INTENT: READ_EMAIL" in last_message:
                return groupchat.agent_by_name("email_reader_agent")
            elif "INTENT: SEARCH_EMAIL" in last_message:
                return groupchat.agent_by_name("email_search_agent")
            elif "INTENT: REPLY_EMAIL" in last_message:
                return groupchat.agent_by_name("email_reply_agent")
            
        #the basic flow of the email manager    
        if last_speaker.name == "planner_agent":
            return groupchat.agent_by_name("content_writer_agent")
        if last_speaker.name == "content_writer_agent":
            return groupchat.agent_by_name("email_caller_agent")
        if last_speaker.name == "email_caller_agent":
            return groupchat.agent_by_name("code_executor_agent")
        if last_speaker.name == "code_executor_agent":
            if "exitcode: 1" in messages[-1]["content"]:
                return groupchat.agent_by_name("debugger_agent")
            elif "exitcode: 0" in messages[-1]["content"]:
                return groupchat.agent_by_name("process_completion_agent")
            else:
                return groupchat.agent_by_name("process_completion_agent")
        #the additional flow for the email manager
        if last_speaker.name == "debugger_agent":
            return groupchat.agent_by_name("code_executor_agent")
        
        elif last_speaker.name == "email_reader_agent":
            return groupchat.agent_by_name("code_executor_agent")

        
        elif last_speaker.name in ["email_search_agent"]:
             return groupchat.agent_by_name("code_executor_agent")
        
        elif last_speaker.name in ["email_reply_agent"]:
            return groupchat.agent_by_name("code_executor_agent")


    def get_agents(self):
        self.intent_classifier = self.get_intent_classifier()
        self.email_reader_agent = self.get_email_reader()
        self.email_search_agent = self.get_email_search()
        self.email_reply_agent = self.get_email_reply()
        self.planner = self.get_planner()
        self.content_writer = self.get_content_writer()
        self.email_caller = self.get_email_caller()
        self.code_executor = self.get_code_executor()
        self.debugger = self.get_debugger()
        self.process_completion = self.get_process_completion()
        return [
            self.intent_classifier,
            self.email_reader_agent,
            self.email_search_agent,
            self.email_reply_agent,
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
        self.manager = CustomGroupChatManager(
            groupchat=self.groupchat,
            llm_config=self.llm_config,
            omni_memory = self.omni_memory,
            capability_name=settings.EMAIL_COLLECTION,
            capability_id=self.capability_id,
            chat_id=self.chat_id,
            call_id=self.call_id,
            human_input_mode="ALWAYS"
        )
        return

