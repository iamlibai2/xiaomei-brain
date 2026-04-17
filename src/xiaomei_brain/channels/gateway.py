"""Gateway 通用层，统一管理多个 Channel"""

import asyncio
import time
from typing import List, Callable, Awaitable, Optional, AsyncIterator
import logging

from .base import Channel
from .types import InboundMsg, OutboundMsg

logger = logging.getLogger(__name__)


class Gateway:
    """Channel 通用管理器，统一管理多个平台适配器"""

    def __init__(self):
        self.channels: List[Channel] = []
        self.running = False
        self._tasks: List[asyncio.Task] = []

    def add_channel(self, channel: Channel) -> None:
        """添加一个 Channel"""
        self.channels.append(channel)
        logger.info(f"Added {channel.platform_name()} channel")

    def add_channels(self, channels: List[Channel]) -> None:
        """批量添加 Channels"""
        for channel in channels:
            self.add_channel(channel)

    async def start_all(self) -> None:
        """启动所有 Channel"""
        if self.running:
            logger.warning("Gateway is already running")
            return

        self.running = True
        logger.info(f"Starting {len(self.channels)} channels...")

        # 启动每个 Channel
        for channel in self.channels:
            logger.info(f"Starting {channel.platform_name()} channel...")
            try:
                # 先设置 streaming handler（如果有）
                if hasattr(channel, 'set_streaming_handler'):
                    logger.info(f"[GATEWAY] Setting streaming handler for {channel.platform_name()}")
                    channel.set_streaming_handler(self.handle_inbound_streaming)
                # 再调用 start（内部会设置 _message_handler）
                await channel.start(self.handle_inbound)
                # 保存后台任务引用
                if hasattr(channel, '_process_task') and channel._process_task:
                    self._tasks.append(channel._process_task)
                    logger.info(f"[GATEWAY] Saved background task for {channel.platform_name()}")
                logger.info(f"{channel.platform_name()} channel started")
            except Exception as e:
                logger.error(f"Failed to start {channel.platform_name()}: {e}", exc_info=True)

        logger.info(f"[GATEWAY] {len(self._tasks)} background tasks registered")

    async def stop_all(self) -> None:
        """停止所有 Channel"""
        if not self.running:
            return

        logger.info("Stopping all channels...")
        self.running = False

        # 取消所有任务
        for task in self._tasks:
            task.cancel()
        self._tasks.clear()

        # 停止每个 Channel
        for channel in self.channels:
            try:
                await channel.stop()
            except Exception as e:
                logger.error(f"Error stopping {channel.platform_name()}: {e}")

        logger.info("All channels stopped")

    async def handle_inbound(self, msg: InboundMsg) -> OutboundMsg:
        """处理入站消息（统一入口）"""
        logger.info("=" * 60)
        logger.info("[GATEWAY] ============================================")
        logger.info("[GATEWAY] ========== 入站消息 ==========")
        logger.info(f"[GATEWAY] 平台: {msg.platform}")
        logger.info(f"[GATEWAY] 发送者: {msg.sender} ({msg.sender_name})")
        logger.info(f"[GATEWAY] 会话ID: {msg.conversation_id}")
        logger.info(f"[GATEWAY] 消息内容: {msg.text[:100] if msg.text else '(empty)'}")
        logger.info(f"[GATEWAY] 时间戳: {msg.timestamp}")
        logger.info(f"[GATEWAY] 附加信息: {msg.extra}")
        logger.info("[GATEWAY] ============================================")

        # 调用具体的消息处理（子类重写）
        try:
            logger.info("[GATEWAY] >>> 调用 on_message() 处理消息...")
            response = await self.on_message(msg)
            logger.info(f"[GATEWAY] <<< on_message() 返回: {response}")
            if response:
                logger.info(f"[GATEWAY]     回复内容: {response.text[:50] if response.text else '(empty)'}...")
                logger.info(f"[GATEWAY]     附件数量: {len(response.attachments) if response.attachments else 0}")
            else:
                logger.info("[GATEWAY]     返回为 None，不发送回复")
            return response
        except Exception as e:
            logger.error(f"[GATEWAY] ERROR in handle_inbound: {e}", exc_info=True)
            return OutboundMsg(text="处理消息时发生错误，请稍后重试")

    async def on_message(self, msg: InboundMsg) -> OutboundMsg:
        """处理消息（子类重写）"""
        # 默认实现：直接返回空回复
        # 实际使用中应该：
        # 1. 路由到对应的 Agent
        # 2. 调用 Agent.stream(msg.text)
        # 3. 返回 Agent 的回复

        logger.warning(f"No message handler for {msg.platform}")
        return OutboundMsg(text="消息处理中，请稍候...")

    async def handle_inbound_streaming(self, msg: InboundMsg) -> AsyncIterator[str]:
        """流式处理入站消息，返回 AsyncIterator[str]"""
        async for chunk in self.on_message_streaming(msg):
            yield chunk

    async def on_message_streaming(self, msg: InboundMsg) -> AsyncIterator[str]:
        """流式返回 Agent 回复（子类重写）"""
        # 默认实现：调用 on_message 并一次性 yield
        response = await self.on_message(msg)
        if response and response.text:
            yield response.text

    async def send_to_platform(self, platform: str, to: str, msg: OutboundMsg) -> None:
        """向指定平台发送消息"""
        for channel in self.channels:
            if channel.platform_name() == platform:
                await channel.send(to, msg)
                return

        raise ValueError(f"Channel for {platform} not found")

    def get_stats(self) -> dict:
        """获取统计信息"""
        return {
            "running": self.running,
            "channels_count": len(self.channels),
            "channels": [ch.platform_name() for ch in self.channels]
        }