"""Campaign Console endpoints: preview, merged export and copy assist for campaign_plan artifacts."""

import csv
import io
from collections import Counter
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from src.agent_runtime import creatives
from src.agent_runtime.tools.artifacts import load_record

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


@router.get("/{chat_id}/{plan_id}/preview")
async def preview(chat_id: str, plan_id: str, recipient: int = 0):
    """Every step as one recipient will get it, plus issue counts across the whole audience."""
    plan, audience = await _plan_and_audience(chat_id, plan_id)
    brief = (plan.get("meta") or {}).get("brief") or {}
    counts = Counter(
        issue for row in audience for step in creatives.steps_for(plan, row)
        for issue in creatives.message(step, row, brief)["issues"]
    )
    row = audience[recipient] if 0 <= recipient < len(audience) else {}
    return {
        "recipients": len(audience),
        "index": recipient,
        "recipient": {k: creatives.field(row, k) for k in ("full_name", "company", "title", "email", "phone", "city", "state")},
        "messages": [creatives.message(step, row, brief) for step in creatives.steps_for(plan, row)],
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
