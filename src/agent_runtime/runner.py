"""Run a persona once on behalf of the orchestrator."""

import asyncio
import uuid

from loguru import logger

from src.agent_runtime.session import PersonaSession
from src.database import create_capability_chat
from src.utilities.custom_manager import ChatContext


async def run_persona(
    name: str,
    query: str,
    *,
    user_id: str,
    chat_id: str,
    chat_dir: str,
    omni_memory,
    websocket_manager,
    call_id: str | None = None,
    task_id: str | None = None,
    cancellation_token=None,
    mirror_collection: str | None = "omni",
) -> str:
    """Create a persona session for one orchestrator call and return its answer."""
    context = ChatContext(
        user_id=user_id,
        chat_id=chat_id,
        chat_dir=chat_dir,
        call_id=call_id or str(uuid.uuid4()),
        capability_id=str(uuid.uuid4()),
        capability_name=name,
        collection_name=name,
        omni_memory=omni_memory,
        cancellation_token=cancellation_token,
        task_id=task_id,
        manager_kwargs={"websocket_manager": websocket_manager, "mirror_collection": mirror_collection},
    )
    session = None
    try:
        await create_capability_chat(context=context)
        session = PersonaSession(context, name)
        return await session.chat(query)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.exception(f"{name} failed for query '{query[:120]}': {e}")
        return f"error: {name} failed: {e}"
    finally:
        if session is not None:
            await session.cleanup()
