"""Pushes campaign replies to Brain_Hands (signals contract [6]): a handoff when it opens, and the replies DAX settles itself."""

import asyncio
import os

import httpx
from loguru import logger

RETRY_AFTER_S = (1, 3)  # a 5xx is tried again twice; nothing else is retried
_tasks: set[asyncio.Task] = set()


async def push(kind: str, id: str, title: str, text: str, **data) -> bool:
    """POST one notification to Brain_Hands; `data` is the contract's data object, empty values left out. Nothing is
    sent when BRAIN_HANDS_URL is unset."""
    url = os.getenv("BRAIN_HANDS_URL", "").rstrip("/")
    if not url:
        return False
    body = {"app": "daxagent", "kind": kind, "id": id, "title": title, "text": text[:3000], "data": {k: v for k, v in data.items() if v}}
    headers = {"Authorization": f"Bearer {os.getenv('BRAIN_HANDS_TOKEN', '')}"}
    async with httpx.AsyncClient(timeout=10) as client:
        for wait in (*RETRY_AFTER_S, None):
            try:
                response = await client.post(f"{url}/notifications", json=body, headers=headers)
            except httpx.HTTPError as e:
                logger.warning(f"[brain_hands] {id} not sent: {e}")
                return False
            if response.status_code < 500 or wait is None:
                break
            await asyncio.sleep(wait)
    if not response.is_success:
        logger.warning(f"[brain_hands] {id} refused: {response.status_code}")
    return response.is_success


async def push_reply(*args, **data) -> bool:
    return await push("reply", *args, **data)


def push_in_background(*args, **data) -> None:
    """push for a caller that must never wait on Brain_Hands."""
    task = asyncio.create_task(push(*args, **data))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
