import ast
import asyncio
import json
import os
import re
import uuid
from collections import defaultdict
from string import Template
from typing import Annotated, Any

import autogen
from autogen import UserProxyAgent
from loguru import logger

from src.capabilities.browser_manager.manager import BrowserManager
from src.capabilities.software_developer.manager import SoftwareDeveloper
from src.configs.datetime_utils import dt
from src.configs.llm_configs_manager import LLMConfigManager
from src.configs.settings import CapabilityType, settings
from src.configs.system_ai_config import GroupchatConfigurationManager
from src.dependencies import get_websocket_manager
from src.omni import orchestrator, prompts
from src.agent_runtime import PERSONAS, prefs, run_persona, specialists
from src.agent_runtime.prompts import (
    BUYER_FINDER_DESCRIPTION,
    CAMPAIGN_BUILDER_DESCRIPTION,
    CAMPAIGN_STRATEGIZER_DESCRIPTION,
    INBOX_AGENT_DESCRIPTION,
    CONTACT_ENRICHER_DESCRIPTION,
    LEAD_FINDER_DESCRIPTION,
    ML_ENGINEER_DESCRIPTION,
    OUTREACH_DESCRIPTION,
    USER_CONTEXT_DESCRIPTION,
)
from src.omni.capabilities_descriptions import (
    email_manager_description,
)
from src.utilities.custom_manager import ChatContext, create_capability_chat
from src.omni.capability_manager import CapabilityConfig, CapabilityManager
from src.omni.memory import OmniMemory
from src.omni.response_format import (
    AgentSelectionResponse,
    CapabilityRoutingResponse,
    ClarifierResponse,
    PlannerResponse,
    QuestionClassification,
)
from src.chat.tools.composio import ComposioToolCache, ComposioToolManager
from src.mcp_client.config import reserved_servers
from src.mcp_client.registry import register_mcp_tools
from src.utilities.async_helpers import async_to_sync
from src.database import answer_decision, log_decision, update_chat_history
from src.utilities.storage import a_speak

today_date = dt.now()


def _steady(llm_config: dict) -> dict:
    """Same request, same decision: the agents that classify, ask, plan and route run at temperature 0
    (measured 2026-10-29: plans for one request varied run to run at the default temperature)."""
    llm_config["temperature"] = 0  # top level: autogen forbids it inside a config_list entry
    return llm_config


class OmniGroupChatManager(autogen.GroupChatManager):
    """Enhanced GroupChatManager with memory, WebSocket, and voice capabilities."""

    def __init__(
        self,
        groupchat,
        memory,
        chat_id: str,
        task_id: str = None,
        llm_config=None,
        human_input_mode: str = "NEVER",
    ):
        super().__init__(
            groupchat=groupchat,
            llm_config=llm_config,
            human_input_mode=human_input_mode,
        )
        self.chat_id = chat_id
        self.task_id = task_id
        self.memory = memory
        # Track previous usage state for each agent to calculate deltas
        self._agent_previous_usage = defaultdict(
            lambda: {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "cost": 0.0,
            }
        )

        # Initialize tracking for all agents
        self._initialize_agent_tracking()

    def _initialize_agent_tracking(self):
        """Initialize usage tracking for all agents."""
        for agent in self.groupchat.agents:
            # Initialize with current usage if any
            current_usage = self._get_agent_current_usage(agent)
            self._agent_previous_usage[agent.name] = current_usage.copy()

    def _get_agent_current_usage(self, agent) -> dict[str, Any]:
        """Get current usage for a specific agent."""
        default_usage = {
            "model": "unknown",
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "cost": 0.0,
        }

        # Check if agent has client and usage summary
        if not hasattr(agent, "client") or not agent.client:
            return default_usage

        usage_summary = getattr(agent.client, "total_usage_summary", None)
        if not usage_summary:
            return default_usage

        # Find the model key (first key that's not 'total_cost')
        model_keys = [k for k in usage_summary.keys() if k != "total_cost"]
        if not model_keys:
            return default_usage

        model_key = model_keys[0]
        model_usage = usage_summary.get(model_key, {})

        return {
            "model": model_key,
            "prompt_tokens": model_usage.get("prompt_tokens", 0),
            "completion_tokens": model_usage.get("completion_tokens", 0),
            "total_tokens": model_usage.get("total_tokens", 0),
            "cost": model_usage.get("cost", 0.0),
        }

    def _calculate_agent_usage_delta(self, agent, agent_name: str) -> dict[str, Any]:
        """Calculate usage delta for a specific agent since last check."""
        current_usage = self._get_agent_current_usage(agent)
        previous_usage = self._agent_previous_usage[agent_name]

        # Calculate the delta (what changed since last check)
        usage_delta = {
            "prompt_tokens": current_usage["prompt_tokens"]
            - previous_usage["prompt_tokens"],
            "completion_tokens": current_usage["completion_tokens"]
            - previous_usage["completion_tokens"],
            "total_tokens": current_usage["total_tokens"]
            - previous_usage["total_tokens"],
            "cost": current_usage["cost"] - previous_usage["cost"],
        }

        # Update the previous usage for next calculation
        self._agent_previous_usage[agent_name] = current_usage.copy()

        # Return both current total and delta for this message
        return {
            "current_total": current_usage,
            "message_delta": usage_delta,
            "agent_name": agent_name,
        }

    def _get_sender_agent_usage(self, sender) -> dict[str, Any]:
        """Get usage details for the sender agent when message is received."""
        return self._calculate_agent_usage_delta(sender, sender.name)

    async def _send_websocket_message(self, message_data: dict) -> None:
        """Send message to WebSocket clients.

        Sends with source='OMNI' and content as the full message_data dict,
        matching the format the frontend expects for omni mode messages.
        """
        try:
            websocket_manager = await get_websocket_manager()
            await websocket_manager.send_chat_message(
                session_id=self.chat_id,
                content=message_data,
                source="OMNI",
            )
        except Exception as e:
            logger.error(f"WebSocket send failed for chat_id {self.chat_id}: {e}")

    async def _handle_voice_alert(self, agent_name: str, content: str) -> None:
        """Handle voice alerts for specific agents."""
        try:
            if agent_name == "manual_verification":
                await a_speak(content)
            elif agent_name == "process_completion_agent":
                await a_speak("Hey there! DAXAGENT finished your task!")
        except Exception as e:
            logger.error(f"Voice alert failed for agent {agent_name}: {e}")

    async def _process_message_async(self, message_data: dict) -> None:
        """Process message asynchronously."""
        await self._handle_voice_alert(message_data["name"], message_data["content"])
        await self._send_websocket_message(message_data)
        await update_chat_history(self.chat_id, message_data, settings.OMNI_COLLECTION)

    def _print_received_message(
        self, message: dict[str, Any], sender: "autogen.Agent"
    ) -> None:
        """Override to handle received messages with enhanced processing."""
        logger.info(f"Received from {sender.name}: {message}")
        super()._print_received_message(message, sender)

        # Get the sender's usage details (current total + delta for this message)
        sender_usage = self._get_sender_agent_usage(sender)

        content = (
            message.get("content", "") if isinstance(message, dict) else str(message)
        )
        message_data = {
            "role": "user",
            "name": sender.name,
            "content": content,
            "raw_message": message,
            "usage": sender_usage,
            "task_id": self.task_id,
        }
        websocket_message = {
            "role": "user",
            "name": sender.name,
            "content": content,
            "raw_message": message,
            "task_id": self.task_id,
        }
        # Log the usage information for debugging
        logger.info(
            f"Agent {sender.name} usage - "
            f"Delta: {sender_usage['message_delta']['total_tokens']} tokens, "
            f"${sender_usage['message_delta']['cost']:.4f} | "
            f"Total: {sender_usage['current_total']['total_tokens']} tokens, "
            f"${sender_usage['current_total']['cost']:.4f}"
        )

        # Store in memory synchronously
        self.memory.push_main_message(
            {k: message_data[k] for k in ["role", "name", "content"]}
        )

        # Process async operations
        # asyncio.create_task(self._handle_voice_alert(message_data["name"], message_data["content"]))
        caller_prose = sender.name == "agent_caller" and not (isinstance(message, dict) and message.get("tool_calls"))
        if not caller_prose:
            # A caller message without a tool call is restated by the conversation
            # agent; forwarding both showed every question twice.
            async_to_sync(self._send_websocket_message(websocket_message))
        async_to_sync(
            update_chat_history(self.chat_id, message_data, settings.OMNI_COLLECTION)
        )

    # Additional utility methods for comprehensive usage tracking

    def get_all_agents_current_usage(self) -> dict[str, dict[str, Any]]:
        """Get current usage for all agents in the group."""
        all_usage = {}
        for agent in self.groupchat.agents:
            all_usage[agent.name] = self._get_agent_current_usage(agent)
        return all_usage

    def get_group_usage_summary(self) -> dict[str, Any]:
        """Get aggregated usage summary for the entire group."""
        all_usage = self.get_all_agents_current_usage()

        total_summary = {
            "total_prompt_tokens": 0,
            "total_completion_tokens": 0,
            "total_tokens": 0,
            "total_cost": 0.0,
            "agents_count": len(all_usage),
            "models_used": set(),
            "per_agent": all_usage,
        }

        for agent_name, usage in all_usage.items():
            total_summary["total_prompt_tokens"] += usage["prompt_tokens"]
            total_summary["total_completion_tokens"] += usage["completion_tokens"]
            total_summary["total_tokens"] += usage["total_tokens"]
            total_summary["total_cost"] += usage["cost"]
            if usage["model"] != "unknown":
                total_summary["models_used"].add(usage["model"])

        total_summary["models_used"] = list(total_summary["models_used"])
        return total_summary

    def reset_usage_tracking(self):
        """Reset usage tracking (useful for starting fresh tracking mid-conversation)."""
        for agent in self.groupchat.agents:
            current_usage = self._get_agent_current_usage(agent)
            self._agent_previous_usage[agent.name] = current_usage.copy()


