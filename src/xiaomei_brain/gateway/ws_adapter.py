"""WSAdapter — WebSocket 通道适配器。

收/发合并在 gateway/ 下：与 server.py 协同构成 WS 完整通道。
"""

from __future__ import annotations

import asyncio
import base64
import logging
import threading
import time
import uuid

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
            "commands": OrganCapability.COMMANDS,
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
        """Stream one PCM speech expression to a Desktop speaker."""
        embodiment = self.embodiment_for_target(target)
        if embodiment is None:
            return False
        from xiaomei_brain.body.embodiment import OrganCapability

        if not embodiment.supports(OrganCapability.SPEECH):
            return False
        if (
            str(getattr(audio, "media_kind", "") or "") == "music"
            and str(getattr(audio, "file_path", "") or "")
        ):
            return self._send_media_file(target, embodiment, audio)
        sample_width = {"pcm_s16": 2, "pcm_f32": 4}.get(audio.codec)
        if sample_width is None or audio.sample_rate <= 0 or audio.channels <= 0:
            raise ValueError(f"Unsupported Desktop speech format: {audio.codec}")

        speech_id = uuid.uuid4().hex
        chunk_target = max(
            sample_width * audio.channels,
            audio.sample_rate * audio.channels * sample_width // 10,
        )
        self.send_event(target, "embodiment.audio.output.started", {
            "speech_id": speech_id,
            "embodiment_id": embodiment.body_id,
            "codec": audio.codec,
            "sample_rate": audio.sample_rate,
            "channels": audio.channels,
            "initial_buffer_ms": max(0, int(audio.initial_buffer_ms)),
            "media_kind": str(getattr(audio, "media_kind", "speech") or "speech"),
            "title": str(getattr(audio, "title", "") or ""),
            "source_ref": str(getattr(audio, "source_ref", "") or ""),
        }, session_id=target)

        pending = bytearray()
        chunk_sequence = 0
        total_bytes = 0

        def publish(raw: bytes) -> None:
            nonlocal chunk_sequence, total_bytes
            chunk_sequence += 1
            total_bytes += len(raw)
            self.send_event(target, "embodiment.audio.output.chunk", {
                "speech_id": speech_id,
                "sequence": chunk_sequence,
                "data_base64": base64.b64encode(raw).decode("ascii"),
            }, session_id=target)

        try:
            for value in audio.chunks:
                if not isinstance(value, (bytes, bytearray, memoryview)) or not value:
                    continue
                pending.extend(value)
                while len(pending) >= chunk_target:
                    publish(bytes(pending[:chunk_target]))
                    del pending[:chunk_target]
            if pending:
                publish(bytes(pending))
            duration_ms = round(
                total_bytes
                / (audio.sample_rate * audio.channels * sample_width)
                * 1000,
            )
            self.send_event(target, "embodiment.audio.output.completed", {
                "speech_id": speech_id,
                "chunks": chunk_sequence,
                "total_bytes": total_bytes,
                "duration_ms": max(0, duration_ms),
            }, session_id=target)
            return total_bytes > 0
        except Exception as exc:
            self.send_event(target, "embodiment.audio.output.failed", {
                "speech_id": speech_id,
                "message": str(exc),
            }, session_id=target)
            raise

    def _send_media_file(self, target: str, embodiment, audio) -> bool:
        """Authorize an encoded file instead of expanding it into PCM frames."""
        from .media_access import MediaAccessError, media_access_registry

        person_ids = {
            self._conn_manager.get_person_id(conn_id)
            for conn_id in self._conn_manager.get_conn_ids(target)
        }
        person_ids.discard(None)
        if not person_ids:
            return False
        try:
            grant = media_access_registry.issue(
                str(audio.file_path),
                session_id=target,
                person_id=str(sorted(person_ids)[0]),
                mime_type=str(getattr(audio, "mime_type", "") or ""),
            )
        except MediaAccessError as exc:
            logger.warning("[WSAdapter] Media reference rejected: %s", exc)
            return False
        playback_id = uuid.uuid4().hex
        self.send_event(target, "embodiment.media.output.started", {
            "playback_id": playback_id,
            "embodiment_id": embodiment.body_id,
            "media_kind": "music",
            "title": str(getattr(audio, "title", "") or grant.path.stem),
            "source_ref": str(getattr(audio, "source_ref", "") or ""),
            "person_id": grant.person_id,
            "session_id": grant.session_id,
            "playlist_id": str(getattr(audio, "playlist_id", "") or ""),
            "playlist_index": max(0, int(getattr(audio, "playlist_index", 0) or 0)),
            "playlist_size": max(1, int(getattr(audio, "playlist_size", 1) or 1)),
            "autoplay": bool(getattr(audio, "autoplay", True)),
            "tool_call_id": str(getattr(audio, "tool_call_id", "") or ""),
            "mime_type": grant.mime_type,
            "size": grant.size,
            "media_path": f"/media/{grant.token}",
            "expires_at": round(grant.expires_at),
        }, session_id=target)
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
