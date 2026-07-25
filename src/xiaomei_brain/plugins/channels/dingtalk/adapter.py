"""DingTalkAdapter — 钉钉通道适配器。

基于 dingtalk-stream SDK（官方），和飞书 FeishuAdapter 模式一致：
- SDK WebSocket 接收消息 → 内联回调 → Router + living.put_message()
- Router.deliver() → adapter.send() → SDK reply_text/markdown

不依赖 ConsciousLiving 上的特定回调方法，新增频道无需改 ConsciousLiving。
"""

from __future__ import annotations

import logging
import re
import threading
import time

from xiaomei_brain.gateway.channel_adapter import ChannelAdapter, ChannelCapabilities
from .client import DingTalkClient

logger = logging.getLogger(__name__)


def register(ctx):
    """插件入口：从 config.json 读取配置，注册钉钉频道。

    兼容新旧命名：clientId/clientSecret 优先，appKey/appSecret 兜底。
    """
    client_id = ctx.config.get("clientId") or ctx.config.get("appKey", "")
    client_secret = ctx.config.get("clientSecret") or ctx.config.get("appSecret", "")

    if not client_id or not client_secret:
        ctx.logger.warning("钉钉配置缺失（clientId/clientSecret），跳过注册")
        return

    ctx.register_channel("dingtalk", create_adapter(ctx.config))


def create_adapter(config: dict) -> "DingTalkAdapter":
    """Build an adapter from a normalized DingTalk account configuration."""
    client_id = (
        config.get("clientId")
        or config.get("appId")
        or config.get("appKey")
        or ""
    )
    client_secret = (
        config.get("clientSecret")
        or config.get("appSecret")
        or ""
    )
    if not client_id or not client_secret:
        raise ValueError("钉钉 Client ID 和 Client Secret 不能为空")
    return DingTalkAdapter(DingTalkClient(client_id, client_secret))


