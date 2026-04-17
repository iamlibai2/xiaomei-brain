"""微信平台适配器"""

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


class WeChatChannel(Channel):
    """微信公众号/企业微信平台适配器"""

    def __init__(self, app_id: str, app_secret: str, verification_token: str):
        super().__init__(app_id, app_secret)
        self.verification_token = verification_token
        # 微信公众号和企业微信使用不同的 API 端点
        self.api_base = "https://qyapi.weixin.qq.com"  # 企业微信
        # 如果是公众号，使用: https://api.weixin.qq.com
        self.session: Optional[aiohttp.ClientSession] = None
        self.message_queue: Queue = Queue(maxsize=1000)
        self._message_handler: Optional[Callable[[InboundMsg], Awaitable[OutboundMsg]]] = None
        self.is_enterprise = True  # 默认为企业微信

    def platform_name(self) -> str:
        return "wechat"

    def set_enterprise(self, is_enterprise: bool = True):
        """设置为企业微信或公众号"""
        self.is_enterprise = is_enterprise
        base_url = "https://qyapi.weixin.qq.com" if is_enterprise else "https://api.weixin.qq.com"
        self.api_base = base_url

    async def start(self, on_message: Callable[[InboundMsg], Awaitable[OutboundMsg]]) -> None:
        """启动消息监听"""
        await super().start(on_message)
        self._message_handler = on_message
        logger.info(f"WeChatChannel started (Enterprise: {self.is_enterprise})")

        # 获取 access token
        self.access_token = await self._get_access_token()

        # 启动消息处理任务
        self._message_processor_task = asyncio.create_task(self._process_messages())

        # 启动 webhook 监听
        self._webhook_listener_task = asyncio.create_task(self._simulate_webhook_listener())

    def verify(self, challenge: str) -> str:
        """微信 URL 验证"""
        return challenge

    async def _get_access_token(self) -> str:
        """获取微信 access token"""
        url = f"{self.api_base}/cgi-bin/gettoken"
        params = {
            "corpid": self.app_id,
            "corpsecret": self.app_secret
        } if self.is_enterprise else {
            "appid": self.app_id,
            "secret": self.app_secret
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    error = await resp.text()
                    logger.error(f"Failed to get access token: {error}")
                    raise Exception(f"Failed to get access token: {error}")

                data = await resp.json()
                if data.get("errcode") != 0:
                    logger.error(f"WeChat API error: {data.get('errmsg')}")
                    raise Exception(f"WeChat API error: {data.get('errmsg')}")

                return data["access_token"]

    async def send(self, to: str, msg: OutboundMsg) -> None:
        """发送消息到微信"""
        if self.session is None:
            self.session = aiohttp.ClientSession()

        # 检查 access token 是否过期
        if not hasattr(self, 'access_token') or not self.access_token:
            self.access_token = await self._get_access_token()

        # 微信支持的消息类型
        if msg.text:
            # 文本消息
            data = {
                "touser": to,
                "msgtype": "text",
                "agentid": self.app_id,  # 企业微信需要
                "text": {
                    "content": msg.text
                }
            }

            # 如果是公众号，去掉 agentid
            if not self.is_enterprise:
                data.pop("agentid", None)
                data["touser"] = "openid"  # 需要用户的 openid
        elif msg.attachments:
            # 图片消息
            data = {
                "touser": to,
                "msgtype": "image",
                "agentid": self.app_id,
                "image": {
                    "media_id": msg.attachments[0]  # 需要先上传获取 media_id
                }
            }

            if not self.is_enterprise:
                data.pop("agentid", None)
                data["touser"] = "openid"
        else:
            # 默认文本消息
            data = {
                "touser": to,
                "msgtype": "text",
                "agentid": self.app_id,
                "text": {
                    "content": msg.text or "无内容"
                }
            }

            if not self.is_enterprise:
                data.pop("agentid", None)
                data["touser"] = "openid"

        # 发送消息
        url = f"{self.api_base}/cgi-bin/message/send" if self.is_enterprise else f"{self.api_base}/cgi-bin/message/custom/send"

        async with self.session.post(
            url,
            json=data,
            headers={
                "Content-Type": "application/json"
            }
        ) as resp:
            if resp.status != 200:
                error = await resp.text()
                logger.error(f"Failed to send message to WeChat: {error}")
                raise Exception(f"Failed to send message: {error}")
            else:
                result = await resp.json()
                if result.get("errcode") != 0:
                    logger.error(f"WeChat API error: {result.get('errmsg')}")
                    # 如果是 token 过期，重新获取
                    if result.get("errcode") == 40014:
                        self.access_token = await self._get_access_token()
                        # 重试一次
                        await self.send(to, msg)
                        return
                    raise Exception(f"WeChat API error: {result.get('errmsg')}")
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
        """从微信事件解析消息"""
        # 企业微信事件格式：
        # {
        #   "MsgType": "text",
        #   "Content": "你好",
        #   "CreateDt": 1642512345678,
        #   "FromUserName": "user123",
        #   "ToUserName": "chat123",
        #   "AgentID": 1000002,
        #   "MsgId": 123456789
        # }

        # 公众号事件格式（XML）需要先解析 XML
        if "xml" in payload:
            # 这里简化处理，实际需要解析 XML
            xml_content = payload["xml"]
            text_content = xml_content.get("Content", "")
            sender = xml_content.get("FromUserName", "")
            conversation_id = xml_content.get("ToUserName", "")
        else:
            # 企业微信 JSON 格式
            text_content = payload.get("Content", "")
            sender = payload.get("FromUserName", "")
            conversation_id = payload.get("ToUserName", "")

        return InboundMsg(
            platform="wechat",
            sender=sender,
            sender_name="",  # 微信不直接提供发送者名称
            conversation_id=conversation_id,
            text=text_content,
            timestamp=payload.get("CreateDt", 0) / 1000 if "CreateDt" in payload else time.time(),
            attachments=[],  # 微信消息通常没有附件
            extra={
                "message_id": payload.get("MsgId"),
                "msg_type": payload.get("MsgType"),
                "agent_id": payload.get("AgentID")
            }
        )

    def to_webhook_handler(self):
        """返回 webhook 处理函数（供 Flask/Fastapi 使用）"""
        async def webhook_handler(request):
            # 获取请求体
            body = await request.json()

            # URL 验证
            if request.method == "GET":
                return {"echostr": body.get("echostr", "")}

            # 微信签名验证
            signature = request.query_params.get("signature")
            timestamp = request.query_params.get("timestamp")
            nonce = request.query_params.get("nonce")

            if signature and timestamp and nonce:
                if not self.verify_signature(timestamp, nonce, signature):
                    return {"errcode": 1, "errmsg": "Invalid signature"}

            # 解析消息
            try:
                msg = self.from_event(body)
                # 将消息放入队列进行处理
                await self.message_queue.put(msg)
                return {"errcode": 0, "errmsg": "success"}
            except Exception as e:
                logger.error(f"Error processing WeChat event: {e}")
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
        logger.info("WeChat webhook listener started (simulation)")
        try:
            # 模拟接收一些测试消息
            test_messages = [
                {
                    "MsgType": "text",
                    "Content": "你好，这是微信测试消息",
                    "CreateDt": int(time.time() * 1000),
                    "FromUserName": "test_user",
                    "ToUserName": "test_chat",
                    "AgentID": 1000002,
                    "MsgId": 123456789
                }
            ]

            # 发送测试消息到队列
            for payload in test_messages:
                msg = self.from_event(payload)
                await self.message_queue.put(msg)
                logger.info(f"Test message enqueued: {msg.text}")

            # 保持任务运行
            while True:
                await asyncio.sleep(10)  # 微信建议 10 秒轮询一次

        except Exception as e:
            logger.error(f"Webhook listener error: {e}")

    def verify_signature(self, timestamp: str, nonce: str, signature: str) -> bool:
        """验证微信签名"""
        # 微信签名算法：SHA1(sort(timestamp + nonce + token))
        arr = [self.verification_token, timestamp, nonce]
        arr.sort()
        sha1 = hashlib.sha1()
        sha1.update("".join(arr).encode("utf-8"))
        my_signature = sha1.hexdigest()

        return my_signature == signature