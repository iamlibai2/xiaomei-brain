from __future__ import annotations

import wave
import threading
from pathlib import Path
from types import SimpleNamespace

from xiaomei_brain.plugins.tools.music_minimax import provider as provider_module
from xiaomei_brain.plugins.tools.music_minimax import tool as music_tool
from xiaomei_brain.tools.execution_context import bind_tool_execution


class _StreamingResponse:
    def __init__(self) -> None:
        self.closed = False

    def raise_for_status(self) -> None:
        return None

    def iter_lines(self, decode_unicode: bool = False):
        assert decode_unicode is True
        yield 'data: {"data":{"audio":"01000200","status":1},"base_resp":{"status_code":0}}'
        yield 'data: {"data":{"audio":"03000400","status":1},"base_resp":{"status_code":0}}'
        yield 'data: {"data":{"audio":"0100020003000400","status":2},"base_resp":{"status_code":0}}'
        yield "data: [DONE]"

    def close(self) -> None:
        self.closed = True


def test_music_provider_consumes_real_streaming_response(monkeypatch) -> None:
    response = _StreamingResponse()
    request: dict = {}

    def fake_post(url, **kwargs):
        request.update(url=url, **kwargs)
        return response

    monkeypatch.setattr(provider_module.requests, "post", fake_post)
    provider = provider_module.MusicProvider("secret")

    chunks = list(provider.generate_streaming("warm pop", "[verse] hello", audio_format="pcm"))

    assert chunks == [b"\x01\x00\x02\x00", b"\x03\x00\x04\x00"]
    assert request["stream"] is True
    assert request["json"]["stream"] is True
    assert request["json"]["output_format"] == "hex"
    assert request["json"]["audio_setting"]["format"] == "pcm"
    assert response.closed is True


def test_music_provider_accepts_status_2_only_response(monkeypatch) -> None:
    class FinalOnlyResponse(_StreamingResponse):
        def iter_lines(self, decode_unicode: bool = False):
            yield 'data: {"data":{"audio":"01000200","status":2},"base_resp":{"status_code":0}}'

    response = FinalOnlyResponse()
    monkeypatch.setattr(provider_module.requests, "post", lambda *_args, **_kwargs: response)
    provider = provider_module.MusicProvider("secret")

    assert list(provider.generate_streaming("warm pop", "[verse] hello")) == [
        b"\x01\x00\x02\x00",
    ]


def test_music_provider_keeps_new_tail_from_final_snapshot(monkeypatch) -> None:
    class FinalTailResponse(_StreamingResponse):
        def iter_lines(self, decode_unicode: bool = False):
            yield 'data: {"data":{"audio":"01000200","status":1},"base_resp":{"status_code":0}}'
            yield 'data: {"data":{"audio":"0100020003000400","status":2},"base_resp":{"status_code":0}}'

    response = FinalTailResponse()
    monkeypatch.setattr(provider_module.requests, "post", lambda *_args, **_kwargs: response)
    provider = provider_module.MusicProvider("secret")

    assert list(provider.generate_streaming("warm pop", "[verse] hello")) == [
        b"\x01\x00\x02\x00",
        b"\x03\x00\x04\x00",
    ]


def test_music_provider_builds_documented_instrumental_payload() -> None:
    provider = provider_module.MusicProvider("secret", model="music-3.0")

    payload = provider._build_payload(
        "cinematic industrial score",
        None,
        "music-3.0",
        stream=False,
        is_instrumental=True,
    )

    assert payload["model"] == "music-3.0"
    assert payload["is_instrumental"] is True
    assert "lyrics" not in payload


def test_music_provider_builds_documented_lyrics_optimizer_payload() -> None:
    provider = provider_module.MusicProvider("secret", model="music-3.0")

    payload = provider._build_payload(
        "warm company theme song",
        None,
        "music-3.0",
        stream=False,
        lyrics_optimizer=True,
    )

    assert payload["lyrics_optimizer"] is True
    assert "lyrics" not in payload


def test_music_model_catalog_prefers_3_0_and_keeps_2_6() -> None:
    assert provider_module.get_available_models() == [
        "music-3.0",
        "music-2.6",
        "music-3.0-free",
        "music-2.6-free",
    ]