class DingTalkAdapter(ChannelAdapter):
    """钉钉通道适配器。

    消息流：
    1. SDK WebSocket 接收 → on_message 回调 → Router.register_peer() + living.put_message()
    2. Core 处理后 Router.deliver() → adapter.send() → client.reply(session_webhook, text)
    """

    def __init__(self, client: DingTalkClient) -> None:
        self._client = client
        # 缓存：session_id → {"session_webhook": ..., "sdk_message": ChatbotMessage}
        self._sessions: dict[str, dict] = {}
        self._sessions_lock = threading.Lock()

    @property
    def capabilities(self) -> ChannelCapabilities:
        return ChannelCapabilities(
            clarify=True,
            action_approval=True,
            attachments=True,
        )

    @property
    def channel_type(self) -> str:
        return "dingtalk"

    def send(self, target: str, text: str, msg_type: str = "text") -> None:
        """向钉钉用户/群发送消息。Core 通过 Router.deliver() 调用此方法。

        优先使用 SDK 的 sessionWebhook 回复（含 @发送者），
        缓存过期则降级为主动发送。
        """
        logger.info("[DingTalkAdapter] Router.deliver -> target=%s text=%s", target, text[:80])

        # 自动检测 Markdown
        msg_type = "text"
        if any(c in text for c in "#*>-[]`_") and "\n" in text:
            msg_type = "markdown"

        # 优先使用缓存的 session 信息回复
        with self._sessions_lock:
            session = self._sessions.get(target)
        if session:
            webhook = session.get("session_webhook", "")
            sdk_msg = session.get("sdk_message")
            if webhook:
                ok = self._client.reply(webhook, text, msg_type, incoming_msg=sdk_msg)
                if ok:
                    return
            # 回复失败，清除过期缓存
            with self._sessions_lock:
                self._sessions.pop(target, None)

        # 降级：主动发送
        is_group = target.startswith("cid")
        self._client.send(target, text, msg_type, is_group=is_group)

    def setup(self, living=None) -> None:
        """启动通道，桥接 living 和钉钉消息。

        内联回调闭包捕捉 living._router + living.put_message()。
        """
        if not living or not self._client:
            return

        router = living._router
        people = getattr(living, "_people_service", None)
        link_service = getattr(living, "_identity_link_service", None)
        issuer = f"dingtalk:app:{self._client.client_id}"
        adapter = self

        def on_message(msg_dict: dict) -> None:
            sender = msg_dict["sender"]
            conversation_id = msg_dict["conversation_id"]
            text = msg_dict["text"]
            is_group = msg_dict["is_group"]
            bot_mentioned = msg_dict.get("bot_mentioned")
            session_webhook = msg_dict.get("session_webhook", "")
            sdk_message = msg_dict.get("sdk_message")
            media_paths = msg_dict.get("media_paths", [])

            output_target = conversation_id if is_group else sender

            # Match the natural DingTalk bot behavior used by WorkBuddy:
            # direct messages are always accepted, while group chatter is
            # ignored when DingTalk explicitly says the bot wasn't mentioned.
            # An absent flag is allowed so SDK/platform variations don't make
            # valid @ messages disappear silently.
            if is_group and bot_mentioned is False:
                logger.info(
                    "[DingTalk] group message ignored (bot not mentioned): "
                    "conversation=%s sender=%s",
                    conversation_id,
                    sender,
                )
                return

            # 缓存 session 信息用于回复（key 用 output_target，与 send() 对齐）
            if session_webhook:
                with adapter._sessions_lock:
                    adapter._sessions[output_target] = {
                        "session_webhook": session_webhook,
                        "sdk_message": sdk_message,
                    }

            match = re.search(
                r"(?:^|\n)\s*(?:绑定|bind)\s+(\d{6})\s*$",
                text,
                re.IGNORECASE,
            )
            if match:
                if is_group:
                    self.send(output_target, "请在与机器人的私聊中完成身份绑定。")
                    return
                try:
                    binding = (
                        link_service.consume(
                            "dingtalk", issuer, sender, match.group(1),
                        )
                        if link_service else None
                    )
                except ValueError as exc:
                    self.send(output_target, str(exc))
                    return
                if binding is None:
                    self.send(
                        output_target,
                        "绑定码无效或已过期，请在 Desktop 中重新生成。",
                    )
                    return
                self.send(output_target, "身份绑定成功，现在我能认出你了。")
                return

            resolved = (
                people.resolve_verified_identity(issuer, sender)
                if people else None
            )
            if resolved is None:
                self.send(
                    output_target,
                    "我还不能确认你是谁。请在 Desktop 的渠道配置中生成绑定码，再发送“绑定 123456”。",
                )
                return
            person, _binding = resolved
            person_id = person.person_id
            # Group conversations are scoped per recognized Person for now.
            # This prevents one colleague from reading another's context until
            # a first-class multi-person conversation model exists.
            session_id = (
                f"dingtalk-group-{conversation_id}-{person_id}"
                if is_group
                else f"dingtalk-{person_id}"
            )
            people.store.ensure_person_session(session_id, person_id)

            # 注册 Peer 映射
            has_route = (
                router.has_route(session_id, "dingtalk", output_target)
                if hasattr(router, "has_route") else False
            )
            if not has_route:
                router.register_peer(
                    peer_type="human",
                    peer_id=person_id,
                    channel="dingtalk",
                    session_id=session_id,
                    output_type="dingtalk",
                    output_target=output_target,
                    priority=10,
                )

            ts = time.strftime("%H:%M:%S")
            logger.info("[DingTalk] <- %s: %s", sender, text[:80])

            gw = getattr(living, '_gateway_inbound', None)
            if gw:
                from xiaomei_brain.gateway.inbound import RawMessage
                result = gw.accept(RawMessage(
                    content=text, source="human", channel="dingtalk",
                    peer_id=person_id, peer_type="human",
                    images=media_paths, session_id=session_id,
                    metadata={
                        "external_issuer": issuer,
                        "external_subject": sender,
                        "external_conversation_id": conversation_id,
                    },
                    reply_channel="dingtalk", reply_target=output_target,
                ))
                reason = getattr(result, "reason", "")
                if reason and not getattr(result, "silent", False):
                    self.send(output_target, "这条消息暂时没有接收成功，请稍后重试。")
            else:
                living.put_message(text, source="human", session_id=session_id,
                                  images=media_paths)
            if hasattr(living, "_debug_log"):
                living._debug_log("dingtalk", f"{ts} <- {sender}: {text[:80]}")

        logger.info("[DingTalkAdapter] 注册 on_message 回调，启动 client...")
        self._client.set_on_message(on_message)
        self._client.start()
        logger.info("[DingTalkAdapter] 通道已启动（Stream Mode）")

    def shutdown(self) -> None:
        """关闭钉钉通道。"""
        if self._client:
            try:
                self._client.stop()
                with self._sessions_lock:
                    self._sessions.clear()
                logger.info("[DingTalkAdapter] 通道已关闭")
            except Exception as e:
                logger.warning("[DingTalkAdapter] 关闭通道失败: %s", e)

    def status(self) -> dict:
        return self._client.status()
