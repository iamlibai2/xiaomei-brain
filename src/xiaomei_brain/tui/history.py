"""HistoryLoader — 从 Gateway 加载聊天历史。

通过 chat.history RPC 拉取历史消息，注入到 ChatLog。
参考 OpenClaw tui-session-actions.ts 的 loadHistory()。
"""

from __future__ import annotations

import logging

from xiaomei_brain.tui.chat_log import ChatLog
from xiaomei_brain.tui.gateway import GatewayClient
from xiaomei_brain.tui.text_utils import sanitize

logger = logging.getLogger(__name__)


class HistoryLoader:
    """历史消息加载器。"""

    def __init__(
        self,
        client: GatewayClient,
        chat_log: ChatLog,
    ) -> None:
        self.client = client
        self.chat_log = chat_log

    async def load_recent(self, limit: int = 50) -> int:
        """加载最近的历史消息。

        Returns:
            加载的消息数量
        """
        result = await self.client.send_history(limit=limit)
        messages = result.get("messages", [])
        if not messages:
            return 0

        return self._insert_messages(messages)

    def load_empty(self, message: str = "开始新的对话") -> None:
        """无历史时显示提示消息。"""
        self.chat_log.add_system(message)

    # ── 内部 ────────────────────────────────────────────────

    def _insert_messages(self, messages: list[dict]) -> int:
        """将历史消息按序插入 ChatLog。"""
        count = 0
        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if not content:
                continue

            content = sanitize(str(content))

            if role == "user":
                self.chat_log.add_user(content)
                count += 1
            elif role == "assistant":
                self.chat_log.add_assistant(content)
                count += 1
            # tool / system roles 暂不处理

        return count
