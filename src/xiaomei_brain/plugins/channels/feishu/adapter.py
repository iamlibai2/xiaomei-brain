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
            structured_events=True,
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

            if not text:
                logger.info("[Feishu/Inbound] ignored empty message")
                return

            is_group = chat_type != "p2p"
            resolved = (
                people.resolve_verified_identity(issuer, sender)
                if people else None
            )
            person_id = resolved[0].person_id if resolved is not None else ""

            if is_group:
                session_id = (
                    f"feishu-group-{self._channel.app_id}-{conversation_id}"
                )
                if people:
                    people.store.ensure_session(
                        session_id,
                        "conversation",
                        f"{issuer}:chat:{conversation_id}",
                        metadata={
                            "channel": "feishu",
                            "issuer": issuer,
                            "conversation_id": conversation_id,
                        },
                    )

                # Ordinary group chatter is perception, not a request. Store it
                # separately so it cannot enter fresh_tail, dreams or personal
                # memory, and never create a Turn or a reply.
                if not msg_dict.get("bot_mentioned", False):
                    gw = getattr(living, "_gateway_inbound", None)
                    if gw and hasattr(gw, "observe_group_message"):
                        from xiaomei_brain.gateway.inbound import RawMessage
                        gw.observe_group_message(RawMessage(
                            content=text,
                            source="human",
                            channel="feishu",
                            peer_id=person_id,
                            peer_type="human",
                            session_id=session_id,
                            metadata={
                                "external_issuer": issuer,
                                "external_subject": sender,
                                "external_conversation_id": conversation_id,
                                "external_message_id": msg_dict.get("message_id", ""),
                                "external_timestamp": msg_dict.get("timestamp"),
                                "sender_display_name": (
                                    resolved[0].display_name
                                    if resolved is not None
                                    else (
                                        msg_dict.get("sender_name")
                                        if msg_dict.get("sender_name") not in {"", "user"}
                                        else sender
                                    )
                                ),
                                "message_type": msg_dict.get("msg_type", "text"),
                            },
                        ))
                    logger.info(
                        "[Feishu/Inbound] stored group observation: %s",
                        conversation_id,
                    )
                    return

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

            if resolved is None:
                self.send(
                    conversation_id,
                    "我还不能确认你是谁。请在 Desktop 的渠道配置中生成绑定码，再发送“绑定 123456”。",
                )
                return
            person, _binding = resolved
            person_id = person.person_id
            if not is_group:
                session_id = f"feishu-{person_id}"
                people.store.ensure_person_session(session_id, person_id)

            # 注册 peer（确保 Router 能匹配到）
            has_route = (
                router.has_route(session_id, "feishu", conversation_id)
                if hasattr(router, "has_route") else False
            )
            if not has_route:
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
                result = gw.accept(RawMessage(
                    content=text, source="human", channel="feishu",
                    peer_id=person_id, peer_type="human",
                    session_id=session_id,
                    metadata={
                        "external_issuer": issuer,
                        "external_subject": sender,
                        "external_conversation_id": conversation_id,
                        "external_message_id": msg_dict.get("message_id", ""),
                    },
                    reply_channel="feishu",
                    reply_target=conversation_id,
                ))
                # External channels cannot inspect Gateway return values.
                # Surface exceptional admission failures instead of silence.
                reason = getattr(result, "reason", "")
                if reason and not getattr(result, "silent", False):
                    self.send(conversation_id, "这条消息暂时没有接收成功，请稍后重试。")
            else:
                living.put_message(text, source="human", session_id=session_id)
            if hasattr(living, "_debug_log"):
                living._debug_log("feishu", f"{ts} ← {sender}: {text[:80]}")
            logger.info("[Feishu/Step4] 等待主循环处理 (session=%s)", session_id)

        self._channel.set_on_message(on_message)

        def on_card_action(callback: dict) -> tuple[bool, str]:
            value = callback.get("value") or {}
            operator = str(callback.get("operator_open_id", ""))
            conversation_id = str(callback.get("conversation_id", ""))
            expected_conversation = str(value.get("conversation_id", ""))
            if not operator or (
                expected_conversation and conversation_id != expected_conversation
            ):
                return False, "这张卡片不属于当前会话。"

            resolved = people.resolve_verified_identity(issuer, operator) if people else None
            if resolved is None:
                return False, "当前飞书身份尚未绑定。"
            person, _binding = resolved
            session_id = str(value.get("session_id", ""))
            turn_id = str(value.get("turn_id", ""))
            kind = str(value.get("kind", ""))

            if kind == "interaction":
                broker = getattr(living, "_interaction_broker", None)
                response = str(value.get("response", "")).strip()
                accepted = bool(
                    broker
                    and broker.respond(
                        str(value.get("request_id", "")),
                        response,
                        session_id,
                        turn_id,
                        person.person_id,
                    )
                )
                return (
                    (True, f"已选择：{response}")
                    if accepted else (False, "问题已结束或不属于当前会话。")
                )

            if kind == "action":
                broker = getattr(living, "_action_broker", None)
                decision = str(value.get("decision", ""))
                accepted = bool(
                    broker
                    and broker.respond(
                        str(value.get("action_id", "")),
                        decision,
                        session_id,
                        turn_id,
                        person.person_id,
                    )
                )
                if not accepted:
                    return False, "审批已结束或不属于当前会话。"
                return True, "已允许此操作。" if decision == "allow" else "已拒绝此操作。"

            return False, "无法识别这张卡片的操作。"

        self._channel.set_on_card_action(on_card_action)
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

    def send_event(
        self,
        target: str,
        event: str,
        payload: dict,
        *,
        session_id: str = "",
        turn_id: str = "",
        timestamp: int = 0,
    ) -> None:
        """Render structured interaction events as native Feishu cards."""
        if event == "interaction.requested":
            choices = [
                str(item).strip()
                for item in payload.get("choices", [])
                if str(item).strip()
            ]
            if choices:
                logger.info(
                    "[Feishu/Card] sending Clarify card: target=%s "
                    "request=%s choices=%d",
                    target,
                    payload.get("id", ""),
                    len(choices[:4]),
                )
                self._channel.send_card(
                    target,
                    self._interaction_card(
                        payload,
                        choices[:4],
                        target,
                        session_id,
                        turn_id,
                    ),
                )
                return
        elif event == "action.proposed":
            self._channel.send_card(
                target,
                self._action_card(payload, target, session_id, turn_id),
            )
            return
        super().send_event(
            target,
            event,
            payload,
            session_id=session_id,
            turn_id=turn_id,
            timestamp=timestamp,
        )

    @staticmethod
    def _interaction_card(
        payload: dict,
        choices: list[str],
        conversation_id: str,
        session_id: str,
        turn_id: str,
    ) -> dict:
        question = str(payload.get("question", "")).strip()
        request_id = str(payload.get("id", ""))
        actions = []
        for index, choice in enumerate(choices):
            actions.append({
                "tag": "button",
                "text": {"tag": "plain_text", "content": choice},
                "type": "primary" if index == 0 else "default",
                "value": {
                    "kind": "interaction",
                    "request_id": request_id,
                    "response": choice,
                    "conversation_id": conversation_id,
                    "session_id": session_id,
                    "turn_id": turn_id,
                },
            })
        return {
            "config": {"wide_screen_mode": True},
            "header": {
                "template": "blue",
                "title": {"tag": "plain_text", "content": "想和你确认"},
            },
            "elements": [
                {"tag": "div", "text": {"tag": "lark_md", "content": question}},
                {"tag": "action", "actions": actions},
            ],
        }

    @staticmethod
    def _action_card(
        payload: dict,
        conversation_id: str,
        session_id: str,
        turn_id: str,
    ) -> dict:
        action_id = str(payload.get("id", ""))
        summary = str(payload.get("summary", "")).strip()
        reason = str(payload.get("reason", "")).strip()
        risk = str(payload.get("risk_level", "")).strip()
        detail = summary
        if reason:
            detail += f"\n\n**原因：** {reason}"
        if risk:
            detail += f"\n\n**风险级别：** {risk}"

        def value(decision: str) -> dict:
            return {
                "kind": "action",
                "action_id": action_id,
                "decision": decision,
                "conversation_id": conversation_id,
                "session_id": session_id,
                "turn_id": turn_id,
            }

        return {
            "config": {"wide_screen_mode": True},
            "header": {
                "template": "orange",
                "title": {"tag": "plain_text", "content": "需要你的确认"},
            },
            "elements": [
                {"tag": "div", "text": {"tag": "lark_md", "content": detail}},
                {
                    "tag": "action",
                    "actions": [
                        {
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": "允许"},
                            "type": "primary",
                            "value": value("allow"),
                        },
                        {
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": "拒绝"},
                            "type": "danger",
                            "value": value("deny"),
                        },
                    ],
                },
            ],
        }
