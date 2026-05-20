"""AttentionLayer: 注意层——Layer 1 会话管理。

单线程、可切换会话。一次只处理一个对话对象。
负责：
- 会话保存/恢复（_session_messages dict）
- switch_to() 会话切换
- 为未来的多 peer 路由提供基础

设计原则：
- 纯内存操作，无磁盘 IO（ConversationDB 是标准日志）
- 保存时只保留最近 500 条消息（上下文窗口上限）
- 切换成本 = 指针交换，O(1)
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# 每个会话最多保留的消息数
MAX_SESSION_MESSAGES = 500


class AttentionLayer:
    """注意层——Layer 1 会话管理。

    持有 agent 引用，通过 RLock 安全读写 agent.messages。
    Layer 0 / Layer 2 不通过此类访问 agent（它们有自己的实例或不需要）。
    """

    def __init__(self, agent_core: Any) -> None:
        self._agent = agent_core
        self._session_messages: dict[str, list[dict[str, Any]]] = {}
        self._current_session: str = "main"
        self._lock: threading.RLock = threading.RLock()

        # 给外部读锁用
        self.lock = self._lock

    # ── Properties ─────────────────────────────────────────

    @property
    def current_session(self) -> str:
        return self._current_session

    @property
    def session_ids(self) -> list[str]:
        return sorted(self._session_messages.keys())

    # ── Core Operations ────────────────────────────────────

    def save_session(self, session_id: str | None = None) -> None:
        """保存当前会话的 agent.messages 到 _session_messages。"""
        sid = session_id or self._current_session
        if not sid:
            return
        with self._lock:
            msgs = self._agent.messages
            if msgs:
                self._session_messages[sid] = list(msgs[-MAX_SESSION_MESSAGES:])
                logger.debug(
                    "[Attention] 保存会话 %s: %d 条消息（截断前 %d 条）",
                    sid, min(len(msgs), MAX_SESSION_MESSAGES), len(msgs),
                )

    def restore_session(self, session_id: str) -> None:
        """恢复目标会话的 agent.messages。"""
        with self._lock:
            saved = self._session_messages.get(session_id, [])
            self._agent.messages = list(saved)  # 复制，避免引用共享
            self._agent.session_id = session_id
            self._current_session = session_id
            logger.info(
                "[Attention] 恢复会话 %s: %d 条消息",
                session_id, len(saved),
            )

    def switch_to(self, session_id: str) -> None:
        """切换会话：保存当前 → 恢复目标。

        如果目标就是当前会话，不做任何操作。
        """
        if session_id == self._current_session:
            return

        self.save_session()
        self.restore_session(session_id)

    def new_session(self, session_id: str) -> None:
        """创建新会话：保存当前，清空 messages，开始新会话。"""
        self.save_session()
        with self._lock:
            self._agent.messages = []
            self._agent.session_id = session_id
            self._current_session = session_id
        logger.info("[Attention] 新建会话: %s", session_id)

    # ── Query ──────────────────────────────────────────────

    def get_message_count(self, session_id: str | None = None) -> int:
        """获取会话的消息数（已保存的消息数）。"""
        sid = session_id or self._current_session
        if sid == self._current_session:
            return len(self._agent.messages)
        return len(self._session_messages.get(sid, []))

    def get_recent_messages(
        self, session_id: str, limit: int = 10
    ) -> list[dict[str, Any]]:
        """获取指定会话的最近 N 条消息。"""
        if session_id == self._current_session:
            msgs = self._agent.messages
        else:
            msgs = self._session_messages.get(session_id, [])
        return msgs[-limit:] if msgs else []
