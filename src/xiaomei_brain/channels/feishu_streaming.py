"""飞书流式卡片会话管理 - 使用 CardKit 2.0 API 实现流式回复"""

import asyncio
import json
import logging
import time
from typing import Optional

from lark_oapi import Client
from lark_oapi.api.cardkit.v1.model import CreateCardRequest, CreateCardRequestBody
from lark_oapi.api.cardkit.v1.model.content_card_element_request import ContentCardElementRequest
from lark_oapi.api.cardkit.v1.model.content_card_element_request_body import ContentCardElementRequestBody
from lark_oapi.api.cardkit.v1.model.settings_card_request import SettingsCardRequest
from lark_oapi.api.cardkit.v1.model.settings_card_request_body import SettingsCardRequestBody
from lark_oapi.api.cardkit.v1.model.update_card_request import UpdateCardRequest
from lark_oapi.api.cardkit.v1.model.update_card_request_body import UpdateCardRequestBody

logger = logging.getLogger(__name__)


class StreamingCardError(Exception):
    """流式卡片异常，包含错误信息供调用方 fallback"""


class FeishuStreamingCardSession:
    """一次流式回复的完整生命周期管理

    流程:
    1. start() - 创建 CardKit 卡片实体 (card_id)
    2. start() - 发送 IM 消息引用卡片 (message_id)
    3. start() - 开启流式模式 (streaming_mode=true)
    4. append() - 每收到一个 chunk → 更新卡片元素内容 (带节流)
    5. finish() - 关闭流式模式 (streaming_mode=false)
    """

    def __init__(
        self,
        app_id: str,
        app_secret: str,
        chat_id: str,
        msg_type: str = "p2p",
        header_title: str = "小美",
        element_id: str = "streaming_content",
    ):
        self.app_id = app_id
        self.app_secret = app_secret
        self.chat_id = chat_id
        self.msg_type = msg_type
        self.header_title = header_title
        self.element_id = element_id

        # 状态机
        self.state = "idle"  # idle/creating/streaming/completed/aborted

        # 卡片标识
        self.card_id: Optional[str] = None
        self.message_id: Optional[str] = None

        # 内容累积
        self.content = ""
        self.sequence = 0

        # 节流控制
        self._throttle_ms = 100  # CardKit 元素内容更新最小间隔
        self._last_update_time = 0.0

        # 延迟初始化 client
        self._client: Optional[Client] = None

    def _get_client(self) -> Client:
        """延迟创建 Lark 客户端"""
        if self._client is None:
            from lark_oapi import AppType
            self._client = (
                Client.builder()
                .app_id(self.app_id)
                .app_secret(self.app_secret)
                .app_type(AppType.SELF)
                .build()
            )
        return self._client

    def _build_card_data(self) -> dict:
        """构建卡片数据 (Schema 2.0)"""
        return {
            "schema": "2.0",
            "config": {
                "streaming_mode": True,
                "locales": ["zh_cn", "en_us"],
                "summary": {
                    "content": "Thinking...",
                    "i18n_content": {"zh_cn": "思考中...", "en_us": "Thinking..."},
                },
            },
            "header": {
                "title": {"tag": "plain_text", "content": f"{self.header_title} 正在思考..."},
                "template": "blue",
            },
            "body": {
                "elements": [
                    {
                        "tag": "markdown",
                        "element_id": self.element_id,
                        "content": "",
                        "text_align": "left",
                        "text_size": "normal_v2",
                        "margin": "0px 0px 0px 0px",
                    }
                ]
            },
        }

    async def start(self) -> None:
        """创建卡片 + 发送消息 + 开启流式模式"""
        logger.info(f"[STREAMING] Starting session for chat_id={self.chat_id}")
        self.state = "creating"

        try:
            client = self._get_client()

            # 1. 创建 CardKit 卡片实体
            card_data = self._build_card_data()
            create_req_body = (
                CreateCardRequestBody.builder()
                .type("card_json")
                .data(json.dumps(card_data))
                .build()
            )
            create_req = (
                CreateCardRequest.builder()
                .request_body(create_req_body)
                .build()
            )
            create_resp = await asyncio.to_thread(client.cardkit.v1.card.create, create_req)

            if not create_resp.success():
                raise Exception(f"Failed to create card: {create_resp.msg}")

            self.card_id = create_resp.data.card_id
            logger.info(f"[STREAMING] Card created: card_id={self.card_id}")

            # 2. 发送 IM 消息引用卡片
            from lark_oapi.api.im.v1 import CreateMessageRequest
            from lark_oapi.api.im.v1.model import CreateMessageRequestBody

            receive_id_type = "open_id" if self.chat_id.startswith("ou_") else "chat_id"

            message_req = (
                CreateMessageRequest.builder()
                .receive_id_type(receive_id_type)
                .request_body(
                    CreateMessageRequestBody.builder()
                    .receive_id(self.chat_id)
                    .msg_type("interactive")
                    .content(json.dumps({"type": "card", "data": {"card_id": self.card_id}}))
                    .build()
                )
                .build()
            )
            message_resp = await asyncio.to_thread(client.im.v1.message.create, message_req)

            if not message_resp.success():
                raise Exception(f"Failed to send message: {message_resp.msg}")

            self.message_id = message_resp.data.message_id
            logger.info(f"[STREAMING] Message sent: message_id={self.message_id}")

            # 3. 开启流式模式 (settings PATCH)
            self.sequence += 1
            settings_data = {"streaming_mode": True}
            settings_req_body = (
                SettingsCardRequestBody.builder()
                .settings(json.dumps(settings_data))
                .sequence(self.sequence)
                .build()
            )
            settings_req = (
                SettingsCardRequest.builder()
                .card_id(self.card_id)
                .request_body(settings_req_body)
                .build()
            )

            client = self._get_client()
            settings_resp = await asyncio.to_thread(client.cardkit.v1.card.settings, settings_req)

            if not settings_resp.success():
                logger.warning(f"[STREAMING] Failed to enable streaming mode: {settings_resp.msg}")

            self.state = "streaming"
            logger.info("[STREAMING] Session started, ready to stream content")

        except Exception as e:
            logger.error(f"[STREAMING] Error in start(): {e}", exc_info=True)
            self.state = "aborted"
            raise StreamingCardError(str(e)) from e

    async def append(self, chunk: str) -> None:
        """追加内容块，带节流 (100ms)"""
        if not chunk or self.state != "streaming":
            return

        self.content += chunk
        now = time.time()

        # CardKit 节流: 100ms
        if now - self._last_update_time >= (self._throttle_ms / 1000):
            await self._update_element()
            self._last_update_time = now

    async def finish(self) -> None:
        """流式完成：最终更新 + 关闭流式模式"""
        if self.state not in ("streaming", "creating"):
            logger.warning(f"[STREAMING] Session not active, state={self.state}")
            return

        logger.info("[STREAMING] Finishing session")
        self.state = "completed"

        try:
            # 1. 强制最终更新 element content
            await self._update_element()

            # 2. 关闭流式模式
            self.sequence += 1
            settings_data = {"streaming_mode": False}
            settings_req_body = (
                SettingsCardRequestBody.builder()
                .settings(json.dumps(settings_data))
                .sequence(self.sequence)
                .build()
            )
            settings_req = (
                SettingsCardRequest.builder()
                .card_id(self.card_id)
                .request_body(settings_req_body)
                .build()
            )

            client = self._get_client()
            settings_resp = await asyncio.to_thread(client.cardkit.v1.card.settings, settings_req)

            if not settings_resp.success():
                logger.warning(f"[STREAMING] Failed to disable streaming mode: {settings_resp.msg}")

            logger.info("[STREAMING] Streaming mode disabled")

            # 3. 更新 header 标题（去掉"正在思考..."）
            await self._update_header()

        except Exception as e:
            logger.error(f"[STREAMING] Error in finish(): {e}", exc_info=True)

    async def abort(self, error: str) -> None:
        """异常终止"""
        logger.warning(f"[STREAMING] Aborting session: {error}")
        self.state = "aborted"

        if not self.card_id:
            return

        try:
            # 关闭流式模式
            self.sequence += 1
            settings_data = {"streaming_mode": False}
            settings_req_body = (
                SettingsCardRequestBody.builder()
                .settings(json.dumps(settings_data))
                .sequence(self.sequence)
                .build()
            )
            settings_req = (
                SettingsCardRequest.builder()
                .card_id(self.card_id)
                .request_body(settings_req_body)
                .build()
            )
            client = self._get_client()
            await asyncio.to_thread(client.cardkit.v1.card.settings, settings_req)

            # 更新卡片显示错误信息
            await self._update_element_content(f"\n\n⚠️ 回复中断: {error}")
        except Exception as e:
            logger.error(f"[STREAMING] Error in abort(): {e}", exc_info=True)

    async def _update_element(self) -> None:
        """更新 CardKit 元素内容"""
        if not self.card_id:
            logger.warning("[STREAMING] No card_id, skipping update")
            return

        try:
            # 调用前递增 sequence
            self.sequence += 1

            content_req_body = (
                ContentCardElementRequestBody.builder()
                .content(self.content)
                .sequence(self.sequence)
                .build()
            )
            content_req = (
                ContentCardElementRequest.builder()
                .card_id(self.card_id)
                .element_id(self.element_id)
                .request_body(content_req_body)
                .build()
            )

            client = self._get_client()
            content_resp = await asyncio.to_thread(client.cardkit.v1.card_element.content, content_req)

            if not content_resp.success():
                logger.warning(f"[STREAMING] Failed to update element: {content_resp.msg}")

            logger.debug(f"[STREAMING] Updated element, sequence={self.sequence}, content_len={len(self.content)}")

        except Exception as e:
            logger.error(f"[STREAMING] Error in _update_element(): {e}", exc_info=True)

    async def _update_element_content(self, content: str) -> None:
        """强制更新元素内容（不检查节流）"""
        self.content = content
        await self._update_element()

    async def _update_header(self) -> None:
        """更新卡片 header 标题（流式完成后调用）"""
        if not self.card_id:
            return

        try:
            self.sequence += 1

            # 构建完整卡片数据（header 标题去掉"正在思考..."）
            card_data = {
                "schema": "2.0",
                "config": {
                    "streaming_mode": False,
                    "locales": ["zh_cn", "en_us"],
                    "summary": {
                        "content": self.content[:50],
                        "i18n_content": {"zh_cn": self.content[:50], "en_us": self.content[:50]},
                    },
                },
                "header": {
                    "title": {"tag": "plain_text", "content": self.header_title},
                    "template": "blue",
                },
                "body": {
                    "elements": [
                        {
                            "tag": "markdown",
                            "element_id": self.element_id,
                            "content": self.content,
                            "text_align": "left",
                            "text_size": "normal_v2",
                            "margin": "0px 0px 0px 0px",
                        }
                    ]
                },
            }

            from lark_oapi.api.cardkit.v1.model import Card

            card_obj = Card.builder().type("card_json").data(json.dumps(card_data)).build()
            update_req_body = (
                UpdateCardRequestBody.builder()
                .card(card_obj)
                .sequence(self.sequence)
                .build()
            )
            update_req = (
                UpdateCardRequest.builder()
                .card_id(self.card_id)
                .request_body(update_req_body)
                .build()
            )

            client = self._get_client()
            update_resp = await asyncio.to_thread(client.cardkit.v1.card.update, update_req)

            if not update_resp.success():
                logger.warning(f"[STREAMING] Failed to update header: {update_resp.msg}")
            else:
                logger.info("[STREAMING] Header updated successfully")

        except Exception as e:
            logger.error(f"[STREAMING] Error in _update_header(): {e}", exc_info=True)

