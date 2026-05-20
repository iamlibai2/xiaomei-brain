"""WSAdapter — WebSocket 通道适配器。"""

from __future__ import annotations

import asyncio
import logging

from ...gateway.channel_adapter import ChannelAdapter
from ...server.ws.connection import ConnectionManager

logger = logging.getLogger(__name__)


def register(ctx):
    """插件入口：注册 WebSocket 频道。"""
    from ...server.ws.server import cm as _cm
    ctx.register_channel("ws", WSAdapter(_cm))


class WSAdapter(ChannelAdapter):
    """WebSocket 通道适配器：向已连接的 WebSocket 客户端发送消息。"""

    _loop = None  # uvicorn 事件循环（由 server/ws/server.py 在启动时设置）

    def __init__(self, conn_manager: ConnectionManager) -> None:
        self._conn_manager = conn_manager

    @classmethod
    def set_loop(cls, loop) -> None:
        """设置 uvicorn 事件循环（由 server/ws/server.py startup 事件调用）。"""
        cls._loop = loop

    @property
    def channel_type(self) -> str:
        return "ws"

    def send(self, target: str, text: str) -> None:
        """推送文本到指定 WebSocket 连接。

        target: session_id（会话标识，对应 ConnectionManager 中的映射）
        """
        conn_id = self._conn_manager.get_conn_id(target)
        if conn_id is None:
            logger.debug("[WSAdapter] 无连接: session=%s", target)
            return

        loop = self._loop
        if loop is None:
            logger.debug("[WSAdapter] 事件循环未设置: session=%s", target)
            return

        asyncio.run_coroutine_threadsafe(
            self._conn_manager.send(conn_id, {"type": "text", "text": text}),
            loop,
        )
