"""One thread in a messaging app (Teams, Slack) driving one DAXAGENT task chat.

The thread is the WebSocket the omni route talks to, in process: the app's messages go in as the
task (or as the answer the agents wait on), and the events the web app would render come back as
text through ``say``. Which task chat a thread belongs to is kept in user_prefs under the app's name.
"""

import asyncio
import json
import os
from collections.abc import Awaitable, Callable
from typing import Any

from starlette.websockets import WebSocketDisconnect

from src.database import load_pref, save_pref
from src.dependencies import get_websocket_manager
from src.services.chat_service import ChatService

# whose workspace the apps and the MCP act in: the hosted app's owner (their tasks show in their web app at once),
# else the local workspace. init_db moves local_user rows to the owner anyway, but only at the next start.
USER_ID = os.getenv("DAXAGENT_OWNER") or "local_user"
IDLE_SECONDS = 1800  # a quiet thread drops its agents; the next message reopens the chat from history
_threads: dict[str, "Thread"] = {}
_lock = asyncio.Lock()


def _loads(text: Any) -> dict:
    try:
        data = json.loads(text) if isinstance(text, str) else text
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _question(card: dict) -> str | None:
    """A question the agents wait on, as text (None when the thread already read it)."""
    if "agent" in card:  # the orchestrator's own prompts: {"agent", "prompt"}
        if card["agent"] == "get_user_acceptance":
            return "Do you approve this plan? Reply **yes**, or say what to change."
        return None  # user_input's question was already sent as manual_verification's text
    lines = [card.get("title"), card.get("message")]
    if card.get("subject"):
        lines.append(f"Subject: {card['subject']}")
    if card.get("body_preview"):
        lines.append(str(card["body_preview"])[:1500])
    for q in card.get("questions") or []:  # form card
        options = ", ".join(str(o.get("label")) for o in q.get("options") or [])
        lines.append(f"- {q.get('label')}" + (f" ({options})" if options else ""))
    for o in card.get("options") or []:  # choose card
        lines.append(f"- {o.get('label')}" + (f": {o['description']}" if o.get("description") else ""))
    if card.get("card") in ("confirm_spend", "confirm_send", "review_artifact"):
        lines.append("Reply **yes** or **no**.")
    return "\n\n".join(line for line in lines if line) or None


def text_of(event: dict, notes: dict[str, str | None]) -> str | None:
    """What the app's user reads for one WebSocket event (None: nothing), following the web app.

    ``notes`` holds each running agent's latest text; like the web app's activity line, only the
    last one is shown, when the agent finishes.
    """
    kind, data = event.get("type"), event.get("data") or {}
    source, payload = data.get("source"), data.get("content")
    if kind == "error":
        return f"Something went wrong: {event.get('message') or event.get('error') or 'unknown error'}"
    if kind == "completion":
        return "Stopped." if event.get("status") == "cancelled" else None
    if kind == "input_request":
        return _question(_loads(payload) if isinstance(payload, str) else payload or {})
    if kind != "message" or not isinstance(payload, dict):
        return None
    if source == "OMNI":
        name, text = payload.get("name"), payload.get("content") or ""
        if name in ("conversation_agent", "process_completion_agent"):
            return text or None
        if name == "planner_agent":
            steps = _loads(text).get("breakdown") or []
            plan = "\n\n".join(f"{i}. {s.get('task')} ({s.get('capability')})" for i, s in enumerate(steps, 1))
            return f"Plan:\n\n{plan}" if steps else None
        if name == "manual_verification":
            form = _loads(text)
            return None if form.get("questions") else (form.get("intro") or text)
        return None
    inner = payload.get("content")  # persona envelope: {name, type, content: {...}}
    if not isinstance(inner, dict):
        return None
    inner_type = payload.get("type") or inner.get("type")
    if inner_type == "agent_status":
        persona = inner.get("persona") or source
        if inner.get("status") == "started":
            notes[persona] = None
            return None
        return notes.pop(persona, None)
    if inner_type == "artifact" and inner.get("artifact"):
        artifact = inner["artifact"]
        return f"Saved {artifact.get('kind') or 'artifact'}: {artifact.get('title') or ''}".strip()
    if inner_type == "task_suggestion" and (s := inner.get("suggestion")):  # chat says this needs a task, and which
        return f"This needs a task ({s.get('title') or 'task'}). Start it with this request:\n{s.get('request') or ''}".strip()
    text = inner.get("content") if inner_type == "message" else None
    if not isinstance(text, str) or not text.strip() or inner.get("streaming"):
        return None
    if source in notes:
        notes[source] = text
        return None
    return text


