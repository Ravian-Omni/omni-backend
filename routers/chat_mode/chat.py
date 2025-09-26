# Chat Mode API matching agent_mode practices
from fastapi import APIRouter, Request, HTTPException
from datetime import datetime, timezone
import uuid
import os
from configs.settings import settings
from utilities.storage import ensure_path
from utilities.api_client import api_client

router = APIRouter()


@router.post("/new_chat")
async def create_new_chat(request: Request, user_id: str = "default_user"):
    try:
        # Get chat_dir and agent_mode from query parameters
        chat_dir = request.query_params.get(
            "chat_dir", os.path.join(settings.ROOT_DIR, "ravian"))
        chat_dir = ensure_path(chat_dir)
        agent_mode_str = request.query_params.get("agent_mode", "false")
        agent_mode = True if agent_mode_str.lower() == "true" else False

        # Generate unique chat identifier
        chat_id = str(uuid.uuid4())

        # Prepare chat document
        chat_document = {
            "user_id": user_id,
            "chat_id": chat_id,
            "chat_dir": chat_dir,
            "messages": [],
            "raw_messages": [],
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
            "agent_mode": agent_mode
        }

        # Create database record
        create_chat = await api_client.post("/chats/new", params={"capability": "chat_mode"}, data=chat_document)
        create_chat = create_chat.standard_response()
        if not create_chat.get("success"):
            raise Exception(
                f"Failed to create chat_mode_chat: {create_chat.get('message', 'Unknown error')}")

        result = create_chat.get("data")

        # Return standardized response
        return result

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Chat creation failed due to server error: {e}"
        )
