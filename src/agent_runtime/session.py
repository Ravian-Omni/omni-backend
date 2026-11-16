"""One persona run on the Claude Agent SDK, speaking the existing chat protocol.

``PersonaSession`` builds the SDK options for a persona (system prompt, tools,
in-process and remote MCP servers, permission gate), drives a
``ClaudeSDKClient``, and translates its message stream into the WebSocket
messages the frontend already renders (``message``, ``tool_use``,
``tool_result``, plus ``artifact`` and the decision cards). It exposes the
same surface the old LangGraph ``SoftwareDeveloper`` had, so the standalone
software-developer router and the orchestrator keep working unchanged.
"""

import ast
import asyncio
import json
import os
import shutil
import uuid
from typing import Any

from loguru import logger

from src.agent_runtime import leads, prefs
from src.agent_runtime.decisions import DecisionCards
from src.agent_runtime.personas import Persona, fill, get_persona
from src.agent_runtime.tools import ToolContext, build_server, full_name
from src.configs.datetime_utils import dt
from src.configs.settings import settings
from src.database import update_chat_history, update_chat_history_by_context
from src.managers.cancellation_token import CancellationToken
from src.agent_runtime.tools.context import server_of
from src.mcp_client import auth_headers, call_tool, is_connected, list_tools, options, server_names, server_url
from src.mcp_client.client import server_notes, warm
from src.mcp_client.classify import classify_tool
from src.mcp_client.config import personas_for
from src.database import load_mcp_tool_classes
from src.utilities.custom_manager import ChatContext
from src.utilities.storage import ensure_path

_RESULT_PREVIEW = 4000
_NOTE_INTRO = (
    "The user sent this while you were working. Take it into account now; "
    "if it changes the task, adjust, and say so in your reply:\n"
)


def _python_executable() -> str:
    try:
        from src.utilities.venv_config import AG2AIVirtualEnvContext

        return str(AG2AIVirtualEnvContext().python_executable)
    except Exception:
        return "python3"


def _result_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    parts = []
    for block in content:
        if isinstance(block, dict):
            if block.get("type") == "text":
                parts.append(block.get("text", ""))
            else:
                parts.append(json.dumps(block)[:500])
        else:
            parts.append(str(block))
    return "\n".join(parts)


def _attach(files: list, folder: str) -> list[str]:
    """Copy the files a message attached into the chat's files folder; return their paths there.

    Uploads from the web UI land in a shared uploads folder, so each chat keeps its own copy
    next to its other files. A path that cannot be read is passed through unchanged.
    """
    paths = []
    for f in files:
        src = str((f.get("filePath") or f.get("path")) if isinstance(f, dict) else f)
        dst = os.path.join(folder, os.path.basename(src))
        if os.path.isfile(src) and os.path.abspath(src) != os.path.abspath(dst):
            os.makedirs(folder, exist_ok=True)
            shutil.copy2(src, dst)
        paths.append(dst if os.path.isfile(dst) else src)
    return paths


def offered(persona: Persona, server: str) -> bool:
    """Whether a persona gets a remote server. A server's `personas` list names exactly the job personas that
    use it (reserved ones too, e.g. Data Axle for the three sales finders); without a list a reserved server
    goes to every job persona and any other belongs to its own specialist. Specialists and the chat assistant
    carry an explicit list of servers instead ("*" = all)."""
    from src.mcp_client.config import is_reserved

    if persona.mcp_servers is not None:
        return "*" in persona.mcp_servers or server in persona.mcp_servers
    allowed = personas_for(server)
    return persona.name in allowed if allowed is not None else is_reserved(server)


def _routed(server: str, tool: str, ctx: ToolContext):
    """Handler for an app tool served by the built-in server: calls the app over its kept-open connection."""

    async def handler(args: dict[str, Any]) -> dict[str, Any]:
        ctx.data_sources.add(server)
        try:
            text = await call_tool(server, tool, args)
            await leads.note_source(ctx.chat_id, server, text)  # Data Axle's own emails get the in-house check
            return {"content": [{"type": "text", "text": text}]}
        except Exception as e:
            return {"content": [{"type": "text", "text": f"{tool} failed: {e}"}], "is_error": True}

    return handler


