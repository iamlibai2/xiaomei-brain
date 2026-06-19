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
from lark_oapi.ws.enum import FrameType as _FrameType
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
        streaming_header_title: str = "agent",
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
            lambda _: None
        ).register_p2_im_message_reaction_deleted_v1(
            lambda _: None
        ).register_p2_im_message_message_read_v1(
            lambda _: None  # 已读回执，静默忽略
        ).register_p2_im_message_recalled_v1(
            lambda _: None  # 撤回消息，静默忽略
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

                # 注入诊断：patch _handle_message 捕获异常帧
                _orig_handle_msg = self._ws_client._handle_message

                async def _patched_handle_msg(msg: bytes) -> None:
                    try:
                        await _orig_handle_msg(msg)
                    except Exception:
                        logger.error("[Feishu/WS] _handle_message 异常: len=%d", len(msg), exc_info=True)

                self._ws_client._handle_message = _patched_handle_msg

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
        """获取 tenant access token（与 SDK WS 共享缓存，避免互相踢 token）。

        lark_oapi SDK 的 WS 连接内部也用 TokenManager.get_self_tenant_token()
        管理 token，使用进程级单例 LocalCache。这里复用同一个缓存，
        确保 send 和 WS 用的是同一个 token，不会因各自刷新而互相踢。
        """
        from lark_oapi.core.model.config import Config
        from lark_oapi.core.token.manager import TokenManager

        config = Config()
        config.app_id = self.app_id
        config.app_secret = self.app_secret

        try:
            return TokenManager.get_self_tenant_token(config)
        except Exception as e:
            logger.error("[Feishu/Auth] 获取 token 异常: %s", e)
            return None

    @staticmethod
    def _invalidate_token_cache(app_id: str) -> None:
        """强制使共享 token 缓存失效（触发下次调用时重新获取）。"""
        from lark_oapi.core.token.manager import TokenManager

        cache_key = f"self_tenant_token:{app_id}"
        # LocalCache 没有 delete，通过设一个过期时间戳来失效
        TokenManager.cache.set(cache_key, "", 0)

    def send(self, to: str, msg: OutboundMsg) -> None:
        """发送消息到飞书。与 SDK WS 共享 token 缓存，避免互相踢。"""
        import requests as _requests

        # 设置 SDK 的 app_id/app_secret（首次发送时懒初始化）
        if not hasattr(self, '_sdk_config_set'):
            from lark_oapi.core.model.config import Config
            self._sdk_config = Config()
            self._sdk_config.app_id = self.app_id
            self._sdk_config.app_secret = self.app_secret
            self._sdk_config_set = True

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
                    return

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
                    self._invalidate_token_cache(self.app_id)
                    continue

                # HTTP 401：token 过期/无效，强制刷新后重试
                if resp.status_code == 401:
                    logger.warning("[Feishu] HTTP 401，刷新后重试 (attempt %d)", attempt + 1)
                    self._invalidate_token_cache(self.app_id)
                    continue

                logger.error("[Feishu] -> FAILED: HTTP=%s code=%s msg=%s",
                             resp.status_code, code, msg_text)
                return

            logger.error("[Feishu] -> 重试后仍失败")

        except Exception as e:
            logger.error("[Feishu] send error: %s", e, exc_info=True)
