"""WSAdapter — WebSocket 通道适配器。

收/发合并在 gateway/ 下：与 server.py 协同构成 WS 完整通道。
"""

from __future__ import annotations

import asyncio
import logging

from .channel_adapter import ChannelAdapter
from .connection import ConnectionManager
from .protocol import build_event

logger = logging.getLogger(__name__)


class WSAdapter(ChannelAdapter):
    """WebSocket 通道适配器：向已连接的 WebSocket 客户端发送消息。

    收（入站）由 gateway/server.py 的 /ws 端点处理。
    发（出站）由本适配器的 send() 处理。
    """

    _loop = None

    def __init__(self, conn_manager: ConnectionManager) -> None:
        self._conn_manager = conn_manager

    @classmethod
    def set_loop(cls, loop) -> None:
        cls._loop = loop

    @property
    def channel_type(self) -> str:
        return "ws"

    def send(self, target: str, text: str, msg_type: str = "text") -> None:
        """推送文本到指定 WebSocket 连接。

        target: session_id
        msg_type: "text" 完整消息 → event:"message.complete"
                  "text_chunk" 流式块 → event:"message.delta"
        """
        conn_id = self._conn_manager.get_conn_id(target)
        if conn_id is None:
            logger.warning("[WSAdapter] 丢弃消息，无连接: session=%s msg=%.100s", target, text)
            return

        loop = self._loop
        if loop is None:
            logger.warning("[WSAdapter] 丢弃消息，事件循环未设置: session=%s msg=%.100s", target, text)
            return

        if msg_type == "text_chunk":
            event_name = "message.delta"
        elif msg_type == "internal_display":
            event_name = "internal.display"
        elif msg_type == "tool.start":
            event_name = "tool.start"
        elif msg_type == "tool.complete":
            event_name = "tool.complete"
        elif msg_type == "interaction.requested":
            event_name = "interaction.requested"
        elif msg_type == "interaction.updated":
            event_name = "interaction.updated"
        else:
            event_name = "message.complete"

        self.send_event(
            target,
            event_name,
            {"text": text, **({"status": "complete"} if event_name == "message.complete" else {})},
            session_id=target,
        )

    def send_event(
        self,
        target: str,
        event: str,
        payload: dict,
        *,
        session_id: str = "",
        turn_id: str = "",
    ) -> None:
        """向 WebSocket 原样发送结构化 Gateway 事件。"""
        conn_id = self._conn_manager.get_conn_id(target)
        if conn_id is None:
            logger.warning("[WSAdapter] 丢弃事件，无连接: session=%s event=%s", target, event)
            return

        loop = self._loop
        if loop is None:
            logger.warning("[WSAdapter] 丢弃事件，事件循环未设置: session=%s event=%s", target, event)
            return

        frame = build_event(
            event,
            payload,
            session_id=session_id or target,
            turn_id=turn_id,
        )
        asyncio.run_coroutine_threadsafe(
            self._conn_manager.send(conn_id, frame),
            loop,
        )
