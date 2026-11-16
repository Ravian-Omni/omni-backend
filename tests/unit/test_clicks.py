"""Click tracking: links in a sent email go through our redirect and a click reaches Brain_Hands, all off until a public URL
is configured; images are not links, and there is no open-tracking pixel."""

import asyncio
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src import auth
from src.agent_runtime import clicks
from src.agent_runtime.tools import sales
from src.database import connection, get_link
from src.routers import track
from tests.unit.test_brain_hands_push import server
from tests.unit.test_leads import temp_db  # noqa: F401 - the temp_db fixture

BASE = "https://dax.example.com"


def rewrite(body, html=False):
    return asyncio.run(clicks.rewrite(body, html, "Ana@Acme.com", "campaign_plan-p1", 1, "Hello"))


def tokens(text):
    return [part.split()[0].rstrip(".,)") for part in text.split(f"{BASE}/r/")[1:]]


def test_nothing_changes_and_nothing_is_stored_while_no_public_url_is_set(temp_db, monkeypatch):
    monkeypatch.delenv("DAXAGENT_PUBLIC_URL", raising=False)
    body = "Read https://acme.com/case-study today."
    assert rewrite(body) == body


def test_each_link_in_a_plain_text_email_goes_through_its_own_redirect(temp_db, monkeypatch):
    monkeypatch.setenv("DAXAGENT_PUBLIC_URL", BASE + "/")
    out = rewrite("Read https://acme.com/case-study. Or (https://x.co/a?b=1) soon.")
    first, second = tokens(out)
    assert out.startswith(f"Read {BASE}/r/{first}. Or ({BASE}/r/{second}) soon.")  # the punctuation stays outside the link
    link = asyncio.run(get_link(first))
    assert (link["url"], link["recipient"], link["plan_id"], link["step"], link["subject"]) == ("https://acme.com/case-study", "ana@acme.com", "campaign_plan-p1", 1, "Hello")
    assert asyncio.run(get_link(second))["url"] == "https://x.co/a?b=1"


def test_in_html_the_links_change_but_an_image_does_not_and_no_pixel_is_added(temp_db, monkeypatch):
    monkeypatch.setenv("DAXAGENT_PUBLIC_URL", BASE)
    html = '<p>See https://acme.com/x</p><p><a href="https://acme.com/y">y</a></p><p><img src="https://cdn.example.com/banner.png" alt="b"></p>'
    out = rewrite(html, html=True)
    assert 'src="https://cdn.example.com/banner.png"' in out and out.count("<img") == 1  # the image stays, and nothing is added
    assert "https://acme.com/x" not in out and 'href="https://acme.com/y"' not in out and out.count(f"{BASE}/r/") == 2


def test_a_tracked_link_is_open_to_a_recipient_without_a_session():
    assert auth.OPEN.match("/r/abc_-123") and not auth.OPEN.match("/r/") and not auth.OPEN.match("/chats/new_chat")


@pytest.fixture
def client(temp_db):
    app = FastAPI()
    app.include_router(track.router, prefix="/r")
    with TestClient(app) as c:
        yield c


def test_a_click_redirects_is_recorded_and_pushed_to_brain_hands(client, monkeypatch):
    monkeypatch.setenv("DAXAGENT_PUBLIC_URL", BASE)
    seen = server(monkeypatch, 200, 200)
    token = tokens(rewrite("Read https://acme.com/case-study"))[0]
    reply = client.get(f"/r/{token}", follow_redirects=False)
    assert (reply.status_code, reply.headers["location"]) == (302, "https://acme.com/case-study")
    client.get(f"/r/{token}", follow_redirects=False)  # a second click is its own event
    time.sleep(0.5)
    first, second = (json.loads(r.read()) for r in seen)
    assert (first["app"], first["kind"], first["title"]) == ("daxagent", "click", "Hello")
    assert first["data"]["email"] == "ana@acme.com" and first["data"]["url"] == "https://acme.com/case-study"
    assert (first["data"]["campaign_id"], first["data"]["step"]) == ("campaign_plan-p1", 1) and first["data"]["clicked_at"]
    assert first["id"] != second["id"] and first["id"].startswith(f"click:{token}:")


def test_an_unknown_link_is_a_404_and_goes_nowhere(client):
    assert client.get("/r/nope", follow_redirects=False).status_code == 404


def test_the_send_tool_tracks_a_sent_email_but_not_a_blocked_one_or_a_draft(temp_db, tmp_path, monkeypatch):
    monkeypatch.setenv("DAXAGENT_PUBLIC_URL", BASE)
    gmail = AsyncMock(return_value={"successful": True, "data": {}})
    monkeypatch.setattr(sales, "gmail_call", gmail)
    ctx = SimpleNamespace(chat_id="chat-1", user_id="u", persona="outreach", task_id=None, artifacts_dir=str(tmp_path), data_sources=set(), emit=AsyncMock(),
                          decisions=None, send_allowance={"*": 9}, send_approved=set())
    tools = {t.name: t.handler for t in sales.build(ctx)}
    body = "See https://acme.com/case-study"
    asyncio.run(tools["gmail_send_email"]({"to": "ana@acme.com", "subject": "Hi", "body": body}))
    sent = gmail.await_args.args[2]["body"]
    assert f"{BASE}/r/" in sent and "acme.com/case-study" not in sent
    asyncio.run(tools["gmail_send_email"]({"to": "info@acme.com", "subject": "Hi", "body": body}))  # refused by the send gate
    asyncio.run(tools["gmail_create_draft"]({"to": "ana@acme.com", "subject": "Hi", "body": body}))
    assert gmail.await_count == 2 and gmail.await_args.args[2]["body"] == body  # the draft is untouched
    assert asyncio.run(_count()) == 1  # only the one real send made a link


async def _count():
    cursor = await (await connection.get_db()).execute("SELECT count(*) FROM tracked_links")
    return (await cursor.fetchone())[0]
