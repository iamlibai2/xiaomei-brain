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
    EmbodimentCommandResponseParams,
    EmbodimentRegisterParams,
    format_error,
)

logger = logging.getLogger(__name__)


class _HearingLeaseEnded(RuntimeError):
    """A queued audio segment finished after continuous hearing was released."""


class EmbodimentMethods:
    """Own connection-scoped bodies without turning them into identities."""

    def __init__(self, living: Any) -> None:
        self._living = living
        self._hearing_owner: str | None = None
        self._hearing_lease_depth = 0
        self._resume_local_listener = False
        self._vision_owner: str | None = None
        self._resume_local_camera = False
        self._resume_expression_monitor = False
        self._attention_gates: dict[str, Any] = {}
        self._hearing_lock = threading.RLock()
        self._vision_lock = threading.RLock()
        self._gate_lock = threading.Lock()

    @property
    def handlers(self) -> dict[str, Any]:
        return {
            "embodiment.register": self.handle_register,
            "embodiment.unregister": self.handle_unregister,
            "embodiment.hearing.acquire": self.handle_hearing_acquire,
            "embodiment.hearing.release": self.handle_hearing_release,
            "embodiment.vision.acquire": self.handle_vision_acquire,
            "embodiment.vision.release": self.handle_vision_release,
            "embodiment.audio.input": self.handle_audio_input,
            "embodiment.command.respond": self.handle_command_respond,
        }

    def handle_command_respond(self, conn_id: str, req_id: str, params: dict) -> dict:
        try:
            parsed = EmbodimentCommandResponseParams.model_validate(params)
        except Exception as exc:
            return build_error(req_id, ErrorCode.INVALID_REQUEST, f"参数无效: {format_error(exc)}")
        embodiment = cm.get_embodiment_for_conn(conn_id)
        session_id = cm.get_session_id(conn_id) or ""
        if not embodiment or "commands" not in embodiment.get("capabilities", []):
            return build_error(req_id, ErrorCode.UNAUTHORIZED, "当前 Desktop 未登记命令能力")
        broker = getattr(self._living, "_embodiment_command_broker", None)
        embodiment_id = f"desktop:{embodiment.get('device_id', '')}"
        accepted = bool(broker and broker.respond(
            command_id=parsed.command_id,
            session_id=session_id,
            embodiment_id=embodiment_id,
            status=parsed.status,
            result=parsed.result,
            error=parsed.error,
        ))
        if not accepted:
            return build_error(req_id, ErrorCode.INVALID_REQUEST, "命令不存在或不属于当前 Desktop")
        return build_response(req_id, result={"accepted": True})

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
        self.drop_connection(conn_id)
        cm.unregister_embodiment(conn_id)
        return build_response(req_id, result={"unregistered": True})

    def handle_hearing_acquire(
        self,
        conn_id: str,
        req_id: str,
        _params: dict,
    ) -> dict:
        embodiment = cm.get_embodiment_for_conn(conn_id)
        person_id = cm.get_person_id(conn_id)
        if not embodiment or "hearing" not in embodiment.get("capabilities", []) or not person_id:
            return build_error(req_id, ErrorCode.UNAUTHORIZED, "当前 Desktop 没有可用的麦克风身体")
        with self._hearing_lock:
            if self._hearing_owner not in {None, conn_id}:
                return build_error(req_id, ErrorCode.INVALID_REQUEST, "另一具身体正在持续监听")
            if self._hearing_owner == conn_id:
                self._hearing_lease_depth += 1
                gate = self._attention_gates.get(conn_id)
                logger.debug(
                    "[Embodiment] Continuous hearing lease nested: depth=%d",
                    self._hearing_lease_depth,
                )
                return build_response(req_id, result={
                    "acquired": True,
                    "embodiment_id": f"desktop:{embodiment.get('device_id', '')}",
                    "attention_timeout_seconds": getattr(gate, "timeout_seconds", 0),
                    "wake_words": getattr(gate, "wake_words", []),
                    "voiceprint_enrolled": bool(getattr(gate, "voiceprint_enrolled", False)),
                })
            self._hearing_owner = conn_id
            self._hearing_lease_depth = 1
            listener = getattr(self._living, "_voice_listener", None)
            if listener is not None and getattr(listener, "is_running", False):
                listener.stop()
                self._resume_local_listener = True
            gate = self._new_attention_gate(person_id)
            self._attention_gates[conn_id] = gate
        logger.info("[Embodiment] Continuous hearing acquired: %s", embodiment.get("device_id"))
        return build_response(req_id, result={
            "acquired": True,
            "embodiment_id": f"desktop:{embodiment.get('device_id', '')}",
            "attention_timeout_seconds": getattr(gate, "timeout_seconds", 0),
            "wake_words": getattr(gate, "wake_words", []),
            "voiceprint_enrolled": bool(getattr(gate, "voiceprint_enrolled", False)),
        })

    def handle_hearing_release(
        self,
        conn_id: str,
        req_id: str,
        _params: dict,
    ) -> dict:
        released = self._release_hearing(conn_id)
        return build_response(req_id, result={"released": released})

    def handle_vision_acquire(
        self,
        conn_id: str,
        req_id: str,
        _params: dict,
    ) -> dict:
        embodiment = cm.get_embodiment_for_conn(conn_id)
        if not embodiment or "vision" not in embodiment.get("capabilities", []):
            return build_error(
                req_id,
                ErrorCode.UNAUTHORIZED,
                "当前 Desktop 没有可用的摄像头身体",
            )
        with self._vision_lock:
            if self._vision_owner not in {None, conn_id}:
                return build_error(
                    req_id,
                    ErrorCode.INVALID_REQUEST,
                    "另一具身体正在使用摄像头",
                )
            if self._vision_owner == conn_id:
                return build_response(req_id, result={
                    "acquired": True,
                    "local_camera_released": self._resume_local_camera,
                })
            self._vision_owner = conn_id
            eyes = getattr(getattr(self._living, "body", None), "eyes", None)
            device = getattr(eyes, "device", None)
            monitor = getattr(self._living, "_expression_monitor", None)
            self._resume_local_camera = bool(
                eyes is not None
                and getattr(eyes, "enabled", False)
                and device is not None
                and device.is_operational()
            )
            self._resume_expression_monitor = bool(
                self._resume_local_camera
                and monitor is not None
                and getattr(monitor, "_running", False)
            )
            if self._resume_expression_monitor:
                monitor.stop()
            if self._resume_local_camera:
                device.close()
                eyes.online = False
        logger.info(
            "[Embodiment] Camera leased to Desktop: %s released_local=%s",
            embodiment.get("device_id"),
            self._resume_local_camera,
        )
        return build_response(req_id, result={
            "acquired": True,
            "local_camera_released": self._resume_local_camera,
        })

    def handle_vision_release(
        self,
        conn_id: str,
        req_id: str,
        _params: dict,
    ) -> dict:
        released = self._release_vision(conn_id)
        return build_response(req_id, result={"released": released})

    def drop_connection(self, conn_id: str) -> None:
        """Release connection-scoped senses after an unclean socket close."""
        self._release_hearing(conn_id, force=True)
        self._release_vision(conn_id)

    def _release_hearing(self, conn_id: str, *, force: bool = False) -> bool:
        with self._hearing_lock:
            if self._hearing_owner != conn_id:
                return False
            if not force and self._hearing_lease_depth > 1:
                self._hearing_lease_depth -= 1
                logger.debug(
                    "[Embodiment] Continuous hearing lease released: depth=%d",
                    self._hearing_lease_depth,
                )
                return True
            self._attention_gates.pop(conn_id, None)
            self._hearing_owner = None
            self._hearing_lease_depth = 0
            should_resume = self._resume_local_listener
            self._resume_local_listener = False
        if should_resume:
            listener = getattr(self._living, "_voice_listener", None)
            if listener is not None and getattr(self._living, "_ears_enabled", True):
                try:
                    listener.start()
                except Exception:
                    logger.exception("[Embodiment] Failed to restore local VoiceListener")
        logger.info("[Embodiment] Continuous hearing released")
        return True

    def _release_vision(self, conn_id: str) -> bool:
        with self._vision_lock:
            if self._vision_owner != conn_id:
                return False
            self._vision_owner = None
            should_resume_camera = self._resume_local_camera
            should_resume_monitor = self._resume_expression_monitor
            self._resume_local_camera = False
            self._resume_expression_monitor = False

        eyes = getattr(getattr(self._living, "body", None), "eyes", None)
        device = getattr(eyes, "device", None)
        reopened = False
        if (
            should_resume_camera
            and eyes is not None
            and getattr(eyes, "enabled", False)
            and device is not None
        ):
            try:
                reopened = bool(device.open())
                eyes.online = reopened
            except Exception:
                logger.exception("[Embodiment] Failed to restore local camera")
        if reopened and should_resume_monitor:
            monitor = getattr(self._living, "_expression_monitor", None)
            if monitor is not None:
                try:
                    monitor.start()
                except Exception:
                    logger.exception("[Embodiment] Failed to restore ExpressionMonitor")
        logger.info("[Embodiment] Desktop camera lease released: restored=%s", reopened)
        return True

    def _new_attention_gate(self, person_id: str) -> Any | None:
        biometrics = getattr(self._living, "_people_biometrics", None)
        if biometrics is None:
            return None
        try:
            from xiaomei_brain.body.perception.attention_gate import AttentionGate
            wake_words = [
                str(getattr(self._living, "_display_name", "") or ""),
                str(getattr(self._living, "_agent_id", "") or ""),
            ]
            gate = AttentionGate(
                getattr(biometrics, "speaker_id", None),
                None,
                wake_words=[word for word in wake_words if word],
                allow_user_switch=False,
            )
            # Enabling continuous hearing is an explicit start of a dialog.
            gate.set_current_user(person_id)
            return gate
        except Exception:
            logger.exception("[Embodiment] Failed to initialize Desktop attention gate")
            return None

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
                parsed.continuous,
                conn_id,
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
        continuous: bool,
        conn_id: str,
    ) -> None:
        route = OutputRoute("ws", session_id)
        try:
            from xiaomei_brain.body.perception.remote_audio import (
                RemoteAudioPerception,
            )
            result, pcm = RemoteAudioPerception().perceive_with_pcm(data)
            text = str(result.get("text", "")).strip()
            if not text:
                raise ValueError("没有辨认出语音内容")
            from xiaomei_brain.body.perception.transcript_filter import (
                is_meaningful_transcript,
            )
            if not is_meaningful_transcript(text):
                logger.debug("[Embodiment] 丢弃远程语音碎片: %r", text)
                self._notify(route, "embodiment.audio.input.completed", {
                    "request_id": request_id,
                    "status": "ignored",
                    "text": text,
                    "reason": "transcript_fragment",
                })
                return

            if continuous:
                with self._hearing_lock:
                    owns_hearing = self._hearing_owner == conn_id
                    gate = self._attention_gates.get(conn_id)
                if not owns_hearing:
                    raise _HearingLeaseEnded("Desktop 已失去持续监听权")
                if gate is not None:
                    with self._gate_lock:
                        should_pass, _target_person = gate.process(
                            text,
                            pcm,
                            str(result.get("emotion", "")),
                        )
                        same_person = gate.current_user_id == person_id
                    if not should_pass or not same_person:
                        decision_reason = str(
                            getattr(gate, "last_decision_reason", "attention_gate")
                        )
                        self._notify(route, "embodiment.audio.input.completed", {
                            "request_id": request_id,
                            "status": "ignored",
                            "text": text,
                            "reason": decision_reason,
                            "attention_state": (
                                "waiting_wake"
                                if decision_reason in {
                                    "wake_required",
                                    "voiceprint_unverified",
                                    "voiceprint_mismatch",
                                }
                                else "active"
                            ),
                        })
                        return

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
                    "continuous": continuous,
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
        except _HearingLeaseEnded as exc:
            logger.info("[Embodiment] Discarded queued audio after hearing release")
            self._notify(route, "embodiment.audio.input.completed", {
                "request_id": request_id,
                "status": "ignored",
                "reason": "hearing_released",
                "error": str(exc),
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
