from __future__ import annotations

from types import SimpleNamespace

import pytest

from xiaomei_brain.mcp.remote import RemoteMCPClient, RemoteMCPError


class _Session:
    def __init__(self, response):
        self.response = response
        self.request = None

    def post(self, url, **kwargs):
        self.request = (url, kwargs)
        return self.response


def test_remote_mcp_unwraps_structured_json_and_authenticates():
    response = SimpleNamespace(
        status_code=200,
        headers={"content-type": "application/json"},
        text="",
        json=lambda: {"jsonrpc": "2.0", "id": 1, "result": {"structuredContent": {"ok": True}}},
    )
    session = _Session(response)
    client = RemoteMCPClient("https://example.com/mcp", "person-token", session=session)

    assert client.call_tool("search", {"q": "hello"}) == {"ok": True}
    assert session.request[1]["headers"]["Authorization"] == "Bearer person-token"
    assert session.request[1]["json"]["params"] == {
        "name": "search",
        "arguments": {"q": "hello"},
    }


def test_remote_mcp_parses_sse_and_reports_tool_error():
    response = SimpleNamespace(
        status_code=200,
        headers={"content-type": "text/event-stream"},
        text='event: message\ndata: {"jsonrpc":"2.0","id":1,"result":{"isError":true,"content":[{"type":"text","text":"denied"}]}}\n\n',
    )
    client = RemoteMCPClient("https://example.com/mcp", "token", session=_Session(response))

    with pytest.raises(RemoteMCPError, match="denied"):
        client.call_tool("send", {})
