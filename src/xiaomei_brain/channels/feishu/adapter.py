"""FeishuAdapter — 飞书通道适配器。

消息流：飞书 WS 事件 → 内联回调 → Router.register_peer() + living.put_message()。
不依赖 ConsciousLiving 上的特定回调方法，新增频道无需改 ConsciousLiving。
"""

from __future__ import annotations

import logging
import os
import time
import warnings

# 飞书 SDK (lark_oapi) 内部使用了已弃用的 pkg_resources API
warnings.filterwarnings("ignore", category=UserWarning, module="lark_oapi")

from ...gateway.channel_adapter import ChannelAdapter
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
    channel = FeishuChannel(app_id=app_id, app_secret=app_secret)
    ctx.register_channel("feishu", FeishuAdapter(channel))


class FeishuAdapter(ChannelAdapter):
    """飞书通道适配器。"""

    def __init__(self, channel: FeishuChannel) -> None:
        self._channel = channel

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

        def on_message(msg_dict: dict) -> None:
            sender = msg_dict["sender"]
            conversation_id = msg_dict["conversation_id"]
            text = msg_dict["text"]
            session_id = f"feishu-{sender}"

            # 注册 peer（确保 Router 能匹配到）
            existing = router.route_for_session(session_id)
            if existing is None:
                router.register_peer(
                    peer_type="human", peer_id=sender,
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
                    peer_id=sender, peer_type="human",
                    session_id=session_id,
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

    def send(self, target: str, text: str, msg_type: str = "text") -> None:
        logger.info("[FeishuAdapter] Router.deliver → target=%s text=%s", target, text[:80])
        msg = OutboundMsg(text=text)
        self._channel.send(target, msg)
