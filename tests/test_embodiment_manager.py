from __future__ import annotations

from dataclasses import dataclass

import pytest

from xiaomei_brain.body.embodiment import (
    EmbodimentKind,
    EmbodimentManager,
    OrganCapability,
)
from xiaomei_brain.gateway.channel_adapter import (
    ChannelAdapter,
    ChannelCapabilities,
)
from xiaomei_brain.gateway.router import OutputRoute
from xiaomei_brain.media_services.audio import SpeechAudio


class FakeRouter:
    def __init__(self, route: OutputRoute | None = None) -> None:
        self.route = route

    def route_for_turn(self, turn_id: str, session_id: str = ""):
        return self.route


class FakeThroat:
    def __init__(self) -> None:
        self.calls = []

    def play_stream(self, chunks, **options):
        self.calls.append((list(chunks), options))


@dataclass
class FakeBody:
    throat: FakeThroat | None = None
    ears: object | None = None
    eyes: object | None = None


class SpeechChannel(ChannelAdapter):
    def __init__(self, state: str = "running") -> None:
        self.state = state
        self.sent = []

    @property
    def channel_type(self) -> str:
        return "feishu"

    @property
    def embodiment_id(self) -> str:
        return "feishu:work"

    @property
    def capabilities(self) -> ChannelCapabilities:
        return ChannelCapabilities(audio_input=True, audio_output=True)

    @property
    def exposes_embodiment(self) -> bool:
        return True

    def status(self) -> dict:
        return {"state": self.state}

    def send(self, target: str, text: str, msg_type: str = "text") -> None:
        pass

    def send_audio(self, target: str, audio) -> bool:
        self.sent.append((target, audio))
        return True


class TextOnlyChannel(SpeechChannel):
    @property
    def channel_type(self) -> str:
        return "text-only"

    @property
    def capabilities(self) -> ChannelCapabilities:
        return ChannelCapabilities()

    @property
    def exposes_embodiment(self) -> bool:
        return False


class SilentRemoteBody(TextOnlyChannel):
    @property
    def channel_type(self) -> str:
        return "dingtalk"

    @property
    def embodiment_id(self) -> str:
        return "dingtalk:work"

    @property
    def exposes_embodiment(self) -> bool:
        return True


def test_registers_local_and_remote_body_capabilities():
    manager = EmbodimentManager(FakeRouter())
    local = manager.register_local(FakeBody(
        throat=FakeThroat(),
        ears=object(),
        eyes=object(),
    ))
    remote = manager.register_channel("feishu", SpeechChannel())

    assert local.body_id == "local-host"
    assert local.kind == EmbodimentKind.LOCAL
    assert local.capabilities == {
        OrganCapability.HEARING,
        OrganCapability.SPEECH,
        OrganCapability.VISION,
    }
    assert remote is not None
    assert remote.body_id == "feishu:work"
    assert remote.kind == EmbodimentKind.REMOTE
    assert not remote.allow_proactive_use
    assert manager.register_channel("text-only", TextOnlyChannel()) is None


def test_turn_route_selects_remote_body_and_preserves_channel_target():
    router = FakeRouter(OutputRoute("feishu", "ou_person"))
    manager = EmbodimentManager(router)
    manager.register_local(FakeBody(throat=FakeThroat()))
    channel = SpeechChannel()
    manager.register_channel("feishu", channel)

    resolution = manager.resolve_for_turn(
        "turn-1",
        "session-1",
        OrganCapability.SPEECH,
    )
    assert resolution is not None
    assert resolution.embodiment.body_id == "feishu:work"
    assert resolution.target == "ou_person"

    audio = SpeechAudio([b"pcm"], "pcm_s16", 16000)
    assert manager.speak(resolution, audio)
    assert channel.sent == [("ou_person", audio)]


def test_desktop_route_uses_local_body_until_it_registers_audio():
    router = FakeRouter(OutputRoute("ws", "desktop-a"))
    throat = FakeThroat()
    manager = EmbodimentManager(router)
    manager.register_local(FakeBody(throat=throat))

    resolution = manager.resolve_for_turn(
        "turn-1",
        "desktop-session",
        OrganCapability.SPEECH,
    )
    assert resolution is not None
    assert resolution.embodiment.body_id == "local-host"
    assert manager.speak(
        resolution,
        SpeechAudio([b"pcm"], "pcm_s16", 16000),
    )
    assert throat.calls[0][0] == [b"pcm"]


def test_known_remote_body_never_falls_back_to_server_speaker():
    router = FakeRouter(OutputRoute("feishu", "ou_person"))
    manager = EmbodimentManager(router)
    manager.register_local(FakeBody(throat=FakeThroat()))
    channel = SpeechChannel(state="reconnecting")
    manager.register_channel("feishu", channel)

    resolution = manager.resolve_for_turn(
        "turn-1",
        "session-1",
        OrganCapability.SPEECH,
    )
    assert resolution is not None
    assert not manager.speak(
        resolution,
        SpeechAudio([b"pcm"], "pcm_s16", 16000),
    )
    assert channel.sent == []


def test_known_remote_body_without_speech_never_uses_local_throat():
    router = FakeRouter(OutputRoute("dingtalk", "user-1"))
    throat = FakeThroat()
    manager = EmbodimentManager(router)
    manager.register_local(FakeBody(throat=throat))
    remote = manager.register_channel("dingtalk", SilentRemoteBody())

    assert remote is not None
    assert remote.capabilities == frozenset()
    assert manager.resolve_for_turn(
        "turn-1",
        "session-1",
        OrganCapability.SPEECH,
    ) is None
    assert throat.calls == []


def test_duplicate_body_id_is_rejected():
    manager = EmbodimentManager(FakeRouter())
    manager.register_local(FakeBody(throat=FakeThroat()))
    with pytest.raises(ValueError, match="已注册"):
        manager.register_local(FakeBody(throat=FakeThroat()))