def test_sing_buffers_complete_song_when_generation_is_slower_than_playback() -> None:
    now = [0.0]
    chunks = [b"a" * 4_000, b"b" * 4_000, b"c" * 4_000]

    def slow_source():
        yield chunks[0]
        now[0] = 10.0
        yield chunks[1]
        now[0] = 20.0
        yield chunks[2]

    stream, mode, buffered_seconds = music_tool._prepare_continuous_pcm_stream(
        slow_source(),
        sample_rate=1_000,
        channels=1,
        clock=lambda: now[0],
    )

    assert mode == "buffered"
    assert buffered_seconds == 6.0
    assert list(stream) == chunks


def test_sing_starts_streaming_when_generation_stays_ahead_of_playback() -> None:
    now = [0.0]
    chunks = [b"a" * 6_000, b"b" * 6_000, b"c" * 2_000]

    def fast_source():
        yield chunks[0]
        now[0] = 0.5
        yield chunks[1]
        now[0] = 1.0
        yield chunks[2]

    stream, mode, buffered_seconds = music_tool._prepare_continuous_pcm_stream(
        fast_source(),
        sample_rate=1_000,
        channels=1,
        clock=lambda: now[0],
    )

    assert mode == "streaming"
    assert buffered_seconds == 6.0
    assert list(stream) == chunks


class _FakeSingingProvider:
    audio_config = SimpleNamespace(sample_rate=44100)

    def generate_streaming(self, **kwargs):
        assert kwargs["audio_format"] == "pcm"
        yield b"\x01\x00\x02\x00" * 100
        yield b"\x03\x00\x04\x00" * 100


def test_sing_streams_through_embodiment_and_saves_wav(tmp_path: Path, monkeypatch) -> None:
    received = bytearray()
    completed = threading.Event()
    published: list[str] = []

    def play(audio):
        assert audio.codec == "pcm_s16"
        assert audio.sample_rate == 44100
        assert audio.channels == 2
        for chunk in audio.chunks:
            received.extend(chunk)
        return "已通过 Desktop 表达语音。"

    monkeypatch.setattr(music_tool, "_music_provider", _FakeSingingProvider())
    monkeypatch.setattr(music_tool, "_output_base", str(tmp_path))
    with bind_tool_execution(
        tool_call_id="sing-1",
        tool_name="sing",
        arguments={"prompt": "warm pop", "lyrics": "[verse] hello"},
        artifact_callback=lambda _id, _name, _args, result: (
            published.append(result), completed.set()
        ),
        speech_callback=play,
    ):
        result = music_tool.music_sing_tool.execute(
            prompt="warm pop",
            lyrics="[verse] hello",
            filename="demo.mp3",
        )

    assert "正在准备演唱" in result
    assert completed.wait(timeout=2)
    output = tmp_path / "workspace" / "outputs" / "audio" / "demo.wav"
    assert output.is_file()
    with wave.open(str(output), "rb") as wav_file:
        assert wav_file.getnchannels() == 2
        assert wav_file.getframerate() == 44100
        assert wav_file.readframes(wav_file.getnframes()) == bytes(received)
    assert str(output) in published[0]
    assert "Desktop" in published[0]


def test_play_music_prefers_current_embodiment(monkeypatch, tmp_path) -> None:
    from xiaomei_brain.plugins.tools.play_music import adapter

    played = bytearray()
    published_audio = []
    workspace = tmp_path / "workspace"
    music = tmp_path / "music"
    workspace.mkdir()
    music.mkdir()
    audio_file = music / "song.mp3"
    audio_file.write_bytes(b"test")
    resolved_paths = []

    def stream(path):
        resolved_paths.append(path)
        return iter((b"\x00\x00\x00\x00",))

    monkeypatch.setattr(
        adapter,
        "stream_audio_file_as_pcm",
        stream,
    )

    def play(audio):
        published_audio.append(audio)
        for chunk in audio.chunks:
            played.extend(chunk)
        return "Desktop"

    with bind_tool_execution(
        tool_call_id="play-1",
        tool_name="play_music",
        arguments={"audio_paths": ["music/song.mp3"]},
        artifact_callback=None,
        speech_callback=play,
        workspace_root=str(workspace),
        working_directory=str(workspace),
        writable_roots=(str(music),),
    ):
        result = adapter.play_music(["music/song.mp3"])

    assert played == b"\x00\x00\x00\x00"
    assert resolved_paths == [str(audio_file.resolve())]
    assert published_audio[0].media_kind == "music"
    assert published_audio[0].title == "song"
    assert published_audio[0].source_ref == "music/song.mp3"
    assert published_audio[0].file_path == str(audio_file.resolve())
    assert published_audio[0].mime_type == "audio/mpeg"
    assert published_audio[0].playlist_id
    assert published_audio[0].playlist_index == 0
    assert published_audio[0].playlist_size == 1
    assert published_audio[0].autoplay is True
    assert published_audio[0].tool_call_id == "play-1"
    assert result == {
        "played": ["music/song.mp3"],
        "queue_size": 1,
        "through": "Desktop",
    }


