"""Person-scoped QQ Mail authorization-code runtime."""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from xiaomei_brain.capabilities.runtime import CapabilityRuntimeState
from xiaomei_brain.external_accounts import ExternalAccountStore

from .client import IMAP_HOST, IMAP_PORT, SMTP_HOST, SMTP_PORT, QQMailClient


@dataclass
class _SetupJob:
    id: str
    action: str
    person_id: str
    state: str = "running"
    output: str = ""
    error: str = ""
    urls: list[str] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)
    completed_at: float | None = None
    cancel_requested: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "action": self.action,
            "state": self.state,
            "output": self.output,
            "error": self.error,
            "urls": list(self.urls),
            "callback_mode": "",
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }


class QQMailRuntime:
    capability_id = "qq_mail"
    provider_id = "qq_mail"
    _ACTIONS = frozenset({"authorize", "disconnect"})

    def __init__(self, *, agent_dir: str | Path, account_store: ExternalAccountStore) -> None:
        self.agent_dir = Path(agent_dir).resolve()
        self.account_store = account_store
        self._jobs: dict[str, _SetupJob] = {}
        self._latest_job: dict[str, str] = {}
        self._lock = threading.RLock()

    def inspect(self, person_id: str = "") -> CapabilityRuntimeState:
        details: dict[str, Any] = {
            "authenticated": False,
            "setup_forms": [
                {
                    "action": "authorize",
                    "scope": "person",
                    "action_label": "连接 QQ 邮箱",
                    "title": "连接 QQ 邮箱",
                    "description": "输入 QQ 邮箱地址和邮箱设置中生成的授权码。授权码仅属于当前人物，并会加密保存。",
                    "submit_label": "连接邮箱",
                    "fields": [
                        {
                            "key": "email",
                            "label": "QQ 邮箱地址",
                            "type": "text",
                            "required": True,
                            "placeholder": "name@qq.com",
                        },
                        {
                            "key": "authorization_code",
                            "label": "邮箱授权码",
                            "type": "secret",
                            "required": True,
                            "help": "不是 QQ 登录密码，请在 QQ 邮箱的账号与安全设置中生成。",
                        },
                    ],
                }
            ],
            "documentation_url": "https://wx.mail.qq.com/list/readtemplate?name=app_intro.html#/agreement/authorizationCode",
        }
        if not person_id:
            return CapabilityRuntimeState(False, "person_required", "需要先确认当前人物身份", details, ())
        account = self.account_store.get_active(person_id, self.provider_id)
        if account is None:
            return CapabilityRuntimeState(False, "needs_authorization", "QQ 邮箱尚未连接", details, ("authorize",))
        details.update({"authenticated": True, "email": account.subject})
        return CapabilityRuntimeState(True, "ready", "QQ 邮箱已连接", details, ("authorize", "disconnect"))

    def start(
        self,
        action: str,
        person_id: str,
        parameters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        action = str(action).strip().lower()
        if action not in self._ACTIONS:
            raise ValueError(f"QQ 邮箱不支持配置动作: {action}")
        if not person_id:
            raise ValueError("当前连接没有经过验证的人物身份")
        job = _SetupJob(uuid.uuid4().hex, action, person_id)
        with self._lock:
            previous = self._jobs.get(self._latest_job.get(person_id, ""))
            if previous is not None and previous.state == "running":
                raise RuntimeError("当前人物已有 QQ 邮箱配置任务正在执行")
            self._jobs[job.id] = job
            self._latest_job[person_id] = job.id
        threading.Thread(
            target=self._run_action,
            args=(job, dict(parameters or {})),
            daemon=True,
        ).start()
        return job.to_dict()

    def job_status(self, person_id: str, job_id: str = "") -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id or self._latest_job.get(person_id, ""))
            return job.to_dict() if job is not None and job.person_id == person_id else None

    def cancel(self, person_id: str, job_id: str = "") -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id or self._latest_job.get(person_id, ""))
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
        raise RuntimeError("QQ 邮箱授权不需要浏览器回调")

    def client_for(self, person_id: str) -> QQMailClient:
        account = self.account_store.get_active(person_id, self.provider_id)
        if account is None:
            raise RuntimeError("当前人物尚未连接 QQ 邮箱")
        credentials = self.account_store.credentials(account.account_id)
        authorization_code = str(credentials.get("authorization_code") or "")
        if not authorization_code:
            raise RuntimeError("QQ 邮箱授权码不存在，请重新连接")
        return QQMailClient(account.subject, authorization_code)

    def _run_action(self, job: _SetupJob, parameters: dict[str, Any]) -> None:
        try:
            if job.action == "authorize":
                email_address = str(parameters.get("email") or "").strip().lower()
                authorization_code = str(parameters.get("authorization_code") or "").strip()
                if not email_address.endswith(("@qq.com", "@foxmail.com")):
                    raise ValueError("请输入有效的 QQ 邮箱地址")
                if not authorization_code:
                    raise ValueError("QQ 邮箱授权码不能为空")
                QQMailClient(email_address, authorization_code).verify()
                if job.cancel_requested:
                    return
                self.account_store.save(
                    person_id=job.person_id,
                    provider=self.provider_id,
                    subject=email_address,
                    display_name=email_address,
                    scopes=("imap", "smtp"),
                    credentials={"authorization_code": authorization_code},
                    metadata={
                        "imap_host": IMAP_HOST,
                        "imap_port": IMAP_PORT,
                        "smtp_host": SMTP_HOST,
                        "smtp_port": SMTP_PORT,
                    },
                )
                job.output = f"已连接 QQ 邮箱 {email_address}"
            else:
                count = self.account_store.revoke(job.person_id, self.provider_id)
                job.output = "QQ 邮箱已断开" if count else "没有已连接的 QQ 邮箱"
            job.state = "completed"
        except Exception as exc:
            if job.state == "running":
                job.state = "failed"
                job.error = str(exc)
        finally:
            job.completed_at = time.time()
