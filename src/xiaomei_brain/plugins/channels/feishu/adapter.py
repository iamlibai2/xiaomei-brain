"""FeishuAdapter — 飞书通道适配器。

消息流：飞书 WS 事件 → 内联回调 → Router.register_peer() + living.put_message()。
不依赖 ConsciousLiving 上的特定回调方法，新增频道无需改 ConsciousLiving。
"""

from __future__ import annotations

import logging
import os
import re
import time
import warnings

# 飞书 SDK (lark_oapi) 内部使用了已弃用的 pkg_resources API
warnings.filterwarnings("ignore", category=UserWarning, module="lark_oapi")

from xiaomei_brain.gateway.channel_adapter import ChannelAdapter, ChannelCapabilities
from .types import OutboundMsg
from .client import FeishuChannel

logger = logging.getLogger(__name__)


def register(ctx):
    """插件入口：注册飞书频道。"""
    app_id = ctx.config.get("appId") or ctx.config.get("app_id") or os.getenv("FEISHU_APP_ID", "")
    app_secret = ctx.config.get("appSecret") or ctx.config.get("app_secret") or os.getenv("FEISHU_APP_SECRET", "")
    if not app_id or not app_secret:
        ctx.logger.warning("飞书配置缺失，跳过注册")
        return
    ctx.register_channel("feishu", create_adapter(ctx.config))


def create_adapter(config: dict) -> "FeishuAdapter":
    """Build an adapter from a normalized Feishu account configuration."""
    app_id = config.get("appId") or config.get("app_id") or os.getenv("FEISHU_APP_ID", "")
    app_secret = config.get("appSecret") or config.get("app_secret") or os.getenv("FEISHU_APP_SECRET", "")
    if not app_id or not app_secret:
        raise ValueError("飞书 appId 和 appSecret 不能为空")
    account_id = config.get("accountId") or config.get("account_id") or "default"
    return FeishuAdapter(FeishuChannel(
        app_id=app_id,
        app_secret=app_secret,
        account_id=account_id,
    ))


class FeishuAdapter(ChannelAdapter):
    """飞书通道适配器。"""

    def __init__(self, channel: FeishuChannel) -> None:
        self._channel = channel

    @property
    def capabilities(self) -> ChannelCapabilities:
        return ChannelCapabilities(
            clarify=True,
            action_approval=True,
            attachments=True,
        )

    @property
    def channel_type(self) -> str:
        return "feishu"

    def setup(self, living=None) -> None:
        """设置回调并启动飞书通道。

        回调内联在适配器中：解析平台消息 → Router 注册 peer → put_message()。
        这样 ConsciousLiving 不需要知道飞书的存在。
        """
        if not living or not self._channel:
            return

        router = living._router
        people = getattr(living, "_people_service", None)
        link_service = getattr(living, "_identity_link_service", None)
        issuer = f"feishu:app:{self._channel.app_id}"

        def on_message(msg_dict: dict) -> None:
            sender = msg_dict["sender"]
            conversation_id = msg_dict["conversation_id"]
            text = msg_dict["text"]
            chat_type = msg_dict.get("chat_type", "p2p")
            logger.info(
                "[Feishu/Inbound] sender=%s chat_type=%s text=%r",
                sender,
                chat_type,
                text[:200],
            )

            # Feishu replies and mentions may add a prefix before the command.
            # Only accept a six-digit command on the final line so ordinary
            # conversation containing the word "绑定" cannot consume a code.
            match = re.search(
                r"(?:^|\n)\s*(?:绑定|bind)\s+(\d{6})\s*$",
                text,
                re.IGNORECASE,
            )
            if match:
                if chat_type != "p2p":
                    self.send(conversation_id, "请在与机器人的私聊中完成身份绑定。")
                    return
                try:
                    binding = (
                        link_service.consume("feishu", issuer, sender, match.group(1))
                        if link_service else None
                    )
                except ValueError as exc:
                    self.send(conversation_id, str(exc))
                    return
                if binding is None:
                    self.send(conversation_id, "绑定码无效或已过期，请在 Desktop 中重新生成。")
                    return
                self.send(conversation_id, "身份绑定成功，现在我能认出你了。")
                return

            resolved = people.resolve_verified_identity(issuer, sender) if people else None
            if resolved is None:
                self.send(
                    conversation_id,
                    "我还不能确认你是谁。请在 Desktop 的渠道配置中生成绑定码，再发送“绑定 123456”。",
                )
                return
            person, _binding = resolved
            person_id = person.person_id
            session_id = f"feishu-{person_id}"
            people.store.ensure_person_session(session_id, person_id)

            # 注册 peer（确保 Router 能匹配到）
            existing = router.route_for_session(session_id)
            if existing is None:
                router.register_peer(
                    peer_type="human", peer_id=person_id,
                    channel="feishu", session_id=session_id,
                    output_type="feishu", output_target=conversation_id,
                    priority=10,
                )

            ts = time.strftime("%H:%M:%S")
            logger.info("[Feishu] ──────────────────────────────────────────")
            logger.info("[Feishu/Step1] 收到: sender=%s conv=%s text=%s", sender, conversation_id, text[:80])
            logger.info("[Feishu/Step2] 注册 peer: feishu → session=%s output_target=%s", session_id, conversation_id)
            logger.info("[Feishu/Step3] put_message → Layer 1 队列 (session=%s)", session_id)

            gw = getattr(living, '_gateway_inbound', None)
            if gw:
                from xiaomei_brain.gateway.inbound import RawMessage
                gw.accept(RawMessage(
                    content=text, source="human", channel="feishu",
                    peer_id=person_id, peer_type="human",
                    session_id=session_id,
                    metadata={
                        "external_issuer": issuer,
                        "external_subject": sender,
                        "external_conversation_id": conversation_id,
                    },
                ))
            else:
                living.put_message(text, source="human", session_id=session_id)
            if hasattr(living, "_debug_log"):
                living._debug_log("feishu", f"{ts} ← {sender}: {text[:80]}")
            logger.info("[Feishu/Step4] 等待主循环处理 (session=%s)", session_id)

        self._channel.set_on_message(on_message)
        self._channel.start()
        logger.info("[FeishuAdapter] 通道已启动")

    def shutdown(self) -> None:
        """关闭飞书通道。"""
        if self._channel:
            try:
                self._channel.stop()
                logger.info("[FeishuAdapter] 通道已关闭")
            except Exception as e:
                logger.warning("[FeishuAdapter] 关闭通道失败: %s", e)

    def status(self) -> dict:
        return self._channel.status()

    def send(self, target: str, text: str, msg_type: str = "text") -> None:
        logger.info("[FeishuAdapter] Router.deliver → target=%s text=%s", target, text[:80])
        msg = OutboundMsg(text=text)
        self._channel.send(target, msg)
