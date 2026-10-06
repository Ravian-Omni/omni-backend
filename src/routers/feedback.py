"""Ratings of finished runs ("How was your experience?"), bound to the conversation's chat_id."""

from fastapi import APIRouter
from pydantic import BaseModel, Field

from src.database import load_feedback, save_feedback

router = APIRouter()


class FeedbackIn(BaseModel):
    chat_id: str = Field(..., min_length=1, description="The conversation")
    task_id: str = Field("", description="The run in the conversation being rated")
    rating: int = Field(..., ge=1, le=5)
    description: str = Field("", max_length=5000)
    user_id: str = "local_user"


@router.post("")
async def submit_feedback(body: FeedbackIn) -> dict:
    return await save_feedback(body.chat_id, body.task_id, body.user_id, body.rating, body.description.strip())


@router.get("/{chat_id}")
async def conversation_feedback(chat_id: str) -> dict:
    return {"chat_id": chat_id, "data": await load_feedback(chat_id)}
