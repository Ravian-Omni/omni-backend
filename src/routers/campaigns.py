"""Campaign Console endpoints: preview, merged export and copy assist for campaign_plan artifacts."""

import csv
import io
from collections import Counter
from typing import Any

import os

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from src.agent_runtime import assets, creatives
from src.agent_runtime.tools.artifacts import load_record
from src.database import delete_creative, get_creative, list_creatives, update_creative

router = APIRouter()


async def _plan_and_audience(chat_id: str, plan_id: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    try:
        _, plan = await load_record(chat_id, plan_id)
        audience_id = (plan.get("meta") or {}).get("audience_artifact_id")
        if not audience_id:
            raise HTTPException(status_code=400, detail="This campaign plan names no audience (meta.audience_artifact_id)")
        _, audience = await load_record(chat_id, audience_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return plan, audience.get("rows", [])


class CreativeLink(BaseModel):
    url: str = Field("", max_length=2000, description="A public link to the creative ('' to clear)")


@router.post("/{chat_id}/{plan_id}/creatives")
async def upload_creatives(chat_id: str, plan_id: str, files: list[UploadFile] = File(...)) -> dict:
    """Ad creatives for a campaign: images, PDFs or text, up to 10 MB each; each is read once for the copywriter."""
    try:
        record, _ = await load_record(chat_id, plan_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    saved = []
    for f in files:
        mime = assets.kind_of(f.filename or "", f.content_type or "")
        if not mime:
            raise HTTPException(status_code=415, detail=f"{f.filename}: use an image (PNG, JPEG, GIF, WebP), a PDF or a text file")
        data = await f.read()
        if len(data) > assets.MAX_BYTES:
            raise HTTPException(status_code=413, detail=f"{f.filename} is over 10 MB")
        saved.append(await assets.store(chat_id, plan_id, os.path.dirname(record["path"]), f.filename or "file", mime, data))
    return {"creatives": saved}


@router.get("/{chat_id}/{plan_id}/creatives")
async def campaign_creatives(chat_id: str, plan_id: str) -> dict:
    return {"creatives": await list_creatives(chat_id, plan_id)}


@router.get("/creatives/{creative_id}/file")
async def creative_file(creative_id: str):
    c = await get_creative(creative_id)
    if not c or not os.path.exists(c["path"]):
        raise HTTPException(status_code=404, detail="No such creative")
    return FileResponse(c["path"], media_type=c["mime"], filename=c["name"])


@router.patch("/creatives/{creative_id}")
async def set_creative_link(creative_id: str, body: CreativeLink) -> dict:
    url = body.url.strip()
    if url and not url.startswith(("https://", "http://")):
        raise HTTPException(status_code=422, detail="Use a full link starting with https://")
    c = await update_creative(creative_id, url)
    if not c:
        raise HTTPException(status_code=404, detail="No such creative")
    return c


@router.delete("/creatives/{creative_id}")
async def remove_creative(creative_id: str) -> dict:
    c = await get_creative(creative_id)
    if not c:
        raise HTTPException(status_code=404, detail="No such creative")
    await delete_creative(creative_id)
    if os.path.exists(c["path"]):
        os.remove(c["path"])
    return {"deleted": creative_id}


@router.get("/{chat_id}/{plan_id}/preview")
async def preview(chat_id: str, plan_id: str, recipient: int = 0):
    """Every step as one recipient will get it, plus issue counts across the whole audience."""
    plan, audience = await _plan_and_audience(chat_id, plan_id)
    brief = (plan.get("meta") or {}).get("brief") or {}
    assets = {c["id"]: c for c in await list_creatives(chat_id, plan_id)}
    counts = Counter(
        issue for row in audience for step in creatives.steps_for(plan, row)
        for issue in creatives.message(step, row, brief, assets)["issues"]
    )
    row = audience[recipient] if 0 <= recipient < len(audience) else {}
    return {
        "recipients": len(audience),
        "index": recipient,
        "recipient": {k: creatives.field(row, k) for k in ("full_name", "company", "title", "email", "phone", "city", "state")},
        "messages": [creatives.message(step, row, brief, assets) for step in creatives.steps_for(plan, row)],
        "issues": dict(counts),
    }


@router.get("/{chat_id}/{plan_id}/export")
async def export(chat_id: str, plan_id: str):
    """One CSV row per recipient x step, fully rendered: a mail-merge file and a call sheet."""
    plan, audience = await _plan_and_audience(chat_id, plan_id)
    brief = (plan.get("meta") or {}).get("brief") or {}
    approved_only = any(s.get("status") == "approved" for s in plan.get("rows", []))
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["recipient", "name", "company", "email", "phone", "step", "role", "channel", "subject", "body", "issues"])
    for i, row in enumerate(audience, 1):
        for step in creatives.steps_for(plan, row):
            if approved_only and step.get("status") != "approved":
                continue
            m = creatives.message(step, row, brief)
            writer.writerow([i, creatives.field(row, "full_name"), creatives.field(row, "company"), m["to"], m["phone"],
                             m["step"], m["role"], m["channel"], m["subject"], m["body"], "; ".join(m["issues"])])
    return Response("\ufeff" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{plan_id}-merged.csv"'})


class Assist(BaseModel):
    text: str
    instruction: str
    brief: dict[str, Any] | None = None


@router.post("/assist")
async def assist(body: Assist):
    """Rewrite one piece of copy (shorten, change tone, subject lines); nothing is saved."""
    from src.agent_runtime.llm import complete

    system = (
        "You edit cold outbound sales copy. Follow the instruction exactly. Keep every {{token}} unchanged. "
        "Plain text only: no preamble, no quotes, no markdown. Do not invent claims, numbers or customers."
    )
    brief = f"\nBrief: {body.brief}" if body.brief else ""
    return {"text": await complete(system, f"Instruction: {body.instruction}{brief}\n\nCopy:\n{body.text}")}
