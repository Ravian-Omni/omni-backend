"""The redirect behind a tracked link (/r/<token>): it records the click, tells Brain_Hands and sends the reader on.

Open to anyone (a recipient has no session), so it only ever redirects to an address stored when the email was sent."""

from fastapi import APIRouter, HTTPException
from fastapi.responses import RedirectResponse

from src.configs.datetime_utils import dt
from src.database import get_link, record_click
from src.services import brain_hands

router = APIRouter()


@router.get("/{token}")
async def follow(token: str):
    link = await get_link(token)
    if not link:
        raise HTTPException(status_code=404, detail="Unknown link")
    click_id = await record_click(token)
    brain_hands.push_in_background("click", f"click:{token}:{click_id}", link["subject"], f"{link['recipient']} clicked {link['url']}",
                                   email=link["recipient"], url=link["url"], campaign_id=link["plan_id"], step=link["step"], clicked_at=dt.now_iso())
    return RedirectResponse(link["url"], status_code=302)
