"""Channel 抽象基类"""

from abc import ABC, abstractmethod
from typing import Callable, Awaitable, Optional, AsyncIterator
import logging

from .types import InboundMsg, OutboundMsg

logger = logging.getLogger(__name__)


class Channel(ABC):
    """平台适配器抽象基类"""

    def __init__(self, app_id: str, app_secret: str):
        self.app_id = app_id
        self.app_secret = app_secret
        self._message_handler: Optional[Callable[[InboundMsg], Awaitable[OutboundMsg]]] = None
        self._streaming_handler: Optional[Callable[[InboundMsg], AsyncIterator[str]]] = None

    @abstractmethod
    async def start(self, on_message: Callable[[InboundMsg], Awaitable[OutboundMsg]]) -> None:
        """启动消息监听（webhook/polling/websocket）"""
        # 保存 on_message 回调
        self._message_handler = on_message
        # 具体实现由子类实现

    @abstractmethod
    async def send(self, to: str, msg: OutboundMsg) -> None:
        """发送消息到指定会话"""
        pass

    @abstractmethod
    def verify(self, challenge: str) -> str:
        """URL 验证（webhook 需要）"""
        pass

    async def stop(self) -> None:
        """停止监听，默认实现"""
        logger.info(f"Channel {self.__class__.__name__} stopped")

    @abstractmethod
    def platform_name(self) -> str:
        """返回平台名称"""
        pass

    def set_streaming_handler(self, handler: Optional[Callable[[InboundMsg], AsyncIterator[str]]]) -> None:
        """设置流式消息处理回调 (channel 可选择使用流式回复)"""
        self._streaming_handler = handler