class Thread:
    """One app thread driving one task chat; it is the WebSocket the omni route talks to."""

    drives_run = True  # opening the chat in the web app must not take the run's events (or the run) away from it

    def __init__(self, app: str, key: str, chat_id: str, say: Callable[[str], Awaitable[None]]):
        self.app, self.key, self.chat_id, self.say = app, key, chat_id, say
        self.inbox: asyncio.Queue[str] = asyncio.Queue()
        self.pending = False  # the agents wait on an answer
        self.ready = False
        self.notes: dict[str, str | None] = {}
        self.task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        from src.routers import websocket

        try:
            await websocket.omni_websocket(self, self.chat_id, USER_ID, await get_websocket_manager())
        finally:
            if not self.ready:  # the chat could not be opened: the next message starts a new one
                await save_pref(self.app, self.key, None)
            if _threads.get(f"{self.app}:{self.key}") is self:
                _threads.pop(f"{self.app}:{self.key}")

    def send(self, text: str) -> None:
        """An app message: the answer the agents wait on, else the (next) task; "stop" cancels the run."""
        if text.lower() == "stop":
            message: dict[str, Any] = {"type": "stop"}
        elif self.pending:
            self.pending, message = False, {"type": "input_response", "response": text}
        else:
            message = {"type": "start", "task": text, "files": []}
        self.inbox.put_nowait(json.dumps(message))

    # -- the WebSocket interface the omni route uses --
    async def accept(self) -> None:
        pass

    async def close(self, code: int = 1000, reason: str = "") -> None:
        pass

    async def receive_text(self) -> str:
        manager = await get_websocket_manager()
        while True:
            try:
                return await asyncio.wait_for(self.inbox.get(), IDLE_SECONDS)
            except TimeoutError:
                if not manager.is_running(self.chat_id):
                    raise WebSocketDisconnect(1000, "idle") from None

    async def send_json(self, event: dict) -> None:
        if event.get("type") == "init_status" and event.get("status") == "ready":
            self.ready = True
        if event.get("type") == "input_request":
            self.pending = True
        elif event.get("type") == "completion":
            self.pending = False
        if text := text_of(event, self.notes):
            await self.say(text)


class ChatThread(Thread):
    """The same thread on a chat-mode chat (the chat route, one assistant): a quick job in one turn, no plan."""

    def __init__(self, chat_id: str):
        self.turn: asyncio.Queue[str | None] = asyncio.Queue()  # the turn's texts; None: it ended or waits on an answer
        self.asked = ""  # the open question's text, while one is open
        super().__init__("chat", chat_id, chat_id, self.turn.put)

    async def _run(self) -> None:
        from src.routers import websocket

        try:
            await websocket.chat_websocket(self, self.chat_id, USER_ID, await get_websocket_manager())
        finally:
            self.turn.put_nowait(None)  # a turn waiting on a thread that closed is told, not left hanging

    async def send_json(self, event: dict) -> None:
        if event.get("type") == "input_request":
            self.asked = text_of(event, {}) or "The assistant waits on an answer."
        await super().send_json(event)
        if event.get("type") in ("completion", "input_request", "error"):
            self.turn.put_nowait(None)


async def open_thread(app: str, key: str, say: Callable[[str], Awaitable[None]]) -> Thread:
    """The live thread for this app conversation, opened on its task chat (a new one the first time)."""
    async with _lock:
        thread = _threads.get(f"{app}:{key}")
        if thread and not thread.task.done():
            thread.say = say  # replies go where the latest message came from
            return thread
        chat_id = await load_pref(app, key)  # user_prefs keyed by conversation: no new table
        if not chat_id:
            chat_id = (await ChatService.create_omni_chat(USER_ID))["chat_id"]
            await save_pref(app, key, chat_id)
        thread = _threads[f"{app}:{key}"] = Thread(app, key, chat_id, say)
        return thread
