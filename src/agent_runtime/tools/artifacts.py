"""Typed artifacts: the lists, tables and plans personas hand to each other.

Each artifact is a JSON file under ``<chat_dir>/artifacts`` plus a row in the
``artifacts`` table, and saving one pushes an ``artifact`` message to the
chat so the UI can show it.
"""

import json
import os
import uuid
from typing import Any

from src.agent_runtime.tools.context import ToolContext
from src.configs.datetime_utils import dt
from src.database import get_artifact as db_get_artifact
from src.database import list_artifacts as db_list_artifacts
from src.database import save_artifact as db_save_artifact

KINDS = (
    "lead_list", "buyer_map", "enriched_contacts", "campaign_plan", "send_log",
    "scored_leads", "segments", "analysis", "dataset", "chart", "map", "snippets", "other",
)

# Visual kinds ship their data with the chat event so the UI can draw them at once.
VISUAL_KINDS = ("chart", "map")
VISUAL_PREVIEW_ROWS = 500


def _path(ctx: ToolContext, artifact_id: str) -> str:
    return os.path.join(ctx.artifacts_dir, f"{artifact_id}.json")


def load(ctx: ToolContext, artifact_id: str) -> dict[str, Any]:
    path = _path(ctx, artifact_id)
    if not os.path.exists(path):
        raise FileNotFoundError(f"No artifact '{artifact_id}' in this chat")
    with open(path) as f:
        return json.load(f)


