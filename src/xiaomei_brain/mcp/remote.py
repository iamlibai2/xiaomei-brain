"""Small synchronous client for stateless remote MCP tool servers.

This transport is intentionally provider-neutral. Person/account selection and
OAuth token lifecycle belong to the capability that creates a client instance.
"""

from __future__ import annotations

import json
from typing import Any

import requests


class RemoteMCPError(RuntimeError):
    pass


class RemoteMCPClient:
    def __init__(
        self,
        server_url: str,
        access_token: str,
        *,
        timeout: float = 30.0,
        session: requests.Session | None = None,
    ) -> None:
        self.server_url = server_url.rstrip("/")
        self.access_token = access_token
        self.timeout = timeout
        self.session = session or requests.Session()
        self._request_id = 0

    def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        self._request_id += 1
        response = self.session.post(
            self.server_url,
            headers={
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            },
            json={
                "jsonrpc": "2.0",
                "id": self._request_id,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            },
            timeout=self.timeout,
        )
        payload = self._response_payload(response)
        if response.status_code >= 400:
            raise RemoteMCPError(self._error_message(payload, response.status_code))
        if isinstance(payload, dict) and payload.get("error"):
            raise RemoteMCPError(str(payload["error"]))
        result = payload.get("result", payload) if isinstance(payload, dict) else payload
        return self._unwrap_content(result)

    @staticmethod
    def _response_payload(response: requests.Response) -> Any:
        content_type = response.headers.get("content-type", "").lower()
        if "text/event-stream" not in content_type:
            try:
                return response.json()
            except ValueError:
                return {"message": response.text[:2000]}
        payload: Any = {}
        for line in response.text.splitlines():
            if not line.startswith("data:"):
                continue
            try:
                payload = json.loads(line[5:].strip())
            except json.JSONDecodeError:
                continue
        return payload

    @staticmethod
    def _unwrap_content(result: Any) -> Any:
        if not isinstance(result, dict):
            return result
        if result.get("isError"):
            raise RemoteMCPError(str(result.get("content") or "Remote MCP tool failed"))
        structured = result.get("structuredContent")
        if structured is not None:
            return structured
        content = result.get("content")
        if not isinstance(content, list):
            return result
        texts = [
            str(item.get("text", ""))
            for item in content
            if isinstance(item, dict) and item.get("type") == "text"
        ]
        if len(texts) == 1:
            try:
                return json.loads(texts[0])
            except json.JSONDecodeError:
                return texts[0]
        return texts

    @staticmethod
    def _error_message(payload: Any, status: int) -> str:
        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict):
                return str(error.get("message") or error)
            if error:
                return str(error)
            if payload.get("message"):
                return str(payload["message"])
        return f"Remote MCP request failed (HTTP {status})"
