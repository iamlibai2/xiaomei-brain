"""Gmail remote MCP and REST delivery client."""

from __future__ import annotations

import base64
import mimetypes
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Iterable

import requests

from xiaomei_brain.mcp.remote import RemoteMCPClient, RemoteMCPError


GMAIL_MCP_URL = "https://gmailmcp.googleapis.com/mcp/v1"
GMAIL_API_URL = "https://gmail.googleapis.com/gmail/v1/users/me"


class GmailClientError(RuntimeError):
    pass


class GmailClient:
    """Use Google's official MCP where available and REST only for sending."""

    def __init__(self, access_token: str, *, timeout: float = 30.0) -> None:
        self.access_token = access_token
        self.timeout = timeout
        self._mcp = RemoteMCPClient(GMAIL_MCP_URL, access_token, timeout=timeout)

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}"}

    def profile(self) -> dict[str, Any]:
        return self._rest("GET", f"{GMAIL_API_URL}/profile")

    def mcp_call(self, name: str, arguments: dict[str, Any]) -> Any:
        try:
            return self._mcp.call_tool(name, arguments)
        except RemoteMCPError as exc:
            raise GmailClientError(str(exc)) from exc

    def search(self, query: str, page_size: int = 10) -> Any:
        return self.mcp_call(
            "search_threads",
            {
                "query": query,
                "pageSize": max(1, min(int(page_size), 50)),
                "view": "THREAD_VIEW_MINIMAL",
            },
        )

    def get_message(self, message_id: str) -> Any:
        return self.mcp_call(
            "get_message",
            {"messageId": message_id, "messageFormat": "FULL_CONTENT"},
        )

    def get_thread(self, thread_id: str) -> Any:
        return self.mcp_call(
            "get_thread",
            {"threadId": thread_id, "messageFormat": "FULL_CONTENT"},
        )

    def create_draft(
        self,
        *,
        to: Iterable[str],
        subject: str,
        body: str,
        cc: Iterable[str] = (),
        bcc: Iterable[str] = (),
        reply_to_message_id: str = "",
    ) -> Any:
        arguments: dict[str, Any] = {
            "to": list(to),
            "cc": list(cc),
            "bcc": list(bcc),
            "subject": subject,
            "body": body,
        }
        if reply_to_message_id:
            arguments["replyToMessageId"] = reply_to_message_id
        return self.mcp_call("create_draft", arguments)

    def send(
        self,
        *,
        to: Iterable[str],
        subject: str,
        body: str,
        cc: Iterable[str] = (),
        bcc: Iterable[str] = (),
        attachment_paths: Iterable[Path] = (),
        thread_id: str = "",
        in_reply_to: str = "",
        references: str = "",
    ) -> dict[str, Any]:
        message = EmailMessage()
        message["To"] = ", ".join(to)
        if cc:
            message["Cc"] = ", ".join(cc)
        if bcc:
            message["Bcc"] = ", ".join(bcc)
        message["Subject"] = subject
        if in_reply_to:
            message["In-Reply-To"] = in_reply_to
        if references:
            message["References"] = references
        message.set_content(body)
        for path in attachment_paths:
            content_type, _ = mimetypes.guess_type(path.name)
            maintype, subtype = (
                content_type.split("/", 1)
                if content_type and "/" in content_type
                else ("application", "octet-stream")
            )
            message.add_attachment(
                path.read_bytes(),
                maintype=maintype,
                subtype=subtype,
                filename=path.name,
            )
        payload: dict[str, Any] = {
            "raw": base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
        }
        if thread_id:
            payload["threadId"] = thread_id
        return self._rest("POST", f"{GMAIL_API_URL}/messages/send", json_body=payload)

    def reply(self, message_id: str, body: str, *, reply_all: bool = False) -> dict[str, Any]:
        source = self._rest(
            "GET",
            f"{GMAIL_API_URL}/messages/{message_id}",
            params={"format": "metadata", "metadataHeaders": ["From", "To", "Cc", "Subject", "Message-ID", "References"]},
        )
        headers = {
            str(item.get("name", "")).lower(): str(item.get("value", ""))
            for item in source.get("payload", {}).get("headers", [])
            if isinstance(item, dict)
        }
        sender = headers.get("from", "")
        to = [sender] if sender else []
        cc: list[str] = []
        if reply_all:
            to.extend(self._split_addresses(headers.get("to", "")))
            cc.extend(self._split_addresses(headers.get("cc", "")))
        subject = headers.get("subject", "")
        if subject and not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"
        message_id_header = headers.get("message-id", "")
        references = " ".join(value for value in (headers.get("references", ""), message_id_header) if value)
        return self.send(
            to=to,
            cc=cc,
            subject=subject,
            body=body,
            thread_id=str(source.get("threadId", "")),
            in_reply_to=message_id_header,
            references=references,
        )

    @staticmethod
    def _split_addresses(value: str) -> list[str]:
        return [item.strip() for item in value.split(",") if item.strip()]

    def _rest(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        response = requests.request(
            method,
            url,
            headers={**self.headers, "Content-Type": "application/json"},
            params=params,
            json=json_body,
            timeout=self.timeout,
        )
        try:
            payload = response.json()
        except ValueError:
            payload = {"message": response.text[:1000]}
        if response.status_code >= 400:
            raise GmailClientError(self._error_message(payload, response.status_code))
        return payload if isinstance(payload, dict) else {"result": payload}

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
        return f"Gmail request failed (HTTP {status})"
