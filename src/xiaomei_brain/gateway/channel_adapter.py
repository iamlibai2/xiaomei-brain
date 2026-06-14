"""ChannelAdapter: 通道适配器抽象基类。

Gateway 核心接口。每个频道（CLI/HTTP P2P/WebSocket/Feishu/...）
实现自己的适配器，负责：
- send: OutputRoute → 通道输出

纯同步接口，与 ConsciousLiving 的同步模型一致。
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

from .router import InboundMsg

logger = logging.getLogger(__name__)


class ChannelAdapter(ABC):
    """通道适配器抽象基类。"""

    @abstractmethod
    def send(self, target: str, text: str, msg_type: str = "text") -> None:
        """向目标发送文本。

        Args:
            target: 路由目标（"stdout" / agent_id / client_id / conversation_id）
            text: 要发送的文本
            msg_type: 消息类型（"text" / "text_chunk"），非 WS 通道忽略
        """
        ...

    def receive(self) -> InboundMsg | None:
        """非阻塞接收一条消息。无消息时返回 None。

        子类可选实现。CLIAdapter 在主线程用 input() 阻塞接收，
        不走此接口。
        """
        return None

    def setup(self, living: Any = None) -> None:
        """Post-load 初始化。

        在插件加载完成后调用。适配器在这里启动通道（打开连接、启动服务器等）。
        """

    def shutdown(self) -> None:
        """关闭通道。释放连接、停止服务器。默认无操作。"""

    @property
    @abstractmethod
    def channel_type(self) -> str:
        """通道类型标识（"cli" / "http_p2p" / "ws" / "feishu" / ...）。"""
        ...
