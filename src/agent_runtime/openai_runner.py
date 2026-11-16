"""Run a persona on an OpenAI chat-completions model (gpt-5.6-luna).

Same personas, tools, gates, WebSocket events and history as the Claude
Agent SDK path in ``session.py``; only the model loop differs. Tools come
from three places: the in-process "daxagent" tools, the file/web tools in
``tools/files.py`` (standing in for the SDK's built-ins), and the remote MCP
servers the persona may use. Spend/send tools go through the same
permission gate, so decision cards work unchanged.
"""

import asyncio
import json
import re
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from loguru import logger

from src.agent_runtime import leads, prefs
from src.agent_runtime.tools import all_tools, build_server, files, full_name
from src.configs.datetime_utils import dt
from src.configs.llm_configs_manager import LLMConfigManager
from src.configs.settings import settings
from src.mcp_client.client import call_tool, server_notes
from src.mcp_client.config import options as server_options

RESULT_PREVIEW = 4000        # chars of a tool result shown in the UI
RESULT_FOR_MODEL = 40_000    # chars of a tool result fed back to the model
RETRYABLE_ATTEMPTS = 3
MAX_TOOLS = 128  # OpenAI's limit per request
NOTE_INTRO = (
    "The user sent this while you were working. Take it into account now; "
    "if it changes the task, adjust, and say so in your reply:\n"
)
DEFAULT_MAX_OUTPUT_TOKENS = 8192
HISTORY_CHARS = 12_000


@dataclass
class ToolDef:
    name: str                 # name the model sees (OpenAI: ^[a-zA-Z0-9_-]{1,64}$)
    full_name: str            # mcp__<server>__<tool> style name used for classes and events
    description: str
    parameters: dict[str, Any]
    handler: Callable[[dict[str, Any]], Awaitable[Any]]

    def spec(self) -> dict[str, Any]:
        params = self.parameters or {"type": "object", "properties": {}}
        return {"type": "function", "function": {"name": self.name, "description": self.description[:1024], "parameters": params}}


def _safe_name(raw: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "_", raw)[:64]


def _result_to_text(result: Any) -> tuple[str, bool]:
    """Normalise a tool result (SDK-style dict or plain text) to (text, is_error)."""
    if isinstance(result, dict) and "content" in result:
        parts = []
        for block in result.get("content") or []:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
            else:
                parts.append(json.dumps(block, default=str))
        return "\n".join(parts), bool(result.get("is_error"))
    if isinstance(result, (dict, list)):
        return json.dumps(result, default=str), False
    return str(result), False