class PersonaManager:
    """Compatibility wrapper: the WebSocket manager drives ``manager.a_initiate_chat``."""

    def __init__(self, session: "PersonaSession"):
        self.session = session
        self._messages: list[dict[str, Any]] = []

    async def a_initiate_chat(self, recipient=None, message: str = "", clear_history: bool = False, **_) -> str:
        task = message
        files: list = []
        if isinstance(message, str) and message.startswith("{"):
            try:
                parsed = ast.literal_eval(message)
                if isinstance(parsed, dict):
                    task = parsed.get("task") or ""
                    files = parsed.get("files") or []
            except (ValueError, SyntaxError):
                pass
        if files:
            listed = "\n".join(f"- {p}" for p in _attach(files, self.session.file_location))
            task = f"{task}\n\nFiles the user attached (under {self.session.file_location}):\n{listed}"
        return await self.session.chat(task)

    def resume(self, messages: list[dict[str, Any]]) -> tuple[Any, Any]:
        self._messages = messages or []
        self.session.load_history(self._messages)
        last = self._messages[-1] if self._messages else None
        return None, last


def _settings_version() -> tuple[int, int]:
    """Changes in Settings (memory, agent instructions, server switches); a change rebuilds the client."""
    from src.mcp_client.config import flags_version

    return prefs.version(), flags_version()


