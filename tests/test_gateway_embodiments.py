from __future__ import annotations

import base64
from types import SimpleNamespace

from xiaomei_brain.body.embodiment import EmbodimentManager, OrganCapability
from xiaomei_brain.gateway.connection import cm
from xiaomei_brain.gateway.inbound import Accepted, Rejected
from xiaomei_brain.gateway.router import OutputRoute
from xiaomei_brain.gateway.server_methods import MethodRouter
from xiaomei_brain.gateway.ws_adapter import WSAdapter
from xiaomei_brain.media.audio import SpeechAudio


class ImmediateThread:
    def __init__(self, *, target, args, **_kwargs):
        self._target = target
        self._args = args

    def start(self):
        self._target(*self._args)


def test_gateway_advertises_desktop_audio_streaming():
    methods = MethodRouter(living=SimpleNamespace())

    assert "embodiment.audio_stream" in methods._capabilities()
    assert "embodiment.commands" in methods._capabilities()


def test_desktop_can_acknowledge_only_its_registered_command():
    conn_id = "desktop-command-response"
    cm.set_session("session-command-response", conn_id, "person-1")

    class Broker:
        received = None

        def respond(self, **kwargs):
            self.received = kwargs
            return True

    broker = Broker()
    methods = MethodRouter(living=SimpleNamespace(_embodiment_command_broker=broker))
    methods._auth_sessions.add(conn_id)
    try:
        methods.dispatch(conn_id, "1", "embodiment.register", {
            "device_id": "device-command-response",
            "label": "Desktop",
            "capabilities": ["commands"],
        })
        response = methods.dispatch(conn_id, "2", "embodiment.command.respond", {
            "command_id": "1234567890abcdef",
            "status": "completed",
            "result": {"visible": True},
        })

        assert response["result"]["accepted"] is True
        assert broker.received["session_id"] == "session-command-response"
        assert broker.received["embodiment_id"] == "desktop:device-command-response"
    finally:
        cm.unregister(conn_id)


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


def test_continuous_hearing_temporarily_owns_local_listener():
    conn_id = "desktop-embodiment-hearing-owner"
    cm.set_session("session-hearing-owner", conn_id, "person-1")

    class Listener:
        is_running = True
        stops = 0
        starts = 0

        def stop(self):
            self.is_running = False
            self.stops += 1

        def start(self):
            self.is_running = True
            self.starts += 1
            return True

    listener = Listener()
    living = SimpleNamespace(
        _voice_listener=listener,
        _ears_enabled=True,
        _identity_mgr=None,
    )
    methods = MethodRouter(living=living)
    methods._auth_sessions.add(conn_id)
    try:
        methods.dispatch(conn_id, "1", "embodiment.register", {
            "device_id": "device-hearing-owner",
            "label": "Desktop",
            "capabilities": ["hearing"],
        })
        acquired = methods.dispatch(conn_id, "2", "embodiment.hearing.acquire", {})
        assert acquired["result"]["acquired"] is True
        assert acquired["result"]["attention_timeout_seconds"] == 0
        assert acquired["result"]["wake_words"] == []
        assert acquired["result"]["voiceprint_enrolled"] is False
        assert listener.stops == 1
        assert listener.is_running is False

        methods.drop_session(conn_id)
        assert listener.starts == 1
        assert listener.is_running is True
    finally:
        cm.unregister(conn_id)


def test_same_desktop_can_nest_hearing_lease_without_stopping_live_voice():
    conn_id = "desktop-embodiment-nested-hearing"
    cm.set_session("session-nested-hearing", conn_id, "person-1")

    class Listener:
        is_running = True
        stops = 0
        starts = 0

        def stop(self):
            self.is_running = False
            self.stops += 1

        def start(self):
            self.is_running = True
            self.starts += 1
            return True

    listener = Listener()
    methods = MethodRouter(living=SimpleNamespace(
        _voice_listener=listener,
        _ears_enabled=True,
    ))
    methods._auth_sessions.add(conn_id)
    try:
        methods.dispatch(conn_id, "1", "embodiment.register", {
            "device_id": "device-nested-hearing",
            "label": "Desktop",
            "capabilities": ["hearing"],
        })
        methods.dispatch(conn_id, "2", "embodiment.hearing.acquire", {})
        methods.dispatch(conn_id, "3", "embodiment.hearing.acquire", {})
        methods.dispatch(conn_id, "4", "embodiment.hearing.release", {})

        embodiment_methods = methods._embodiment_methods
        assert embodiment_methods._hearing_owner == conn_id
        assert embodiment_methods._hearing_lease_depth == 1
        assert listener.stops == 1
        assert listener.starts == 0

        methods.dispatch(conn_id, "5", "embodiment.hearing.release", {})
        assert embodiment_methods._hearing_owner is None
        assert listener.starts == 1
    finally:
        methods.drop_session(conn_id)
        cm.unregister(conn_id)


