"""FeishuChannel — 飞书 WebSocket 客户端 + HTTP 发送。"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from typing import Callable

from lark_oapi.api.im.v1.model import P2ImMessageReceiveV1, P2ImMessageReactionCreatedV1, P2ImMessageReactionDeletedV1
from lark_oapi.event.dispatcher_handler import EventDispatcherHandler
from lark_oapi.core.enum import LogLevel
from lark_oapi.ws import Client
import lark_oapi.ws.client as _lark_ws_client

from .types import OutboundMsg

logger = logging.getLogger(__name__)


class FeishuChannel:
    """飞书 WebSocket 客户端 — 基于 lark-oapi SDK。"""

    def __init__(
        self,
        app_id: str,
        app_secret: str,
        verification_token: str = "",
        account_id: str = "default",
        streaming: bool = False,
        streaming_header_title: str = "小美",
    ):
        self.app_id = app_id
        self.app_secret = app_secret
        self.verification_token = verification_token
        self.account_id = account_id
        self.streaming = streaming
        self.streaming_header_title = streaming_header_title
        self._on_feishu_message: Callable[[dict], None] | None = None
        self._ws_client: Client | None = None
        self._ws_thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        # Token 缓存：避免每次发送都获取新 token（多实例共享同一应用时会互相踢掉）
        self._cached_token: str = ""
        self._token_expires_at: float = 0.0

    def platform_name(self) -> str:
        return "feishu"

    def set_on_message(self, callback: Callable[[dict], None]) -> None:
        self._on_feishu_message = callback

    def _create_ws_client(self) -> Client:
        handler = EventDispatcherHandler.builder(
            encrypt_key="",
            verification_token=self.verification_token,
            level=LogLevel.INFO
        ).register_p2_im_message_receive_v1(
            self._on_message
        ).register_p2_im_message_reaction_created_v1(
            lambda _: None  # 忽略表情反应事件
        ).register_p2_im_message_reaction_deleted_v1(
            lambda _: None
        ).build()

        return Client(
            app_id=self.app_id,
            app_secret=self.app_secret,
            log_level=LogLevel.INFO,
            event_handler=handler
        )

    def _on_message(self, data: P2ImMessageReceiveV1) -> None:
        try:
            event = data.event
            logger.info("[Feishu/WS] 收到事件: type=%s has_message=%s",
                        type(data).__name__, bool(event and event.message))
            if not event or not event.message:
                return

            message = event.message

            content = message.content or "{}"
            try:
                content_obj = json.loads(content)
            except json.JSONDecodeError:
                content_obj = {"text": content}

            text = content_obj.get("text", "")
            chat_type = message.chat_type or "p2p"

            sender_open_id = event.sender.sender_id.open_id if event.sender and event.sender.sender_id else ""
            sender_name = getattr(event.sender, 'sender_name', None) or getattr(event.sender, 'sender_type', '') or ""

            msg_dict = {
                "platform": "feishu",
                "sender": sender_open_id,
                "sender_name": sender_name,
                "conversation_id": message.chat_id or "",
                "text": text,
                "timestamp": float(message.create_time) if message.create_time else 0,
                "message_id": message.message_id,
                "chat_type": chat_type,
                "msg_type": message.message_type,
                "account_id": self.account_id,
            }

            logger.info("[Feishu] <- %s: %s", sender_open_id, text[:80] if text else "(empty)")

            if self._on_feishu_message:
                self._on_feishu_message(msg_dict)

        except Exception as e:
            logger.error("[Feishu] _on_message error: %s", e, exc_info=True)

    def start(self) -> None:
        logger.info("[Feishu] Starting channel: app_id=%s account=%s", self.app_id, self.account_id)

        def run_ws():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            # 覆盖 SDK 模块级 loop——SDK start() 内部直接引用 this
            _lark_ws_client.loop = loop
            self._loop = loop
            logger.info("[Feishu/WS] daemon thread started (loop=%s)", loop)
            try:
                self._ws_client = self._create_ws_client()
                logger.info("[Feishu/WS] ws_client created, calling start()...")
                self._ws_client.start()
                logger.info("[Feishu/WS] ws_client.start() returned")
            except Exception as e:
                logger.error("[Feishu/WS] Error: %s", e, exc_info=True)
            finally:
                logger.info("[Feishu/WS] daemon thread exiting, closing loop")
                loop.close()
                self._loop = None

        self._ws_thread = threading.Thread(target=run_ws, daemon=True, name="feishu-ws")
        self._ws_thread.start()

    def stop(self) -> None:
        self._on_feishu_message = None
        if self._ws_thread:
            self._ws_thread.join(timeout=5)

    def _get_token(self) -> str | None:
        """获取 tenant access token（带缓存，expires 约 2h，提前 5min 刷新）。"""
        import time as _time
        import requests as _requests

        now = _time.time()
        if self._cached_token and now < self._token_expires_at:
            return self._cached_token

        try:
            token_resp = _requests.post(
                "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                json={"app_id": self.app_id, "app_secret": self.app_secret},
                headers={"Content-Type": "application/json; charset=utf-8"},
                timeout=10,
            )
            token_data = token_resp.json()
            if token_data.get("code") != 0:
                logger.error("[Feishu/Auth] 获取 token 失败: %s", token_data.get("msg"))
                return None
            self._cached_token = token_data["tenant_access_token"]
            # 提前 5 分钟过期，避免边界情况
            self._token_expires_at = now + token_data.get("expire", 7200) - 300
            logger.debug("[Feishu/Auth] token 已刷新，过期时间=%d", int(self._token_expires_at - now))
            return self._cached_token
        except Exception as e:
            logger.error("[Feishu/Auth] 获取 token 异常: %s", e)
            return None

    def send(self, to: str, msg: OutboundMsg) -> None:
        """发送消息到飞书。使用缓存 token，避免多实例互相踢 token。"""
        import requests as _requests

        try:
            receive_id_type = "open_id" if to.startswith("ou_") else "chat_id"

            if msg.text and msg.attachments:
                card_content = {
                    "header": {"title": {"tag": "plain_text", "content": msg.text[:50]}},
                    "elements": [{
                        "tag": "action",
                        "actions": [{
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": "查看详情"},
                            "url": msg.attachments[0],
                            "type": "primary"
                        }]
                    }]
                }
                body = {
                    "receive_id": to,
                    "msg_type": "interactive",
                    "content": json.dumps({"card": card_content}),
                }
            elif msg.text:
                body = {
                    "receive_id": to,
                    "msg_type": "text",
                    "content": json.dumps({"text": msg.text}),
                }
            else:
                return

            for attempt in range(3):
                token = self._get_token()
                if not token:
                    return   # token 获取失败，不重试

                resp = _requests.post(
                    f"https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type={receive_id_type}",
                    json=body,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json; charset=utf-8",
                    },
                    timeout=15,
                )
                data = resp.json()
                code = data.get("code", -1)
                msg_text = data.get("msg", "")

                if code == 0:
                    logger.info("[Feishu] -> OK (msg_id=%s)",
                                data.get("data", {}).get("message_id", "?"))
                    return

                # 飞书 token 类错误码（过期/无效/被踢等）
                if code in (99991663, 99991664, 99991665, 99991666):
                    logger.warning("[Feishu] token 失效 (code=%d)，刷新后重试 (attempt %d)", code, attempt + 1)
                    self._cached_token = ""  # 强制刷新
                    self._token_expires_at = 0
                    continue

                # HTTP 401
                if resp.status_code == 401:
                    logger.warning("[Feishu] HTTP 401, 刷新 token 后重试 (attempt %d)", attempt + 1)
                    self._cached_token = ""
                    self._token_expires_at = 0
                    continue

                logger.error("[Feishu] -> FAILED: HTTP=%s code=%s msg=%s",
                             resp.status_code, code, msg_text)
                return

            logger.error("[Feishu] -> 重试后仍失败")

        except Exception as e:
            logger.error("[Feishu] send error: %s", e, exc_info=True)
