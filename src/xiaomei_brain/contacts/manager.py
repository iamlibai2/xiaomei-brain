"""IdentityManager — 多用户身份管理 + 渠道绑定。

两层模型：
- identities: {identity_id: {password_hash, display_name}}
- bindings:   {sender_id: identity_id}

sender_id = 渠道原生标识（飞书 open_id、钉钉 user_id、CLI --user 值）
identity_id = 归一化后的用户标识（如 "zhangsan"）
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class IdentityManager:
    """管理多用户身份和渠道绑定。"""

    def __init__(self, data_dir: str | Path) -> None:
        self._dir = Path(data_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._identities: dict[str, dict] = {}
        self._bindings: dict[str, str] = {}
        self._load()

    # ── look up ────────────────────────────────────────────────

    def get_identity(self, sender_id: str) -> str | None:
        """根据 sender_id 查找归一化的 identity_id。"""
        return self._bindings.get(sender_id)

    def is_trusted(self, sender_id: str) -> bool:
        """该 sender 是否已验证。"""
        return sender_id in self._bindings

    # ── verify ─────────────────────────────────────────────────

    def verify_password(self, identity_id: str, password: str) -> bool:
        """验证密码是否正确。"""
        entry = self._identities.get(identity_id)
        if not entry:
            return False
        return entry.get("password_hash") == self._hash(password)

    def create_identity(self, identity_id: str, password: str, display_name: str = "") -> None:
        """创建新身份。"""
        if identity_id in self._identities:
            raise ValueError(f"身份 {identity_id} 已存在")
        self._identities[identity_id] = {
            "password_hash": self._hash(password),
            "display_name": display_name or identity_id,
        }
        self._save_identities()
        logger.info("[Contacts] 创建身份: %s", identity_id)

    def bind(self, sender_id: str, identity_id: str) -> None:
        """绑定 sender_id → identity_id。

        sender_id 格式建议：
        - feishu-{open_id} (飞书)
        - dingtalk-{user_id} (钉钉)
        - cli-{name} (CLI)
        - ws-{client_id} (WebSocket)
        """
        if identity_id not in self._identities:
            raise ValueError(f"身份 {identity_id} 不存在")
        self._bindings[sender_id] = identity_id
        self._save_bindings()
        logger.info("[Contacts] 绑定: %s → %s", sender_id, identity_id)

    def unbind(self, sender_id: str) -> None:
        """解绑。"""
        removed = self._bindings.pop(sender_id, None)
        if removed:
            self._save_bindings()
            logger.info("[Contacts] 解绑: %s → %s", sender_id, removed)

    def get_display_name(self, identity_id: str) -> str:
        """获取显示名。"""
        entry = self._identities.get(identity_id, {})
        return entry.get("display_name", identity_id)

    # ── persistence ────────────────────────────────────────────

    def _load(self) -> None:
        id_file = self._dir / "identities.json"
        if id_file.exists():
            try:
                self._identities = json.loads(id_file.read_text())
            except Exception as e:
                logger.warning("[Contacts] 加载 identities 失败: %s", e)

        bind_file = self._dir / "bindings.json"
        if bind_file.exists():
            try:
                self._bindings = json.loads(bind_file.read_text())
            except Exception as e:
                logger.warning("[Contacts] 加载 bindings 失败: %s", e)

    def _save_identities(self) -> None:
        (self._dir / "identities.json").write_text(
            json.dumps(self._identities, ensure_ascii=False, indent=2)
        )

    def _save_bindings(self) -> None:
        (self._dir / "bindings.json").write_text(
            json.dumps(self._bindings, ensure_ascii=False, indent=2)
        )

    @staticmethod
    def _hash(password: str) -> str:
        return hashlib.sha256(password.encode()).hexdigest()