def test_desktop_hearing_uses_person_biometrics_instead_of_legacy_identities():
    conn_id = "desktop-person-biometrics"
    cm.set_session("session-person-biometrics", conn_id, "person-1")

    class LegacyIdentityManager:
        @property
        def speaker_id(self):
            raise AssertionError("Desktop hearing accessed legacy identities.yaml biometrics")

    living = SimpleNamespace(
        _agent_id="test",
        _display_name="Test Agent",
        _identity_mgr=LegacyIdentityManager(),
        _people_biometrics=SimpleNamespace(
            speaker_id=SimpleNamespace(known_voices=["person-1"]),
        ),
    )
    methods = MethodRouter(living=living)
    methods._auth_sessions.add(conn_id)
    try:
        methods.dispatch(conn_id, "1", "embodiment.register", {
            "device_id": "device-person-biometrics",
            "label": "Desktop",
            "capabilities": ["hearing"],
        })
        acquired = methods.dispatch(conn_id, "2", "embodiment.hearing.acquire", {})

        assert acquired["result"]["voiceprint_enrolled"] is True
        assert acquired["result"]["wake_words"] == ["Test Agent", "test"]
    finally:
        methods.drop_session(conn_id)
        cm.unregister(conn_id)


def test_desktop_camera_temporarily_releases_and_restores_local_eyes():
    from xiaomei_brain.body import Body
    from xiaomei_brain.body.device.mock import MockCamera
    from xiaomei_brain.body.sense import Eyes

    conn_id = "desktop-embodiment-camera-owner"
    cm.set_session("session-camera-owner", conn_id, "person-1")

    class Monitor:
        _running = True
        stops = 0
        starts = 0

        def stop(self):
            self._running = False
            self.stops += 1

        def start(self):
            self._running = True
            self.starts += 1

    body = Body()
    eyes = Eyes()
    camera = MockCamera()
    body.register_sense(eyes, camera)
    body.open()
    monitor = Monitor()
    living = SimpleNamespace(body=body, _expression_monitor=monitor)
    methods = MethodRouter(living=living)
    methods._auth_sessions.add(conn_id)
    try:
        methods.dispatch(conn_id, "1", "embodiment.register", {
            "device_id": "device-camera-owner",
            "label": "Desktop",
            "capabilities": ["vision"],
        })
        acquired = methods.dispatch(conn_id, "2", "embodiment.vision.acquire", {})
        assert acquired["result"]["acquired"] is True
        assert camera.is_operational() is False
        assert eyes.online is False
        assert monitor.stops == 1

        released = methods.dispatch(conn_id, "3", "embodiment.vision.release", {})
        assert released["result"]["released"] is True
        assert camera.is_operational() is True
        assert eyes.online is True
        assert monitor.starts == 1
    finally:
        cm.unregister(conn_id)


def test_continuous_hearing_respects_attention_gate(monkeypatch):
    conn_id = "desktop-embodiment-attention"
    session_id = "session-attention"
    cm.set_session(session_id, conn_id, "person-1")
    events = []

    class Router:
        def deliver_event(self, event, payload, route, **metadata):
            events.append((event, payload, route, metadata))
            return True

    living = SimpleNamespace(
        _agent_id="test",
        _identity_mgr=None,
        _gateway_inbound=SimpleNamespace(
            accept=lambda _raw: (_ for _ in ()).throw(AssertionError("ignored audio entered Gateway")),
        ),
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
        "RemoteAudioPerception.perceive_with_pcm",
        lambda _self, _data: ({"text": "background speech", "emotion": ""}, b"\0\0" * 16000),
    )

    class Gate:
        current_user_id = "person-1"

        def process(self, _text, _pcm, _emotion):
            return False, None

    try:
        methods.dispatch(conn_id, "1", "embodiment.register", {
            "device_id": "device-attention-1",
            "label": "Desktop",
            "capabilities": ["hearing"],
        })
        methods.dispatch(conn_id, "2", "embodiment.hearing.acquire", {})
        methods._embodiment_methods._attention_gates[conn_id] = Gate()
        data = b"webm-audio"
        response = methods.dispatch(conn_id, "3", "embodiment.audio.input", {
            "data_base64": base64.b64encode(data).decode("ascii"),
            "mime_type": "audio/webm",
            "size": len(data),
            "client_request_id": "continuous-1",
            "continuous": True,
        })
        assert response["result"]["status"] == "processing"
        assert events[-1][0] == "embodiment.audio.input.completed"
        assert events[-1][1]["status"] == "ignored"
    finally:
        methods.drop_session(conn_id)
        cm.unregister(conn_id)


