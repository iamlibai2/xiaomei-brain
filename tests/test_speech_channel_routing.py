from __future__ import annotations

import base64
import shutil

import pytest

from xiaomei_brain.body.perception.remote_audio import RemoteAudioPerception
from xiaomei_brain.gateway.attachments import prepare_attachments, read_stored_attachment
from xiaomei_brain.media import audio as audio_module
from xiaomei_brain.media.audio import (
    SpeechAudio,
    encode_audio_file_as_opus,
    encode_speech_as_opus,
)
from xiaomei_brain.media.audio import decode_to_pcm_s16
from xiaomei_brain.plugins.channels.feishu.client import FeishuChannel
from xiaomei_brain.tools.execution_context import (
    bind_tool_execution,
    current_tool_execution,
)


def test_encode_pcm_speech_as_opus_tracks_duration(monkeypatch):
    captured = {}

    def fake_run(arguments, data):
        captured["arguments"] = arguments
        captured["data"] = data
        return b"opus"

    monkeypatch.setattr(audio_module, "_run_ffmpeg", fake_run)
    encoded = encode_speech_as_opus(SpeechAudio(
        chunks=[b"\0" * 3200, b"\0" * 3200],
        codec="pcm_s16",
        sample_rate=16000,
    ))

    assert encoded.data == b"opus"
    assert encoded.duration_ms == 200
    assert captured["data"] == b"\0" * 6400
    assert "libopus" in captured["arguments"]


def test_encode_wav_artifact_as_opus_tracks_duration(monkeypatch):
    import io
    import wave

    output = io.BytesIO()
    with wave.open(output, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16000)
        wav_file.writeframes(b"\0\0" * 8000)
    monkeypatch.setattr(
        "xiaomei_brain.media.audio._run_ffmpeg",
        lambda arguments, data: b"opus-music",
    )

    encoded = encode_audio_file_as_opus(output.getvalue(), "music.wav")

    assert encoded.data == b"opus-music"
    assert encoded.duration_ms == 500


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg unavailable")
def test_ffmpeg_opus_round_trip():
    pcm = b"\0" * 16000  # half a second, mono s16 at 16 kHz
    encoded = encode_speech_as_opus(SpeechAudio(
        chunks=[pcm],
        codec="pcm_s16",
        sample_rate=16000,
    ))
    decoded = decode_to_pcm_s16(encoded.data)

    assert encoded.duration_ms == 500
    assert encoded.data.startswith(b"OggS")
    assert len(decoded) >= 14000


def test_tool_execution_context_publishes_speech():
    received = []
    with bind_tool_execution(
        tool_call_id="call-1",
        tool_name="speak",
        arguments={"text": "你好"},
        artifact_callback=None,
        speech_callback=lambda audio: received.append(audio) or "sent",
    ):
        context = current_tool_execution()
        assert context is not None
        audio = SpeechAudio([b"pcm"], "pcm_s16", 16000)
        assert context.publish_speech(audio) == "sent"

    assert received[0].codec == "pcm_s16"
    assert current_tool_execution() is None


def test_remote_audio_perception_uses_common_stt():
    calls = {}

    class FakeStt:
        def transcribe(self, pcm, sample_rate):
            calls["pcm"] = pcm
            calls["sample_rate"] = sample_rate
            return {"text": "你好", "emotion": "开心", "events": []}

    perception = RemoteAudioPerception(
        decoder=lambda data, sample_rate: b"decoded-" + data,
        stt=FakeStt(),
    )
    result = perception.perceive(b"opus")

    assert result["text"] == "你好"
    assert calls == {"pcm": b"decoded-opus", "sample_rate": 16000}


def test_audio_attachment_is_durable_session_asset(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    raw = b"fake-opus"
    prepared, image_paths, _saved = prepare_attachments(
        "test",
        "feishu-person",
        [{
            "id": "audio_123",
            "name": "voice.opus",
            "mime_type": "audio/opus",
            "size": len(raw),
            "data_base64": base64.b64encode(raw).decode("ascii"),
        }],
    )

    assert prepared[0]["kind"] == "audio"
    assert image_paths == []
    restored = read_stored_attachment("test", "feishu-person", prepared[0])
    assert base64.b64decode(restored["data_base64"]) == raw


def test_feishu_sends_native_audio_payload(monkeypatch):
    channel = object.__new__(FeishuChannel)
    monkeypatch.setattr(channel, "_upload_file", lambda name, data: "file-key")
    sent = {}

    def fake_send(to, msg_type, content):
        sent.update(to=to, msg_type=msg_type, content=content)
        return "message-id"

    monkeypatch.setattr(channel, "_send_payload", fake_send)
    assert channel.send_audio("ou_person", "speech.opus", b"opus", 1250)
    assert sent == {
        "to": "ou_person",
        "msg_type": "audio",
        "content": {"file_key": "file-key", "duration": 1250},
    }