class OpenAIRunner:
    """One persona run on the OpenAI model, driving a PersonaSession's plumbing."""

    def __init__(self, session):
        self.s = session
        self.tools: dict[str, ToolDef] = {}

    # ------------------------------------------------------------- model
    @staticmethod
    def model_config() -> dict[str, Any]:
        """Model name, key and request extras for the persona runtime."""
        cfg = LLMConfigManager.get_config("default")
        entry = (cfg.get("config_list") or [{}])[0] if isinstance(cfg, dict) else {}
        model = getattr(settings, "AGENT_MODEL", None) or entry.get("model") or "gpt-5.6-luna"
        return {
            "model": model,
            "api_key": entry.get("api_key") or settings.OPENAI_API_KEY or "",
            "base_url": entry.get("base_url"),
            "extra_body": entry.get("extra_body") or {"reasoning_effort": "none"},
            "max_output_tokens": int(getattr(settings, "AGENT_MAX_OUTPUT_TOKENS", 0) or DEFAULT_MAX_OUTPUT_TOKENS),
        }

    # ------------------------------------------------------------- tools
    async def _collect_tools(self) -> str:
        """Build the tool table; returns the system-prompt notes of the remote servers."""
        s = self.s
        _, dax_names, dax_classes = build_server(s.tool_context)
        for t in all_tools(s.tool_context):  # the same list the SDK server serves
            fname = full_name(t.name)
            cls = dax_classes.get(fname, "read")
            # Same visibility rule as the SDK path: hide only spend/send tools the persona lacks.
            if t.name not in s.persona.daxagent_tools and cls != "read":
                continue
            self.tools[t.name] = ToolDef(t.name, fname, t.description, t.input_schema, t.handler)

        wanted = set(s.persona.builtin_tools)
        for t in files.build(s.tool_context):
            if t.name in wanted:
                self.tools[t.name] = ToolDef(t.name, t.name, t.description, t.input_schema, t.handler)

        remote, remote_classes = await s._remote_servers()
        s.tool_context.remote_tool_classes = remote_classes
        s._classes = {**dax_classes, **remote_classes}
        notes = ""
        # OpenAI takes at most 128 tools: the in-process and file tools come first, then each app gets an equal share.
        room = max(0, MAX_TOOLS - len(self.tools))
        share = room // max(1, len(remote))
        for server in remote:
            note = server_options(server).get("persona_prompt_append") or server_options(server).get("system_prompt_append")
            if note:
                notes += note
            notes += server_notes(server)  # when to call it, as the server itself publishes on initialize()
            schemas = s._remote_tools.get(server, [])
            if len(schemas) > share:
                logger.warning(f"[{s.persona.name}] {server}: offering {share} of {len(schemas)} tools (OpenAI allows {MAX_TOOLS})")
                notes += f"\n\nOnly the first {share} tools of {server} are available in this run.\n"
            for t in schemas[:share]:
                fname = f"mcp__{server}__{t['name']}"
                name = _safe_name(f"{server}__{t['name']}")
                if name in self.tools:
                    name = _safe_name(fname)

                async def _call(args: dict, _server=server, _tool=t["name"]) -> str:
                    s.tool_context.data_sources.add(_server)
                    text = await call_tool(_server, _tool, args)
                    await leads.note_source(s.tool_context.chat_id, _server, text)  # Data Axle's own emails get the in-house check
                    return text

                self.tools[name] = ToolDef(name, fname, t.get("description") or "", t.get("input_schema") or {}, _call)
        return notes

    def _system_prompt(self, notes: str) -> str:
        base = self.s._system_prompt(notes)
        remote = sorted({d.full_name.split("__")[1] for d in self.tools.values() if d.full_name.startswith("mcp__") and not d.full_name.startswith("mcp__daxagent__")})
        extra = (
            "\n\n## Tool naming\n"
            "- Files: Read, Write, Edit, MultiEdit, Glob, Grep, WebFetch work on the working directory and the shared-files folder.\n"
        )
        if remote:
            extra += "- Connected app tools are named <server>__<tool>, e.g. " + ", ".join(f"{r}__<tool>" for r in remote) + ".\n"
        extra += "- Call tools with real arguments only; never describe a call in prose instead of making it.\n"
        return base + extra

    # ------------------------------------------------------------- one tool call
    async def _run_tool(self, call_id: str, name: str, raw_args: str) -> str:
        s = self.s
        tdef = self.tools.get(name)
        try:
            args = json.loads(raw_args) if raw_args else {}
            if not isinstance(args, dict):
                raise ValueError("arguments must be a JSON object")
        except (json.JSONDecodeError, ValueError) as e:
            args, parse_error = {}, f"Invalid JSON arguments for {name}: {e}"
        else:
            parse_error = None
        fname = tdef.full_name if tdef else name
        short = fname.split("__")[-1]
        event = {"type": "tool_use", "tool_use_id": call_id, "tool_name": short, "tool_full_name": fname,
                 "tool_input": args, "tool_class": s._class_of(fname), "status": "executing"}
        await s._stream_message(event)
        await s._persist("assistant", s.persona.name, event)

        if parse_error:
            text, is_error = parse_error, True
        elif tdef is None:
            text, is_error = f"Unknown tool '{name}'. Available: {', '.join(sorted(self.tools))}", True
        else:
            from claude_agent_sdk import PermissionResultDeny

            verdict = await s._permission_gate(fname, args, None)
            if isinstance(verdict, PermissionResultDeny):
                text, is_error = verdict.message, True
            else:
                try:
                    text, is_error = _result_to_text(await tdef.handler(args))
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.exception(f"[{s.persona.name}] tool {name} failed")
                    text, is_error = f"{name} failed: {e}", True
        result_event = {
            "type": "tool_result", "tool_use_id": call_id, "tool_name": short, "tool_full_name": fname,
            "status": "failed" if is_error else "completed",
            "content": text[:RESULT_PREVIEW], "truncated": len(text) > RESULT_PREVIEW,
        }
        await s._stream_message(result_event)
        await s._persist("assistant", s.persona.name, result_event)
        if len(text) > RESULT_FOR_MODEL:
            text = text[:RESULT_FOR_MODEL] + f"\n... truncated ({len(text)} chars); narrow the request or page through it"
        return ("ERROR: " + text) if is_error and not text.startswith("ERROR") else text

    # ------------------------------------------------------------- the loop
    async def _complete(self, client, cfg: dict[str, Any], messages: list[dict], specs: list[dict]):
        from openai import APIConnectionError, APIStatusError, RateLimitError

        delay = 2.0
        for attempt in range(1, RETRYABLE_ATTEMPTS + 1):
            try:
                kwargs: dict[str, Any] = dict(model=cfg["model"], messages=messages, max_completion_tokens=cfg["max_output_tokens"])
                if specs:
                    kwargs["tools"] = specs
                    kwargs["tool_choice"] = "auto"
                if cfg.get("extra_body"):
                    kwargs["extra_body"] = cfg["extra_body"]
                return await client.chat.completions.create(**kwargs)
            except (RateLimitError, APIConnectionError) as e:
                if attempt == RETRYABLE_ATTEMPTS:
                    raise
                logger.warning(f"[{self.s.persona.name}] OpenAI {type(e).__name__}; retry {attempt} in {delay:.0f}s")
                await asyncio.sleep(delay)
                delay *= 2
            except APIStatusError as e:
                if e.status_code >= 500 and attempt < RETRYABLE_ATTEMPTS:
                    await asyncio.sleep(delay)
                    delay *= 2
                    continue
                raise

    async def run(self, user_message: str) -> str:
        s = self.s
        from openai import AsyncOpenAI

        cfg = self.model_config()
        if not cfg["api_key"]:
            raise RuntimeError("OPENAI_API_KEY is not set; the persona runtime cannot reach the model")
        client = AsyncOpenAI(api_key=cfg["api_key"], base_url=cfg.get("base_url") or None)
        notes = await self._collect_tools()
        notes += await prefs.prompt_notes(s.context.user_id, s.persona.name)  # Settings > Memory and Agents
        s._own_prompt = await prefs.agent_prompt(s.context.user_id, s.persona.name)
        specs = [t.spec() for t in self.tools.values()]
        logger.info(f"[{s.persona.name}] openai runner: model={cfg['model']} tools={len(specs)}")

        messages: list[dict[str, Any]] = [{"role": "system", "content": self._system_prompt(notes)}]
        earlier = [m for m in s._history[:-1] if m.get("content")]
        if earlier:
            budget = HISTORY_CHARS
            kept: list[dict[str, Any]] = []
            for m in reversed(earlier):
                content = str(m["content"])
                if budget - len(content) < 0:
                    content = content[-max(0, budget):]
                if not content:
                    break
                kept.append({"role": "assistant" if m.get("role") == "assistant" else "user", "content": content})
                budget -= len(content)
            messages.extend(reversed(kept))
        messages.append({"role": "user", "content": user_message})

        texts: list[str] = []
        final_text = ""
        tools_called = 0
        outcome = "finished"
        run_started = dt.now()
        max_turns = int(getattr(settings, "AGENT_MAX_TURNS", 0) or s.persona.max_turns or 60)
        started_event = {"type": "agent_status", "status": "started", "persona": s.persona.name,
                         "display_name": s.persona.display_name, "task": user_message[:300]}
        await s._stream_message(started_event)
        await s._persist("assistant", s.persona.name, started_event)
        note = ""
        try:
            for turn in range(max_turns):
                if s._check_cancellation():
                    raise asyncio.CancelledError("Operation cancelled during execution")
                response = await self._complete(client, cfg, messages, specs)
                usage = getattr(response, "usage", None)
                if usage:
                    s._usage["prompt_tokens"] += int(usage.prompt_tokens or 0)
                    s._usage["completion_tokens"] += int(usage.completion_tokens or 0)
                    s._usage["total_tokens"] = s._usage["prompt_tokens"] + s._usage["completion_tokens"]
                choice = response.choices[0]
                msg = choice.message
                content = (msg.content or "").strip()
                if content:
                    texts.append(content)
                    await s._stream_message({"type": "message", "content": content, "streaming": False})
                    await s._persist("assistant", s.persona.name, {"role": "assistant", "content": content}, content=content)
                calls = list(msg.tool_calls or [])
                if not calls:
                    if choice.finish_reason == "length":
                        note = f"\n\n**{s.persona.display_name} stopped: the reply hit the output-length limit.** Ask to continue for the rest."
                    break
                messages.append({
                    "role": "assistant", "content": msg.content or "",
                    "tool_calls": [{"id": c.id, "type": "function", "function": {"name": c.function.name, "arguments": c.function.arguments or "{}"}} for c in calls],
                })
                for c in calls:
                    tools_called += 1
                    result = await self._run_tool(c.id, c.function.name, c.function.arguments or "")
                    messages.append({"role": "tool", "tool_call_id": c.id, "content": result})
                if user_notes := s._take_notes():  # sent mid-run: the model sees it before its next step
                    messages.append({"role": "user", "content": NOTE_INTRO + user_notes})
            else:
                note = f"\n\n**{s.persona.display_name} stopped at the turn limit for this persona ({max_turns}).** What was produced so far is kept (artifacts, files); ask to continue for the rest."
            if note:
                await s._stream_message({"type": "message", "content": note.strip(), "streaming": False})
        except asyncio.CancelledError:
            outcome = "cancelled"
            raise
        except Exception as e:
            outcome = "failed"
            reason = str(e)
            m = re.search(r"'message': '([^']+)'", reason) or re.search(r'"message":\s*"([^"]+)"', reason)
            if m:
                reason = m.group(1)
            logger.exception(f"[{s.persona.name}] openai run failed")
            fail_note = f"**{s.persona.display_name} could not continue: {reason[:300]}**"
            await s._stream_message({"type": "message", "content": fail_note, "streaming": False})
            texts.append(fail_note)
        finally:
            finished_event = {
                "type": "agent_status", "status": outcome, "persona": s.persona.name, "display_name": s.persona.display_name,
                "duration_ms": int((dt.now() - run_started).total_seconds() * 1000), "tools_called": tools_called,
                "cost_usd": round(s._usage.get("cost_usd", 0.0), 4), "cards_answered": len(s.decisions.history),
                "model": cfg["model"], "tokens": s._usage.get("total_tokens", 0),
            }
            try:
                await s._stream_message(finished_event)
                await s._persist("assistant", s.persona.name, finished_event, usage=s.run_usage(cfg["model"]))
            except Exception as e:
                logger.debug(f"[{s.persona.name}] could not emit finish status: {e}")

        final_text = (texts[-1] if texts else "No response generated.") + note
        if s._notes_seen:  # the orchestrator must learn the request changed, or it redoes the old version
            final_text += "\n\nUSER UPDATE (sent while this step ran; it supersedes the original request):\n" + "\n".join(f"- {n}" for n in s._notes_seen)
        s._history.append({"role": "assistant", "content": final_text})
        await s._persist("assistant", s.persona.name, {"role": "assistant", "content": final_text, "final": True}, content=None)
        return final_text