def test_desktop_hearing_ignores_short_transcript_fragments(monkeypatch):
    conn_id = "desktop-embodiment-fragment"
    session_id = "session-fragment"
    cm.set_session(session_id, conn_id, "person-1")
    events = []

    class Router:
        def deliver_event(self, event, payload, route, **metadata):
            events.append((event, payload, route, metadata))
            return True

    living = SimpleNamespace(
        _agent_id="test",
        _gateway_inbound=SimpleNamespace(
            accept=lambda _raw: (_ for _ in ()).throw(
                AssertionError("speech fragment entered Gateway"),
            ),
        ),
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
        "RemoteAudioPerception.perceive_with_pcm",
        lambda _self, _data: ({"text": "。", "emotion": ""}, b"\0\0" * 16000),
    )
    try:
        methods.dispatch(conn_id, "1", "embodiment.register", {
            "device_id": "device-fragment-1",
            "label": "Desktop",
            "capabilities": ["hearing"],
        })
        data = b"webm-audio"
        response = methods.dispatch(conn_id, "2", "embodiment.audio.input", {
            "data_base64": base64.b64encode(data).decode("ascii"),
            "mime_type": "audio/webm",
            "size": len(data),
            "client_request_id": "fragment-1",
        })
        assert response["result"]["status"] == "processing"
        assert events[-1][0] == "embodiment.audio.input.completed"
        assert events[-1][1]["status"] == "ignored"
        assert events[-1][1]["reason"] == "transcript_fragment"
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
        "RemoteAudioPerception.perceive_with_pcm",
        lambda _self, data: ({
            "text": "帮我查看今天的安排",
            "emotion": "calm",
            "events": ["speech"],
        }, b"\0\0" * 16000) if data == b"webm-audio" else ({}, b""),
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


def test_desktop_clarify_audio_is_completed_without_creating_turn(monkeypatch):
    conn_id = "desktop-embodiment-clarify"
    session_id = "session-clarify"
    cm.set_session(session_id, conn_id, "person-1")
    events = []

    class Gateway:
        def accept(self, _raw):
            return Rejected(reason="HANDLED", silent=True)

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
        "RemoteAudioPerception.perceive_with_pcm",
        lambda _self, _data: ({"text": "就演示小美 Agent", "emotion": "calm"}, b"\0\0" * 16000),
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
            "device_id": "device-clarify-1",
            "label": "Desktop",
            "capabilities": ["hearing"],
        })
        data = b"webm-audio"
        response = methods.dispatch(conn_id, "2", "embodiment.audio.input", {
            "data_base64": base64.b64encode(data).decode("ascii"),
            "mime_type": "audio/webm",
            "size": len(data),
            "client_request_id": "voice-clarify-1",
        })

        assert response["result"]["status"] == "processing"
        assert events[-1][0] == "embodiment.audio.input.completed"
        assert events[-1][1]["status"] == "completed"
        assert events[-1][1]["disposition"] == "interaction_response"
        assert "turn_id" not in events[-1][1]
        assert "message_id" not in events[-1][1]
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
            SpeechAudio(
                [b"pcm"], "pcm_s16", 16000, initial_buffer_ms=500,
                media_kind="music", title="Midnight",
                source_ref="music/midnight.mp3",
            ),
        )
        assert [item[1] for item in sent] == [
            "embodiment.audio.output.started",
            "embodiment.audio.output.chunk",
            "embodiment.audio.output.completed",
        ]
        speech_id = sent[0][2]["speech_id"]
        assert sent[0][2]["initial_buffer_ms"] == 500
        assert sent[0][2]["media_kind"] == "music"
        assert sent[0][2]["title"] == "Midnight"
        assert sent[0][2]["source_ref"] == "music/midnight.mp3"
        assert sent[1][2]["speech_id"] == speech_id
        assert sent[1][2]["sequence"] == 1
        assert base64.b64decode(sent[1][2]["data_base64"]) == b"pcm"
        assert sent[2][2]["duration_ms"] == 0
    finally:
        cm.unregister(conn_id)
