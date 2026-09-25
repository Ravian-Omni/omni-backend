"""Visual artifacts: charts and maps the UI renders as interactive components.

A chart is an artifact of kind ``chart`` whose rows are the data points and
whose ``meta.chart`` holds the spec (chart type, x key, series). A map is an
artifact of kind ``map`` whose rows are the located points and whose
``meta.map`` holds the display hints. Both download as CSV/Excel like any
other artifact and are rebuilt from history after a refresh.
"""

from typing import Any

from src.agent_runtime.geo import locate_points, normalize_state
from src.agent_runtime.tools import artifacts
from src.agent_runtime.tools.context import ToolContext

CHART_TYPES = ("bar", "horizontal_bar", "stacked_bar", "line", "area", "pie", "scatter")
VALUE_FORMATS = ("number", "currency", "percent")
MAX_CHART_POINTS = 2000
MAX_MAP_POINTS = 2000


def _series_list(raw: Any) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for s in raw or []:
        if isinstance(s, str):
            out.append({"key": s, "label": s})
        elif isinstance(s, dict) and s.get("key"):
            out.append({"key": str(s["key"]), "label": str(s.get("label") or s["key"]), **({"color": s["color"]} if s.get("color") else {})})
    return out


def build(ctx: ToolContext):
    from claude_agent_sdk import tool

    _text, _error = artifacts._text, artifacts._error

    @tool(
        "save_chart",
        "Save a chart the user sees as an interactive visualization (bar, horizontal_bar, stacked_bar, line, "
        "area, pie or scatter). data is a list of objects; x_key names the category/x field; series lists the "
        "numeric fields to plot (for pie: one series holding the slice values). Use it whenever a comparison, "
        "distribution, trend or breakdown would be clearer as a picture than as a table. Returns the artifact id.",
        {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "chart_type": {"type": "string", "enum": list(CHART_TYPES)},
                "data": {"type": "array", "items": {"type": "object"}, "description": "Data points, one object per x value (or per point for scatter)"},
                "x_key": {"type": "string", "description": "Field used for the x axis / category / pie slice name"},
                "series": {
                    "type": "array",
                    "items": {"anyOf": [{"type": "string"}, {"type": "object", "properties": {"key": {"type": "string"}, "label": {"type": "string"}, "color": {"type": "string"}}, "required": ["key"]}]},
                    "description": "Numeric fields to plot, as keys or {key,label,color}",
                },
                "x_label": {"type": "string"},
                "y_label": {"type": "string"},
                "value_format": {"type": "string", "enum": list(VALUE_FORMATS), "description": "How to format values on axes and tooltips"},
                "description": {"type": "string", "description": "One sentence on what the chart shows, shown under the title"},
                "source": {"type": "string", "description": "Where the numbers came from (artifact id, dataset, query)"},
                "artifact_id": {"type": "string", "description": "Existing chart artifact to replace"},
            },
            "required": ["title", "chart_type", "data", "x_key", "series"],
        },
    )
    async def save_chart(args: dict) -> dict:
        data = args.get("data") or []
        if not isinstance(data, list) or not data or any(not isinstance(r, dict) for r in data):
            return _error("data must be a non-empty list of objects")
        if len(data) > MAX_CHART_POINTS:
            return _error(f"Too many data points ({len(data)}); aggregate to at most {MAX_CHART_POINTS}")
        chart_type = args.get("chart_type")
        if chart_type not in CHART_TYPES:
            return _error(f"chart_type must be one of {', '.join(CHART_TYPES)}")
        x_key = str(args.get("x_key") or "")
        series = _series_list(args.get("series"))
        if not series:
            return _error("series must name at least one numeric field")
        keys = {k for r in data for k in r}
        missing = [k for k in [x_key, *(s["key"] for s in series)] if k not in keys]
        if missing:
            return _error(f"Fields not present in data: {', '.join(missing)}. Available: {', '.join(sorted(keys))}")
        spec = {
            "chart_type": chart_type,
            "x_key": x_key,
            "series": series,
            "x_label": args.get("x_label") or "",
            "y_label": args.get("y_label") or "",
            "value_format": args.get("value_format") if args.get("value_format") in VALUE_FORMATS else "number",
            "description": args.get("description") or "",
        }
        columns = [x_key, *[s["key"] for s in series], *[k for k in keys if k != x_key and k not in {s["key"] for s in series}]]
        record = await artifacts.write(
            ctx, "chart", args["title"], [dict(r) for r in data], columns, args.get("source", ""),
            artifact_id=args.get("artifact_id"), meta={"chart": spec},
        )
        return _text({"artifact_id": record["id"], "points": record["row_count"], "chart_type": chart_type})

    @tool(
        "save_map",
        "Save a map the user sees as an interactive component. points is a list of objects with a label and "
        "either lat/lng or city/state (US city names are geocoded, unknown cities fall back to the state centre). "
        "Optional per point: value (marker size), group (marker colour), and any other fields shown in the popup. "
        "Use it for anything geographic: where the leads are, territory coverage, contacts by region. Returns the artifact id.",
        {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "points": {"type": "array", "items": {"type": "object"}, "description": "One object per place: label, lat/lng or city/state, optional value and group"},
                "value_label": {"type": "string", "description": "What 'value' means, e.g. 'employees' or 'leads'"},
                "description": {"type": "string", "description": "One sentence on what the map shows"},
                "source": {"type": "string", "description": "Where the points came from (artifact id, search)"},
                "artifact_id": {"type": "string", "description": "Existing map artifact to replace"},
            },
            "required": ["title", "points"],
        },
    )
    async def save_map(args: dict) -> dict:
        points = args.get("points") or []
        if not isinstance(points, list) or not points or any(not isinstance(p, dict) for p in points):
            return _error("points must be a non-empty list of objects")
        if len(points) > MAX_MAP_POINTS:
            return _error(f"Too many points ({len(points)}); aggregate by city or state to at most {MAX_MAP_POINTS}")
        rows = [dict(p) for p in points]
        for r in rows:
            if r.get("state"):
                r["state"] = normalize_state(r["state"])
            r.setdefault("label", r.get("name") or r.get("masked_name") or r.get("city") or "")
        counts = await locate_points(rows)
        placed = [r for r in rows if r.get("lat") is not None]
        if not placed:
            return _error("None of the points could be placed: give lat/lng or a US city and state")
        groups = sorted({str(r["group"]) for r in rows if r.get("group") not in (None, "")})
        spec = {
            "value_label": args.get("value_label") or "",
            "description": args.get("description") or "",
            "groups": groups[:12],
            "placed": len(placed),
            "unplaced": len(rows) - len(placed),
            "geo_sources": counts,
            "center": [sum(r["lat"] for r in placed) / len(placed), sum(r["lng"] for r in placed) / len(placed)],
        }
        fixed = ["label", "city", "state", "value", "group", "lat", "lng", "geo_source"]
        columns = [c for c in fixed if any(c in r for r in rows)] + [k for k in {k for r in rows for k in r} if k not in fixed]
        record = await artifacts.write(
            ctx, "map", args["title"], rows, columns, args.get("source", ""),
            artifact_id=args.get("artifact_id"), meta={"map": spec},
        )
        return _text({"artifact_id": record["id"], "points": len(rows), "placed": len(placed), "geo_sources": counts})

    return [save_chart, save_map]
