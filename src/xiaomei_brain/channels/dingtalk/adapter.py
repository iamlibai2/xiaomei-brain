"""DingTalkAdapter — 钉钉通道适配器。

基于 dingtalk-stream SDK（官方），和飞书 FeishuAdapter 模式一致：
- SDK WebSocket 接收消息 → 内联回调 → Router + living.put_message()
- Router.deliver() → adapter.send() → SDK reply_text/markdown

不依赖 ConsciousLiving 上的特定回调方法，新增频道无需改 ConsciousLiving。
"""

from __future__ import annotations

import logging
import time

from ...gateway.channel_adapter import ChannelAdapter
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

    client = DingTalkClient(client_id=client_id, client_secret=client_secret)
    ctx.register_channel("dingtalk", DingTalkAdapter(client))


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
        session = self._sessions.get(target)
        if session:
            webhook = session.get("session_webhook", "")
            sdk_msg = session.get("sdk_message")
            if webhook:
                ok = self._client.reply(webhook, text, msg_type, incoming_msg=sdk_msg)
                if ok:
                    return
            # 回复失败，清除过期缓存
            del self._sessions[target]

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
        adapter = self

        def on_message(msg_dict: dict) -> None:
            sender = msg_dict["sender"]
            conversation_id = msg_dict["conversation_id"]
            text = msg_dict["text"]
            is_group = msg_dict["is_group"]
            session_webhook = msg_dict.get("session_webhook", "")
            sdk_message = msg_dict.get("sdk_message")
            media_paths = msg_dict.get("media_paths", [])

            # session_id
            if is_group:
                session_id = f"dingtalk-cid-{conversation_id}"
                output_target = f"cid{conversation_id}"
            else:
                session_id = f"dingtalk-{sender}"
                output_target = sender

            # 缓存 session 信息用于回复（key 用 output_target，与 send() 对齐）
            if session_webhook:
                adapter._sessions[output_target] = {
                    "session_webhook": session_webhook,
                    "sdk_message": sdk_message,
                }

            # 注册 Peer 映射
            if router.route_for_session(session_id) is None:
                router.register_peer(
                    peer_type="human",
                    peer_id=sender,
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
                gw.accept(RawMessage(
                    content=text, source="human", channel="dingtalk",
                    peer_id=sender, peer_type="human",
                    images=media_paths, session_id=session_id,
                ))
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
                self._sessions.clear()
                logger.info("[DingTalkAdapter] 通道已关闭")
            except Exception as e:
                logger.warning("[DingTalkAdapter] 关闭通道失败: %s", e)
