"""Agent runtime endpoints: personas, artifacts (read, download, user edits), decision log."""

import csv
import io
import json
import os
import re
from typing import Any

from loguru import logger
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, ValidationError

from src.agent_runtime import PERSONAS, prefs
from src.agent_runtime.tools.artifacts import load_record, save_payload
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


class PrefValue(BaseModel):
    value: Any


def _pref_key(key: str) -> None:
    if key not in prefs.SCHEMAS:
        raise HTTPException(status_code=404, detail=f"Unknown setting '{key}' (use {', '.join(prefs.SCHEMAS)})")


@router.get("/prefs/{key}")
async def get_prefs(key: str, user_id: str = "local_user"):
    """The user's saved memory, per-agent instructions or workflows."""
    _pref_key(key)
    return {"value": await prefs.get(user_id, key)}


@router.put("/prefs/{key}")
async def put_prefs(key: str, body: PrefValue, user_id: str = "local_user"):
    """Replace one of them; new chats and tasks pick the change up."""
    _pref_key(key)
    try:
        return {"value": await prefs.put(user_id, key, body.value)}
    except ValidationError as e:
        err = e.errors()[0]
        raise HTTPException(status_code=422, detail=f"{'.'.join(map(str, err['loc']))}: {err['msg']}")


@router.get("/apps")
async def app_agents_status(user_id: str = "local_user") -> dict:
    """The app agents (Salesforce, HubSpot, Slack, Gmail): what each does, whether its app is connected,
    and whether it is used in tasks (switching it off keeps it out of tasks; chat can still use the app)."""
    import asyncio

    from src.agent_runtime import app_agents, specialists
    from src.mcp_client import options, server_names
    from src.mcp_client.config import in_mode, is_enabled

    connected: set[str] = set()
    try:
        from src.routers.mcp import _composio_client

        client, _ = _composio_client()
        conns = await asyncio.to_thread(client.connected_accounts.list, user_ids=[user_id])
        connected = {c.toolkit.slug.lower() for c in conns.items if c.toolkit and c.status == "ACTIVE"}
    except Exception as e:
        logger.warning(f"App agents: Composio connections unavailable: {e}")
    servers = {app_agents.toolkit_of(options(name)): name for name in server_names() if app_agents.toolkit_of(options(name))}
    out = []
    for toolkit, a in app_agents.APPS.items():
        server = servers.get(toolkit)
        persona = specialists._by_server.get(server) if server else None
        out.append({
            "toolkit": toolkit, "agent": a["agent"], "app": a["app"], "tagline": a["tagline"], "abilities": a["abilities"],
            "icon": (options(server).get("icon", "") if server else "") or a["logo"], "connected": toolkit in connected, "server": server,
            "in_tasks": bool(server and is_enabled(server) and in_mode(server, "task")), "persona": persona,
        })
    return {"apps": out}


@router.get("/suggestions")
async def starter_prompts(mode: str = "chat", user_id: str = "local_user"):
    """Fill-in-the-blank starter prompts for the home screen, written from the user's own work."""
    from src.agent_runtime.suggestions import suggestions

    return {"templates": await suggestions(user_id, mode)}


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


class ArtifactEdit(BaseModel):
    rows: list[dict[str, Any]] | None = None
    meta: dict[str, Any] | None = None  # merged into the existing meta
    base_rev: int | None = None  # the rev the editor loaded; a mismatch means someone else saved since


@router.patch("/artifacts/{chat_id}/{artifact_id}")
async def edit_artifact(chat_id: str, artifact_id: str, body: ArtifactEdit):
    """Save a user edit (Console) to an artifact's rows or meta."""
    try:
        record, payload = await load_record(chat_id, artifact_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    meta = payload.setdefault("meta", {})
    rev = int(meta.get("rev") or 0)
    if body.base_rev is not None and body.base_rev != rev:
        raise HTTPException(status_code=409, detail={"message": "Changed since you loaded it", "rev": rev})
    if body.rows is not None:
        payload["rows"] = body.rows
    meta.update(body.meta or {})
    meta["rev"] = rev + 1
    await save_payload(record, payload)
    return {"rev": meta["rev"], "row_count": record["row_count"]}


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
