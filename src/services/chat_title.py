"""A chat's title: three to six words from its first message, written once and never over an existing title."""

from loguru import logger

from src.agent_runtime import llm
from src.database import get_chat_title, set_chat_title

SYSTEM = "Title this conversation in 3 to 6 words from the user's first message. Reply with the title only: no quotes, no final period."


async def name_chat(chat_id: str, request: str) -> str | None:
    """The title written for the chat, or None when it already has one, the request is empty or the model failed."""
    if not request.strip() or await get_chat_title(chat_id):
        return None
    try:
        title = " ".join((await llm.complete(SYSTEM, request[:1000], max_tokens=24)).strip("\"'. \n").split()[:6])
    except Exception as e:
        logger.warning(f"[chat_title] {chat_id} not named: {e}")
        return None
    return title if title and await set_chat_title(chat_id, title) else None
