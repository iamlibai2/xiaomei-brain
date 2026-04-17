"""钉钉平台适配器"""

import json
import aiohttp
import asyncio
from typing import Dict, Any, Callable, Awaitable, Optional
import logging
import time
import hashlib
import hmac
from queue import Queue

from .base import Channel
from .types import InboundMsg, OutboundMsg

logger = logging.getLogger(__name__)


class DingtalkChannel(Channel):
    """钉钉平台适配器"""

    def __init__(self, app_key: str, app_secret: str, verify_token: str):
        super().__init__(app_key, app_secret)
        self.verify_token = verify_token
        self.webhook_url = f"https://oapi.dingtalk.com/robot/send?access_token={app_key}"
        self.session: Optional[aiohttp.ClientSession] = None
        self.message_queue: Queue = Queue(maxsize=1000)
        self._message_handler: Optional[Callable[[InboundMsg], Awaitable[OutboundMsg]]] = None

    def platform_name(self) -> str:
        return "dingtalk"

    async def start(self, on_message: Callable[[InboundMsg], Awaitable[OutboundMsg]]) -> None:
        """启动 webhook 监听和消息处理"""
        await super().start(on_message)
        self._message_handler = on_message
        logger.info(f"DingtalkChannel started, webhook URL: {self.webhook_url}")

        # 启动消息处理任务
        self._message_processor_task = asyncio.create_task(self._process_messages())

        # 启动 webhook 监听（钉钉使用轮询模式）
        self._webhook_listener_task = asyncio.create_task(self._simulate_webhook_listener())

    def verify(self, challenge: str) -> str:
        """钉钉 webhook URL 验证"""
        return challenge

    async def send(self, to: str, msg: OutboundMsg) -> None:
        """发送消息到钉钉群聊"""
        if self.session is None:
            self.session = aiohttp.ClientSession()

        # 钉钉支持的消息类型
        if msg.text:
            # 文本消息
            data = {
                "msgtype": "text",
                "text": {
                    "content": msg.text
                },
                "at": {
                    "atMobiles": [],
                    "isAtAll": False
                }
            }
        elif msg.attachments:
            # 链接消息
            data = {
                "msgtype": "actionCard",
                "actionCard": {
                    "title": msg.text or "消息",
                    "text": msg.text,
                    "btnOrientation": "0",
                    "singleTitle": "查看详情",
                    "singleURL": msg.attachments[0]
                }
            }
        else:
            # 默认文本消息
            data = {
                "msgtype": "text",
                "text": {
                    "content": msg.text or "无内容"
                },
                "at": {
                    "atMobiles": [],
                    "isAtAll": False
                }
            }

        async with self.session.post(
            self.webhook_url,
            json=data,
            headers={
                "Content-Type": "application/json"
            }
        ) as resp:
            if resp.status != 200:
                error = await resp.text()
                logger.error(f"Failed to send message to Dingtalk: {error}")
                raise Exception(f"Failed to send message: {error}")
            else:
                result = await resp.json()
                if result.get("errcode") != 0:
                    logger.error(f"Dingtalk API error: {result.get('errmsg')}")
                    raise Exception(f"Dingtalk API error: {result.get('errmsg')}")
                logger.info(f"Message sent to {to} successfully")

    async def stop(self) -> None:
        """停止监听"""
        # 取消消息处理任务
        if hasattr(self, '_message_processor_task'):
            self._message_processor_task.cancel()
            try:
                await self._message_processor_task
            except asyncio.CancelledError:
                pass

        # 取消 webhook 监听任务
        if hasattr(self, '_webhook_listener_task'):
            self._webhook_listener_task.cancel()
            try:
                await self._webhook_listener_task
            except asyncio.CancelledError:
                pass

        # 关闭 session
        if self.session:
            await self.session.close()
            self.session = None
        await super().stop()

    @classmethod
    def from_event(cls, payload: Dict[str, Any]) -> InboundMsg:
        """从钉钉 webhook 事件解析消息"""
        # 钉钉事件格式示例：
        # {
        #   "robotId": "robot123",
        #   "timestamp": 1642512345678,
        #   "sign": "xxx",
        #   "conversationId": "chat123",
        #   "senderStaffId": "user123",
        #   "senderNick": "张三",
        #   "chatId": "chat123",
        #   "type": 1,
        #   "sessionWebhook": "xxx",
        #   "sessionWebhookExpiredTime": 1642512345678,
        #   "text": {
        #     "content": "你好"
        #   },
        #   "at": {
        #     "atMobiles": [],
        #     "atUserIds": [],
        #     "isAtAll": false
        #   }
        # }

        text_content = payload.get("text", {}).get("content", "")

        return InboundMsg(
            platform="dingtalk",
            sender=payload.get("senderStaffId", ""),
            sender_name=payload.get("senderNick", ""),
            conversation_id=payload.get("conversationId", ""),
            text=text_content,
            timestamp=payload.get("timestamp", 0) / 1000,  # 钉钉时间戳是毫秒
            attachments=[],  # 钉钉消息通常没有附件
            extra={
                "message_id": payload.get("chatId"),
                "event_type": payload.get("type"),
                "is_at_all": payload.get("at", {}).get("isAtAll", False)
            }
        )

    def to_webhook_handler(self):
        """返回 webhook 处理函数（供 Flask/Fastapi 使用）"""
        async def webhook_handler(request):
            # 获取请求体
            body = await request.json()

            # URL 验证
            if request.method == "GET":
                return {"challenge": body.get("challenge", "")}

            # 钉钉签名验证
            timestamp = body.get("timestamp")
            sign = body.get("sign")
            if not timestamp or not sign:
                return {"errcode": 1, "errmsg": "Missing timestamp or sign"}

            if not self.verify_signature(timestamp, sign):
                return {"errcode": 1, "errmsg": "Invalid signature"}

            # 解析消息
            try:
                msg = self.from_event(body)
                # 将消息放入队列进行处理
                await self.message_queue.put(msg)
                return {"errcode": 0, "errmsg": "success"}
            except Exception as e:
                logger.error(f"Error processing Dingtalk event: {e}")
                return {"errcode": 1, "errmsg": f"error: {str(e)}"}

        return webhook_handler

    async def _process_messages(self):
        """处理消息队列中的消息（Streaming 实现）"""
        while True:
            try:
                # 从队列获取消息
                msg = await self.message_queue.get()
                logger.info(f"Processing message: {msg}")

                # 处理消息
                if self._message_handler:
                    response = await self._message_handler(msg)
                    logger.info(f"Response: {response}")

                # 标记任务完成
                self.message_queue.task_done()
            except Exception as e:
                logger.error(f"Error processing message: {e}")
                # 继续处理下一条消息
                continue

    async def _simulate_webhook_listener(self):
        """模拟 webhook 监听（测试用）"""
        logger.info("Dingtalk webhook listener started (simulation)")
        try:
            # 模拟接收一些测试消息
            test_messages = [
                {
                    "robotId": "test_robot",
                    "timestamp": int(time.time() * 1000),
                    "sign": "test_sign",
                    "conversationId": "test_chat",
                    "senderStaffId": "test_user",
                    "senderNick": "测试用户",
                    "chatId": "test_chat",
                    "type": 1,
                    "text": {
                        "content": "你好，这是钉钉测试消息"
                    },
                    "at": {
                        "atMobiles": [],
                        "atUserIds": [],
                        "isAtAll": False
                    }
                }
            ]

            # 发送测试消息到队列
            for payload in test_messages:
                msg = self.from_event(payload)
                await self.message_queue.put(msg)
                logger.info(f"Test message enqueued: {msg.text}")

            # 保持任务运行
            while True:
                await asyncio.sleep(5)  # 钉钉建议 5 秒轮询一次

        except Exception as e:
            logger.error(f"Webhook listener error: {e}")

    def verify_signature(self, timestamp: str, sign: str) -> bool:
        """验证钉钉签名"""
        # 钉钉签名算法：HMAC-SHA256(timestamp + "\n" + app_secret, app_secret)
        string_to_sign = f"{timestamp}\n{self.app_secret}"
        hmac_sha256 = hmac.new(
            self.app_secret.encode("utf-8"),
            string_to_sign.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()

        return hmac_sha256 == sign