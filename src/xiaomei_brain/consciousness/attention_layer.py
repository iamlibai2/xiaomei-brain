"""AttentionLayer: 注意层——Layer 1 短期上下文管理。

单线程、可切换会话。一次只处理一个对话对象。
负责：
- 上下文保存/恢复（_context_messages dict）
- switch_to() 上下文切换
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

# 每个上下文最多保留的消息数
MAX_SESSION_MESSAGES = 500


class AttentionLayer:
    """注意层——Layer 1 会话管理。

    持有 agent 引用，通过 RLock 安全读写 agent.messages。
    Layer 0 / Layer 2 不通过此类访问 agent（它们有自己的实例或不需要）。
    """

    def __init__(self, agent_core: Any) -> None:
        self._agent = agent_core
        self._context_messages: dict[str, list[dict[str, Any]]] = {}
        self._current_context: str = "session:main"
        self._lock: threading.RLock = threading.RLock()

        # 给外部读锁用
        self.lock = self._lock

    # ── Properties ─────────────────────────────────────────

    @property
    def current_session(self) -> str:
        """Compatibility alias; returns the active context key."""
        return self._current_context

    @property
    def current_context(self) -> str:
        return self._current_context

    @property
    def session_ids(self) -> list[str]:
        """Compatibility alias for known in-memory context keys."""
        return sorted(self._context_messages.keys())

    # ── Core Operations ────────────────────────────────────

    def save_session(self, context_key: str | None = None) -> None:
        """保存当前上下文的 agent.messages。"""
        key = context_key or self._current_context
        if not key:
            return
        with self._lock:
            msgs = self._agent.messages
            if msgs:
                self._context_messages[key] = list(msgs[-MAX_SESSION_MESSAGES:])
                logger.debug(
                    "[Attention] 保存上下文 %s: %d 条消息（截断前 %d 条）",
                    key, min(len(msgs), MAX_SESSION_MESSAGES), len(msgs),
                )

    def restore_session(self, context_key: str) -> None:
        """恢复目标上下文的 agent.messages。"""
        with self._lock:
            saved = self._context_messages.get(context_key, [])
            self._agent.context_key = context_key
            self._agent.messages = list(saved)  # 复制，避免引用共享
            self._current_context = context_key
            logger.info(
                "[Attention] 恢复上下文 %s: %d 条消息",
                context_key, len(saved),
            )

    def switch_to(self, context_key: str) -> None:
        """切换上下文：保存当前 → 恢复目标。

        如果目标就是当前上下文，不做任何操作。
        """
        if context_key == self._current_context:
            return

        self.save_session()
        self.restore_session(context_key)

    def new_session(self, context_key: str) -> None:
        """创建新上下文：保存当前，清空 messages。"""
        self.save_session()
        with self._lock:
            self._agent.context_key = context_key
            self._agent.messages = []
            self._current_context = context_key
        logger.info("[Attention] 新建上下文: %s", context_key)

    def activate_loaded(
        self,
        context_key: str,
        messages: list[dict[str, Any]],
    ) -> None:
        """Activate a context using messages loaded specifically for it.

        The previously active context is saved first.  An empty target remains
        empty and never inherits the previous context's message list.
        """
        if context_key != self._current_context:
            self.save_session()
        loaded = list(messages[-MAX_SESSION_MESSAGES:])
        with self._lock:
            self._context_messages[context_key] = list(loaded)
            self._agent.context_key = context_key
            self._agent.messages = list(loaded)
            self._current_context = context_key
        logger.info(
            "[Attention] 加载并激活上下文 %s: %d 条消息",
            context_key,
            len(loaded),
        )

    def preload_loaded(
        self,
        context_key: str,
        messages: list[dict[str, Any]],
    ) -> None:
        """Cache a context without changing the currently executing Turn.

        Authentication and channel connection can happen while another
        conversation is still using the shared realtime Agent Core.  Those
        control-plane operations may prepare history for their future Turn,
        but must never replace ``agent.messages`` or the active context.
        """
        loaded = list(messages[-MAX_SESSION_MESSAGES:])
        with self._lock:
            self._context_messages[context_key] = list(loaded)
        logger.info(
            "[Attention] 预加载上下文 %s: %d 条消息（未激活）",
            context_key,
            len(loaded),
        )

    # ── Query ──────────────────────────────────────────────

    def get_message_count(self, context_key: str | None = None) -> int:
        """获取上下文的消息数（已保存的消息数）。"""
        key = context_key or self._current_context
        if key == self._current_context:
            return len(self._agent.messages)
        return len(self._context_messages.get(key, []))

    def get_recent_messages(
        self, context_key: str, limit: int = 10
    ) -> list[dict[str, Any]]:
        """获取指定上下文的最近 N 条消息。"""
        if context_key == self._current_context:
            msgs = self._agent.messages
        else:
            msgs = self._context_messages.get(context_key, [])
        return msgs[-limit:] if msgs else []