async def load_record(chat_id: str, artifact_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """An artifact's record and payload by id, checked against the chat."""
    record = await db_get_artifact(artifact_id)
    if not record or record["chat_id"] != chat_id or not os.path.exists(record["path"]):
        raise FileNotFoundError(f"No artifact '{artifact_id}' in this chat")
    with open(record["path"]) as f:
        return record, json.load(f)


async def save_payload(record: dict[str, Any], payload: dict[str, Any]) -> None:
    """Rewrite an artifact in place (a user edit from the Console)."""
    payload["row_count"] = record["row_count"] = len(payload.get("rows", []))
    with open(record["path"], "w") as f:
        json.dump(payload, f, indent=1, default=str)
    await db_save_artifact(record)


def _columns(rows: list[dict], given: list[str] | None) -> list[str]:
    if given:
        return given
    seen: dict[str, None] = {}
    for r in rows:
        for k in r:
            seen.setdefault(k, None)
    return list(seen)


async def write(
    ctx: ToolContext,
    kind: str,
    title: str,
    rows: list[dict[str, Any]],
    columns: list[str] | None = None,
    source: str = "",
    artifact_id: str | None = None,
    meta: dict[str, Any] | None = None,
    announce: bool = True,
) -> dict[str, Any]:
    """Create or replace an artifact and (unless announce is False) show it in the chat."""
    artifact_id = artifact_id or f"{kind}-{uuid.uuid4().hex[:8]}"
    os.makedirs(ctx.artifacts_dir, exist_ok=True)
    columns = _columns(rows, columns)
    for i, r in enumerate(rows):
        r.setdefault("_id", i + 1)
    record = {
        "id": artifact_id,
        "chat_id": ctx.chat_id,
        "task_id": ctx.task_id,
        "persona": ctx.persona,
        "kind": kind if kind in KINDS else "other",
        "title": title,
        "path": _path(ctx, artifact_id),
        "row_count": len(rows),
        "source": source,
        "created_at": dt.now_iso(),
    }
    meta = {**(meta or {}), "rev": int((meta or {}).get("rev") or 0) + 1}  # lets the Console spot agent edits
    payload = {**record, "columns": columns, "rows": rows, "meta": meta}
    with open(record["path"], "w") as f:
        json.dump(payload, f, indent=1, default=str)
    await db_save_artifact(record)
    if not announce:
        return record
    preview = rows[:VISUAL_PREVIEW_ROWS] if record["kind"] in VISUAL_KINDS else rows[:10]
    await ctx.emit(
        {
            "type": "artifact",
            "artifact": {**record, "columns": columns, "preview": preview, "meta": meta or {}},
        }
    )
    return record


def _text(payload: Any) -> dict:
    return {"content": [{"type": "text", "text": payload if isinstance(payload, str) else json.dumps(payload, default=str)}]}


def _error(msg: str) -> dict:
    return {"content": [{"type": "text", "text": msg}], "is_error": True}


def build(ctx: ToolContext):
    """Return the artifact tools bound to a session."""
    from claude_agent_sdk import tool

    @tool(
        "save_artifact",
        "Save a list or table as a named artifact other personas and the user can see. "
        f"kind is one of {', '.join(KINDS)}. rows is a list of objects with the same keys. "
        "Returns the artifact id to refer to it later.",
        {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": list(KINDS)},
                "title": {"type": "string"},
                "rows": {"type": "array", "items": {"type": "object"}},
                "columns": {"type": "array", "items": {"type": "string"}, "description": "Column order; defaults to the keys of the rows"},
                "source": {"type": "string", "description": "Where the rows came from, e.g. 'Data Axle business_search, SIC 8021, Austin TX'"},
                "meta": {"type": "object", "description": "Anything else worth keeping with the artifact"},
            },
            "required": ["kind", "title", "rows"],
        },
    )
    async def save_artifact(args: dict) -> dict:
        rows = args.get("rows") or []
        if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows):
            return _error("rows must be a list of objects")
        record = await write(ctx, args["kind"], args["title"], rows, args.get("columns"), args.get("source", ""), meta=args.get("meta"))
        return _text({"artifact_id": record["id"], "row_count": record["row_count"], "path": record["path"]})

    @tool("list_artifacts", "List the artifacts saved in this chat (id, kind, title, row count, source).", {"type": "object", "properties": {}})
    async def list_artifacts(args: dict) -> dict:
        rows = await db_list_artifacts(ctx.chat_id)
        return _text([{k: r[k] for k in ("id", "kind", "title", "row_count", "source", "persona", "created_at")} for r in rows])

    @tool(
        "read_artifact",
        "Read rows of an artifact by id. Use offset and limit to page through large lists.",
        {
            "type": "object",
            "properties": {
                "artifact_id": {"type": "string"},
                "offset": {"type": "integer", "minimum": 0},
                "limit": {"type": "integer", "minimum": 1, "maximum": 500},
            },
            "required": ["artifact_id"],
        },
    )
    async def read_artifact(args: dict) -> dict:
        try:
            payload = load(ctx, args["artifact_id"])
        except FileNotFoundError as e:
            return _error(str(e))
        offset = int(args.get("offset") or 0)
        limit = int(args.get("limit") or 100)
        rows = payload["rows"][offset : offset + limit]
        return _text({
            "artifact_id": payload["id"], "kind": payload["kind"], "title": payload["title"],
            "columns": payload["columns"], "row_count": payload["row_count"],
            "offset": offset, "rows": rows, "meta": payload.get("meta", {}),
        })

    @tool(
        "update_artifact",
        "Replace the rows of an artifact, or remove rows by their _id. Keeps the same artifact id.",
        {
            "type": "object",
            "properties": {
                "artifact_id": {"type": "string"},
                "rows": {"type": "array", "items": {"type": "object"}, "description": "Full replacement rows"},
                "remove_ids": {"type": "array", "items": {"type": "integer"}, "description": "_id values to drop"},
                "base_rev": {"type": "integer", "description": "meta.rev from your read_artifact; required with rows"},
                "title": {"type": "string"},
            },
            "required": ["artifact_id"],
        },
    )
    async def update_artifact(args: dict) -> dict:
        try:
            payload = load(ctx, args["artifact_id"])
        except FileNotFoundError as e:
            return _error(str(e))
        rev = int((payload.get("meta") or {}).get("rev") or 0)
        if args.get("rows") is not None and int(args.get("base_rev") or 0) != rev:
            # The user may have edited it in the Console since you read it; replacing rows would lose that.
            return _error(f"'{payload['id']}' changed since you read it (now rev {rev}). read_artifact again and reapply your change with base_rev {rev}.")
        rows = args.get("rows") if args.get("rows") is not None else payload["rows"]
        if args.get("remove_ids"):
            drop = set(args["remove_ids"])
            rows = [r for r in rows if r.get("_id") not in drop]
        record = await write(
            ctx, payload["kind"], args.get("title") or payload["title"], rows, payload.get("columns"),
            payload.get("source", ""), artifact_id=payload["id"], meta=payload.get("meta"),
        )
        return _text({"artifact_id": record["id"], "row_count": record["row_count"]})

    return [save_artifact, list_artifacts, read_artifact, update_artifact]