class PersonaSession:
    """Runs one persona for one chat."""

    def __init__(self, context: ChatContext, persona: str | Persona | None = None):
        self.context = context
        self.persona: Persona = persona if isinstance(persona, Persona) else get_persona(persona or context.capability_name)
        self.websocket_manager = (context.manager_kwargs or {}).get("websocket_manager")
        # When the orchestrator runs a persona, its output is also written into the
        # parent chat's raw history so the UI can rebuild it after a reload.
        self.mirror_collection: str | None = (context.manager_kwargs or {}).get("mirror_collection")
        self.cancellation_token: CancellationToken | None = context.cancellation_token
        self.task_id = context.task_id or str(uuid.uuid4())
        self.custom_instructions = ""
        self._history: list[dict[str, Any]] = []
        self._client = None
        self._client_lock = asyncio.Lock()
        self._tool_names: dict[str, str] = {}
        self._remote_tools: dict[str, list[dict[str, Any]]] = {}  # server -> tool schemas (OpenAI runner)
        self._stale = False  # a connection changed: rebuild the client (and its tool list) before the next turn
        self._notes_seen: list[str] = []  # user notes delivered during the current turn
        self._primed = False  # the current SDK client has seen this chat (else the history is replayed)
        self._warm_task: asyncio.Task | None = None
        self._usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "cost_usd": 0.0}
        self._run_start = dict(self._usage)  # the counter at the start of the current run (it runs on across a chat's turns)
        self._model = ""

        self.working_directory = ensure_path(os.path.join(context.chat_dir, "workspace"))
        self.file_location = ensure_path(os.path.join(context.chat_dir, "files"))
        self.artifacts_dir = ensure_path(os.path.join(context.chat_dir, "artifacts"))

        # Imported here: the software_developer package imports this module for its shim.
        from src.capabilities.software_developer.pty_terminal import PtyTerminalManager
        from src.capabilities.software_developer.tools import AsyncToolRegistry

        self.tool_registry = AsyncToolRegistry(
            working_directory=self.working_directory,
            session_id=context.chat_id,
            websocket_manager=self.websocket_manager,
        )
        self.terminal_manager = PtyTerminalManager(websocket_manager=self.websocket_manager)
        self.decisions = DecisionCards(
            self.websocket_manager, context.chat_id, self.persona.name,
            task_id=self.task_id, call_id=context.call_id, capability_id=context.capability_id,
        )
        self.tool_context = ToolContext(
            chat_id=context.chat_id, user_id=context.user_id, persona=self.persona.name,
            chat_dir=context.chat_dir, working_directory=self.working_directory,
            file_location=self.file_location, artifacts_dir=self.artifacts_dir,
            python_executable=_python_executable(), decisions=self.decisions, emit=self._emit_event,
            tool_registry=self.tool_registry, task_id=self.task_id, call_id=context.call_id,
            capability_id=context.capability_id,
        )
        self.decisions.persist = lambda payload: self._persist("assistant", self.persona.name, payload)
        self.manager = PersonaManager(self)
        logger.info(f"PersonaSession[{self.persona.name}] ready for chat {context.chat_id}")

    # ------------------------------------------------------------------ options
    async def _remote_servers(self) -> tuple[dict[str, Any], dict[str, str]]:
        """Remote MCP servers this persona may use, and their tools' classes."""
        servers: dict[str, Any] = {}
        classes: dict[str, str] = {}
        if not self.persona.remote_mcp:
            return servers, classes
        from src.mcp_client.config import in_mode, is_enabled

        mode = "chat" if self.persona.name == "assistant" else "task"  # chat mode runs only the assistant
        self._remote_tools = {}
        wanted = [name for name in server_names() if is_enabled(name) and in_mode(name, mode) and offered(self.persona, name)
                  and not options(name).get("guarded")]  # a guarded server's tools are DAXAGENT's own (tools/treg.py), never listed raw

        async def probe(name: str):
            if not await is_connected(name):
                return None
            try:
                return name, await auth_headers(name), await list_tools(name)
            except Exception as e:
                logger.warning(f"Skipping MCP server '{name}' for {self.persona.name}: {e}")
                return None

        for found in await asyncio.gather(*(probe(n) for n in wanted)):  # in parallel: each is a network round trip
            if not found:
                continue
            name, headers, tools = found
            servers[name] = {"type": "http", "url": server_url(name), **({"headers": headers} if headers else {})}
            self._remote_tools[name] = tools
            overrides = await load_mcp_tool_classes(name)
            for t in tools:
                classes[f"mcp__{name}__{t['name']}"] = classify_tool(
                    t["name"], t["description"], t.get("annotations"), overrides.get(t["name"])
                )
        return servers, classes

    def _routed_tools(self, remote_classes: dict[str, str]) -> tuple[list, dict[str, str]]:
        """App tools served through the built-in server, keeping each tool's read/spend/send class.

        The CLI then connects to no app server at start (that took ~4 s per session); the
        backend calls the apps over connections it keeps open.
        """
        from claude_agent_sdk import SdkMcpTool

        tools, classes = [], {}
        for server, schemas in self._remote_tools.items():
            warm(server)
            alias = server.removeprefix("composio-")
            for t in schemas:
                name = f"{alias}__{t['name']}"
                tools.append(SdkMcpTool(name=name, description=t["description"],
                                        input_schema=t["input_schema"] or {"type": "object", "properties": {}},
                                        handler=_routed(server, t["name"], self.tool_context)))
                classes[full_name(name)] = remote_classes.get(f"mcp__{server}__{t['name']}", "read")
        return tools, classes

    def _system_prompt(self, remote_notes: str) -> str:
        values = dict(
            working_directory=self.working_directory,
            file_location=self.file_location,
            artifacts_dir=self.artifacts_dir,
            python_executable=self.tool_context.python_executable,
            today=dt.now().strftime("%Y-%m-%d"),
            custom_instructions=self.custom_instructions,
        )
        own = getattr(self, "_own_prompt", "")  # the user's rewrite (Settings > Orchestrator), loaded before each build
        return (fill(own, values) if own else self.persona.system_prompt.format(**values)) + remote_notes

    async def _build_options(self):
        from claude_agent_sdk import ClaudeAgentOptions, HookMatcher

        self._built_for = _settings_version()
        remote, remote_classes = await self._remote_servers()
        routed, routed_classes = self._routed_tools(remote_classes)
        server, dax_names, dax_classes = build_server(self.tool_context, routed)
        dax_classes.update(routed_classes)  # spend/send app tools stay behind the approval gate
        self.tool_context.remote_tool_classes = routed_classes
        self._classes = dax_classes

        # Nothing is hidden: a hidden tool the model still calls ends in a hard denial mid-run.
        # Spend/send tools stay out of `allowed`, so every call goes through the approval gate.
        allowed = list(self.persona.builtin_tools)
        allowed += [full_name(n) for n in dax_names if dax_classes.get(full_name(n)) == "read"]

        notes = ""
        for name in remote:
            # persona_prompt_append: the server's rules written for agents that have approval cards
            note = options(name).get("persona_prompt_append") or options(name).get("system_prompt_append")
            if note:
                notes += note
            notes += server_notes(name)  # when to call it, as the server itself publishes on initialize()
        notes += await prefs.prompt_notes(self.context.user_id, self.persona.name)  # Settings > Memory and Agents
        self._own_prompt = await prefs.agent_prompt(self.context.user_id, self.persona.name)
        api_key = settings.ANTHROPIC_API_KEY or os.environ.get("ANTHROPIC_API_KEY", "")
        model = self._model = getattr(settings, "AGENT_MODEL", None) or "claude-haiku-4-5-20251001"
        self._budget = float(getattr(settings, "AGENT_MAX_BUDGET_USD", None) or self.persona.max_budget_usd or 0) or None
        opts = ClaudeAgentOptions(
            system_prompt=self._system_prompt(notes),
            tools=list(self.persona.builtin_tools),
            allowed_tools=allowed,
            mcp_servers={"daxagent": server},  # app tools are routed through it (see _routed_tools)
            strict_mcp_config=True,
            permission_mode="default",
            can_use_tool=self._permission_gate,
            hooks={  # user notes sent mid-run reach the agent at its next step
                "PostToolUse": [HookMatcher(hooks=[self._note_after_tool])],
                "Stop": [HookMatcher(hooks=[self._note_before_stop])],
            },
            cwd=self.working_directory,
            add_dirs=[self.file_location, self.artifacts_dir],
            env={"ANTHROPIC_API_KEY": api_key},
            setting_sources=[],
            model=model,
            max_turns=int(getattr(settings, "AGENT_MAX_TURNS", 0) or self.persona.max_turns),
        )
        effort = getattr(settings, "AGENT_EFFORT", None)
        if effort:
            opts.effort = effort
        budget = getattr(settings, "AGENT_MAX_BUDGET_USD", None) or self.persona.max_budget_usd
        if budget:
            opts.max_budget_usd = float(budget)
        return opts

    # ------------------------------------------------------------- permission
    def _class_of(self, tool_name: str) -> str:
        if tool_name in self._classes:
            return self._classes[tool_name]
        short = tool_name.split("__")[-1]
        for full, cls in self._classes.items():
            if full.split("__")[-1] == short:
                return cls
        return "read"

    async def _permission_gate(self, tool_name: str, input_data: dict[str, Any], context: Any):
        from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny

        cls = self._class_of(tool_name)
        short = tool_name.split("__")[-1]
        server = server_of(tool_name) if tool_name.startswith("mcp__") else "builtin"
        if cls == "read":
            return PermissionResultAllow(updated_input=input_data)
        allowance = self.tool_context.spend_allowance if cls == "spend" else self.tool_context.send_allowance
        key = tool_name if tool_name in self._classes else next((k for k in self._classes if k.endswith("__" + short)), tool_name)
        for k in (key, "*"):  # "*" = an approved send batch, whichever send tool the agent then uses
            if allowance.get(k, 0) > 0:
                allowance[k] -= 1
                return PermissionResultAllow(updated_input=input_data)
        if cls == "spend":
            # One card per batch, never one per call: the agent asks for the whole batch first.
            return PermissionResultDeny(message=(
                f"No credit approval for this call, and nothing was spent. Call request_spend_approval once with "
                f"tool={short} and the total number of records you will enrich; after the user approves, retry the calls."
            ))
        recipients = [str(input_data.get(k)) for k in ("to", "recipient_email", "recipient", "email") if input_data.get(k)]
        decision = await self.decisions.confirm_send(
            tool=short, server=server, channel="email" if "mail" in short.lower() else short,
            recipients=recipients or ["(see details)"], subject=str(input_data.get("subject", "")),
            body_preview=str(input_data.get("body") or input_data.get("message") or input_data.get("text") or "")[:2000],
            detail=json.dumps({k: v for k, v in input_data.items() if k not in ("body", "message", "text")})[:300],
            plan_id=str(input_data.get("plan_id") or ""), step=input_data.get("step"),
        )
        if decision.approved:
            return PermissionResultAllow(updated_input=input_data)
        if decision.suggestion:
            return PermissionResultDeny(message=f"The user answered instead of approving: {decision.suggestion}. Apply it and ask again.")
        return PermissionResultDeny(message="The user declined this send. Do not retry it; report and ask what to change.")

    # ------------------------------------------------------------- streaming
    async def _stream_message(self, content: dict[str, Any]) -> None:
        if self.websocket_manager is None:
            return
        try:
            await self.websocket_manager.send_chat_message(
                session_id=self.context.chat_id,
                content={
                    "role": "assistant",
                    "name": self.persona.name,
                    "content": content,
                    "type": content.get("type", "message"),
                    "call_id": self.context.call_id,
                    "capability_id": self.context.capability_id,
                    "task_id": self.task_id,
                },
                source=self.persona.name,
            )
        except Exception as e:
            logger.warning(f"[{self.persona.name}] websocket send failed: {e}")

    async def _emit_event(self, content: dict[str, Any]) -> None:
        """Stream an event (artifact, ...) and keep it in history so it survives a reload."""
        await self._stream_message(content)
        if content.get("type") in ("artifact", "handoff", "task_suggestion"):
            await self._persist("assistant", self.persona.name, content)

    async def _persist(self, role: str, name: str, raw_message: Any, content: str | None = None, usage: dict | None = None) -> None:
        message = {"role": role, "name": name, "raw_message": raw_message, "usage": usage or {}, "task_id": self.task_id}
        try:
            own = dict(message)
            if content:
                own["content"] = content
            if self.context.call_id:
                await update_chat_history_by_context(self.context, own)
            else:  # chat mode: its row carries no call/capability id to filter on
                await update_chat_history(self.context.chat_id, own, self.context.collection_name)
        except Exception as e:
            logger.warning(f"[{self.persona.name}] history write failed: {e}")
        if self.mirror_collection:
            # Raw history only: the parent chat's `messages` feed AutoGen's resume,
            # which rejects speakers that are not group-chat agents.
            try:
                await update_chat_history(self.context.chat_id, message, self.mirror_collection)
            except Exception as e:
                logger.warning(f"[{self.persona.name}] mirror history write failed: {e}")

    # ------------------------------------------------------------------ chat
    def _check_cancellation(self) -> bool:
        return bool(self.cancellation_token and self.cancellation_token.is_cancelled())

    async def _watch_cancellation(self, client) -> None:
        while True:
            await asyncio.sleep(0.5)
            if self._check_cancellation():
                logger.info(f"[{self.persona.name}] cancellation requested; interrupting")
                try:
                    await client.interrupt()
                except Exception as e:
                    logger.debug(f"interrupt failed: {e}")
                return

    async def _ensure_client(self):
        from claude_agent_sdk import ClaudeSDKClient

        async with self._client_lock:
            if self._client is None:
                options = await self._build_options()
                self._client = ClaudeSDKClient(options)
                await self._client.connect()
            return self._client

    async def _ensure_chat_record(self) -> None:
        """Create the chat row history writes need, when the caller did not."""
        if getattr(self, "_chat_record_checked", False):
            return
        self._chat_record_checked = True
        try:
            from src.database import create_capability_chat, get_chat_repository

            repo = await get_chat_repository()
            existing = await repo.get_chat(
                self.context.user_id, self.context.chat_id, self.context.collection_name,
                call_id=self.context.call_id, capability_id=self.context.capability_id,
            )
            if not existing:
                await create_capability_chat(context=self.context)
        except Exception as e:
            logger.warning(f"[{self.persona.name}] could not ensure chat record: {e}")

    async def _ensure_ws(self) -> None:
        """Resolve the global WebSocket manager when the caller did not inject one.

        The capability WebSocket builds instances before it connects and passes
        no manager, so without this the persona would stream to nobody and
        every decision card would be rejected unseen.
        """
        if self.websocket_manager is not None:
            return
        try:
            from src.dependencies import get_websocket_manager

            self.websocket_manager = await get_websocket_manager()
        except Exception as e:
            logger.warning(f"[{self.persona.name}] no websocket manager available: {e}")
            return
        self.decisions.ws = self.websocket_manager
        self.tool_registry.set_websocket_manager(self.websocket_manager)
        self.terminal_manager.set_websocket_manager(self.websocket_manager)

    async def chat(self, user_message: str) -> str:
        """Run the persona on one user message; returns its final text."""
        if self._check_cancellation():
            raise asyncio.CancelledError("Operation cancelled before start")
        self._run_start = dict(self._usage)
        # An approval covers the turn it was given in, never a later one.
        self.tool_context.spend_allowance.clear()
        self.tool_context.send_allowance.clear()
        self.tool_context.send_approved.clear()
        self.tool_context.data_sources.clear()
        self._notes_seen = []
        if notes := self._take_notes():
            user_message = f"{user_message}\n\n{_NOTE_INTRO}{notes}"
        if self._stale or (self._client is not None and getattr(self, "_built_for", None) != _settings_version()):
            await self._drop_client()  # the next call builds a client with the current tools and prompt
            self._stale = False
        await self._ensure_ws()
        await self._ensure_chat_record()
        await self._persist("user", "user", {"role": "user", "content": user_message}, content=user_message)
        self._history.append({"role": "user", "content": user_message})

        if (getattr(settings, "AGENT_PROVIDER", "anthropic") or "anthropic") == "openai":
            from src.agent_runtime.openai_runner import OpenAIRunner

            return await OpenAIRunner(self).run(user_message)

        prompt = user_message
        if self._history[:-1]:
            # The SDK session keeps its own context while connected; for a fresh
            # connection we replay the stored history as context.
            if not self._primed:
                previous = "\n\n".join(
                    f"[{m['role']}] {m['content']}" for m in self._history[:-1] if m.get("content")
                )[-12000:]
                prompt = f"Earlier in this chat:\n{previous}\n\nNew request:\n{user_message}"

        from claude_agent_sdk import (
            AssistantMessage, ResultMessage, SystemMessage, TextBlock, ToolResultBlock, ToolUseBlock, UserMessage,
        )

        client = await self._ensure_client()
        watcher = asyncio.create_task(self._watch_cancellation(client))
        final_text = ""
        texts: list[str] = []
        run_started = dt.now()
        tools_called = 0
        outcome = "finished"
        started_event = {
            "type": "agent_status", "status": "started", "persona": self.persona.name,
            "display_name": self.persona.display_name, "task": user_message[:300],
        }
        await self._stream_message(started_event)
        await self._persist("assistant", self.persona.name, started_event)
        try:
            await client.query(prompt)
            self._primed = True
            async for msg in client.receive_response():
                if isinstance(msg, SystemMessage):
                    if msg.subtype == "init":
                        tools = msg.data.get("tools") or []
                        servers = msg.data.get("mcp_servers") or []
                        logger.info(f"[{self.persona.name}] session init: {len(tools)} tools, mcp={servers}")
                        mcp_tools = [t for t in tools if isinstance(t, str) and t.startswith("mcp__")]
                        logger.debug(f"[{self.persona.name}] mcp tools: {mcp_tools}")
                elif isinstance(msg, AssistantMessage):
                    for block in msg.content:
                        if isinstance(block, TextBlock) and block.text.strip():
                            texts.append(block.text)
                            await self._stream_message({"type": "message", "content": block.text, "streaming": False})
                            await self._persist("assistant", self.persona.name, {"role": "assistant", "content": block.text}, content=block.text)
                        elif isinstance(block, ToolUseBlock):
                            self._tool_names[block.id] = block.name
                            tools_called += 1
                            short = block.name.split("__")[-1]
                            event = {"type": "tool_use", "tool_use_id": block.id, "tool_name": short, "tool_full_name": block.name,
                                     "tool_input": block.input, "tool_class": self._class_of(block.name), "status": "executing"}
                            await self._stream_message(event)
                            await self._persist("assistant", self.persona.name, event)
                elif isinstance(msg, UserMessage) and not isinstance(msg.content, str):
                    for block in msg.content:
                        if isinstance(block, ToolResultBlock):
                            name = self._tool_names.get(block.tool_use_id, "tool")
                            text = _result_text(block.content)
                            event = {
                                "type": "tool_result", "tool_use_id": block.tool_use_id, "tool_name": name.split("__")[-1], "tool_full_name": name,
                                "status": "failed" if block.is_error else "completed",
                                "content": text[:_RESULT_PREVIEW], "truncated": len(text) > _RESULT_PREVIEW,
                            }
                            await self._stream_message(event)
                            await self._persist("assistant", self.persona.name, event)
                elif isinstance(msg, ResultMessage):
                    usage = msg.usage or {}
                    self._usage["prompt_tokens"] += sum(int(usage.get(k) or 0) for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
                    self._usage["completion_tokens"] += int(usage.get("output_tokens", 0) or 0)
                    self._usage["total_tokens"] = self._usage["prompt_tokens"] + self._usage["completion_tokens"]
                    self._usage["cost_usd"] += float(msg.total_cost_usd or 0.0)
                    final_text = msg.result or ""
                    if msg.is_error or (msg.subtype or "").startswith("error"):
                        reasons = {
                            "error_max_budget_usd": f"stopped at the cost ceiling (${opts_budget:.2f} for this run)" if (opts_budget := self._budget) else "stopped at the cost ceiling",
                            "error_max_turns": "stopped at the turn limit for this persona",
                            "error_during_execution": "the runtime hit an error",
                        }
                        if msg.subtype in reasons:
                            why = reasons[msg.subtype]
                        elif final_text.strip():
                            # The CLI reports model-API refusals (e.g. "Credit balance is too low")
                            # as is_error with subtype "success"; show the refusal, not "success".
                            why = f"could not continue: {final_text.strip()[:240]}"
                        else:
                            why = f"stopped ({msg.subtype or 'unknown error'})"
                        if msg.subtype not in ("error_max_budget_usd", "error_max_turns"):
                            outcome = "failed"
                        logger.error(f"[{self.persona.name}] run ended early: {msg.subtype}: {final_text[:300]}")
                        if "credit balance" in final_text.lower():
                            advice = " Add credits to the Anthropic account (console.anthropic.com, Plans & Billing), then ask to continue."
                        else:
                            advice = " What was produced so far is kept (artifacts, files); ask to continue for the rest."
                        note = f"\n\n**{self.persona.display_name} {why}.**" + advice
                        final_text = (texts[-1] if texts else final_text or "") + note
                        await self._stream_message({"type": "message", "content": note.strip(), "streaming": False})
                    logger.info(
                        f"[{self.persona.name}] done: {msg.num_turns} turns, {msg.duration_ms} ms, "
                        f"${msg.total_cost_usd or 0:.4f}, stop={msg.stop_reason}"
                    )
        except asyncio.CancelledError:
            outcome = "cancelled"
            logger.info(f"[{self.persona.name}] chat cancelled for {self.context.chat_id}")
            raise
        except Exception:
            outcome = "failed"
            raise
        finally:
            watcher.cancel()
            finished_event = {
                "type": "agent_status", "status": outcome, "persona": self.persona.name,
                "display_name": self.persona.display_name,
                "duration_ms": int((dt.now() - run_started).total_seconds() * 1000),
                "tools_called": tools_called, "cost_usd": round(self._usage.get("cost_usd", 0.0), 4),
                "cards_answered": len(self.decisions.history),
            }
            try:
                await self._stream_message(finished_event)
                await self._persist("assistant", self.persona.name, finished_event, usage=self.run_usage(self._model))
            except Exception as e:
                logger.debug(f"[{self.persona.name}] could not emit finish status: {e}")

        if not final_text:
            final_text = texts[-1] if texts else "No response generated."
        if self._check_cancellation():
            raise asyncio.CancelledError("Operation cancelled during execution")
        self._history.append({"role": "assistant", "content": final_text})
        await self._persist(
            "assistant", self.persona.name, {"role": "assistant", "content": final_text, "final": True}, content=None,
        )
        if self._notes_seen:  # the orchestrator must learn the request changed, or it redoes the old version
            final_text += "\n\nUSER UPDATE (sent while this step ran; it supersedes the original request):\n" + "\n".join(
                f"- {n}" for n in self._notes_seen)
        return final_text

    # --------------------------------------------------------- user notes
    def _take_notes(self) -> str:
        """Messages the user sent while this run was going, as one block ('' when none)."""
        take = getattr(self.websocket_manager, "take_notes", None)
        notes = take(self.context.chat_id) if take else []
        self._notes_seen += notes
        return "\n".join(f"- {n}" for n in notes)

    async def _note_after_tool(self, input_data: Any, tool_use_id: str | None, context: Any) -> dict:
        notes = self._take_notes()
        if not notes:
            return {}
        logger.info(f"[{self.persona.name}] delivering user note after a tool call")
        return {"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": _NOTE_INTRO + notes}}

    async def _note_before_stop(self, input_data: Any, tool_use_id: str | None, context: Any) -> dict:
        notes = self._take_notes()
        if not notes:
            return {}
        logger.info(f"[{self.persona.name}] user note arrived as the run was ending; continuing")
        return {"decision": "block", "reason": _NOTE_INTRO + notes}

    # --------------------------------------------------------- connections
    async def connect_app(self, app_name: str) -> dict:
        """An app was connected or disconnected in Composio: sync servers; the next turn sees the change."""
        try:
            from src.routers.mcp import sync_composio_servers

            await sync_composio_servers()
        except Exception as e:
            logger.warning(f"[{self.persona.name}] Composio sync after '{app_name}' skipped: {e}")
        self._stale = True
        return {"success": True, "app": app_name}

    disconnect_app = connect_app

    # --------------------------------------------------------- compatibility
    def set_task_id(self, task_id: str) -> None:
        self.task_id = task_id
        self.context.task_id = task_id
        self.decisions.task_id = task_id
        self.tool_context.task_id = task_id

    def _set_cancellation_token(self, token: CancellationToken | None) -> None:
        self.cancellation_token = token
        self.context.cancellation_token = token

    def set_input_function(self, input_func) -> None:
        self._input_func = input_func

    def load_custom_instructions(self, instructions: str) -> None:
        self.custom_instructions = instructions

    def load_history(self, messages: list[dict[str, Any]]) -> None:
        self._history = [
            {"role": m.get("role", "user"), "content": m.get("content", "")}
            for m in messages if isinstance(m.get("content"), str) and m.get("role") in ("user", "assistant")
        ]

    def reset_conversation(self) -> None:
        self._history = []

    def get_usage_summary(self) -> dict[str, Any]:
        return self._usage.copy()

    def run_usage(self, model: str) -> dict[str, Any]:
        """This run's tokens and model, kept on its finish line for the admin dashboard, whatever the outcome (per_run
        marks figures for one run; before 2026-10-29 a run's final message carried the session's running total)."""
        run = {k: self._usage[k] - self._run_start.get(k, 0) for k in ("prompt_tokens", "completion_tokens", "total_tokens")}
        return {**run, "cost_usd": round(self._usage["cost_usd"] - self._run_start.get("cost_usd", 0.0), 6), "model": model, "per_run": True}

    def provide_input(self, process_id: str | None, user_input: str) -> bool:
        return self.tool_registry.provide_input(process_id, user_input)

    def has_pending_input(self) -> bool:
        return self.tool_registry.has_pending_input()

    def resize_command_pty(self, process_id: str | None, cols: int, rows: int) -> bool:
        target = process_id or self.tool_registry.command_executor.get_current_process_id()
        return bool(target and self.tool_registry.command_executor.resize_pty(target, cols, rows))

    def start_warm_up(self) -> None:
        """Start the SDK client and its tool servers in the background, before the first message (~10 s saved)."""

        async def warm() -> None:
            try:
                await self._ensure_ws()
                if (getattr(settings, "AGENT_PROVIDER", "anthropic") or "anthropic") == "openai":
                    return  # the OpenAI runner builds its tools per run; there is no client to start
                await self._ensure_client()
            except Exception as e:
                logger.warning(f"[{self.persona.name}] warm-up failed; the first message starts the client: {e}")

        self._warm_task = asyncio.create_task(warm())

    async def _drop_client(self) -> None:
        """Stop the SDK client; the next turn starts a fresh one with the current tools."""
        if self._warm_task and not self._warm_task.done():
            self._warm_task.cancel()
        self._primed = False
        if self._client is not None:
            try:
                await self._client.disconnect()
            except Exception as e:
                logger.debug(f"[{self.persona.name}] disconnect: {e}")
            self._client = None

    async def cleanup(self) -> None:
        await self._drop_client()
        await self.tool_registry.cleanup()
        await self.terminal_manager.cleanup_all()

    # ------------------------------------------------------- PTY terminal
    async def start_terminal(self, cols: int | None = None, rows: int | None = None, shell: str | None = None) -> bool:
        terminal = await self.terminal_manager.create_terminal(
            session_id=self.context.chat_id, working_directory=self.working_directory, cols=cols, rows=rows, shell=shell,  # nosec B604
        )
        return terminal is not None

    async def write_to_terminal(self, data: str | bytes) -> bool:
        terminal = self.terminal_manager.get_terminal(self.context.chat_id)
        return await terminal.write(data) if terminal else False

    async def resize_terminal(self, cols: int, rows: int) -> None:
        terminal = self.terminal_manager.get_terminal(self.context.chat_id)
        if terminal:
            await terminal.resize(cols, rows)

    async def terminate_terminal(self, force: bool = False) -> bool:
        return await self.terminal_manager.terminate_terminal(self.context.chat_id, force=force)

    def is_terminal_running(self) -> bool:
        terminal = self.terminal_manager.get_terminal(self.context.chat_id)
        return terminal is not None and terminal.is_running

    def get_terminal_status(self) -> dict[str, Any] | None:
        terminal = self.terminal_manager.get_terminal(self.context.chat_id)
        return terminal.get_status() if terminal else None


def persona_capability_class(name: str) -> type:
    """A PersonaSession subclass bound to one persona, for the capability class map."""
    persona = get_persona(name)

    class BoundPersonaSession(PersonaSession):
        def __init__(self, context: ChatContext):
            super().__init__(context, persona)

    BoundPersonaSession.__name__ = "".join(part.title() for part in name.split("_")) + "Session"
    return BoundPersonaSession
