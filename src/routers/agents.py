"""Read endpoints for the agent runtime: personas, artifacts, decision log."""

import csv
import io
import json
import os
import re

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from src.agent_runtime import PERSONAS
from src.database import get_artifact, list_artifacts, list_decisions

router = APIRouter()


@router.get("/personas")
async def personas():
    """The personas the runtime offers, for pickers and cards in the UI."""
    from src.agent_runtime import specialists

    everyone = list(PERSONAS.values()) + list(specialists.all().values())
    return {
        "personas": [
            {
                "name": p.name, "display_name": p.display_name, "tagline": p.tagline, "kind": p.kind,
                "server": p.server, "icon": p.icon, "remote_mcp": p.remote_mcp, "tools": p.daxagent_tools,
            }
            for p in everyone
        ]
    }


@router.post("/personas/refresh")
async def refresh_personas():
    """Rebuild the connected-app specialists (after servers change)."""
    from src.agent_runtime import specialists

    built = await specialists.refresh()
    return {"specialists": list(built)}


@router.get("/artifacts/{chat_id}")
async def artifacts(chat_id: str):
    """Artifacts saved in a chat, newest first (metadata only)."""
    return {"chat_id": chat_id, "artifacts": await list_artifacts(chat_id)}


@router.get("/artifacts/{chat_id}/{artifact_id}")
async def artifact(chat_id: str, artifact_id: str, offset: int = 0, limit: int = 200):
    """One artifact with its rows (paged)."""
    records = {a["id"]: a for a in await list_artifacts(chat_id)}
    record = records.get(artifact_id)
    if not record or not os.path.exists(record["path"]):
        raise HTTPException(status_code=404, detail=f"Unknown artifact {artifact_id}")
    with open(record["path"]) as f:
        payload = json.load(f)
    rows = payload.get("rows", [])
    return {**record, "columns": payload.get("columns", []), "meta": payload.get("meta", {}),
            "offset": offset, "rows": rows[offset : offset + limit]}


@router.get("/decisions/{chat_id}")
async def decisions(chat_id: str):
    """Every confirmation card shown in a chat and what the user answered."""
    return {"chat_id": chat_id, "decisions": await list_decisions(chat_id)}


def _export_columns(payload: dict) -> list[str]:
    """Columns in artifact order, with any extra row keys appended; the internal _id is dropped."""
    cols = [c for c in payload.get("columns", []) if c != "_id"]
    seen = set(cols)
    for row in payload.get("rows", []):
        for k in row:
            if k != "_id" and k not in seen:
                seen.add(k)
                cols.append(k)
    return cols


def _cell(value):
    if value is None:
        return ""
    if isinstance(value, dict | list):
        return json.dumps(value, ensure_ascii=False)
    return value


@router.get("/download/{artifact_id}")
async def download_artifact(artifact_id: str, format: str = "csv"):
    """Download every row of an artifact as csv, xlsx or json."""
    record = await get_artifact(artifact_id)
    if not record or not os.path.exists(record["path"]):
        raise HTTPException(status_code=404, detail=f"Unknown artifact {artifact_id}")
    with open(record["path"]) as f:
        payload = json.load(f)
    rows = payload.get("rows", [])
    columns = _export_columns(payload)
    slug = re.sub(r"[^A-Za-z0-9]+", "-", record["title"]).strip("-")[:60] or record["kind"]
    filename = f"{slug}-{artifact_id}"

    if format == "json":
        body = json.dumps({"id": record["id"], "kind": record["kind"], "title": record["title"],
                           "source": record.get("source"), "columns": columns,
                           "rows": [{c: r.get(c) for c in columns} for r in rows]},
                          ensure_ascii=False, indent=1)
        return Response(body, media_type="application/json",
                        headers={"Content-Disposition": f'attachment; filename="{filename}.json"'})
    if format == "xlsx":
        from openpyxl import Workbook

        wb = Workbook()
        ws = wb.active
        ws.title = record["kind"][:31]
        ws.append(columns)
        for r in rows:
            ws.append([_cell(r.get(c)) for c in columns])
        buf = io.BytesIO()
        wb.save(buf)
        return Response(buf.getvalue(),
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f'attachment; filename="{filename}.xlsx"'})
    if format != "csv":
        raise HTTPException(status_code=400, detail="format must be csv, xlsx or json")
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(columns)
    for r in rows:
        writer.writerow([_cell(r.get(c)) for c in columns])
    return Response("\ufeff" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{filename}.csv"'})
