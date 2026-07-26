"""FeishuChannel — 飞书 WebSocket 客户端 + HTTP 发送。"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
import time
from typing import Callable

from lark_oapi.api.im.v1.model import P2ImMessageReceiveV1, P2ImMessageReactionCreatedV1, P2ImMessageReactionDeletedV1
from lark_oapi.event.dispatcher_handler import EventDispatcherHandler
from lark_oapi.event.callback.model.p2_card_action_trigger import (
    P2CardActionTrigger,
    P2CardActionTriggerResponse,
)
from lark_oapi.core.enum import LogLevel
from lark_oapi.ws import Client
from lark_oapi.ws.enum import FrameType as _FrameType
import lark_oapi.ws.client as _lark_ws_client

from .types import OutboundMsg

logger = logging.getLogger(__name__)


class FeishuChannel:
    """飞书 WebSocket 客户端 — 基于 lark-oapi SDK。"""

    _RECONNECT_TIMEOUT = 60.0
    _SUPERVISOR_INTERVAL = 5.0
    _DEDUP_TTL = 5 * 60.0
    _DEDUP_MAX_SIZE = 2000
    _MESSAGE_MAX_AGE = 30 * 60.0

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
        self._on_feishu_card_action: Callable[[dict], tuple[bool, str]] | None = None
        self._ws_client: Client | None = None
        self._ws_thread: threading.Thread | None = None
        self._supervisor_thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._state = "stopped"
        self._last_error = ""
        self._stopping = False
        self._generation = 0
        self._reconnecting_since = 0.0
        self._restart_lock = threading.Lock()
        self._bot_open_id = ""
        self._seen_messages: dict[str, float] = {}
        self._seen_messages_lock = threading.Lock()

    def platform_name(self) -> str:
        return "feishu"

    def set_on_message(self, callback: Callable[[dict], None]) -> None:
        self._on_feishu_message = callback

    def set_on_card_action(
        self,
        callback: Callable[[dict], tuple[bool, str]],
    ) -> None:
        self._on_feishu_card_action = callback

    def _create_ws_client(self, generation: int) -> Client:
        handler = EventDispatcherHandler.builder(
            encrypt_key="",
            verification_token=self.verification_token,
            level=LogLevel.ERROR
        ).register_p2_im_message_receive_v1(
            lambda data: self._on_message(data, generation)
        ).register_p2_im_message_reaction_created_v1(
            lambda _: None
        ).register_p2_im_message_reaction_deleted_v1(
            lambda _: None
        ).register_p2_im_message_message_read_v1(
            lambda _: None  # 已读回执，静默忽略
        ).register_p2_im_message_recalled_v1(
            lambda _: None  # 撤回消息，静默忽略
        ).register_p2_card_action_trigger(
            lambda data: self._on_card_action(data, generation)
        ).build()

        return Client(
            app_id=self.app_id,
            app_secret=self.app_secret,
            log_level=LogLevel.ERROR,
            event_handler=handler
        )

    def _on_message(self, data: P2ImMessageReceiveV1, generation: int | None = None) -> None:
        # A supervisor restart can briefly leave the SDK's old worker alive.
        # Ignore events from that stale connection so one platform event is
        # never accepted twice.
        if generation is not None and generation != self._generation:
            logger.warning("[Feishu/WS] ignored event from stale connection")
            return
        try:
            event = data.event
            logger.info("[Feishu/WS] 收到事件: type=%s has_message=%s",
                        type(data).__name__, bool(event and event.message))
            if not event or not event.message:
                return

            message = event.message
            message_id = message.message_id or ""
            if self._is_stale_message(message.create_time):
                logger.info("[Feishu/WS] ignored stale message: %s", message_id)
                return
            if self._is_duplicate_message(message_id):
                logger.info("[Feishu/WS] ignored duplicate message: %s", message_id)
                return

            content = message.content or "{}"
            try:
                content_obj = json.loads(content)
            except json.JSONDecodeError:
                content_obj = {"text": content}

            text = content_obj.get("text", "")
            chat_type = message.chat_type or "p2p"
            mentions = message.mentions or []
            bot_mentions = [
                mention for mention in mentions
                if self._bot_open_id
                and getattr(getattr(mention, "id", None), "open_id", None)
                == self._bot_open_id
            ]
            bot_mentioned = chat_type == "p2p" or bool(bot_mentions)
            for mention in bot_mentions:
                key = getattr(mention, "key", "") or ""
                if key:
                    text = re.sub(rf"{re.escape(key)}\s*", "", text)
            text = text.strip()

            sender_open_id = event.sender.sender_id.open_id if event.sender and event.sender.sender_id else ""
            sender_name = getattr(event.sender, 'sender_name', None) or getattr(event.sender, 'sender_type', '') or ""

            msg_dict = {
                "platform": "feishu",
                "sender": sender_open_id,
                "sender_name": sender_name,
                "conversation_id": message.chat_id or "",
                "text": text,
                "timestamp": float(message.create_time) if message.create_time else 0,
                "message_id": message_id,
                "chat_type": chat_type,
                "bot_mentioned": bot_mentioned,
                "msg_type": message.message_type,
                "account_id": self.account_id,
            }

            logger.info("[Feishu] <- %s: %s", sender_open_id, text[:80] if text else "(empty)")

            if self._on_feishu_message:
                self._on_feishu_message(msg_dict)

        except Exception as e:
            logger.error("[Feishu] _on_message error: %s", e, exc_info=True)

    @classmethod
    def _is_stale_message(cls, create_time: str | int | None) -> bool:
        """Ignore delayed backlog events after a reconnect or process restart."""
        if not create_time:
            return False
        try:
            timestamp = float(create_time)
        except (TypeError, ValueError):
            return False
        if timestamp > 10_000_000_000:
            timestamp /= 1000
        return time.time() - timestamp > cls._MESSAGE_MAX_AGE

    def _is_duplicate_message(self, message_id: str) -> bool:
        """Return whether a platform event was already accepted recently."""
        if not message_id:
            return False
        now = time.monotonic()
        with self._seen_messages_lock:
            expired_before = now - self._DEDUP_TTL
            expired = [
                key for key, seen_at in self._seen_messages.items()
                if seen_at < expired_before
            ]
            for key in expired:
                self._seen_messages.pop(key, None)
            if message_id in self._seen_messages:
                return True
            while len(self._seen_messages) >= self._DEDUP_MAX_SIZE:
                self._seen_messages.pop(next(iter(self._seen_messages)))
            self._seen_messages[message_id] = now
            return False

    def _on_card_action(
        self,
        data: P2CardActionTrigger,
        generation: int,
    ) -> P2CardActionTriggerResponse:
        """Translate a trusted Feishu card callback into channel-neutral data."""
        if generation != self._generation:
            return P2CardActionTriggerResponse({
                "toast": {"type": "warning", "content": "连接已更新，请重新操作。"},
            })
        try:
            event = data.event
            action = event.action if event else None
            operator = event.operator if event else None
            context = event.context if event else None
            value = dict(action.value or {}) if action else {}
            callback = {
                "operator_open_id": operator.open_id if operator else "",
                "conversation_id": context.open_chat_id if context else "",
                "message_id": context.open_message_id if context else "",
                "value": value,
            }
            logger.info(
                "[Feishu/Card] action kind=%s operator=%s chat=%s",
                value.get("kind", ""),
                callback["operator_open_id"],
                callback["conversation_id"],
            )
            accepted, message = (
                self._on_feishu_card_action(callback)
                if self._on_feishu_card_action else (False, "当前操作不可用。")
            )
            return P2CardActionTriggerResponse({
                "toast": {
                    "type": "success" if accepted else "warning",
                    "content": message,
                },
            })
        except Exception:
            logger.exception("[Feishu/Card] callback failed")
            return P2CardActionTriggerResponse({
                "toast": {"type": "error", "content": "操作失败，请稍后重试。"},
            })

    def start(self) -> None:
        logger.info("[Feishu] Starting channel: app_id=%s account=%s", self.app_id, self.account_id)
        self._state = "starting"
        self._last_error = ""
        self._stopping = False
        self._bot_open_id = self._get_bot_open_id() or ""
        if not self._bot_open_id:
            logger.warning(
                "[Feishu] bot identity unavailable; group messages will be ignored"
            )
        self._launch_ws_worker()
        self._supervisor_thread = threading.Thread(
            target=self._supervise,
            daemon=True,
            name="feishu-supervisor",
        )
        self._supervisor_thread.start()

    def _launch_ws_worker(self) -> None:
        self._generation += 1
        generation = self._generation

        def run_ws():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            # 覆盖 SDK 模块级 loop——SDK start() 内部直接引用 this
            _lark_ws_client.loop = loop
            self._loop = loop
            logger.info("[Feishu/WS] daemon thread started (loop=%s)", loop)
            try:
                client = self._create_ws_client(generation)
                self._ws_client = client

                original_connect = client._connect

                async def _tracked_connect():
                    result = await original_connect()
                    if generation == self._generation:
                        self._state = "running"
                        self._last_error = ""
                        self._reconnecting_since = 0.0
                        logger.info("[Feishu/WS] connected")
                    return result

                client._connect = _tracked_connect

                original_reconnect = client._reconnect

                async def _tracked_reconnect():
                    if generation == self._generation:
                        self._state = "reconnecting"
                        self._last_error = "飞书长连接已断开，正在重连"
                        self._reconnecting_since = time.monotonic()
                        logger.warning("[Feishu/WS] disconnected; reconnecting")
                    return await original_reconnect()

                client._reconnect = _tracked_reconnect

                # 注入诊断：patch _handle_message 捕获异常帧
                _orig_handle_msg = client._handle_message

                async def _patched_handle_msg(msg: bytes) -> None:
                    try:
                        await _orig_handle_msg(msg)
                    except Exception:
                        logger.error("[Feishu/WS] _handle_message 异常: len=%d", len(msg), exc_info=True)

                client._handle_message = _patched_handle_msg

                logger.info("[Feishu/WS] ws_client created, calling start()...")
                client.start()
                logger.info("[Feishu/WS] ws_client.start() returned")
            except Exception as e:
                if not self._stopping and generation == self._generation:
                    self._state = "error"
                    self._last_error = str(e)
                    logger.error("[Feishu/WS] Error: %s", e, exc_info=True)
            finally:
                logger.info("[Feishu/WS] daemon thread exiting, closing loop")
                loop.close()
                if generation == self._generation:
                    self._loop = None
                    if self._state != "error":
                        self._state = "stopped"

        self._ws_thread = threading.Thread(target=run_ws, daemon=True, name="feishu-ws")
        self._ws_thread.start()

    def _supervise(self) -> None:
        """Restart a dead or wedged SDK worker.

        The SDK reconnect path performs endpoint discovery synchronously. A
        broken network can therefore leave its event loop stuck indefinitely.
        This application-level supervisor gives the channel a fresh connection
        while invalidating callbacks from the old generation.
        """
        while not self._stopping:
            time.sleep(self._SUPERVISOR_INTERVAL)
            if self._stopping:
                return
            thread_dead = self._ws_thread is not None and not self._ws_thread.is_alive()
            reconnect_stuck = (
                self._state == "reconnecting"
                and self._reconnecting_since > 0
                and time.monotonic() - self._reconnecting_since >= self._RECONNECT_TIMEOUT
            )
            if thread_dead or reconnect_stuck or self._state == "error":
                reason = (
                    "reconnect timeout" if reconnect_stuck
                    else "worker stopped" if thread_dead
                    else self._last_error or "unknown error"
                )
                self._restart_ws_worker(reason)

    def _restart_ws_worker(self, reason: str) -> None:
        if not self._restart_lock.acquire(blocking=False):
            return
        try:
            if self._stopping:
                return
            logger.warning("[Feishu/WS] restarting connection: %s", reason)
            old_client = self._ws_client
            old_loop = self._loop
            if old_client is not None:
                # Prevent a disconnected old client from beginning another
                # reconnect cycle after the replacement is online.
                old_client._auto_reconnect = False
            if old_loop is not None and old_loop.is_running():
                old_loop.call_soon_threadsafe(old_loop.stop)
            self._state = "starting"
            self._last_error = ""
            self._reconnecting_since = 0.0
            self._launch_ws_worker()
        finally:
            self._restart_lock.release()

    def stop(self) -> None:
        self._on_feishu_message = None
        self._on_feishu_card_action = None
        self._stopping = True
        loop = self._loop
        if loop and loop.is_running():
            client = self._ws_client
            if client is not None:
                try:
                    future = asyncio.run_coroutine_threadsafe(client._disconnect(), loop)
                    future.result(timeout=3)
                except Exception:
                    logger.debug("[Feishu/WS] disconnect during stop failed", exc_info=True)
            loop.call_soon_threadsafe(loop.stop)
        if self._ws_thread:
            self._ws_thread.join(timeout=5)
        if self._supervisor_thread:
            self._supervisor_thread.join(timeout=self._SUPERVISOR_INTERVAL + 1)
        with self._seen_messages_lock:
            self._seen_messages.clear()
        self._state = "stopped"

    def test_credentials(self) -> bool:
        """Validate credentials without opening a long-lived WebSocket."""
        self._invalidate_token_cache(self.app_id)
        return bool(self._get_token())

    def status(self) -> dict:
        return {
            "state": self._state,
            "error": self._last_error,
            "app_id": self.app_id,
            "account_id": self.account_id,
        }

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

    def _get_bot_open_id(self) -> str | None:
        """Resolve this application's bot identity for exact group @ matching."""
        import requests

        token = self._get_token()
        if not token:
            return None
        try:
            response = requests.get(
                "https://open.feishu.cn/open-apis/bot/v3/info",
                headers={"Authorization": f"Bearer {token}"},
                timeout=15,
            )
            payload = response.json()
            if response.status_code != 200 or payload.get("code", 0) != 0:
                logger.warning(
                    "[Feishu/Auth] failed to load bot identity: status=%s code=%s",
                    response.status_code,
                    payload.get("code"),
                )
                return None
            bot = payload.get("bot") or (payload.get("data") or {}).get("bot") or {}
            return bot.get("open_id") or None
        except Exception:
            logger.warning("[Feishu/Auth] failed to load bot identity", exc_info=True)
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
        if msg.text and msg.attachments:
            card = {
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
            self.send_card(to, card)
        elif msg.text:
            self._send_payload(to, "text", {"text": msg.text})

    def send_card(self, to: str, card: dict) -> None:
        """Send an interactive card using Feishu's message API."""
        self._send_payload(to, "interactive", card)

    def _send_payload(self, to: str, msg_type: str, content: dict) -> None:
        import requests as _requests

        try:
            receive_id_type = "open_id" if to.startswith("ou_") else "chat_id"
            body = {
                "receive_id": to,
                "msg_type": msg_type,
                "content": json.dumps(content, ensure_ascii=False),
            }

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
