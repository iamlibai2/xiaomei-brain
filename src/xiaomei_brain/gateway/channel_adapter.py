"""ChannelAdapter: 通道适配器抽象基类。

Gateway 核心接口。每个频道（CLI/HTTP P2P/WebSocket/Feishu/...）
实现自己的适配器，负责：
- send: OutputRoute → 通道输出

纯同步接口，与 ConsciousLiving 的同步模型一致。
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from .router import InboundMsg

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChannelCapabilities:
    """Interaction features supported by one transport adapter."""

    streaming: bool = False
    structured_events: bool = False
    # Tool arguments/results are developer-facing execution details. Chat
    # channels must opt in or they could expose raw tool payloads to users.
    tool_events: bool = False
    clarify: bool = False
    action_approval: bool = False
    synchronous_action_approval: bool = False
    attachments: bool = False
    message_update: bool = False


class ChannelAdapter(ABC):
    """通道适配器抽象基类。"""

    @abstractmethod
    def send(self, target: str, text: str, msg_type: str = "text") -> None:
        """向目标发送文本。

        Args:
            target: 路由目标（"stdout" / agent_id / client_id / conversation_id）
            text: 要发送的文本
            msg_type: 消息类型（"text" / "text_chunk"），非 WS 通道忽略
        """
        ...

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
        """发送结构化事件；非实时通道退化为可展示文本。"""
        text = self._event_fallback_text(event, payload)
        if text:
            self.send(target, text)

    def _event_fallback_text(self, event: str, payload: dict) -> str:
        if event == "interaction.requested":
            if not self.capabilities.clarify:
                return ""
            question = str(payload.get("question", "")).strip()
            choices = [str(item) for item in payload.get("choices", []) if str(item).strip()]
            lines = ["想和你确认", question]
            lines.extend(f"{index}. {choice}" for index, choice in enumerate(choices, 1))
            lines.append("请直接回复你的答案。")
            return "\n".join(line for line in lines if line)
        if event == "action.proposed":
            if not self.capabilities.action_approval:
                return ""
            action_id = str(payload.get("id", ""))
            summary = str(payload.get("summary", "")).strip()
            reason = str(payload.get("reason", "")).strip()
            lines = ["需要你的确认", summary]
            if reason:
                lines.append(f"原因：{reason}")
            lines.extend([
                f"允许：/approve {action_id} allow",
                f"拒绝：/approve {action_id} deny",
            ])
            return "\n".join(line for line in lines if line)
        if event in {"interaction.updated", "action.completed", "message.start"}:
            return ""
        return str(payload.get("text") or payload.get("summary") or "")

    def request_action_decision(self, payload: dict) -> str | None:
        """Optionally collect approval synchronously for a local interactive UI."""
        return None

    @property
    def capabilities(self) -> ChannelCapabilities:
        """Conservative defaults: transports must opt into interaction powers."""
        return ChannelCapabilities()

    def receive(self) -> InboundMsg | None:
        """非阻塞接收一条消息。无消息时返回 None。

        子类可选实现。CLIAdapter 在主线程用 input() 阻塞接收，
        不走此接口。
        """
        return None

    def setup(self, living: Any = None) -> None:
        """Post-load 初始化。

        在插件加载完成后调用。适配器在这里启动通道（打开连接、启动服务器等）。
        """

    def shutdown(self) -> None:
        """关闭通道。释放连接、停止服务器。默认无操作。"""

    @property
    @abstractmethod
    def channel_type(self) -> str:
        """通道类型标识（"cli" / "http_p2p" / "ws" / "feishu" / ...）。"""
        ...
