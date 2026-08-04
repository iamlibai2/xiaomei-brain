from __future__ import annotations

import base64
from types import SimpleNamespace

from xiaomei_brain.body.embodiment import EmbodimentManager, OrganCapability
from xiaomei_brain.gateway.connection import cm
from xiaomei_brain.gateway.inbound import Accepted
from xiaomei_brain.gateway.router import OutputRoute
from xiaomei_brain.gateway.server_methods import MethodRouter
from xiaomei_brain.gateway.ws_adapter import WSAdapter
from xiaomei_brain.media_services.audio import EncodedAudio, SpeechAudio


class ImmediateThread:
    def __init__(self, *, target, args, **_kwargs):
        self._target = target
        self._args = args

    def start(self):
        self._target(*self._args)


def test_desktop_registration_is_bound_to_authenticated_connection():
    conn_id = "desktop-embodiment-1"
    cm.set_session("session-1", conn_id, "person-1")
    methods = MethodRouter(living=SimpleNamespace())
    methods._auth_sessions.add(conn_id)
    try:
        response = methods.dispatch(conn_id, "1", "embodiment.register", {
            "device_id": "device-12345678",
            "label": "办公室电脑",
            "capabilities": ["speech", "hearing", "vision", "speech"],
        })

        assert response["result"]["embodiment_id"] == "desktop:device-12345678"
        assert response["result"]["capabilities"] == [
            "speech",
            "hearing",
            "vision",
        ]
        assert cm.get_embodiment_for_session("session-1")["person_id"] == "person-1"
    finally:
        cm.unregister(conn_id)


def test_desktop_microphone_is_transcribed_and_enters_gateway(monkeypatch):
    conn_id = "desktop-embodiment-2"
    session_id = "session-voice"
    cm.set_session(session_id, conn_id, "person-1")
    admitted = []
    events = []

    class Gateway:
        def accept(self, raw):
            admitted.append(raw)
            return Accepted(SimpleNamespace(turn_id="turn-voice", message_id=42))

    class Router:
        def deliver_event(self, event, payload, route, **metadata):
            events.append((event, payload, route, metadata))
            return True

    living = SimpleNamespace(
        _agent_id="test",
        _gateway_inbound=Gateway(),
        _router=Router(),
    )
    methods = MethodRouter(living=living)
    methods._auth_sessions.add(conn_id)
    monkeypatch.setattr(
        "xiaomei_brain.gateway.methods.embodiments.threading.Thread",
        ImmediateThread,
    )
    monkeypatch.setattr(
        "xiaomei_brain.body.perception.remote_audio."
        "RemoteAudioPerception.perceive",
        lambda _self, data: {
            "text": "帮我查看今天的安排",
            "emotion": "calm",
            "events": ["speech"],
        } if data == b"webm-audio" else {},
    )
    monkeypatch.setattr(
        "xiaomei_brain.gateway.attachments.prepare_attachments",
        lambda _agent, _session, attachments: (
            [{**attachments[0], "kind": "audio", "local_path": "stored.webm"}],
            [],
            [],
        ),
    )
    try:
        methods.dispatch(conn_id, "1", "embodiment.register", {
            "device_id": "device-voice-1",
            "label": "Desktop",
            "capabilities": ["hearing", "speech"],
        })
        data = b"webm-audio"
        response = methods.dispatch(
            conn_id,
            "2",
            "embodiment.audio.input",
            {
                "data_base64": base64.b64encode(data).decode("ascii"),
                "mime_type": "audio/webm",
                "size": len(data),
                "client_request_id": "voice-client-1",
            },
        )

        assert response["result"]["status"] == "processing"
        assert admitted[0].content == "帮我查看今天的安排"
        assert admitted[0].session_id == session_id
        assert admitted[0].peer_id == "person-1"
        assert admitted[0].attachments[0]["kind"] == "audio"
        assert admitted[0].metadata["embodiment_id"] == "desktop:device-voice-1"
        assert events[-1][0] == "embodiment.audio.input.completed"
        assert events[-1][1]["status"] == "completed"
        assert events[-1][1]["message_id"] == 42
        assert events[-1][1]["attachments"] == [{
            key: admitted[0].attachments[0][key]
            for key in ("id", "name", "mime_type", "size", "kind")
        }]
    finally:
        cm.unregister(conn_id)


def test_ws_turn_resolves_concrete_desktop_and_sends_audio(monkeypatch):
    conn_id = "desktop-embodiment-3"
    session_id = "session-speaker"
    cm.set_session(session_id, conn_id, "person-1")
    cm.register_embodiment(conn_id, {
        "device_id": "device-speaker-1",
        "label": "书房电脑",
        "capabilities": ["speech"],
        "session_id": session_id,
    })

    class Router:
        def route_for_turn(self, _turn_id, _session_id=""):
            return OutputRoute("ws", session_id)

    adapter = WSAdapter(cm)
    sent = []
    monkeypatch.setattr(
        "xiaomei_brain.media_services.audio.encode_speech_as_opus",
        lambda _audio: EncodedAudio(b"ogg-audio", 900, "opus"),
    )
    monkeypatch.setattr(
        adapter,
        "send_event",
        lambda target, event, payload, **metadata: sent.append(
            (target, event, payload, metadata),
        ),
    )
    manager = EmbodimentManager(Router())
    manager.register_channel("ws", adapter)
    try:
        resolution = manager.resolve_for_turn(
            "turn-1",
            session_id,
            OrganCapability.SPEECH,
        )
        assert resolution is not None
        assert resolution.embodiment.body_id == "desktop:device-speaker-1"
        assert [item.embodiment.body_id for item in manager.list()] == [
            "desktop:device-speaker-1",
        ]
        assert manager.speak(
            resolution,
            SpeechAudio([b"pcm"], "pcm_s16", 16000),
        )
        assert sent[0][0:2] == (session_id, "embodiment.audio.output")
        assert base64.b64decode(sent[0][2]["data_base64"]) == b"ogg-audio"
    finally:
        cm.unregister(conn_id)
