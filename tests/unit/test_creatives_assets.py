"""Ad creatives on a campaign: what can be uploaded, what holds a message back, and how a send carries them."""

import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.agent_runtime import assets, creatives
from src.agent_runtime.tools import sales
from src.database import connection, save_artifact, save_creative

IMG = {"id": "creative-img", "chat_id": "chat-1", "mime": "image/png", "url": "", "name": "banner.png", "path": "/x"}


def test_kind_is_the_browser_type_or_the_file_name():
    assert assets.kind_of("banner.png", "image/png") == "image/png"
    assert assets.kind_of("onepager.pdf", "application/octet-stream") == "application/pdf"
    assert assets.kind_of("notes.md") == "text/markdown"
    assert assets.kind_of("setup.exe", "application/x-msdownload") == ""


def test_missing_files_and_unlinked_inline_images_hold_the_message_back():
    step = {"step": 2, "channel": "email", "subject": "Hi", "body": "Hello", "attachments": ["creative-gone"], "inline_image": "creative-img"}
    m = creatives.message(step, {"email": "a@x.com"}, {"opt_out": "Reply STOP", "postal_address": "1 Main St"}, {"creative-img": IMG})
    assert "missing attachment creative-gone" in m["issues"] and "inline image needs a public link" in m["issues"]
    assert set(creatives.blocking(m["issues"])) >= {"missing attachment creative-gone", "inline image needs a public link"}
    assert m["attachments"] == ["creative-gone"] and m["inline_image"] == "creative-img"
    linked = creatives.message({**step, "attachments": []}, {"email": "a@x.com"}, {"opt_out": "x", "postal_address": "y"},
                               {"creative-img": {**IMG, "url": "https://cdn.example.com/b.png"}})
    assert not creatives.blocking(linked["issues"])


def test_html_body_puts_the_image_after_the_first_paragraph_and_escapes_text():
    out = assets.html_body("Hi <Pat>,\n\nSecond para.\nLine two.", "https://cdn.example.com/b.png", 'Spring "sale"')
    assert out.startswith("<p>Hi &lt;Pat&gt;,</p><p><img src=\"https://cdn.example.com/b.png\" alt=\"Spring &quot;sale&quot;\"")
    assert out.endswith("<p>Second para.<br>Line two.</p>")


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(connection.settings, "ROOT_DIR", str(tmp_path))
    monkeypatch.setattr(connection, "_db", None)
    asyncio.run(connection.init_db())
    plan = tmp_path / "campaign_plan-p1.json"
    plan.write_text(json.dumps({"rows": [], "meta": {}}))
    asyncio.run(save_artifact({"id": "campaign_plan-p1", "chat_id": "chat-1", "task_id": None, "persona": "campaign_builder", "kind": "campaign_plan",
                               "title": "Plan", "path": str(plan), "row_count": 0, "source": "", "created_at": "2026-10-04T00:00:00"}))
    yield tmp_path
    asyncio.run(connection.close_db())


def test_upload_list_link_and_delete(env):
    from src.routers import campaigns

    app = FastAPI()
    app.include_router(campaigns.router, prefix="/campaigns")
    client = TestClient(app)
    r = client.post("/campaigns/chat-1/campaign_plan-p1/creatives", files=[("files", ("offer.txt", b"Spring offer: 20% off audits", "text/plain"))])
    c = r.json()["creatives"][0]
    assert c["summary"] == "Spring offer: 20% off audits" and c["path"].startswith(str(env))
    assert client.post("/campaigns/chat-1/campaign_plan-p1/creatives", files=[("files", ("x.exe", b"MZ", "application/x-msdownload"))]).status_code == 415
    assert client.patch(f"/campaigns/creatives/{c['id']}", json={"url": "ftp://nope"}).status_code == 422
    assert client.patch(f"/campaigns/creatives/{c['id']}", json={"url": "https://cdn.example.com/o.txt"}).json()["url"] == "https://cdn.example.com/o.txt"
    assert [x["id"] for x in client.get("/campaigns/chat-1/campaign_plan-p1/creatives").json()["creatives"]] == [c["id"]]
    assert client.delete(f"/campaigns/creatives/{c['id']}").status_code == 200
    assert client.get("/campaigns/chat-1/campaign_plan-p1/creatives").json()["creatives"] == []


def test_a_send_uploads_attachments_and_shows_the_inline_image(env, monkeypatch):
    f = env / "banner.png"
    f.write_bytes(b"png")
    asyncio.run(save_creative({**IMG, "path": str(f), "plan_id": "campaign_plan-p1", "size": 3, "url": "https://cdn.example.com/b.png",
                               "summary": "", "created_at": "2026-10-04T00:00:00"}))
    asyncio.run(save_creative({**IMG, "id": "creative-other", "chat_id": "chat-2", "path": str(f), "plan_id": "p", "size": 3,
                               "summary": "", "created_at": "2026-10-04T00:00:00"}))
    calls = []

    async def upload(path, slug, toolkit):
        return {"name": "banner.png", "mimetype": "image/png", "s3key": f"key-{slug}"}

    async def gmail(user_id, slug, arguments):
        calls.append((slug, arguments))
        return {"successful": True, "data": {}}

    monkeypatch.setattr(sales, "composio_upload", upload)
    monkeypatch.setattr(sales, "gmail_call", gmail)
    ctx = SimpleNamespace(chat_id="chat-1", user_id="u", persona="outreach", task_id=None, emit=None)
    send = next(t for t in sales.build(ctx) if t.name == "gmail_send_email").handler
    asyncio.run(send({"to": "a@x.com", "subject": "Hi", "body": "Hello Pat,\n\nMore.", "attachments": ["creative-img"], "inline_image": "creative-img"}))
    slug, args = calls[0]
    assert slug == "GMAIL_SEND_EMAIL" and args["is_html"] and "<img src=\"https://cdn.example.com/b.png\"" in args["body"]
    assert args["attachment"] == [{"name": "banner.png", "mimetype": "image/png", "s3key": "key-GMAIL_SEND_EMAIL"}]
    refused = asyncio.run(send({"to": "a@x.com", "subject": "Hi", "body": "Hello", "attachments": ["creative-other"]}))
    assert refused.get("is_error") and len(calls) == 1  # another chat's creative is never sent
