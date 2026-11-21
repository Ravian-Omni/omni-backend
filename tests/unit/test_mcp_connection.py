"""A tool call never waits for ever: a session that dies under it fails it, and one that hangs is dropped at the time limit."""

import asyncio
from contextlib import asynccontextmanager

import pytest

from src.mcp_client import client


def fake_session(monkeypatch, tool_call):
    @asynccontextmanager
    async def session_cm(*a):
        yield None, None, None

    class Session:
        def __init__(self, *a):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def initialize(self):
            pass

        call_tool = staticmethod(tool_call)

    async def _session(server):
        return session_cm()

    monkeypatch.setattr(client, "_session", _session)
    monkeypatch.setattr(client, "ClientSession", Session)


def test_a_call_cut_off_by_a_dying_session_fails_instead_of_hanging(monkeypatch):
    async def call_tool(tool, args):
        raise asyncio.CancelledError  # the transport's task group cancels the call: not an Exception

    fake_session(monkeypatch, call_tool)

    async def go():
        return await asyncio.wait_for(client._Connection("srv").call("t", {}), 5)

    with pytest.raises(ConnectionError, match="MCP connection to srv closed"):
        asyncio.run(go())


def test_a_hung_call_times_out_and_its_connection_is_dropped(monkeypatch):
    monkeypatch.setattr(client, "CALL_TIMEOUT_S", 0.2)

    async def call_tool(tool, args):
        await asyncio.sleep(60)

    fake_session(monkeypatch, call_tool)

    async def go():
        conn = client._Connection("srv")
        with pytest.raises(TimeoutError, match="srv.t gave no answer in 0.2 s"):
            await conn.call("t", {})
        await asyncio.sleep(0.05)
        return conn.task.done()

    assert asyncio.run(go()) is True