class CustomUserProxyAgent(UserProxyAgent):
    """Custom user proxy agent with WebSocket input support."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def set_input_function(self, input_function):
        """Set the custom input function for WebSocket communication."""
        self.input_function = input_function
        return self.input_function

    def get_human_input(self, prompt: str) -> str:
        """Override the default input method to use websocket."""
        print("🔄 Waiting for user input via websocket...")

        # Send input request to websocket client
        # self._send_input_request(prompt)

        # Wait for response from websocket
        return super().get_human_input(prompt)

    async def a_get_human_input(self, prompt: str) -> str:
        """Asynchronously get human input via WebSocket."""
        print("🔁 Custom logic before input...")

        # Safely call super, assuming you have registered an async input
        # result = await super().a_get_human_input(prompt)
        prompt = json.dumps({"agent": self.name, "prompt": prompt})
        return await self.input_function(prompt)

        # print(f"✅ Got input: {result}")
        # return await aioconsole.ainput(prompt)


SKIPPED = "The user skipped the questions. Proceed with the stated assumptions and sensible defaults; do not ask again."


class FormProxyAgent(CustomUserProxyAgent):
    """User proxy that shows the clarifier's questions as a form card and returns the answers.

    The card is the same ``decision_card`` message the personas use, so the
    frontend renders it with the other cards, and the answer is logged and
    written to the chat history like every other decision.
    """

    def __init__(self, *args, chat_id: str = "", omni=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.chat_id = chat_id
        self.omni = omni

    @staticmethod
    def _latest_form(messages: list[dict]) -> dict | None:
        for message in reversed(messages):
            if message.get("name") in ("clarifier", "manual_verification"):
                try:
                    data = json.loads(message.get("content") or "{}")
                except (TypeError, ValueError):
                    return None
                return data if isinstance(data, dict) else None
        return None

    @staticmethod
    def _answers_text(form: dict, reply: Any) -> tuple[str, str]:
        """Render the reply as text for the agents, plus a one-line summary."""
        questions = form.get("questions") or []
        if isinstance(reply, str):
            return f"User verification answer: {reply}", reply[:80]
        if not isinstance(reply, dict) or reply.get("action") in ("reject", "skip"):
            return SKIPPED, "skipped"
        values = reply.get("values") or {}
        lines = []
        for q in questions:
            value = values.get(q.get("id"))
            if value in (None, "", []):
                value = q.get("default")
            if isinstance(value, list):
                labels = {o.get("value"): o.get("label") for o in q.get("options") or []}
                value = ", ".join(str(labels.get(v, v)) for v in value)
            elif q.get("options"):
                labels = {o.get("value"): o.get("label") for o in q.get("options") or []}
                value = labels.get(value, value)
            lines.append(f"- {q.get('label')}: {value if value not in (None, '') else '(not provided)'}")
        note = reply.get("text") or reply.get("note")
        text = "User verification answers:\n" + "\n".join(lines)
        if note:
            text += f"\nAdditional note from the user: {note}"
        if form.get("assumptions"):
            text += "\nAssumptions the user saw and accepted:\n" + "\n".join(f"- {a}" for a in form["assumptions"])
        return text, f"answered {len(lines)} question{'s' if len(lines) != 1 else ''}"

    async def a_get_human_input(self, prompt: str) -> str:
        messages = self.omni.groupchat.messages if self.omni is not None else []
        form = self._latest_form(messages)
        if not form or not form.get("questions"):
            return await super().a_get_human_input(prompt)
        asked_by = next((m.get("name") for m in reversed(messages) if m.get("name") in ("clarifier", "manual_verification")), "clarifier")
        card = {
            "card": "form",
            "title": "A few details before I plan" if asked_by == "clarifier" else "Your call",
            "message": form.get("intro") or "",
            "questions": form.get("questions") or [],
            "assumptions": form.get("assumptions") or [],
            "asked_by": asked_by,
            "task_id": getattr(self.omni, "task_id", None),
        }
        decision_id = await log_decision(self.chat_id, card["task_id"], "user_verification", "form", card)
        card["id"] = decision_id
        input_function = getattr(self, "input_function", None) or getattr(self.omni, "input_function", None)
        if input_function is None:
            raise RuntimeError("user_form has no input function; the WebSocket route must call omni.set_input_function")
        reply = await input_function(json.dumps(card), input_type="decision_card", source="user_verification")
        text, summary = self._answers_text(form, reply)
        await answer_decision(decision_id, reply if isinstance(reply, dict | str) else str(reply))
        try:
            await update_chat_history(
                self.chat_id,
                {
                    "role": "assistant",
                    "name": "user_verification",
                    "raw_message": {"type": "decision_card", **card, "answered": True, "answer": reply, "answer_summary": summary},
                    "usage": {},
                    "task_id": card["task_id"],
                },
                settings.OMNI_COLLECTION,
            )
        except Exception as e:
            logger.warning(f"Could not persist verification card: {e}")
        return text


class Omni:
    """Main Omni orchestrator for multi-agent task execution and capability management."""

    def __init__(
        self,
        chat_id: str,
        user_id: str = "default_user",
        chat_dir: str = os.path.join(settings.ROOT_DIR, "daxagent"),
    ):
        self.user_id = user_id
        self.chat_id = chat_id
        self.chat_dir = chat_dir
        self.cancellation_token = None
        self.task_id = None
        self.llm_config = LLMConfigManager.get_config("gpt_4_1_mini")
        self.groupchat_config = (
            GroupchatConfigurationManager.get_instance().get_groupchat_configuration(
                "omni"
            )
        )

        # Memory Configuration
        self.memory = OmniMemory()

        self.capability_manager = CapabilityManager(
            user_id=self.user_id,
            chat_id=self.chat_id,
            chat_dir=self.chat_dir,
            memory=self.memory,
        )

        self._composio_initialized = False
        self.agents = self.get_agents()
        self._register_functions()
        self.get_chat_manager()

    @classmethod
    async def create(
        cls,
        chat_id: str,
        user_id: str = "default_user",
        chat_dir: str = None,
    ) -> "Omni":
        """Async factory method that initializes Omni with Composio tools.

        Args:
            chat_id: Unique chat session identifier.
            user_id: User identifier for Composio tool access.
            chat_dir: Directory for chat files.

        Returns:
            Fully initialized Omni instance with Composio tools registered.
        """
        if chat_dir is None:
            chat_dir = os.path.join(settings.ROOT_DIR, "daxagent")
        instance = cls(chat_id=chat_id, user_id=user_id, chat_dir=chat_dir)
        await instance.initialize_composio_tools_async()
        await instance.register_mcp_specialists()
        await instance.refresh_user_context()
        return instance

    def _persona_function(self, persona_name: str):
        """A callable the caller agent can invoke to run one persona."""

        async def persona_wrapper(
            query: Annotated[
                str,
                "The complete task for this agent: goal, inputs (ids, dates, artifact ids), constraints and the output wanted",
            ]
        ) -> Annotated[str, "The agent's summary and artifact ids"]:
            return await self.run_persona_capability(persona_name, query)

        persona_wrapper.__name__ = persona_name
        return persona_wrapper

    async def register_mcp_specialists(self) -> int:
        """Register one capability per connected-app specialist and tell the planner about them."""
        try:
            personas = await specialists.refresh()
        except Exception as e:
            logger.warning(f"Specialists unavailable: {e}")
            return 0
        if not personas:
            return 0
        for name, persona in personas.items():
            autogen.agentchat.register_function(
                self._persona_function(name),
                caller=self.agent_caller,
                executor=self.agent_executor,
                name=name,
                description=persona.description,
            )
        logger.info(f"Registered {len(personas)} MCP specialist(s): {', '.join(personas)}")
        return len(personas)

    async def initialize_composio_tools_async(self) -> int:
        """Initialize Composio tools and register them with agent_caller/agent_executor.

        Returns:
            Number of Composio tools registered.
        """
        if self._composio_initialized:
            logger.debug(f"Omni {self.chat_id} Composio already initialized")
            return 0

        try:
            composio_tool_manager = ComposioToolManager(
                user_id=self.user_id,
                chat_agent=self.agent_caller,
                agent_executor=self.agent_executor,
            )
            tool_count = await composio_tool_manager.register_all_tools_async()
            self._composio_initialized = True
            logger.info(
                f"Registered {tool_count} Composio tools for omni session {self.chat_id}"
            )

            # Update planner with connected/available app info
            try:
                apps_info = await composio_tool_manager.get_user_connected_apps_async(self.user_id)
                connected_apps = apps_info.get("app_names", [])

                app_capabilities = {
                    "GMAIL": "email — send, read, search, reply, forward emails",
                    "GOOGLECALENDAR": "calendar — create events, check schedule, manage calendar",
                    "GOOGLESHEETS": "spreadsheets — create, read, update spreadsheets",
                    "GOOGLEDRIVE": "file storage — upload, download, share files",
                    "SLACK": "messaging — send messages, manage channels",
                    "ZOOM": "meetings — schedule and manage video meetings",
                    "DISCORD": "chat — send messages, manage servers",
                    "OUTLOOK": "email — Microsoft email and calendar",
                    "ONEDRIVE": "storage — Microsoft cloud file storage",
                    "TEAMS": "collaboration — Microsoft Teams chat and meetings",
                    "GITHUB": "code — manage repos, issues, pull requests",
                    "GITLAB": "devops — code repos and CI/CD",
                    "LINEAR": "issues — create and manage issues/projects",
                    "JIRA": "projects — agile project and issue tracking",
                    "SALESFORCE": "CRM — sales and customer management",
                    "HUBSPOT": "CRM — marketing and sales automation",
                    "PIPEDRIVE": "sales — pipeline and deal management",
                    "ZOHOCRM": "CRM — customer relationship management",
                    "APOLLO": "sales intelligence — find prospects, contacts and company data, run outreach sequences",
                    "ZOOMINFO": "sales intelligence — B2B contact and company data, enrichment and prospecting",
                    "NOTION": "docs — create/edit pages and databases",
                    "AIRTABLE": "data — database and spreadsheet hybrid",
                    "MONDAY": "work — project management and workflows",
                    "CANVA": "design — visual content creation",
                    "TWITTER": "social — post tweets, manage account",
                    "LINKEDIN": "professional — networking and content",
                    "FACEBOOK": "social — page management and posts",
                    "WHATSAPP": "messaging — business communication",
                    "INSTANTLY": "outreach — email outreach automation",
                    "ZENDESK": "support — customer support and ticketing",
                    "PAGERDUTY": "ops — incident management and on-call",
                    "POSTHOG": "analytics — product analytics",
                    "SNOWFLAKE": "data — cloud data warehouse",
                    "RAMP": "finance — corporate card and expenses",
                    "STRAVA": "fitness — activity tracking",
                }
                all_apps = list(app_capabilities.keys())
                not_connected = [a for a in all_apps if a not in connected_apps]

                app_context = "\n\n## App Integration Status\n"

                if connected_apps:
                    app_context += "### Connected Apps (tools available for agent_caller):\n"
                    for app in connected_apps:
                        desc = app_capabilities.get(app, f"{app.lower()} — connected")
                        app_context += f"- **{app}**: {desc}\n"
                    app_context += (
                        "\nFor tasks involving connected apps, use the corresponding capability name "
                        "(e.g., 'email_sender' for Gmail, 'google_calendar' for Google Calendar).\n"
                    )

                if not_connected:
                    app_context += "\n### Available to Connect (NOT yet connected):\n"
                    for app in not_connected:
                        desc = app_capabilities.get(app, f"{app.lower()}")
                        app_context += f"- **{app}**: {desc}\n"

                app_context += (
                    "\nCRITICAL RULE: If a user's task requires an app that is NOT connected, "
                    "you MUST use 'manual_verification' capability to tell the user: "
                    "\"This task requires [App Name] to be connected. Please connect it in Settings > Connections, "
                    "then try again.\" Do NOT attempt the task with any workaround.\n"
                )

                self._apps_context = app_context
                logger.info(f"Updated planner: {len(connected_apps)} connected, {len(not_connected)} available to connect")
            except Exception as e:
                logger.warning(f"Failed to update planner with app info: {e}")

            try:
                # Guardrails go to conversation_agent: it speaks to the user, whereas
                # agent_caller only emits tool calls and could not ask for confirmation.
                tool_count += await register_mcp_tools(
                    self.agent_caller, self.agent_executor, self.conversation_agent,
                                    only=reserved_servers(), mode="task",
                )
            except Exception as e:
                logger.warning(f"MCP tool registration failed: {e}")

            return tool_count
        except Exception as e:
            logger.warning(f"Composio tool init failed (offline?): {e}")
            return 0

    async def connect_app(self, app_name: str) -> dict:
        """Connect a Composio app and register its tools in the live session.

        Args:
            app_name: App name to connect (e.g., 'GMAIL', 'SLACK').

        Returns:
            Dict with success status, app name, and tool count.
        """
        logger.info(f"Connecting app {app_name} for omni session {self.chat_id}")
        composio_tool_manager = ComposioToolManager(
            user_id=self.user_id,
            chat_agent=self.agent_caller,
            agent_executor=self.agent_executor,
        )
        return await composio_tool_manager.connect_app_async(app_name)

    async def disconnect_app(self, app_name: str) -> dict:
        """Disconnect a Composio app and remove its tools from cache.

        Args:
            app_name: App name to disconnect (e.g., 'GMAIL', 'SLACK').

        Returns:
            Dict with success status and removed tool count.
        """
        logger.info(f"Disconnecting app {app_name} for omni session {self.chat_id}")
        composio_tool_manager = ComposioToolManager(
            user_id=self.user_id,
            chat_agent=self.agent_caller,
            agent_executor=self.agent_executor,
        )
        return await composio_tool_manager.disconnect_app_async(app_name)

    def set_input_function(self, input_function):
        """Set the custom input function for user interactions."""
        self.input_function = input_function
        if getattr(self, "user_form", None) is not None:
            self.user_form.set_input_function(input_function)
        return self.input_function

    def _set_cancellation_token(self, cancellation_token):
        self.cancellation_token = cancellation_token

    async def refresh_user_context(self) -> None:
        """Rebuild every step's prompt from the user's settings as they are now (Settings > Orchestrator, Agents and
        Memory), and register the user's own agents. Runs before every task."""
        try:
            cards = await orchestrator.user_cards(self.user_id)
            listed = orchestrator.render(cards) + orchestrator.specialists_block()
            notes = await prefs.memory_notes(self.user_id) + await prefs.off_agents_notes(self.user_id)
            mine = await orchestrator.stage_prompts(self.user_id)  # each step's prompt, as the user has it
            self.judge_question.update_system_message(mine["judge"])
            self.conversation_agent.update_system_message(mine["conversation"])
            self.clarifier.update_system_message(orchestrator.with_cards(mine["clarifier"], listed) + notes)
            self.planner.update_system_message(await orchestrator.planner_prompt(self.user_id) + getattr(self, "_apps_context", ""))
            self.agent_aligner.update_system_message(mine["aligner"])
            self.agent_router.update_system_message(orchestrator.with_cards(mine["router"], listed))
            self.manual_verification.update_system_message(mine["verification"])
            self.process_completion.update_system_message(mine["wrap_up"])
            for c in cards:
                if c["kind"] == "custom" and c["enabled"]:
                    autogen.agentchat.register_function(  # registering a name again replaces it
                        self._persona_function(c["name"]), caller=self.agent_caller, executor=self.agent_executor,
                        name=c["name"], description=f"{c['display_name']} (the user's own agent). {c['call_when']}"[:1000],
                    )
        except Exception as e:
            logger.warning(f"Planner prompts not refreshed: {e}")

    def set_task_id(self, task_id):
        """Set the current task ID for tracking."""
        self.task_id = task_id
        self.manager.task_id = task_id

    def _check_cancellation(self):
        """Check if operations should be cancelled."""
        if self.cancellation_token and self.cancellation_token.is_cancelled():
            raise asyncio.CancelledError(
                f"OMNI operation cancelled for session {self.chat_id}"
            )

    def get_last_call_id(self):
        """Get the last tool call IDs from the agent caller."""
        last_speaker = self.groupchat.messages[-1]
        if last_speaker.get("name") == "agent_caller":
            tool_calls = last_speaker.get("tool_calls")
            result = {}

            for index, item in enumerate(tool_calls):
                function_name = item["function"]["name"]
                call_info = {
                    "id": item["id"],
                    "index": index,
                    "arguments": item["function"].get("arguments", {}),
                }

                if function_name in result:
                    result[function_name].append(call_info)
                else:
                    result[function_name] = [call_info]

            return result
        return None

    def find_call_id(self, capability_name: str, query: str) -> str | None:
        """Find matching call ID for any capability.

        Args:
            capability_name: Name of the capability (e.g., "email_sender", "file_finder")
            query: The query string to match against call arguments

        Returns:
            Optional[str]: The matching call ID if found, None otherwise
        """
        try:
            call_ids = self.get_last_call_id().get(capability_name, [])

            for item in call_ids:
                arguments_str = item.get("arguments", "")

                # Try to parse the arguments as JSON first
                try:
                    arguments_dict = json.loads(arguments_str)
                    # Check if query matches any value in the arguments dict
                    if isinstance(arguments_dict, dict):
                        for key, value in arguments_dict.items():
                            if isinstance(value, str) and query in value:
                                return item["id"]
                    elif isinstance(arguments_dict, str) and query in arguments_dict:
                        return item["id"]
                except json.JSONDecodeError:
                    # If not valid JSON, fall back to string comparison
                    if query in arguments_str:
                        return item["id"]

            return None

        except Exception as e:
            logger.error(f"Error finding {capability_name} call ID: {e}")
            return None


    async def get_web_browser(
        self,
        query: Annotated[
            str,
            "The complete search query with all the details like subject relationship with the message",
        ],
    ) -> Annotated[
        str,
        "The complete search query with all the details like subject relationship with the message",
    ]:
        """Execute the web browser capability."""
        # execute_capability refuses an empty call_id, and find_call_id returns None
        # whenever the recorded tool arguments don't contain the query verbatim.
        call_id = self.find_call_id("web_browser", query) or str(uuid.uuid4())
        self.web_browser_config = CapabilityConfig(
            name=CapabilityType.BROWSER_MANAGER.value,
            collection=settings.BROWSER_COLLECTION,
            manager_class=BrowserManager,
            completion_agent_name="process_completion",
            task_id=self.task_id,
            cancellation_token=self.cancellation_token,
            use_chat_messages=False,
            manager_kwargs={"input_function": self.input_function},
        )
        return await self.capability_manager.execute_capability(
            query, self.web_browser_config, call_id
        )


    async def run_persona_capability(self, name: str, query: str):
        """Run one persona (lead_finder, buyer_finder, ...) on the agent runtime.

        Personas are Claude Agent SDK sessions rather than AutoGen groupchats, so
        they are driven directly instead of through CapabilityManager.
        """
        cm = self.capability_manager
        if not await prefs.agent_enabled(cm.user_id, name):
            return f"{name} is switched off in Settings > Agents, so it did not run. Finish without it, or ask the user to switch it on."
        persona = None
        if name.startswith("custom_"):
            persona = await orchestrator.custom_persona(cm.user_id, name)
            if persona is None:
                return f"{name} was deleted in Settings > Agents, so it did not run. Finish without it."
        websocket_manager = await get_websocket_manager()
        return await run_persona(
            persona or name,
            query,
            user_id=cm.user_id,
            chat_id=cm.chat_id,
            chat_dir=cm.chat_dir,
            omni_memory=cm.memory,
            websocket_manager=websocket_manager,
            call_id=self.find_call_id(name, query) or str(uuid.uuid4()),
            task_id=self.task_id,
            cancellation_token=self.cancellation_token,
        )

    async def get_software_developer(self, query: str):
        """Execute the software developer persona."""
        return await self.run_persona_capability("software_developer", query)

    def _register_functions(self):

        # Wrapper functions before registring to agents


        async def email_sender_wrapper(
            query: Annotated[str, "The complete user query for email operations"]
        ):
            """Email capability via Composio Gmail. Executes directly or returns connect prompt."""
            assigned = self._assigned(self.groupchat.messages)
            if "email_sender" not in assigned:
                # It sends at once, with no approval: the caller once picked it for Campaign Builder's step (four campaign
                # emails marked "do not send"), and only an unparseable recipient stopped it.
                return json.dumps({"error": f"Not sent: this step is for {', '.join(sorted(assigned)) or 'another agent'}. Call that "
                                            "agent with the same query. Campaign emails are drafted and sent only by outreach."})
            try:
                from composio import Composio

                composio_api_key = LLMConfigManager.get_config("composio_api_key")
                api_key = composio_api_key.get("config_list", [])[0].get("api_key")
                if not api_key:
                    return json.dumps({
                        "error": "Composio API key not set. Please set it in Settings.",
                        "action_required": "set_api_key",
                    })

                composio_client = Composio(api_key=api_key)

                # Verify active Gmail connection exists
                connections = composio_client.connected_accounts.list(user_ids=[self.user_id])
                gmail_active = any(
                    c.toolkit and c.toolkit.slug.lower() == "gmail" and c.status == "ACTIVE"
                    for c in connections.items
                )
                if not gmail_active:
                    return json.dumps({
                        "error": "Gmail is not connected. Please connect Gmail via Composio first.",
                        "action_required": "connect_app",
                        "app": "GMAIL",
                        "instructions": "Use the sidebar to connect Gmail, or send: {\"type\": \"connect_app\", \"app\": \"GMAIL\"}",
                    })

                # Use LLM to extract email fields from the query
                import openai as _openai
                oai_key = getattr(settings, "OPENAI_API_KEY", None)
                if not oai_key:
                    return json.dumps({"error": "OpenAI API key not set, needed to parse email query."})

                oai = _openai.OpenAI(api_key=oai_key)
                extraction = oai.chat.completions.create(
                    model="gpt-4.1-mini",
                    response_format={"type": "json_object"},
                    messages=[
                        {"role": "system", "content": "Extract email fields from the user query. Return JSON with: recipient_email, subject, body. If not specified, use reasonable defaults. Body should be plain text."},
                        {"role": "user", "content": query},
                    ],
                )
                email_fields = json.loads(extraction.choices[0].message.content)
                logger.info(f"Extracted email fields: {email_fields}")
                to = str(email_fields.get("recipient_email") or "").strip()
                if not to:
                    return json.dumps({"error": "Not sent: the task names no single recipient email address.", "query": query})
                # The same send card Outreach raises: the user (or an MCP caller's grants) approves every email that leaves
                from src.agent_runtime.decisions import DecisionCards

                cards = DecisionCards(await get_websocket_manager(), self.chat_id, "email_sender", task_id=self.task_id)
                cards.persist = lambda payload: update_chat_history(self.chat_id, {"role": "assistant", "name": "email_sender", "raw_message": payload,
                                                                                    "usage": {}, "task_id": self.task_id}, settings.OMNI_COLLECTION)
                decision = await cards.confirm_send(tool="GMAIL_SEND_EMAIL", server="composio", channel="email", recipients=[to],
                                                    subject=str(email_fields.get("subject") or ""), body_preview=str(email_fields.get("body") or ""),
                                                    detail="One-off email")
                if not decision.approved:
                    return json.dumps({"status": "not_sent", "message": f"The user did not approve this email. They said: {decision.suggestion}"
                                       if decision.suggestion else "The user declined this email; nothing was sent."})

                result = composio_client.tools.execute(
                    slug="GMAIL_SEND_EMAIL",
                    user_id=self.user_id,
                    arguments={
                        "recipient_email": to,
                        "subject": email_fields.get("subject", "No Subject"),
                        "body": email_fields.get("body", ""),
                        "user_id": "me",
                    },
                    dangerously_skip_version_check=True,
                )
                logger.info(f"GMAIL_SEND_EMAIL result: {result}")
                if isinstance(result, dict) and not result.get("successful", True):
                    return json.dumps({"error": f"Not sent: {result.get('error')}", "query": query})
                return json.dumps({
                    "status": "sent",
                    "message": f"Email sent to {email_fields.get('recipient_email', '')}",
                    "subject": email_fields.get("subject", ""),
                    "result": str(result)[:500],
                })
            except Exception as e:
                logger.error(f"Email send via Composio failed: {e}")
                return json.dumps({
                    "error": f"Failed to send email: {str(e)}",
                    "query": query,
                })

        autogen.agentchat.register_function(
            email_sender_wrapper,
            caller=self.agent_caller,
            executor=self.agent_executor,
            name="email_sender",
            description=email_manager_description,
        )

        # Not offered in tasks (2026-10-06): python_coder, web_browser and software_developer
        # (Growth Engineer). get_python_coder(), get_web_browser() and get_software_developer()
        # remain to re-enable them; the personas still answer older chats that used them.
        # ml_engineer (Data Analyst) was brought back on 2026-10-14 to work on attached files.

        # Personas on the agent runtime. Each is one function the caller can invoke;
        # the persona asks the user for approvals and inputs through decision cards.
        persona_descriptions = {
            "user_context": USER_CONTEXT_DESCRIPTION,
        "ml_engineer": ML_ENGINEER_DESCRIPTION,
            "lead_finder": LEAD_FINDER_DESCRIPTION,
            "buyer_finder": BUYER_FINDER_DESCRIPTION,
            "contact_enricher": CONTACT_ENRICHER_DESCRIPTION,
            "campaign_strategizer": CAMPAIGN_STRATEGIZER_DESCRIPTION,
            "campaign_builder": CAMPAIGN_BUILDER_DESCRIPTION,
            "outreach": OUTREACH_DESCRIPTION,
            "inbox_agent": INBOX_AGENT_DESCRIPTION,
        }

        def _make_persona_wrapper(persona_name: str):
            async def persona_wrapper(
                query: Annotated[
                    str,
                    "The complete task for this persona: goal, inputs (artifact ids, files), constraints and the output wanted",
                ]
            ) -> Annotated[str, "The persona's summary and artifact ids"]:
                return await self.run_persona_capability(persona_name, query)

            persona_wrapper.__name__ = persona_name
            return persona_wrapper

        for persona_name, description in persona_descriptions.items():
            if persona_name not in PERSONAS:
                continue
            autogen.agentchat.register_function(
                _make_persona_wrapper(persona_name),
                caller=self.agent_caller,
                executor=self.agent_executor,
                name=persona_name,
                description=description,
            )

    def get_judge_question(self):
        """Create and configure the question judge agent."""
        llm_config_name = (
            self.groupchat_config.get_agent_config("judge_question").llm_config
            or "default"
        )
        llm_config_judge_question = _steady(LLMConfigManager.get_config(llm_config_name))
        llm_config_judge_question["response_format"] = QuestionClassification
        return autogen.AssistantAgent(
            name="judge_question",
            llm_config=llm_config_judge_question,
            system_message=prompts.judge_question,  # update the prompt and json output format to judge question and add to speaker selection and all the agents list
        )

    def get_conversation_agent(self):
        """Create and configure the conversation agent."""
        llm_config_name = (
            self.groupchat_config.get_agent_config("conversation_agent").llm_config
            or "default"
        )
        llm_conversation_agent = LLMConfigManager.get_config(llm_config_name)
        return autogen.AssistantAgent(
            name="conversation_agent",
            llm_config=llm_conversation_agent,
            system_message=prompts.conversation,  # update the prompt and json output format to judge question
        )

    def get_planner(self):
        """Create and configure the planner agent."""
        llm_config_name = (
            self.groupchat_config.get_agent_config("conversation_agent").llm_config
            or "default"
        )
        llm_planner_agent = _steady(LLMConfigManager.get_config(llm_config_name))
        llm_planner_agent["response_format"] = PlannerResponse
        return autogen.AssistantAgent(
            name="planner_agent",
            llm_config=llm_planner_agent,
            system_message=Template(orchestrator.PLANNER_CORE).safe_substitute(today_date=today_date)
            + "\n\n" + orchestrator.render(orchestrator.card_list([], {})),
        )

    def get_user_acceptance(self):
        """Create and configure the user acceptance agent."""
        return CustomUserProxyAgent(
            name="get_user_acceptance",
            # default_auto_reply="Awaiting for manual verification",
            human_input_mode="ALWAYS",
            code_execution_config=False,
            # system_message=prompts.manual_verification,
        )

    def get_agent_aligner(self):
        """Create and configure the agent aligner."""
        llm_config_name = (
            self.groupchat_config.get_agent_config("agent_aligner").llm_config
            or "default"
        )
        llm_agent_aligner = _steady(LLMConfigManager.get_config(llm_config_name))
        llm_agent_aligner["response_format"] = AgentSelectionResponse
        return autogen.AssistantAgent(
            name="agent_aligner",
            llm_config=llm_agent_aligner,
            description="This agent will align the whole process and will share which agent will work next. ",
            system_message=prompts.agent_aligner,
        )

    def get_agent_router(self):
        """Create and configure the agent router."""
        llm_config_name = (
            self.groupchat_config.get_agent_config("agent_router").llm_config
            or "default"
        )
        llm_agent_router = _steady(LLMConfigManager.get_config(llm_config_name))
        llm_agent_router["response_format"] = CapabilityRoutingResponse
        return autogen.AssistantAgent(
            name="agent_router",
            llm_config=llm_agent_router,
            description="""From the initial information route to the capability which will solve the user's question.""",
            system_message=prompts.agent_router.replace(orchestrator.AGENTS_SLOT, orchestrator.render(orchestrator.card_list([], {}))),
        )

    def get_agent_caller(self):
        """Create and configure the agent caller."""
        agent_config = self.groupchat_config.get_agent_config("agent_caller")
        llm_config_name = agent_config.llm_config or "default"
        llm_config_caller = LLMConfigManager.get_config(llm_config_name)
        # llm_config_caller["config_list"][0]["tool_choice"] = {"type": "any"}
        if agent_config.custom_properties.get("tool_choice"):
            llm_config_caller["config_list"][0]["tool_choice"] = (
                agent_config.custom_properties.get("tool_choice")
            )
        caller = autogen.AssistantAgent(
            name="agent_caller",
            llm_config=llm_config_caller,
            # system_message=prompts.agent_caller,
        )
        caller.register_reply([autogen.Agent, None], self._call_assigned_agent, position=0)
        return caller

    def get_agent_executor(self):
        """Create and configure the agent executor."""
        return UserProxyAgent(
            "agent_executor",
            human_input_mode="NEVER",
            # description="""This agent will execute the function which are group chat on their own""",
            code_execution_config=False,
            system_message=prompts.agent_executor.format(today_date=today_date),
            # is_termination_msg=lambda x: x.get("content", "").find("TERMINATE") >= 0,
        )

    def get_problem_status_checker(self):
        """Create and configure the problem status checker agent."""
        llm_config_name = (
            self.groupchat_config.get_agent_config("problem_status_checker").llm_config
            or "default"
        )
        llm_problem_status_checker = LLMConfigManager.get_config(llm_config_name)
        return autogen.AssistantAgent(
            name="problem_status_checker",
            llm_config=llm_problem_status_checker,
            description="""call this agent to check if the Task specified by the user has been completed""",
            system_message=prompts.prob_status_checker,
        )

    def _llm_config_for(self, agent_name: str, fallback: str = "gpt_4_1_mini"):
        try:
            name = self.groupchat_config.get_agent_config(agent_name).llm_config or fallback
        except Exception:
            name = fallback
        return LLMConfigManager.get_config(name)

    def get_clarifier(self):
        """Create the intake agent that asks for missing inputs before planning."""
        llm_config = _steady(self._llm_config_for("clarifier"))
        llm_config["response_format"] = ClarifierResponse
        return autogen.AssistantAgent(
            name="clarifier",
            llm_config=llm_config,
            system_message=prompts.clarifier.replace(orchestrator.AGENTS_SLOT, orchestrator.render(orchestrator.card_list([], {}))),
        )

    def get_user_form(self):
        """Create the proxy that shows clarifier/verification questions as a form card."""
        return FormProxyAgent(
            name="user_form",
            human_input_mode="ALWAYS",
            code_execution_config=False,
            chat_id=self.chat_id,
            omni=self,
        )

    def get_manual_verification(self):
        """Create and configure the manual verification agent."""
        llm_config_name = (
            self.groupchat_config.get_agent_config("manual_verification").llm_config
            or "default"
        )
        llm_config_mini = LLMConfigManager.get_config(llm_config_name)
        llm_config_mini["response_format"] = ClarifierResponse
        return autogen.AssistantAgent(
            name="manual_verification",
            llm_config=llm_config_mini,
            system_message=prompts.manual_verification,
        )

    def get_user_input(self):
        """Create and configure the user input agent."""
        return CustomUserProxyAgent(
            name="user_input",
            default_auto_reply="Awaiting for manual verification",
            human_input_mode="ALWAYS",
            code_execution_config=False,
            system_message=prompts.manual_verification,
        )

    def get_process_completion(self):
        """Create and configure the process completion agent."""
        llm_config_name = (
            self.groupchat_config.get_agent_config(
                "process_completion_agent"
            ).llm_config
            or "default"
        )
        llm_process_completion_agent = LLMConfigManager.get_config(llm_config_name)
        return autogen.AssistantAgent(
            name="process_completion_agent",
            llm_config=llm_process_completion_agent,
            system_message=prompts.process_completion,
        )

    # A reply to the plan that only says yes; anything else is a change the planner works in.
    _APPROVAL = re.compile(r"^\s*(yes|yep|ok|okay|sure|proceed|continue|go ahead|approved?|looks good|lgtm)"
                           r"([\s,.!]+(yes|ok|okay|sure|looks good|go ahead|proceed|please|thanks))*[\s.!]*$", re.I)

    @classmethod
    def _is_approval(cls, content: Any) -> bool:
        return bool(cls._APPROVAL.match(str(content or "")))

    @staticmethod
    def _skipped_verification(messages: list) -> bool:
        """The user skipped a "Your call" form (manual_verification's) since their last request."""
        start = max((i for i, m in enumerate(messages) if m.get("name") == "chat_manager"), default=0)
        asker = None
        for m in messages[start:]:
            if m.get("name") in ("clarifier", "manual_verification"):
                asker = m.get("name")
            elif m.get("name") == "user_form" and asker == "manual_verification" and str(m.get("content") or "").startswith(SKIPPED):
                return True
        return False

    @staticmethod
    def _request_text(content: Any) -> str:
        """The text of a request: chat_manager's content is str({"task": ..., "files": ...})."""
        try:
            parsed = ast.literal_eval(str(content or ""))
        except (ValueError, SyntaxError):
            return str(content or "")
        return str(parsed.get("task") or "") if isinstance(parsed, dict) else str(content)

    @staticmethod
    def _assignments(messages: list) -> list[dict]:
        """The task assignments of the router's latest message."""
        for m in reversed(messages):
            if m.get("name") == "agent_router":
                try:
                    return [a for a in json.loads(m["content"]).get("task_assignments") or [] if isinstance(a, dict)]
                except (TypeError, ValueError, KeyError, AttributeError):
                    return []
        return []

    @staticmethod
    def _assigned(messages: list) -> set[str]:
        """The capabilities the router's latest assignment names."""
        return {str(a.get("capability")) for a in Omni._assignments(messages)}

    @staticmethod
    def _direct_calls(messages: list, tools: list) -> list | None:
        """The tool calls for the router's assignment just made, when every agent it names takes only the task
        (personas, specialists, email_sender); None leaves the pick to the caller model (an app tool's own fields)."""
        if not messages or messages[-1].get("name") != "agent_router":
            return None
        takes_task = {t["function"]["name"] for t in tools if set(t["function"].get("parameters", {}).get("properties") or {}) == {"query"}}
        tasks = Omni._assignments(messages)
        if not tasks or any(a.get("capability") not in takes_task or not a.get("task") for a in tasks):
            return None
        return [{"id": f"call_{uuid.uuid4().hex[:24]}", "type": "function",
                 "function": {"name": a["capability"], "arguments": json.dumps({"query": str(a["task"])})}} for a in tasks]

    def _call_assigned_agent(self, recipient, messages=None, sender=None, config=None):
        # The router already named the agent and wrote its task. Asking the model to pick again went wrong once a chat
        # carried ~180k tokens of history (6e0faa26): it called the wrong agent, or wrote "did not complete" and no call.
        calls = self._direct_calls(self.groupchat.messages, recipient.llm_config.get("tools") or [])
        return (True, {"role": "assistant", "content": None, "tool_calls": calls}) if calls else (False, None)

    @staticmethod
    def _caller_stopped_mid_plan(messages: list) -> bool:
        """The caller answered in prose (blocked, a detail missing, a step it did not run) while the plan has steps left."""
        if len(messages) < 2 or messages[-2].get("name") != "agent_caller":
            return False
        plan = next((m for m in reversed(messages) if m.get("name") == "planner_agent"), None)
        try:
            return json.loads(plan["content"]).get("overall_status") != "completed"
        except (TypeError, ValueError, KeyError, AttributeError):
            return False

    @staticmethod
    def _has_pending_plan(messages: list) -> bool:
        """Check whether an approved plan is still waiting to be executed.

        Scans backwards for the first meaningful marker:
        - process_completion_agent: the workflow already closed out, nothing pending
        - get_user_acceptance: the user approved a plan, keep looking for that plan
        - planner_agent: the plan itself; pending when it was approved and its
          overall_status is not "completed"

        Args:
            messages: Group chat messages, oldest first.

        Returns:
            True if an approved plan still has work left to do.
        """
        approved = False
        for msg in reversed(messages):
            name = msg.get("name")
            if name == "process_completion_agent":
                return False
            if name == "get_user_acceptance":
                approved = approved or Omni._is_approval(msg.get("content"))
            elif name == "planner_agent":
                try:
                    status = json.loads(msg.get("content") or "{}").get(
                        "overall_status"
                    )
                except (TypeError, ValueError):
                    return False
                return approved and status != "completed"
        return False

    # dynamic, query classification and agent selection  conditional chat routing for task agent and manual verification
    def custom_speaker_selection_func(self, last_speaker: Any, groupchat: Any) -> Any:
        """Select the next speaker based on conversation state and agent responses."""
        try:
            self._check_cancellation()

            messages = groupchat.messages
            try:
                if last_speaker.name in ["planner_agent"]:
                    status = json.loads(messages[-1]["content"]).get("overall_status")
                    if status == "completed":
                        return groupchat.agent_by_name("process_completion_agent")
            except Exception as e:
                logger.error(f"Error parsing planner_agent message: {e}")

            if len(messages) == 1:
                # judge a question and understand if the question is a task or  general conversation
                return groupchat.agent_by_name("judge_question")
            if last_speaker.name in ["judge_question"]:
                if "task_oriented" in messages[-1]["content"]:
                    # ask for missing inputs first; the planner runs after the answers
                    return groupchat.agent_by_name("clarifier")
                # if it is a general conversation then route to conversation agent
                if "conversation" in messages[-1]["content"]:
                    return groupchat.agent_by_name("conversation_agent")

            # Agent Aligner will align the process and will route to the next agent
            if last_speaker.name == "agent_aligner":
                if "agent_router" in messages[-1]["content"]:
                    return groupchat.agent_by_name("agent_router")
                elif "manual_verification" in messages[-1]["content"]:
                    return groupchat.agent_by_name("manual_verification")
                elif "process_completion" in messages[-1]["content"]:
                    return groupchat.agent_by_name("process_completion_agent")

            # clarifier: show the form when it has questions, otherwise plan straight away
            if last_speaker.name == "clarifier":
                try:
                    form = json.loads(messages[-1]["content"])
                except (TypeError, ValueError):
                    form = {}
                if form.get("needs_input") and form.get("questions"):
                    return groupchat.agent_by_name("user_form")
                return groupchat.agent_by_name("planner_agent")

            # the form's answers go to whoever asked: intake -> planner, mid-plan -> aligner
            if last_speaker.name == "user_form":
                asked_by = next((m.get("name") for m in reversed(messages[:-1]) if m.get("name") in ("clarifier", "manual_verification")), "clarifier")
                return groupchat.agent_by_name("planner_agent" if asked_by == "clarifier" else "agent_aligner")

            # inner loop planner agent will report back to aligner agent
            if last_speaker.name in ["planner_agent"]:
                if len(messages) >= 2 and messages[-2]["name"] in ("judge_question", "clarifier", "user_form", "get_user_acceptance"):
                    # prompt = json.dumps({"agent":"get_user_acceptance", "prompt":"Please confirm if you want to proceed with the plan generated by the planner agent."})
                    # answer = async_to_sync(self.input_function(prompt))
                    return groupchat.agent_by_name("get_user_acceptance")
                else:
                    return groupchat.agent_by_name("agent_aligner")

            # inner loop planner agent will report back to aligner agent
            if last_speaker.name in ["get_user_acceptance"]:
                if self._is_approval(messages[-1].get("content")):
                    return groupchat.agent_by_name("agent_aligner")
                return groupchat.agent_by_name("planner_agent")  # the user asked for changes: re-plan, then ask again
            # if last_speaker.name in ["user_input"]:
            #     return groupchat.agent_by_name("agent_aligner")

            # manual verification now produces a form; the user_form proxy shows it
            if last_speaker.name in ["manual_verification"]:
                try:
                    form = json.loads(messages[-1]["content"])
                except (TypeError, ValueError):
                    form = {}
                if form.get("questions"):
                    # asked again after a skip, the details it needs have no default: end with what is missing instead of
                    # re-asking (a caller that kept skipping got the same form 17 times in a minute)
                    if self._skipped_verification(messages[:-1]):
                        return groupchat.agent_by_name("process_completion_agent")
                    return groupchat.agent_by_name("user_form")
                return groupchat.agent_by_name("user_input")
            if last_speaker.name in ["user_input"]:
                return groupchat.agent_by_name("agent_aligner")

            # how the sequential processes will get called
            if last_speaker.name == "agent_router":
                # Nothing to run means an input is missing: ask through a form
                # instead of letting the caller write prose the user must parse.
                try:
                    routing = json.loads(messages[-1]["content"])
                except (TypeError, ValueError):
                    routing = {}
                assignments = routing.get("task_assignments") if isinstance(routing, dict) else None
                if not assignments or all(
                    str(a.get("capability", "")).lower() in ("manual_verification", "user_verification")
                    for a in assignments if isinstance(a, dict)
                ):
                    return groupchat.agent_by_name("manual_verification")
                return groupchat.agent_by_name("agent_caller")
            if last_speaker.name == "agent_caller":
                # If agent_caller made a tool call, route to executor
                if messages[-1].get("tool_calls"):
                    return groupchat.agent_by_name("agent_executor")
                # If agent_caller gave a text response (no tool call), route to conversation
                return groupchat.agent_by_name("conversation_agent")
            if last_speaker.name == "conversation_agent" and self._caller_stopped_mid_plan(messages):
                # Wait for the user's reply and carry on, instead of ending with the plan half done: over the MCP the
                # calling agent gets this as a question and can send the verified detail (a run ended "still pending").
                return groupchat.agent_by_name("user_input")
            if last_speaker.name == "agent_executor":
                return groupchat.agent_by_name("planner_agent")
            if last_speaker.name == "chat_manager":
                # A plan that was approved but never finished resumes on a short "ok" / "continue"; otherwise that is
                # classified as small talk and the accepted plan is never carried out. Anything longer is a new request:
                # resuming took it over (an outreach re-run on a stopped chat ended at once, its new task never read).
                if self._is_approval(self._request_text(messages[-1].get("content"))) and self._has_pending_plan(messages):
                    return groupchat.agent_by_name("agent_aligner")
                return groupchat.agent_by_name("judge_question")

            return None
        except asyncio.CancelledError:
            logger.info(f"Speaker selection cancelled for session {self.chat_id}")
            # Return process_completion to gracefully end the chat
            # return groupchat.agent_by_name("process_completion_agent")
            raise

    def get_agents(self):
        """Initialize and return all agents for the Omni workflow."""
        self.judge_question = self.get_judge_question()
        self.conversation_agent = self.get_conversation_agent()
        self.planner = self.get_planner()
        self.clarifier = self.get_clarifier()
        self.user_form = self.get_user_form()
        self.agent_aligner = self.get_agent_aligner()
        self.agent_router = self.get_agent_router()
        self.agent_caller = self.get_agent_caller()
        self.agent_executor = self.get_agent_executor()
        self.manual_verification = self.get_manual_verification()
        self.get_user_acceptance = self.get_user_acceptance()
        self.user_input = self.get_user_input()
        self.process_completion = self.get_process_completion()
        return [
            self.judge_question,
            self.conversation_agent,
            self.clarifier,
            self.user_form,
            self.planner,
            self.agent_aligner,
            self.agent_router,
            self.agent_caller,
            self.agent_executor,
            self.get_user_acceptance,
            self.manual_verification,
            self.user_input,
            self.process_completion,
        ]

    def get_chat_manager(self):
        """Create and configure the group chat manager."""
        self.groupchat = autogen.GroupChat(
            agents=self.agents,
            messages=[],
            speaker_selection_method=self.custom_speaker_selection_func,
            max_round=500,
        )
        self.manager = OmniGroupChatManager(
            groupchat=self.groupchat,
            memory=self.memory,
            llm_config=self.llm_config,
            human_input_mode="ALWAYS",
            chat_id=self.chat_id,
            task_id=self.task_id,
        )
        return self.manager, self.groupchat