def test_play_music_publishes_one_ordered_playlist(monkeypatch, tmp_path) -> None:
    from xiaomei_brain.plugins.tools.play_music import adapter

    workspace = tmp_path / "workspace"
    music = workspace / "outputs" / "audio"
    music.mkdir(parents=True)
    for name in ("one.mp3", "two.mp3", "three.mp3"):
        (music / name).write_bytes(b"audio")

    published_audio = []

    def publish(audio):
        published_audio.append(audio)
        return "Desktop"

    paths = [f"outputs/audio/{name}" for name in ("one.mp3", "two.mp3", "three.mp3")]
    with bind_tool_execution(
        tool_call_id="playlist-1",
        tool_name="play_music",
        arguments={"audio_paths": paths},
        artifact_callback=None,
        speech_callback=publish,
        workspace_root=str(workspace),
        working_directory=str(workspace),
        writable_roots=(str(workspace),),
    ):
        result = adapter.play_music(paths)

    assert result == {"played": paths, "queue_size": 3, "through": "Desktop"}
    assert len(published_audio) == 3
    assert len({audio.playlist_id for audio in published_audio}) == 1
    assert [audio.playlist_index for audio in published_audio] == [0, 1, 2]
    assert [audio.playlist_size for audio in published_audio] == [3, 3, 3]
    assert [audio.autoplay for audio in published_audio] == [True, False, False]
    assert [audio.tool_call_id for audio in published_audio] == ["playlist-1"] * 3


def test_play_music_keeps_local_body_fallback_without_turn_context(tmp_path) -> None:
    from xiaomei_brain.plugins.body._refs import body_ref
    from xiaomei_brain.plugins.tools.play_music import adapter

    audio_file = tmp_path / "local.mp3"
    audio_file.write_bytes(b"audio")
    played = []

    class Throat:
        def is_available(self):
            return True

        def play(self, path):
            played.append(path)

    previous = body_ref[0]
    body_ref[0] = SimpleNamespace(throat=Throat())
    try:
        result = adapter.play_music([str(audio_file)])
    finally:
        body_ref[0] = previous

    assert result == {"played": [str(audio_file)], "queue_size": 1}
    assert played == [str(audio_file)]


def test_voxcpm_file_output_stays_in_current_agent_tts_root(monkeypatch, tmp_path) -> None:
    from xiaomei_brain.plugins.tools.tts_voxcpm import tts

    generated = []

    class Provider:
        def generate_to_file(self, text, path):
            generated.append((text, path))
            Path(path).write_bytes(b"wav")

    workspace = tmp_path / "workspace"
    output_root = workspace / "outputs"
    tts_root = output_root / "audio"
    workspace.mkdir()
    tts_root.mkdir(parents=True)
    monkeypatch.setattr(tts, "_provider", Provider())

    with bind_tool_execution(
        tool_call_id="tts-1",
        tool_name="vox_speak_to_file",
        arguments={},
        artifact_callback=None,
        workspace_root=str(workspace),
        working_directory=str(workspace),
        output_root=str(output_root),
    ):
        result = tts.voxcpm_speak_to_file_tool.execute(
            text="hello",
            filename=str(tmp_path / "outside" / "voice.mp3"),
        )

    expected = tts_root / "voice.wav"
    assert expected.is_file()
    assert generated == [("hello", str(expected))]
    assert str(expected) in result
    assert not (tmp_path / "outside" / "voice.mp3").exists()
