import asyncio
import email

# new imports
import imaplib
import json
import os
import smtplib
from email import encoders
from email.header import decode_header
from email.message import EmailMessage
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import parseaddr
from typing import Any

import aiofiles
import autogen
from loguru import logger

from src.capabilities.email_manager import prompts
from src.capabilities.email_manager.response_format import (
    EmailProcessCompletion,
    IntentClassifier,
)
from src.configs.datetime_utils import dt
from src.configs.llm_configs_manager import LLMConfigManager
from src.configs.settings import settings
from src.configs.system_ai_config import GroupchatConfigurationManager
from src.utilities.async_errors import AsyncErrorCode, create_error
from src.utilities.custom_manager import ChatContext, CustomGroupChatManager
from src.utilities.storage import ensure_path

today_date = dt.now()


def validate_attachments(file_paths):
    """Validate if all attachment files exist before sending."""
    import os

    invalid_paths = []
    for path in file_paths:
        if not os.path.exists(path):
            invalid_paths.append(path)
    return invalid_paths


class EmailManager:
    """Manager for email sending, reading, and searching capabilities."""

    def __init__(self, context: ChatContext):
        self.context = context
        self.groupchat_config = (
            GroupchatConfigurationManager.get_instance().get_groupchat_configuration(
                "email_sender"
            )
        )
        self.user_input_func = self.context.manager_kwargs["input_function"]
        self.llm_config = LLMConfigManager.get_config("default")
        self.username = settings.USER_EMAIL
        self.password = settings.USER_EMAIL_PASSWORD
        self.agents = self.get_agents()
        self._register_functions()
        self.get_chat_manager()

    def _check_cancellation(self):
        """Check if the chat should be cancelled."""
        if (
            self.context.cancellation_token
            and self.context.cancellation_token.is_cancelled()
        ):
            raise asyncio.CancelledError(
                f"Group chat cancelled for session {self.context.chat_id}"
            )

    async def handle_email_confirmation(
        self,
        recipients: list[str],
        subject: str,
        msg_html: str,
        msg_plain: str,
        attachments: list[str],
        sender: str,
    ) -> tuple[bool, dict[str, Any]]:
        """Handle user confirmation and modifications for email sending.

        Returns:
            Tuple[bool, Dict]: (should_send, email_data_or_response)
        """
        # Store original data for comparison
        original_data = {
            "recipients": recipients.copy(),
            "subject": subject,
            "msg_html": msg_html,
            "msg_plain": msg_plain,
            "attachments": attachments.copy() if attachments else [],
            "sender": sender,
        }

        # Create confirmation request
        confirmation_request = {
            "action": "email_confirmation",
            "agent": "send_email_with_attachments",
            "email_data": {
                "recipients": recipients,
                "subject": subject,
                "msg_html": msg_html,
                "msg_plain": msg_plain,
                "sender": sender,
                "attachments": attachments or [],
                "attachment_names": [
                    os.path.basename(path) for path in (attachments or [])
                ],
                "recipient_count": len(recipients),
                "has_html": bool(msg_html),
                "has_plain": bool(msg_plain),
                "has_attachments": bool(attachments),
            },
            "options": {
                "send": "Send email as is",
                "modify": "Modify email before sending",
                "cancel": "Cancel email sending",
            },
            "timestamp": dt.now_iso(),
            "preview": {
                "subject_preview": (
                    subject[:50] + "..." if len(subject) > 50 else subject
                ),
                "content_preview": (
                    (msg_plain or msg_html or "")[:100] + "..."
                    if len(msg_plain or msg_html or "") > 100
                    else (msg_plain or msg_html or "")
                ),
            },
        }

        # Get user response
        user_response = await self.user_input_func(
            json.dumps(confirmation_request, indent=2)
        )

        # Parse user response
        try:
            # response_data = json.loads(user_response)
            response_data = user_response
        except json.JSONDecodeError:
            # Handle simple string responses
            response_data = {"action": user_response.lower().strip()}

        action = response_data.get("action", "").lower()

        # Handle cancel
        if action == "cancel":
            return False, {
                "status": "cancelled",
                "message": "Email sending cancelled by user",
                "action_taken": "cancel",
                "timestamp": dt.now_iso(),
            }

        # Handle send as-is
        if action in ["send", "yes", "y", "ok", "proceed"]:
            return True, {
                "recipients": recipients,
                "subject": subject,
                "msg_html": msg_html,
                "msg_plain": msg_plain,
                "attachments": attachments,
                "sender": sender,
                "was_modified": False,
                "modifications": {},
            }

        # Handle modifications
        if action == "modify":
            modifications = response_data.get("modifications", {})
            changes_made = []

            # Update recipients
            if "recipients" in modifications:
                new_recipients = modifications["recipients"]
                if new_recipients != recipients:
                    added = list(set(new_recipients) - set(recipients))
                    removed = list(set(recipients) - set(new_recipients))
                    recipients = new_recipients

                    if added:
                        changes_made.append(f"Added recipients: {', '.join(added)}")
                    if removed:
                        changes_made.append(f"Removed recipients: {', '.join(removed)}")

            # Update subject
            if "subject" in modifications and modifications["subject"] != subject:
                changes_made.append(
                    f"Subject changed from '{subject}' to '{modifications['subject']}'"
                )
                subject = modifications["subject"]

            # Update message content
            if "msg_html" in modifications and modifications["msg_html"] != msg_html:
                changes_made.append("HTML message content modified")
                msg_html = modifications["msg_html"]

            if "msg_plain" in modifications and modifications["msg_plain"] != msg_plain:
                changes_made.append("Plain text message content modified")
                msg_plain = modifications["msg_plain"]

            # Update attachments
            if "attachments" in modifications:
                new_attachments = modifications["attachments"] or []
                original_attachments = attachments or []

                if set(new_attachments) != set(original_attachments):
                    added = list(set(new_attachments) - set(original_attachments))
                    removed = list(set(original_attachments) - set(new_attachments))
                    attachments = new_attachments

                    if added:
                        changes_made.append(
                            f"Added attachments: {', '.join([os.path.basename(f) for f in added])}"
                        )
                    if removed:
                        changes_made.append(
                            f"Removed attachments: {', '.join([os.path.basename(f) for f in removed])}"
                        )

            # Validate modified attachments
            if attachments:
                invalid_paths = validate_attachments(attachments)
                if invalid_paths:
                    return False, {
                        "status": "error",
                        "message": f"Modified attachments have invalid paths: {invalid_paths}",
                        "error_type": "invalid_modified_attachments",
                    }

            # Create comparison for modifications
            modifications_summary = {}
            current_data = {
                "recipients": recipients,
                "subject": subject,
                "msg_html": msg_html,
                "msg_plain": msg_plain,
                "attachments": attachments or [],
                "sender": sender,
            }

            for key in original_data:
                if original_data[key] != current_data[key]:
                    modifications_summary[key] = {
                        "original": original_data[key],
                        "current": current_data[key],
                    }

            return True, {
                "recipients": recipients,
                "subject": subject,
                "msg_html": msg_html,
                "msg_plain": msg_plain,
                "attachments": attachments,
                "sender": sender,
                "was_modified": True,
                "changes_made": changes_made,
                "modifications_summary": modifications_summary,
            }

        # Invalid response - treat as cancel
        return False, {
            "status": "cancelled",
            "message": "Invalid response - email sending cancelled",
            "action_taken": "cancel",
        }

    async def send_email_with_attachments(
        self,
        to: list[str] | str,
        subject: str,
        msg_html: str,
        msg_plain: str,
        attachments: list[str] = None,
        sender: str = None,
    ):
        """Clean email sending function with separate confirmation handling."""
        if sender is None:
            sender = self.username

        # Validate attachments upfront
        if attachments:
            invalid_paths = validate_attachments(attachments)
            if invalid_paths:
                return {
                    "status": "error",
                    "message": f"Invalid attachment paths: {invalid_paths}",
                    "error_type": "invalid_attachments",
                }

        # Handle recipients
        recipients = to if isinstance(to, list) else [to]

        try:
            # Handle user confirmation and modifications
            should_send, confirmation_result = await self.handle_email_confirmation(
                recipients, subject, msg_html, msg_plain, attachments or [], sender
            )

            # If not sending (cancelled or error), return the result
            if not should_send:
                return confirmation_result

            # Extract potentially modified email data
            final_recipients = confirmation_result["recipients"]
            final_subject = confirmation_result["subject"]
            final_msg_html = confirmation_result["msg_html"]
            final_msg_plain = confirmation_result["msg_plain"]
            final_attachments = confirmation_result["attachments"]
            final_sender = confirmation_result["sender"]
            was_modified = confirmation_result["was_modified"]

            # Create email message
            msg = MIMEMultipart("alternative")
            msg["Subject"] = final_subject
            msg["From"] = final_sender
            msg["To"] = ", ".join(final_recipients)

            # Add body parts
            if final_msg_plain:
                part1 = MIMEText(final_msg_plain, "plain")
                msg.attach(part1)

            if final_msg_html:
                part2 = MIMEText(final_msg_html, "html")
                msg.attach(part2)

            # Add attachments and collect info (using async file I/O)
            attachment_info = []
            if final_attachments:
                for file_path in final_attachments:
                    if os.path.exists(file_path):
                        try:
                            # Use async file I/O for non-blocking reads
                            async with aiofiles.open(
                                file_path, "rb"
                            ) as attachment_file:
                                file_content = await attachment_file.read()

                            part = MIMEBase("application", "octet-stream")
                            part.set_payload(file_content)
                            encoders.encode_base64(part)
                            filename = os.path.basename(file_path)
                            part.add_header(
                                "Content-Disposition",
                                f"attachment; filename= {filename}",
                            )
                            msg.attach(part)
                            attachment_info.append(
                                {
                                    "filename": filename,
                                    "path": file_path,
                                    "size": os.path.getsize(file_path),
                                }
                            )
                        except OSError as e:
                            error = create_error(
                                AsyncErrorCode.FILE_READ_FAILED,
                                "email_attachment_read",
                                user_message=f"Could not read attachment: {os.path.basename(file_path)}",
                                technical_message=str(e),
                                context={"file_path": file_path},
                            )
                            logger.error(
                                f"[{error.code.value}] Attachment read failed: {e}"
                            )
                            return {
                                "status": "error",
                                "error_code": error.code.value,
                                "message": error.user_message,
                                "support_reference": f"Contact support with code: {error.code.value}",
                            }

            # Send email
            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
                server.login(self.username, self.password)
                server.send_message(
                    msg, from_addr=self.username, to_addrs=final_recipients
                )

            # Create success response
            success_response = {
                "status": "sent",
                "message": f"Email sent successfully to {', '.join(final_recipients)}",
                "email_details": {
                    "recipients": final_recipients,
                    "subject": final_subject,
                    "sender": final_sender,
                    "attachments": attachment_info,
                    "content_types": {
                        "html": bool(final_msg_html),
                        "plain": bool(final_msg_plain),
                    },
                },
                "was_modified": was_modified,
                "timestamp": dt.now_iso(),
                "action_taken": "send",
            }

            # Add modification details if email was changed
            if was_modified:
                success_response.update(
                    {
                        "changes_made": confirmation_result.get("changes_made", []),
                        "modifications_summary": confirmation_result.get(
                            "modifications_summary", {}
                        ),
                    }
                )

            return success_response

        except smtplib.SMTPException as e:
            error = create_error(
                AsyncErrorCode.EMAIL_SEND_FAILED,
                "email_send",
                user_message="Failed to send email. Please check your email settings and try again.",
                technical_message=str(e),
                context={
                    "recipients": (
                        final_recipients if "final_recipients" in dir() else recipients
                    )
                },
            )
            logger.error(f"[{error.code.value}] SMTP error: {e}")
            return {
                "status": "error",
                "error_code": error.code.value,
                "message": error.user_message,
                "support_reference": f"Contact support with code: {error.code.value}",
                "timestamp": dt.now_iso(),
            }
        except Exception as e:
            error = create_error(
                AsyncErrorCode.EMAIL_SEND_FAILED,
                "email_send",
                user_message="An unexpected error occurred while sending email. Please try again.",
                technical_message=str(e),
                context={"error_type": type(e).__name__},
            )
            logger.error(f"[{error.code.value}] Email send error: {e}")
            return {
                "status": "error",
                "error_code": error.code.value,
                "message": error.user_message,
                "support_reference": f"Contact support with code: {error.code.value}",
                "timestamp": dt.now_iso(),
            }

    async def read_latest_email_with_attachments(
        self, sender_details: str = None, attachment_dir: str = None
    ):
        """Read the latest email with optional attachment download."""
        try:
            # Connect and login
            imap = imaplib.IMAP4_SSL("imap.gmail.com")
            imap.login(self.username, self.password)
            imap.select("inbox")
        except Exception as e:
            return f"Error connecting to email: {e}"

        # Search for emails from a specific sender
        filtered_sender = f'FROM "{sender_details}"' if sender_details else "ALL"
        status, messages = imap.search(None, filtered_sender)
        email_ids = messages[0].split()

        if not email_ids:
            imap.logout()
            return "No emails found from the specified sender."

        # Fetch the latest email
        latest_email_id = email_ids[-1]
        status, msg_data = imap.fetch(latest_email_id, "(RFC822)")

        # Create folder to save attachments
        if attachment_dir is None:
            attachment_dir = ensure_path(
                os.path.join(self.context.chat_dir, "attachments")
            )
        else:
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
                        if (
                            part.get_content_type() == "text/plain"
                            and "attachment" not in content_disposition
                        ):
                            try:
                                body = part.get_payload(decode=True).decode("utf-8")
                            except UnicodeDecodeError:
                                try:
                                    body = part.get_payload(decode=True).decode(
                                        "latin-1"
                                    )
                                except Exception as e:
                                    logger.error(f"Error decoding email body: {e}")
                                    body = "Could not decode email body"

                        # Download attachment
                        if "attachment" in content_disposition:
                            filename = part.get_filename()
                            if filename:
                                decoded_filename, encoding = decode_header(filename)[0]
                                if isinstance(decoded_filename, bytes):
                                    decoded_filename = decoded_filename.decode(
                                        encoding if encoding else "utf-8"
                                    )

                                filepath = os.path.join(
                                    attachment_dir, decoded_filename
                                )
                                full_path = os.path.abspath(filepath)

                                try:
                                    # Use async file I/O for non-blocking writes
                                    async with aiofiles.open(full_path, "wb") as f:
                                        await f.write(part.get_payload(decode=True))
                                    attachment_paths.append(full_path)
                                except OSError as e:
                                    error = create_error(
                                        AsyncErrorCode.FILE_WRITE_FAILED,
                                        "email_attachment_save",
                                        user_message=f"Could not save attachment: {decoded_filename}",
                                        technical_message=str(e),
                                        context={"file_path": full_path},
                                    )
                                    logger.error(
                                        f"[{error.code.value}] Attachment save failed: {e}"
                                    )
                else:
                    # Single-part email
                    try:
                        body = msg.get_payload(decode=True).decode("utf-8")
                    except UnicodeDecodeError:
                        try:
                            body = msg.get_payload(decode=True).decode("latin-1")
                        except Exception as e:
                            logger.error(f"Error decoding email body: {e}")
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
                    STATUS: Email read successfully
                    """

    async def send_reply_to_email(
        self,
        message_id: str,
        subject: str,
        from_: str,
        body: str,
        reply_content: str = None,
    ):
        """Send a reply to a specific email."""
        if not all([message_id, subject, from_, body]):
            return "Error: Missing required email information"

        try:
            original_message_id = message_id
            msg = EmailMessage()
            msg["Subject"] = subject
            msg["From"] = self.username
            msg["To"] = from_
            msg["In-Reply-To"] = original_message_id
            msg["References"] = original_message_id

            if reply_content:
                msg.set_content(reply_content)
            else:
                msg.set_content(reply_content)
                # Use LLM to generate reply
                # response = self.llm.invoke(f"reply to the email with a short message to the user,--> {body}")
                # msg.set_content(response.content)

            # Send via Gmail SMTP
            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
                smtp.login(self.username, self.password)
                smtp.send_message(msg)

            return "Reply sent successfully."
        except Exception as e:
            return f"Error sending reply: {e}"

    async def search_emails_by_criteria(self, search_criteria: str, limit: int = 5):
        """Search emails based on criteria (sender, subject, etc.)."""
        try:
            imap = imaplib.IMAP4_SSL("imap.gmail.com")
            imap.login(self.username, self.password)
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
                                subject = subject.decode(
                                    encoding if encoding else "utf-8"
                                )

                        from_ = msg.get("From")
                        name, email_address = parseaddr(from_)
                        date = msg.get("Date")

                        body = ""
                        if msg.is_multipart():
                            for part in msg.walk():
                                content_disposition = str(
                                    part.get("Content-Disposition")
                                )
                                if (
                                    part.get_content_type() == "text/plain"
                                    and "attachment" not in content_disposition
                                ):
                                    try:
                                        body = part.get_payload(decode=True).decode(
                                            "utf-8"
                                        )
                                    except UnicodeDecodeError:
                                        try:
                                            body = part.get_payload(decode=True).decode(
                                                "latin-1"
                                            )
                                        except Exception as e:
                                            logger.error(
                                                f"Error decoding email body: {e}"
                                            )
                                            body = "Could not decode email body"
                                    break  # only first plain-text part
                        else:
                            try:
                                body = msg.get_payload(decode=True).decode("utf-8")
                            except UnicodeDecodeError:
                                try:
                                    body = msg.get_payload(decode=True).decode(
                                        "latin-1"
                                    )
                                except Exception:
                                    body = "Could not decode email body"

                        results.append(
                            {
                                "subject": subject,
                                "from": from_,
                                "date": date,
                                "from_email": email_address,
                                "body": body,
                                "message_id": msg.get("Message-ID"),
                                # "headers": list(msg.items())
                            }
                        )

            imap.logout()
            return f"Found {len(results)} emails matching criteria: {results}"

        except Exception as e:
            return f"Error searching emails: {e}"

    def _register_functions(self):
        """Register email management functions with the agents."""
        # Wrapper functions before registering to agents

        async def send_email_with_attachments_wrapper(
            to: list[str] | str,
            subject: str,
            msg_html: str,
            msg_plain: str,
            attachments: list[str] = None,
            sender: str = None,
        ):
            return await self.send_email_with_attachments(
                to, subject, msg_html, msg_plain, attachments, sender
            )

        async def read_latest_email_with_attachments_wrapper(
            sender_details: str = None, attachment_dir: str = None
        ):
            return await self.read_latest_email_with_attachments(
                sender_details, attachment_dir
            )

        async def send_reply_to_email_wrapper(
            message_id: str,
            subject: str,
            from_: str,
            body: str,
            reply_content: str = None,
        ):
            return await self.send_reply_to_email(
                message_id, subject, from_, body, reply_content
            )

        async def search_emails_by_criteria_wrapper(
            search_criteria: str, limit: int = 5
        ):
            return await self.search_emails_by_criteria(search_criteria, limit)

        autogen.register_function(
            send_email_with_attachments_wrapper,
            caller=self.email_caller,
            executor=self.code_executor,
            name="send_email_with_attachments",
            description="Sends an email with HTML and plain text content to one or more recipients, optionally including file attachments.",
        )
        autogen.register_function(
            read_latest_email_with_attachments_wrapper,
            caller=self.email_reader_agent,
            executor=self.code_executor,
            name="read_latest_email_with_attachments",
            description="Search emails by criteria,  read the email content  and save attachments to local if needed.",
        )
        autogen.register_function(
            send_reply_to_email_wrapper,
            caller=self.email_reply_agent,
            executor=self.code_executor,
            name="send_reply_to_email",
            description="Send reply to a specific email",
        )

        autogen.register_function(
            search_emails_by_criteria_wrapper,
            caller=self.email_search_agent,
            executor=self.code_executor,
            name="search_emails_by_criteria",
            description="Search emails by criteria",
        )

    def get_context_keeper(self):
        """Get the context keeper agent."""
        return autogen.AssistantAgent(name="context_keeper", llm_config=self.llm_config)

    def get_intent_classifier(self):
        """Get the intent classifier agent."""
        llm_config_name = (
            self.groupchat_config.get_agent_config("intent_classifier_agent").llm_config
            or "default"
        )
        llm_intent_classifier_agent = LLMConfigManager.get_config(llm_config_name)
        llm_intent_classifier_agent["response_format"] = IntentClassifier
        return autogen.AssistantAgent(
            name="intent_classifier_agent",
            # llm_config=self.llm_config,
            llm_config=self.llm_config,  # llm_config_ic , llm_config
            system_message=prompts.intent_classifier,
        )

    def get_email_reader(self):
        """Get the email reader agent."""
        return autogen.AssistantAgent(
            name="email_reader_agent",
            llm_config=self.llm_config,
            system_message=prompts.email_reader,
        )

    def get_email_search(self):
        """Get the email search agent."""
        return autogen.AssistantAgent(
            name="email_search_agent",
            llm_config=self.llm_config,
            system_message=prompts.email_search,
        )

    def get_email_reply(self):
        """Get the email reply agent."""
        return autogen.AssistantAgent(
            name="email_reply_agent",
            llm_config=self.llm_config,
            system_message=prompts.email_reply,
        )

    def get_planner(self):
        """Get the planner agent."""
        return autogen.AssistantAgent(
            name="planner_agent",
            llm_config=self.llm_config,
            system_message=prompts.planner,
        )

    def get_content_writer(self):
        """Get the content writer agent."""
        llm_config_name = (
            self.groupchat_config.get_agent_config("content_writer_agent").llm_config
            or "default"
        )
        llm_content_writer_agent = LLMConfigManager.get_config(llm_config_name)
        llm_content_writer_agent["max_tokens"] = 16384
        return autogen.AssistantAgent(
            name="content_writer_agent",
            llm_config=llm_content_writer_agent,
            system_message=prompts.content_writer,
        )

    def get_email_caller(self):
        """Get the email caller agent."""
        return autogen.AssistantAgent(
            name="email_caller_agent",
            llm_config=self.llm_config,
            # system_message=prompts.email_caller,
        )

    def get_code_executor(self):
        """Get the code executor agent."""
        return autogen.UserProxyAgent(
            name="code_executor_agent",
            human_input_mode="NEVER",
            code_execution_config=False,
        )

    def get_debugger(self):
        """Get the debugger agent."""
        return autogen.AssistantAgent(
            name="debugger_agent",
            max_consecutive_auto_reply=5,
            llm_config=self.llm_config,
            system_message=prompts.debugger,
        )

    def get_process_completion(self):
        """Get the process completion agent."""
        llm_config_name = (
            self.groupchat_config.get_agent_config(
                "process_completion_agent"
            ).llm_config
            or "default"
        )
        llm_process_completion_agent = LLMConfigManager.get_config(llm_config_name)
        llm_process_completion_agent["response_format"] = EmailProcessCompletion
        return autogen.AssistantAgent(
            name="process_completion_agent",
            # llm_config=self.llm_config,
            llm_config=llm_process_completion_agent,  # llm_config_pc , llm_config
            system_message=prompts.process_completion,
        )

    def custom_speaker_selection_func(self, last_speaker: Any, groupchat: Any) -> Any:
        """Select the next speaker in the group chat based on conversation flow."""
        try:
            self._check_cancellation()

            messages = groupchat.messages
            if len(messages) == 1 or last_speaker.name == "chat_manager":
                print("Initial query received. Starting with intent_classifier.")
                return groupchat.agent_by_name("intent_classifier_agent")
            if last_speaker.name == "intent_classifier_agent":
                last_message = messages[-1]["content"]
                if "INTENT: SEND_EMAIL" in last_message:
                    return groupchat.agent_by_name("planner_agent")
                elif "INTENT: READ_EMAIL" in last_message:
                    return groupchat.agent_by_name("email_search_agent")
                elif "INTENT: SEARCH_EMAIL" in last_message:
                    return groupchat.agent_by_name("email_search_agent")
                elif "INTENT: REPLY_EMAIL" in last_message:
                    return groupchat.agent_by_name("email_reply_agent")

            # the basic flow of the email manager
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
            # the additional flow for the email manager
            if last_speaker.name == "debugger_agent":
                return groupchat.agent_by_name("code_executor_agent")

            elif last_speaker.name == "email_reader_agent":
                return groupchat.agent_by_name("code_executor_agent")

            elif last_speaker.name in ["email_search_agent"]:
                return groupchat.agent_by_name("code_executor_agent")

            elif last_speaker.name in ["email_reply_agent"]:
                return groupchat.agent_by_name("code_executor_agent")

        except asyncio.CancelledError:
            logger.info(
                f"Speaker selection cancelled for session {self.context.chat_id}"
            )
            # Return process_completion to gracefully end the chat
            raise

    def get_agents(self):
        """Initialize and return all agents for the email management workflow."""
        self.intent_classifier = self.get_intent_classifier()
        self.context_keeper = self.get_context_keeper()
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
            self.context_keeper,
            self.email_reader_agent,
            self.email_search_agent,
            self.email_reply_agent,
            self.planner,
            self.content_writer,
            self.email_caller,
            self.code_executor,
            self.debugger,
            self.process_completion,
        ]

    def get_chat_manager(self):
        """Initialize and return the group chat manager."""
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
            human_input_mode="ALWAYS",
        )
        return
