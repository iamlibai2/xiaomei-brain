"""WSAdapter — WebSocket 通道适配器。

收/发合并在 gateway/ 下：与 server.py 协同构成 WS 完整通道。
"""

from __future__ import annotations

import asyncio
import base64
import logging
import threading
import time

from .channel_adapter import ChannelAdapter, ChannelCapabilities
from .connection import ConnectionManager
from .protocol import build_event

logger = logging.getLogger(__name__)


class WSAdapter(ChannelAdapter):
    """WebSocket 通道适配器：向已连接的 WebSocket 客户端发送消息。

    收（入站）由 gateway/server.py 的 /ws 端点处理。
    发（出站）由本适配器的 send() 处理。
    """

    _loop = None

    def __init__(self, conn_manager: ConnectionManager) -> None:
        self._conn_manager = conn_manager
        self._sequence_lock = threading.Lock()
        self._sequences: dict[str, int] = {}

    @property
    def capabilities(self) -> ChannelCapabilities:
        return ChannelCapabilities(
            streaming=True,
            structured_events=True,
            tool_events=True,
            clarify=True,
            action_approval=True,
            attachments=True,
            message_update=True,
            audio_input=True,
            audio_output=True,
        )

    @classmethod
    def set_loop(cls, loop) -> None:
        cls._loop = loop

    @property
    def channel_type(self) -> str:
        return "ws"

    @property
    def embodiment_id(self) -> str:
        return "desktop:dynamic"

    @property
    def embodiment_label(self) -> str:
        return "Desktop"

    @property
    def exposes_embodiment(self) -> bool:
        return True

    def embodiment_for_target(self, target: str):
        """Resolve the concrete Desktop body behind a session route."""
        value = self._conn_manager.get_embodiment_for_session(target)
        if not value:
            return None
        from xiaomei_brain.body.embodiment import (
            Embodiment,
            EmbodimentKind,
            OrganCapability,
        )

        supported = {
            "hearing": OrganCapability.HEARING,
            "speech": OrganCapability.SPEECH,
            "vision": OrganCapability.VISION,
        }
        capabilities = frozenset(
            supported[item]
            for item in value.get("capabilities", [])
            if item in supported
        )
        return Embodiment(
            body_id=f"desktop:{value['device_id']}",
            label=str(value.get("label") or "Desktop"),
            kind=EmbodimentKind.REMOTE,
            capabilities=capabilities,
            allow_proactive_use=bool(value.get("allow_proactive_use", False)),
            channel_type="ws",
        )

    def embodiment_statuses(self):
        from xiaomei_brain.body.embodiment import EmbodimentStatus

        statuses = []
        for value in self._conn_manager.list_embodiments():
            session_id = str(value.get("session_id", ""))
            embodiment = self.embodiment_for_target(session_id)
            if embodiment is not None:
                statuses.append(EmbodimentStatus(
                    embodiment=embodiment,
                    online=True,
                    state="online",
                ))
        return statuses

    def send_audio(self, target: str, audio) -> bool:
        """Encode one speech expression and deliver it to a Desktop speaker."""
        embodiment = self.embodiment_for_target(target)
        if embodiment is None:
            return False
        from xiaomei_brain.body.embodiment import OrganCapability
        from xiaomei_brain.media_services.audio import encode_speech_as_opus

        if not embodiment.supports(OrganCapability.SPEECH):
            return False
        encoded = encode_speech_as_opus(audio)
        self.send_event(
            target,
            "embodiment.audio.output",
            {
                "embodiment_id": embodiment.body_id,
                "mime_type": "audio/ogg",
                "duration_ms": encoded.duration_ms,
                "data_base64": base64.b64encode(encoded.data).decode("ascii"),
            },
            session_id=target,
        )
        return True

    def send(self, target: str, text: str, msg_type: str = "text") -> None:
        """推送文本到指定 WebSocket 连接。

        target: session_id
        msg_type: "text" 完整消息 → event:"message.complete"
                  "text_chunk" 流式块 → event:"message.delta"
        """
        conn_ids = self._conn_manager.get_conn_ids(target)
        if not conn_ids:
            logger.warning("[WSAdapter] 丢弃消息，无连接: session=%s msg=%.100s", target, text)
            return

        loop = self._loop
        if loop is None:
            logger.warning("[WSAdapter] 丢弃消息，事件循环未设置: session=%s msg=%.100s", target, text)
            return

        if msg_type == "text_chunk":
            event_name = "message.delta"
        elif msg_type == "internal_display":
            event_name = "internal.display"
        elif msg_type == "tool.start":
            event_name = "tool.start"
        elif msg_type == "tool.complete":
            event_name = "tool.complete"
        elif msg_type == "interaction.requested":
            event_name = "interaction.requested"
        elif msg_type == "interaction.updated":
            event_name = "interaction.updated"
        else:
            event_name = "message.complete"

        self.send_event(
            target,
            event_name,
            {"text": text, **({"status": "complete"} if event_name == "message.complete" else {})},
            session_id=target,
        )

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
        """向 WebSocket 原样发送结构化 Gateway 事件。"""
        conn_ids = self._conn_manager.get_conn_ids(target)
        if not conn_ids:
            logger.warning("[WSAdapter] 丢弃事件，无连接: session=%s event=%s", target, event)
            return

        loop = self._loop
        if loop is None:
            logger.warning("[WSAdapter] 丢弃事件，事件循环未设置: session=%s event=%s", target, event)
            return

        # The public sequence belongs to this delivered client stream.  The
        # EventHub sequence is Agent-global and naturally skips when another
        # session receives an event, so it cannot be used for gap detection.
        with self._sequence_lock:
            sequence = self._sequences.get(target, 0) + 1
            self._sequences[target] = sequence
            frame = build_event(
                event,
                payload,
                session_id=session_id or target,
                turn_id=turn_id,
                sequence=sequence,
                timestamp=timestamp or int(time.time() * 1000),
            )
            for conn_id in conn_ids:
                asyncio.run_coroutine_threadsafe(
                    self._conn_manager.send(conn_id, frame),
                    loop,
                )
