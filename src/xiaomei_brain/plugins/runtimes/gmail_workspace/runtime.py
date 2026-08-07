"""Person-scoped configuration and OAuth runtime for Gmail."""

from __future__ import annotations

import json
import secrets
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlparse

import requests

from xiaomei_brain.capabilities.runtime import CapabilityRuntimeState
from xiaomei_brain.external_accounts import ExternalAccountStore

from .client import GmailClient, GmailClientError


AUTHORIZATION_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
DEFAULT_REDIRECT_URI = "http://127.0.0.1:19768/oauth/gmail/callback"
DEFAULT_SCOPES = (
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
)


@dataclass
class _SetupJob:
    id: str
    action: str
    person_id: str
    state: str = "running"
    output: str = ""
    error: str = ""
    urls: list[str] = field(default_factory=list)
    callback_mode: str = ""
    started_at: float = field(default_factory=time.time)
    completed_at: float | None = None
    cancel_requested: bool = False
    oauth_state: str = field(default="", repr=False)
    callback_received: bool = field(default=False, repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "action": self.action,
            "state": self.state,
            "output": self.output[-12_000:],
            "error": self.error,
            "urls": list(self.urls),
            "callback_mode": self.callback_mode,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }


class GmailRuntime:
    capability_id = "gmail"
    _ACTIONS = frozenset({"configure", "authorize", "disconnect"})

    def __init__(
        self,
        *,
        agent_dir: str | Path,
        account_store: ExternalAccountStore,
    ) -> None:
        self.agent_dir = Path(agent_dir).resolve()
        self.account_store = account_store
        self.config_path = self.agent_dir / "config.json"
        self._jobs: dict[str, _SetupJob] = {}
        self._latest_job: dict[str, str] = {}
        self._lock = threading.RLock()

    def inspect(self, person_id: str = "") -> CapabilityRuntimeState:
        app = self._app_config()
        configured = bool(app.get("client_id") and app.get("client_secret"))
        details: dict[str, Any] = {
            "configured": configured,
            "authenticated": False,
            "setup_forms": [
                {
                    "action": "configure",
                    "scope": "agent",
                    "action_label": "配置应用",
                    "title": "配置 Google OAuth 应用",
                    "description": "这套应用凭据属于当前 Agent，连接的 Gmail 账户仍按人物分别保存。",
                    "submit_label": "保存配置",
                    "fields": [
                        {
                            "key": "client_id",
                            "label": "OAuth Client ID",
                            "type": "text",
                            "required": True,
                            "value": str(app.get("client_id") or ""),
                        },
                        {
                            "key": "client_secret",
                            "label": "OAuth Client Secret",
                            "type": "secret",
                            "required": True,
                            "configured": bool(app.get("client_secret")),
                        },
                        {
                            "key": "redirect_uri",
                            "label": "授权回调地址",
                            "type": "text",
                            "required": True,
                            "value": str(app.get("redirect_uri") or DEFAULT_REDIRECT_URI),
                        },
                    ],
                },
            ],
            "documentation_url": "https://developers.google.com/workspace/gmail/api/guides/configure-mcp-server",
        }
        if not configured:
            return CapabilityRuntimeState(
                False,
                "needs_configuration",
                "需要配置 Google OAuth 应用",
                details,
                ("configure",),
            )
        if not person_id:
            return CapabilityRuntimeState(
                False,
                "person_required",
                "需要先确认当前人物身份",
                details,
                (),
            )
        account = self.account_store.get_active(person_id, "gmail")
        if account is None:
            return CapabilityRuntimeState(
                False,
                "needs_authorization",
                "Gmail 账户尚未连接",
                details,
                ("configure", "authorize"),
            )
        details.update(
            {
                "authenticated": True,
                "email": account.subject,
                "name": account.display_name,
                "scopes": list(account.scopes),
            }
        )
        try:
            self.access_token(person_id)
        except (RuntimeError, GmailClientError) as exc:
            details["error"] = str(exc)
            return CapabilityRuntimeState(
                False,
                "authorization_expired",
                "Gmail 授权已失效，需要重新连接",
                details,
                ("authorize", "disconnect"),
            )
        return CapabilityRuntimeState(
            True,
            "ready",
            "Gmail 账户已连接",
            details,
            ("configure", "disconnect"),
        )

    def start(
        self,
        action: str,
        person_id: str,
        parameters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        action = str(action).strip().lower()
        if action not in self._ACTIONS:
            raise ValueError(f"Gmail 不支持配置动作: {action}")
        if not person_id:
            raise ValueError("当前连接没有经过验证的人物身份")
        job = _SetupJob(uuid.uuid4().hex, action, person_id)
        with self._lock:
            previous_id = self._latest_job.get(person_id)
            previous = self._jobs.get(previous_id or "")
            if previous is not None and previous.state == "running":
                raise RuntimeError("当前人物已有 Gmail 配置任务正在执行")
            self._jobs[job.id] = job
            self._latest_job[person_id] = job.id

        if action == "authorize":
            self._prepare_authorization(job)
            return job.to_dict()
        threading.Thread(
            target=self._run_simple_action,
            args=(job, dict(parameters or {})),
            daemon=True,
        ).start()
        return job.to_dict()

    def job_status(self, person_id: str, job_id: str = "") -> dict[str, Any] | None:
        with self._lock:
            selected = job_id or self._latest_job.get(person_id, "")
            job = self._jobs.get(selected)
            return job.to_dict() if job is not None and job.person_id == person_id else None

    def cancel(self, person_id: str, job_id: str = "") -> dict[str, Any] | None:
        with self._lock:
            selected = job_id or self._latest_job.get(person_id, "")
            job = self._jobs.get(selected)
            if job is None or job.person_id != person_id:
                return None
            job.cancel_requested = True
            if job.state == "running":
                job.state = "failed"
                job.error = "配置已取消"
                job.completed_at = time.time()
            return job.to_dict()

    def complete(
        self,
        person_id: str,
        job_id: str,
        parameters: dict[str, Any],
    ) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.person_id != person_id:
                return None
            if job.action != "authorize" or job.state != "running":
                raise RuntimeError("该 Gmail 授权任务不再接受回调")
            if job.callback_received:
                raise RuntimeError("Gmail 授权回调已经提交")
            job.callback_received = True
        code = str(parameters.get("code") or "").strip()
        state = str(parameters.get("state") or "").strip()
        error = str(parameters.get("error") or "").strip()
        threading.Thread(
            target=self._complete_authorization,
            args=(job, code, state, error),
            daemon=True,
        ).start()
        return job.to_dict()

    def client_for(self, person_id: str) -> GmailClient:
        return GmailClient(self.access_token(person_id))

    def access_token(self, person_id: str) -> str:
        account = self.account_store.get_active(person_id, "gmail")
        if account is None:
            raise RuntimeError("当前人物尚未连接 Gmail 账户")
        credentials = self.account_store.credentials(account.account_id)
        token = str(credentials.get("access_token") or "")
        expires_at = float(credentials.get("expires_at") or 0)
        if token and expires_at > time.time() + 60:
            return token
        refresh_token = str(credentials.get("refresh_token") or "")
        if not refresh_token:
            raise RuntimeError("Gmail 授权没有可用的 refresh token")
        app = self._require_app_config()
        response = requests.post(
            TOKEN_URL,
            data={
                "client_id": app["client_id"],
                "client_secret": app["client_secret"],
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
            timeout=30,
        )
        payload = self._json_response(response)
        if response.status_code >= 400 or not payload.get("access_token"):
            raise RuntimeError(str(payload.get("error_description") or payload.get("error") or "Gmail token refresh failed"))
        credentials.update(payload)
        credentials["refresh_token"] = refresh_token
        credentials["expires_at"] = time.time() + float(payload.get("expires_in") or 3600)
        self.account_store.update_credentials(account.account_id, credentials)
        return str(credentials["access_token"])

    def _run_simple_action(self, job: _SetupJob, parameters: dict[str, Any]) -> None:
        try:
            if job.action == "configure":
                self._save_app_config(parameters)
                job.output = "Google OAuth 应用配置已保存"
            elif job.action == "disconnect":
                count = self.account_store.revoke(job.person_id, "gmail")
                job.output = "Gmail 账户已断开" if count else "没有已连接的 Gmail 账户"
            job.state = "completed"
        except Exception as exc:
            job.state = "failed"
            job.error = str(exc)
        finally:
            job.completed_at = time.time()

    def _prepare_authorization(self, job: _SetupJob) -> None:
        app = self._require_app_config()
        redirect = urlparse(str(app["redirect_uri"]))
        if redirect.scheme != "http" or redirect.hostname not in {"127.0.0.1", "localhost"} or not redirect.port:
            raise ValueError("授权回调地址必须是带固定端口的本机 HTTP 地址")
        state = secrets.token_urlsafe(32)
        job.oauth_state = state
        job.callback_mode = "desktop"
        query = urlencode({
            "client_id": app["client_id"],
            "redirect_uri": app["redirect_uri"],
            "response_type": "code",
            "scope": " ".join(DEFAULT_SCOPES),
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "true",
            "state": state,
        })
        job.urls.append(f"{AUTHORIZATION_URL}?{query}")

    def _complete_authorization(
        self,
        job: _SetupJob,
        code: str,
        state: str,
        error: str,
    ) -> None:
        app = self._require_app_config()
        expected_state = job.oauth_state
        try:
            if job.cancel_requested:
                return
            if error:
                raise RuntimeError(f"Gmail 授权被拒绝: {error}")
            if not secrets.compare_digest(state, expected_state):
                raise RuntimeError("Gmail OAuth state 校验失败")
            if not code:
                raise RuntimeError("Gmail OAuth 未返回授权码")
            response = requests.post(
                TOKEN_URL,
                data={
                    "client_id": app["client_id"],
                    "client_secret": app["client_secret"],
                    "code": code,
                    "redirect_uri": app["redirect_uri"],
                    "grant_type": "authorization_code",
                },
                timeout=30,
            )
            payload = self._json_response(response)
            if response.status_code >= 400 or not payload.get("access_token"):
                raise RuntimeError(str(payload.get("error_description") or payload.get("error") or "Gmail token exchange failed"))
            payload["expires_at"] = time.time() + float(payload.get("expires_in") or 3600)
            profile = GmailClient(str(payload["access_token"])).profile()
            email = str(profile.get("emailAddress") or "").strip()
            if not email:
                raise RuntimeError("Gmail 没有返回当前邮箱地址")
            self.account_store.save(
                person_id=job.person_id,
                provider="gmail",
                subject=email,
                display_name=email,
                scopes=str(payload.get("scope") or "").split() or list(DEFAULT_SCOPES),
                credentials=payload,
                metadata={"history_id": profile.get("historyId", "")},
            )
            job.output = f"已连接 Gmail 账户 {email}"
            job.state = "completed"
        except Exception as exc:
            if job.state == "running":
                job.state = "failed"
                job.error = str(exc)
        finally:
            job.completed_at = time.time()

    def _app_config(self) -> dict[str, Any]:
        data = self._read_config()
        plugins = data.get("plugins", {})
        entries = plugins.get("entries", {}) if isinstance(plugins, dict) else {}
        value = entries.get("gmail_workspace", {}) if isinstance(entries, dict) else {}
        return dict(value) if isinstance(value, dict) else {}

    def _require_app_config(self) -> dict[str, str]:
        value = self._app_config()
        client_id = str(value.get("client_id") or "").strip()
        client_secret = str(value.get("client_secret") or "").strip()
        redirect_uri = str(value.get("redirect_uri") or DEFAULT_REDIRECT_URI).strip()
        if not client_id or not client_secret:
            raise RuntimeError("请先配置 Google OAuth Client ID 和 Client Secret")
        return {"client_id": client_id, "client_secret": client_secret, "redirect_uri": redirect_uri}

    def _save_app_config(self, values: dict[str, Any]) -> None:
        existing = self._app_config()
        client_id = str(values.get("client_id") or existing.get("client_id") or "").strip()
        client_secret = str(values.get("client_secret") or existing.get("client_secret") or "").strip()
        redirect_uri = str(values.get("redirect_uri") or existing.get("redirect_uri") or DEFAULT_REDIRECT_URI).strip()
        if not client_id or not client_secret:
            raise ValueError("OAuth Client ID 和 Client Secret 不能为空")
        parsed = urlparse(redirect_uri)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"} or not parsed.port:
            raise ValueError("授权回调地址必须是带固定端口的本机 HTTP 地址")
        data = self._read_config()
        plugins = data.setdefault("plugins", {})
        if not isinstance(plugins, dict):
            plugins = {}
            data["plugins"] = plugins
        entries = plugins.setdefault("entries", {})
        if not isinstance(entries, dict):
            entries = {}
            plugins["entries"] = entries
        entries["gmail_workspace"] = {
            "enabled": True,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
        }
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=self.config_path.parent,
            delete=False,
            suffix=".tmp",
        ) as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            temp_path = Path(handle.name)
        temp_path.replace(self.config_path)

    def _read_config(self) -> dict[str, Any]:
        if not self.config_path.is_file():
            return {}
        try:
            value = json.loads(self.config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"无法读取 Agent config.json: {exc}") from exc
        if not isinstance(value, dict):
            raise RuntimeError("Agent config.json 必须是 JSON 对象")
        return value

    @staticmethod
    def _json_response(response: requests.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError:
            return {"error": response.text[:1000]}
        return payload if isinstance(payload, dict) else {"result": payload}
