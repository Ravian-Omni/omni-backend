"""newton_upload sends the file itself to Newton: new project or existing one, inside the allowed folders only."""

import asyncio
import base64
from types import SimpleNamespace

from src.agent_runtime.tools import newton


def _tool(tmp_path, monkeypatch):
    calls = []

    async def fake_call(server, name, args):
        calls.append((server, name, args))
        return '{"project_id": "p1"}'

    monkeypatch.setattr("src.mcp_client.call_tool", fake_call)
    ctx = SimpleNamespace(chat_dir=str(tmp_path), working_directory=str(tmp_path), file_location=str(tmp_path),
                          artifacts_dir=str(tmp_path), data_sources=set())
    return next(t for t in newton.build(ctx) if t.name == "newton_upload").handler, calls, ctx


def test_new_project_then_existing_one(tmp_path, monkeypatch):
    (tmp_path / "z.csv").write_text("a,b\n1,2\n")
    upload, calls, ctx = _tool(tmp_path, monkeypatch)
    out = asyncio.run(upload({"path": str(tmp_path / "z.csv"), "title": "Z", "problem": "EDA"}))
    server, name, args = calls[-1]
    assert (server, name, args["title"], args["filename"]) == ("newton", "create_project", "Z", "z.csv")
    assert base64.b64decode(args["content_base64"]) == b"a,b\n1,2\n" and "p1" in out["content"][0]["text"]
    assert ctx.data_sources == {"newton"}
    asyncio.run(upload({"path": "z.csv", "project_id": "p1"}))
    assert calls[-1][1] == "upload_data" and calls[-1][2]["project_id"] == "p1"


def test_refuses_paths_outside_and_oversized_files(tmp_path, monkeypatch):
    upload, calls, _ = _tool(tmp_path, monkeypatch)
    assert asyncio.run(upload({"path": "/etc/hosts"}))["is_error"]
    (tmp_path / "big.csv").write_text("x")
    monkeypatch.setattr(newton, "MAX_BYTES", 0)
    assert asyncio.run(upload({"path": "big.csv"}))["is_error"] and not calls
