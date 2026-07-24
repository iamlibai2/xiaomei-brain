"""一次性身份 challenge。"""

from __future__ import annotations

import json
import secrets
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any


class ChallengeError(ValueError):
    """Challenge 不存在、过期、连接不符或用途不符。"""


@dataclass(frozen=True)
class PendingChallenge:
    challenge_id: str
    connection_id: str
    purpose: str
    challenge: str
    payload: dict[str, Any]
    expires_at: float


class ChallengeManager:
    """在内存中管理短时、一次性且绑定连接的 challenge。"""

    def __init__(self, ttl_seconds: int = 120) -> None:
        self._ttl_seconds = ttl_seconds
        self._pending: dict[str, PendingChallenge] = {}
        self._lock = threading.Lock()

    def begin(
        self,
        connection_id: str,
        purpose: str,
        payload: dict[str, Any],
        *,
        now: float | None = None,
    ) -> PendingChallenge:
        issued_at = time.time() if now is None else now
        challenge_id = f"challenge_{uuid.uuid4().hex}"
        expires_at = issued_at + self._ttl_seconds
        # 客户端必须签署这段完整原文。连接、用途和过期时间都进入签名，
        # 因此截获的签名不能换连接或换用途重放。
        challenge = json.dumps(
            {
                "version": 1,
                "challenge_id": challenge_id,
                "connection_id": connection_id,
                "purpose": purpose,
                "nonce": secrets.token_urlsafe(32),
                "issued_at": issued_at,
                "expires_at": expires_at,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        pending = PendingChallenge(
            challenge_id=challenge_id,
            connection_id=connection_id,
            purpose=purpose,
            challenge=challenge,
            payload=dict(payload),
            expires_at=expires_at,
        )
        with self._lock:
            self._purge_locked(issued_at)
            # 同一连接同一用途只保留最新 challenge，限制内存占用并避免
            # 客户端误用旧挑战。
            stale = [
                current_id
                for current_id, current in self._pending.items()
                if current.connection_id == connection_id
                and current.purpose == purpose
            ]
            for current_id in stale:
                self._pending.pop(current_id, None)
            self._pending[challenge_id] = pending
        return pending

    def consume(
        self,
        challenge_id: str,
        connection_id: str,
        purpose: str,
        *,
        now: float | None = None,
    ) -> PendingChallenge:
        timestamp = time.time() if now is None else now
        with self._lock:
            # 先移除再验证，失败的 challenge 同样不能反复试签名。
            pending = self._pending.pop(challenge_id, None)
        if pending is None:
            raise ChallengeError("challenge 不存在或已使用")
        if pending.expires_at <= timestamp:
            raise ChallengeError("challenge 已过期")
        if pending.connection_id != connection_id:
            raise ChallengeError("challenge 不属于当前连接")
        if pending.purpose != purpose:
            raise ChallengeError("challenge 用途不匹配")
        return pending

    def drop_connection(self, connection_id: str) -> None:
        """断开连接时销毁该连接尚未使用的全部 challenge。"""
        with self._lock:
            challenge_ids = [
                challenge_id
                for challenge_id, pending in self._pending.items()
                if pending.connection_id == connection_id
            ]
            for challenge_id in challenge_ids:
                self._pending.pop(challenge_id, None)

    def _purge_locked(self, now: float) -> None:
        expired = [
            challenge_id
            for challenge_id, pending in self._pending.items()
            if pending.expires_at < now
        ]
        for challenge_id in expired:
            self._pending.pop(challenge_id, None)
