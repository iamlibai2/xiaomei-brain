"""Authenticated Desktop Embodiment registration and sensory input."""

from __future__ import annotations

import base64
import binascii
import logging
import threading
import uuid
from typing import Any

from ..connection import cm
from ..protocol import ErrorCode, build_error, build_response
from ..router import OutputRoute
from ..schemas import (
    EmbodimentAudioInputParams,
    EmbodimentRegisterParams,
    format_error,
)

logger = logging.getLogger(__name__)


class EmbodimentMethods:
    """Own connection-scoped bodies without turning them into identities."""

    def __init__(self, living: Any) -> None:
        self._living = living

    @property
    def handlers(self) -> dict[str, Any]:
        return {
            "embodiment.register": self.handle_register,
            "embodiment.unregister": self.handle_unregister,
            "embodiment.audio.input": self.handle_audio_input,
        }

    def handle_register(
        self,
        conn_id: str,
        req_id: str,
        params: dict,
    ) -> dict:
        try:
            parsed = EmbodimentRegisterParams.model_validate(params)
        except Exception as exc:
            return build_error(
                req_id,
                ErrorCode.INVALID_REQUEST,
                f"参数无效: {format_error(exc)}",
            )
        session_id = cm.get_session_id(conn_id)
        person_id = cm.get_person_id(conn_id)
        if not session_id or not person_id:
            return build_error(req_id, ErrorCode.UNAUTHORIZED, "当前连接尚未认证")
        capabilities = list(dict.fromkeys(parsed.capabilities))
        cm.register_embodiment(conn_id, {
            "device_id": parsed.device_id,
            "label": parsed.label,
            "capabilities": capabilities,
            "allow_proactive_use": parsed.allow_proactive_use,
            "session_id": session_id,
            "person_id": person_id,
        })
        logger.info(
            "[Embodiment] Desktop registered: device=%s session=%s caps=%s",
            parsed.device_id,
            session_id,
            capabilities,
        )
        return build_response(req_id, result={
            "registered": True,
            "embodiment_id": f"desktop:{parsed.device_id}",
            "session_id": session_id,
            "capabilities": capabilities,
        })

    def handle_unregister(
        self,
        conn_id: str,
        req_id: str,
        _params: dict,
    ) -> dict:
        cm.unregister_embodiment(conn_id)
        return build_response(req_id, result={"unregistered": True})

    def handle_audio_input(
        self,
        conn_id: str,
        req_id: str,
        params: dict,
    ) -> dict:
        try:
            parsed = EmbodimentAudioInputParams.model_validate(params)
        except Exception as exc:
            return build_error(
                req_id,
                ErrorCode.INVALID_REQUEST,
                f"参数无效: {format_error(exc)}",
            )
        embodiment = cm.get_embodiment_for_conn(conn_id)
        session_id = cm.get_session_id(conn_id)
        person_id = cm.get_person_id(conn_id)
        if (
            not embodiment
            or "hearing" not in embodiment.get("capabilities", [])
            or not session_id
            or not person_id
        ):
            return build_error(
                req_id,
                ErrorCode.UNAUTHORIZED,
                "当前 Desktop 没有可用的麦克风身体",
            )
        try:
            data = base64.b64decode(parsed.data_base64, validate=True)
        except (binascii.Error, ValueError):
            return build_error(req_id, ErrorCode.INVALID_PARAMS, "语音数据无效")
        if len(data) != parsed.size:
            return build_error(req_id, ErrorCode.INVALID_PARAMS, "语音大小不一致")

        request_id = f"voice_{uuid.uuid4().hex}"
        threading.Thread(
            target=self._process_audio,
            args=(
                request_id,
                session_id,
                person_id,
                str(embodiment.get("device_id", "")),
                parsed.mime_type,
                data,
            ),
            name="desktop-remote-hearing",
            daemon=True,
        ).start()
        return build_response(req_id, result={
            "accepted": True,
            "status": "processing",
            "request_id": request_id,
            "client_request_id": parsed.client_request_id,
        })

    def _process_audio(
        self,
        request_id: str,
        session_id: str,
        person_id: str,
        device_id: str,
        mime_type: str,
        data: bytes,
    ) -> None:
        route = OutputRoute("ws", session_id)
        try:
            from xiaomei_brain.body.perception.remote_audio import (
                RemoteAudioPerception,
            )
            result = RemoteAudioPerception().perceive(data)
            text = str(result.get("text", "")).strip()
            if not text:
                raise ValueError("没有辨认出语音内容")

            from ..attachments import prepare_attachments, public_attachment_metadata
            suffix = {
                "audio/webm": ".webm",
                "audio/ogg": ".ogg",
                "audio/opus": ".opus",
                "audio/mpeg": ".mp3",
                "audio/wav": ".wav",
                "audio/amr": ".amr",
            }[mime_type]
            attachment_id = f"audio_{uuid.uuid4().hex}"
            attachments, _images, _paths = prepare_attachments(
                getattr(self._living, "_agent_id", "default"),
                session_id,
                [{
                    "id": attachment_id,
                    "name": f"{attachment_id}{suffix}",
                    "mime_type": mime_type,
                    "size": len(data),
                    "data_base64": base64.b64encode(data).decode("ascii"),
                }],
            )
            gateway = getattr(self._living, "_gateway_inbound", None)
            if gateway is None:
                raise RuntimeError("Gateway 尚未初始化")
            from ..inbound import Accepted, RawMessage
            accepted = gateway.accept(RawMessage(
                content=text,
                source="human",
                channel="ws",
                peer_id=person_id,
                peer_type="human",
                session_id=session_id,
                attachments=attachments,
                metadata={
                    "message_type": "audio",
                    "embodiment_id": f"desktop:{device_id}",
                    "speech_emotion": str(result.get("emotion", "")),
                    "speech_events": list(result.get("events", []) or []),
                },
                reply_channel="ws",
                reply_target=session_id,
            ))
            if not isinstance(accepted, Accepted):
                raise RuntimeError(getattr(accepted, "reason", "语音消息未被接收"))
            self._notify(route, "embodiment.audio.input.completed", {
                "request_id": request_id,
                "status": "completed",
                "text": text,
                "turn_id": accepted.living_message.turn_id,
                "message_id": accepted.living_message.message_id,
                "attachments": public_attachment_metadata(attachments),
            })
        except Exception as exc:
            logger.exception("[Embodiment] Desktop microphone processing failed")
            self._notify(route, "embodiment.audio.input.completed", {
                "request_id": request_id,
                "status": "failed",
                "error": str(exc),
            })

    def _notify(self, route: OutputRoute, event: str, payload: dict) -> None:
        router = getattr(self._living, "_router", None)
        if router is not None:
            router.deliver_event(
                event,
                payload,
                route,
                session_id=route.target,
            )
