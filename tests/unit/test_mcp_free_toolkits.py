"""Composio toolkits that need no sign-in or API key: listed in Connections, added as servers without an auth config."""

import asyncio
from types import SimpleNamespace as NS

from src.routers import mcp


def kit(slug, no_auth=True, tools=3):
    return NS(slug=slug, name=slug.title(), no_auth=no_auth, meta=NS(description=f"{slug} tools", logo=f"logo/{slug}", tools_count=tools))


class Toolkits:
    pages = {None: ([kit("hackernews", tools=14), kit("gmail", no_auth=False), kit("composio")], "p2"),
             "p2": ([kit("browser_tool", tools=5)], None)}

    def list(self, cursor=None, **_):
        items, nxt = self.pages[cursor]
        return NS(items=items, next_cursor=nxt)

    def get(self, slug):
        return NS(name=slug.title(), meta=NS(description="", logo=""))


def fake_client(monkeypatch, created):
    def create(name, toolkits, allowed_tools):
        created.append(toolkits)
        return NS(id="srv_1")

    client = NS(client=NS(toolkits=Toolkits()), toolkits=Toolkits(),
                auth_configs=NS(create=lambda **_: (_ for _ in ()).throw(AssertionError("no auth config for a free toolkit"))),
                mcp=NS(create=create, generate=lambda **_: NS(url="https://mcp/srv_1")))
    monkeypatch.setattr(mcp, "_composio_client", lambda: (client, "key"))
    monkeypatch.setattr(mcp, "_free", {})


def test_lists_free_toolkits_across_pages_and_marks_added_ones(monkeypatch):
    fake_client(monkeypatch, [])
    monkeypatch.setattr(mcp, "server_names", lambda: ["composio-browser-tool"])
    monkeypatch.setattr(mcp, "options", lambda name: {"composio": {"toolkits": ["browser_tool"]}})
    listed = asyncio.run(mcp.composio_free_toolkits())["toolkits"]
    assert [(t["toolkit"], t["tools"], t["server"]) for t in listed] == [("hackernews", 14, None), ("browser_tool", 5, "composio-browser-tool")]


def test_a_free_toolkit_becomes_a_server_without_an_auth_config(monkeypatch):
    created, added = [], {}

    async def none(*_, **__):
        return None

    async def listing():
        return {"toolkits": []}

    async def add(slug, entry):
        added[slug] = entry

    async def describe(slug):
        return {"name": slug}

    async def tools(slug):
        return [{"name": "HACKERNEWS_GET_TOP_STORIES"}]

    fake_client(monkeypatch, created)
    monkeypatch.setattr(mcp, "composio_toolkits", listing)
    monkeypatch.setattr(mcp, "save_mcp_server_flag", none)
    monkeypatch.setattr(mcp, "server_names", lambda: [])
    monkeypatch.setattr(mcp, "add_server", add)
    monkeypatch.setattr(mcp, "store_static_token", none)
    monkeypatch.setattr(mcp.specialists, "refresh", none)
    monkeypatch.setattr(mcp, "_describe", describe)
    monkeypatch.setattr(mcp, "list_tools", tools)
    result = asyncio.run(mcp.create_composio_server(mcp.ComposioServer(toolkits=["hackernews"])))
    assert created == [[{"toolkit": "hackernews"}]]
    assert added["composio-hackernews"]["url"] == "https://mcp/srv_1"
    assert result["tools"] == ["HACKERNEWS_GET_TOP_STORIES"]
