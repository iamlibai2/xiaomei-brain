"""飞书平台适配器 - 使用官方 lark-oapi SDK"""

import json
import asyncio
import logging
import threading
import queue
from typing import Dict, Any, Callable, Awaitable, Optional

from lark_oapi.api.im.v1 import CreateMessageRequest
from lark_oapi.api.im.v1.model import CreateMessageRequestBody, P2ImMessageReceiveV1
from lark_oapi.event.dispatcher_handler import EventDispatcherHandler
from lark_oapi.core.enum import LogLevel
from lark_oapi.ws import Client

from .base import Channel
from .types import InboundMsg, OutboundMsg

logger = logging.getLogger(__name__)


class FeishuChannel(Channel):
    """飞书平台适配器 - 基于官方 lark-oapi SDK"""

    def __init__(
        self,
        app_id: str,
        app_secret: str,
        verification_token: str = "",
        account_id: str = "default",
        streaming: bool = False,
        streaming_header_title: str = "小美",
    ):
        super().__init__(app_id, app_secret)
        self.app_id = app_id
        self.app_secret = app_secret
        self.verification_token = verification_token
        self.account_id = account_id  # For multi-account routing
        self.streaming = streaming
        self.streaming_header_title = streaming_header_title
        self._message_handler: Optional[Callable[[InboundMsg], Awaitable[OutboundMsg]]] = None
        self._ws_client: Optional[Client] = None
        self._ws_thread: Optional[threading.Thread] = None
        self._msg_queue: queue.Queue = queue.Queue()
        self._process_task: Optional[asyncio.Task] = None  # Keep reference to task

    def platform_name(self) -> str:
        return "feishu"

    def verify(self, challenge: str) -> str:
        """URL 验证（webhook 模式需要）"""
        return challenge

    def _create_ws_client(self) -> Client:
        """创建 WebSocket 客户端（在独立线程中运行）"""
        handler = EventDispatcherHandler.builder(
            encrypt_key="",
            verification_token=self.verification_token,
            level=LogLevel.INFO
        ).register_p2_im_message_receive_v1(
            self._on_message
        ).build()

        return Client(
            app_id=self.app_id,
            app_secret=self.app_secret,
            log_level=LogLevel.INFO,
            event_handler=handler
        )

    async def start(self, on_message: Callable[[InboundMsg], Awaitable[OutboundMsg]]) -> None:
        """启动 WebSocket 监听（在独立线程中）"""
        logger.info("[START] ========================================")
        logger.info("[START] FeishuChannel.start() 开始")
        # 直接设置 handler，不调用 super().start() 以避免同步问题
        self._message_handler = on_message
        logger.info(f"[START] app_id={self.app_id}")
        logger.info(f"[START] streaming={self.streaming}, streaming_header_title={self.streaming_header_title}")
        logger.info(f"[START] _message_handler is None: {self._message_handler is None}")
        logger.info(f"[START] _streaming_handler is None: {self._streaming_handler is None}")

        # 启动消息处理协程
        logger.info("[START] 创建 _process_messages 协程任务")
        try:
            loop = asyncio.get_running_loop()
            logger.info(f"[START] Event loop: {loop}")
            logger.info(f"[START] Event loop is running: {loop.is_running()}")
            self._process_task = asyncio.create_task(self._process_messages(), name="feishu_process_messages")
            logger.info(f"[START] _process_messages 协程任务已创建: {self._process_task}")
            logger.info(f"[START] Task done: {self._process_task.done()}")
            logger.info("[START] ========================================")
        except Exception as e:
            logger.warning(f"[START] Failed to create _process_messages task: {e}", exc_info=True)

        # 在独立线程中运行 WebSocket 客户端
        def run_ws():
            logger.info("[START][WS-THREAD] WebSocket 线程开始")
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                self._ws_client = self._create_ws_client()
                logger.info("[START][WS-THREAD] WebSocket client 创建成功，调用 start()...")
                self._ws_client.start()
            except Exception as e:
                logger.error(f"[START][WS-THREAD] WebSocket error: {e}", exc_info=True)
            finally:
                logger.info("[START][WS-THREAD] WebSocket 线程结束")
                loop.close()

        logger.info("[START] 创建 WebSocket daemon 线程")
        self._ws_thread = threading.Thread(target=run_ws, daemon=True)
        self._ws_thread.start()
        logger.info("[START] WebSocket 线程已启动 (daemon=True)")
        logger.info("[START] FeishuChannel.start() 完成")

    def _on_message(self, data: P2ImMessageReceiveV1) -> None:
        """处理收到的消息事件 - 将消息放入队列"""
        logger.info("=" * 60)
        logger.info("[STEP 1] _on_message called - WebSocket 线程收到消息")
        logger.info(f"[STEP 1] data type: {type(data)}")
        logger.info(f"[STEP 1] data: {data}")

        try:
            event = data.event
            logger.info(f"[STEP 1] event: {event}")

            if not event or not event.message:
                logger.warning("[STEP 1] Received event without message")
                return

            message = event.message
            logger.info(f"[STEP 1] message_id: {message.message_id}")
            logger.info(f"[STEP 1] chat_id: {message.chat_id}")
            logger.info(f"[STEP 1] chat_type: {message.chat_type}")
            logger.info(f"[STEP 1] msg_type: {message.message_type}")
            logger.info(f"[STEP 1] content: {message.content}")
            logger.info(f"[STEP 1] create_time: {message.create_time}")

            if event.sender:
                sender_id = event.sender.sender_id
                sender_open_id = sender_id.open_id if sender_id else 'N/A'
                # sender_name 可能不存在，使用 getattr 安全获取
                sender_name = getattr(event.sender, 'sender_name', None) or getattr(event.sender, 'sender_type', 'Unknown')
                logger.info(f"[STEP 1] sender.open_id: {sender_open_id}")
                logger.info(f"[STEP 1] sender.name/type: {sender_name}")

            # 提取消息内容
            content = message.content or "{}"
            try:
                content_obj = json.loads(content)
            except json.JSONDecodeError:
                content_obj = {"text": content}

            text = content_obj.get("text", "")
            chat_type = message.chat_type or "p2p"

            logger.info(f"[STEP 1] parsed text: '{text}'")
            logger.info(f"[STEP 1] chat_type: {chat_type}")

            # 构建 InboundMsg
            sender_open_id = event.sender.sender_id.open_id if event.sender and event.sender.sender_id else ""
            sender_name = getattr(event.sender, 'sender_name', None) or getattr(event.sender, 'sender_type', '') or ""

            inbound = InboundMsg(
                platform="feishu",
                sender=sender_open_id,
                sender_name=sender_name,
                conversation_id=message.chat_id or "",
                text=text,
                timestamp=float(message.create_time) if message.create_time else 0,
                attachments=[],
                extra={
                    "message_id": message.message_id,
                    "chat_type": chat_type,
                    "msg_type": message.message_type,
                    "account_id": self.account_id,  # For multi-account routing
                }
            )

            logger.info(f"[STEP 1] InboundMsg 构建完成")
            logger.info(f"[STEP 1] sender={inbound.sender}, conversation_id={inbound.conversation_id}")

            # 放入队列
            self._msg_queue.put(inbound)
            logger.info(f"[STEP 1] >>> 消息已放入队列，队列大小: {self._msg_queue.qsize()}")

        except Exception as e:
            logger.error(f"[STEP 1] ERROR: {e}", exc_info=True)

    async def _process_messages(self):
        """从队列处理消息"""
        logger.info("[STEP 2] ========================================")
        logger.info("[STEP 2] _process_messages 协程已启动!")
        logger.info(f"[STEP 2] streaming={self.streaming}, _streaming_handler is None: {self._streaming_handler is None}")
        logger.info(f"[STEP 2] _message_handler is None: {self._message_handler is None}")
        logger.info("[STEP 2] ========================================")
        logger.info("[STEP 2] _process_messages 协程已启动")
        logger.info(f"[STEP 2] streaming={self.streaming}, _streaming_handler is None: {self._streaming_handler is None}")
        logger.info(f"[STEP 2] _message_handler is None: {self._message_handler is None}")
        logger.info("[STEP 2] ========================================")

        while True:
            try:
                logger.debug("[STEP 2] Waiting for message from queue...")
                msg = await asyncio.to_thread(self._msg_queue.get, timeout=1)
                logger.info(f"[STEP 2] <<< 从队列取出消息: {msg.text[:30] if msg.text else '(empty)'}...")
                logger.info(f"[STEP 2] sender={msg.sender}, conversation_id={msg.conversation_id}")

                # 流式路径：有 streaming_handler 且开启 streaming
                if self.streaming and self._streaming_handler:
                    logger.info(f"[STEP 2] 使用流式处理...")
                    await self._process_streaming(msg)
                # 非流式路径
                elif self._message_handler:
                    logger.info(f"[STEP 2] 调用 Gateway.handle_inbound()...")
                    response = await self._message_handler(msg)
                    logger.info(f"[STEP 2] Gateway.handle_inbound() 返回完成")

                    if response:
                        logger.info(f"[STEP 3] >>> 调用 FeishuChannel.send() 发送回复...")
                        await self.send(msg.conversation_id, response)
                        logger.info(f"[STEP 3] <<< FeishuChannel.send() 完成")
                    else:
                        logger.info(f"[STEP 2] 业务处理返回 None，不发送回复")
                else:
                    logger.warning(f"[STEP 2] _message_handler 未设置，跳过处理")

                self._msg_queue.task_done()
                logger.info(f"[STEP 2] 消息处理完成，队列剩余: {self._msg_queue.qsize()}")

            except queue.Empty:
                # 静默等待，不打日志避免刷屏
                continue
            except Exception as e:
                logger.error(f"[STEP 2] ERROR: {e}", exc_info=True)

    async def _process_streaming(self, msg: InboundMsg) -> None:
        """流式处理消息"""
        from .feishu_streaming import FeishuStreamingCardSession, StreamingCardError

        logger.info("[STREAMING] === FeishuStreamingCardSession 开始 ===")

        # 确定 msg_type
        chat_type = msg.extra.get("chat_type", "p2p") if msg.extra else "p2p"

        session = FeishuStreamingCardSession(
            app_id=self.app_id,
            app_secret=self.app_secret,
            chat_id=msg.conversation_id,
            msg_type=chat_type,
            header_title=self.streaming_header_title,
        )

        try:
            # 启动会话：创建卡片 + 发送消息 + 开启流式模式
            await session.start()

            # 调用 streaming_handler 获取 agent 的 chunk
            if self._streaming_handler:
                async for chunk in self._streaming_handler(msg):
                    await session.append(chunk)

            # 完成流式
            await session.finish()

        except StreamingCardError as e:
            # 卡片创建失败，fallback 到普通文本消息
            logger.warning(f"[STREAMING] Card creation failed, falling back to text: {e}")
            try:
                if self._message_handler:
                    response = await self._message_handler(msg)
                    if response:
                        await self.send(msg.conversation_id, response)
            except Exception as fallback_err:
                logger.error(f"[STREAMING] Fallback failed: {fallback_err}", exc_info=True)

        except Exception as e:
            logger.error(f"[STREAMING] Error in _process_streaming(): {e}", exc_info=True)
            await session.abort(str(e))

    async def send(self, to: str, msg: OutboundMsg) -> None:
        """发送消息到飞书"""
        logger.info("[STEP 3] ============================================")
        logger.info("[STEP 3] 准备发送回复到飞书")
        logger.info(f"[STEP 3] 目标会话ID (to): {to}")
        logger.info(f"[STEP 3] 消息类型: {'text' if msg.text and not msg.attachments else 'interactive/card'}")
        logger.info(f"[STEP 3] 文本内容: {msg.text[:100] if msg.text else '(empty)'}")
        logger.info(f"[STEP 3] 附件数量: {len(msg.attachments) if msg.attachments else 0}")
        if msg.attachments:
            for i, att in enumerate(msg.attachments):
                logger.info(f"[STEP 3]   附件{i+1}: {att[:80]}...")
        logger.info("[STEP 3] ============================================")

        try:
            from lark_oapi import Client, AppType

            logger.info("[STEP 3] 创建 LarkClient HTTP 客户端...")
            client = Client.builder().app_id(self.app_id).app_secret(self.app_secret).app_type(AppType.SELF).build()
            logger.info("[STEP 3] LarkClient 创建完成")

            receive_id_type = "open_id" if to.startswith("ou_") else "chat_id"
            logger.info(f"[STEP 3] receive_id_type: {receive_id_type}")

            if msg.text and msg.attachments:
                card_content = {
                    "header": {
                        "title": {"tag": "plain_text", "content": msg.text[:50]}
                    },
                    "elements": [
                        {
                            "tag": "action",
                            "actions": [
                                {
                                    "tag": "button",
                                    "text": {"tag": "plain_text", "content": "查看详情"},
                                    "url": msg.attachments[0],
                                    "type": "primary"
                                }
                            ]
                        }
                    ]
                }

                request = CreateMessageRequest.builder().receive_id_type(
                    receive_id_type
                ).request_body(
                    CreateMessageRequestBody.builder()
                    .receive_id(to)
                    .msg_type("interactive")
                    .content(json.dumps({"card": card_content}))
                    .build()
                ).build()

                response = client.im.v1.message.create(request)
            elif msg.text:
                request = CreateMessageRequest.builder().receive_id_type(
                    receive_id_type
                ).request_body(
                    CreateMessageRequestBody.builder()
                    .receive_id(to)
                    .msg_type("text")
                    .content(json.dumps({"text": msg.text}))
                    .build()
                ).build()

                response = client.im.v1.message.create(request)
            else:
                logger.warning("Empty message, nothing to send")
                return

            logger.info(f"[STEP 3] API 调用完成，success={response.success()}")
            if not response.success():
                logger.error(f"[STEP 3] !!! 发送失败，错误码: {response.code}, 错误信息: {response.msg}")
                raise Exception(f"Failed to send message: {response.msg}")

            logger.info(f"[STEP 3] >>> 消息发送成功! to={to}")
            logger.info("[STEP 3] ============================================")

        except Exception as e:
            logger.error(f"[STEP 3] !!! ERROR: {e}", exc_info=True)
            raise

    async def stop(self) -> None:
        """停止监听"""
        if self._ws_thread:
            self._ws_thread.join(timeout=5)

        await super().stop()

    @classmethod
    def from_event(cls, payload: Dict[str, Any]) -> InboundMsg:
        """从飞书事件解析消息（兼容旧格式）"""
        event = payload.get("event", {})
        message = event.get("message", {})

        content = message.get("content", "{}")
        try:
            content_obj = json.loads(content)
        except json.JSONDecodeError:
            content_obj = {"text": content}

        return InboundMsg(
            platform="feishu",
            sender=message.get("sender", {}).get("sender_id", {}).get("open_id", ""),
            sender_name=message.get("sender", {}).get("sender_name", ""),
            conversation_id=message.get("chat_id", ""),
            text=content_obj.get("text", ""),
            timestamp=float(message.get("create_time", 0)),
            attachments=[],
            extra={
                "message_id": message.get("message_id"),
                "chat_type": message.get("chat_type"),
                "msg_type": message.get("msg_type")
            }
        )
