from __future__ import annotations

from pathlib import Path
import asyncio

import httpx
import pytest

from xiaomei_brain.gateway.media_access import (
    MediaAccessError,
    MediaAccessRegistry,
    iter_media_range,
    parse_byte_range,
)
from xiaomei_brain.gateway.ws_adapter import WSAdapter
from xiaomei_brain.gateway.server import app
from xiaomei_brain.media.audio import SpeechAudio


def _agent_music(tmp_path: Path) -> Path:
    path = (
        tmp_path / ".xiaomei-brain" / "test" / "workspace"
        / "outputs" / "audio" / "track.mp3"
    )
    path.parent.mkdir(parents=True)
    path.write_bytes(b"0123456789")
    return path


def test_media_grant_is_agent_scoped_and_supports_ranges(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    path = _agent_music(tmp_path)
    registry = MediaAccessRegistry()
    registry.configure("test")

    grant = registry.issue(
        path,
        session_id="session-1",
        person_id="person-1",
        mime_type="audio/mpeg",
    )

    assert registry.resolve(grant.token).path == path.resolve()
    assert parse_byte_range("bytes=2-5", grant.size) == (2, 5)
    assert parse_byte_range("bytes=-3", grant.size) == (7, 9)
    assert b"".join(iter_media_range(path, 2, 5, chunk_size=2)) == b"2345"


def test_media_grant_rejects_files_outside_agent(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    outside = tmp_path / "outside.mp3"
    outside.write_bytes(b"audio")
    registry = MediaAccessRegistry()
    registry.configure("test")

    with pytest.raises(MediaAccessError, match="outside"):
        registry.issue(outside, session_id="session-1", person_id="person-1")


def test_gateway_media_endpoint_serves_complete_and_partial_content(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    path = _agent_music(tmp_path)
    from xiaomei_brain.gateway.media_access import media_access_registry

    media_access_registry.configure("test")
    grant = media_access_registry.issue(
        path,
        session_id="session-1",
        person_id="person-1",
        mime_type="audio/mpeg",
    )

    async def request_media():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://gateway") as client:
            complete = await client.get(f"/media/{grant.token}")
            partial = await client.get(
                f"/media/{grant.token}",
                headers={"Range": "bytes=3-6"},
            )
            return complete, partial

    complete, partial = asyncio.run(request_media())
    assert complete.status_code == 200
    assert complete.content == b"0123456789"
    assert complete.headers["accept-ranges"] == "bytes"
    assert partial.status_code == 206
    assert partial.content == b"3456"
    assert partial.headers["content-range"] == "bytes 3-6/10"


def test_ws_adapter_sends_media_reference_without_consuming_pcm(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    path = _agent_music(tmp_path)
    from xiaomei_brain.gateway.media_access import media_access_registry

    media_access_registry.configure("test")

    class Connections:
        def get_embodiment_for_session(self, session_id):
            assert session_id == "session-1"
            return {
                "device_id": "desktop-1",
                "label": "Desktop",
                "capabilities": ["speech"],
                "allow_proactive_use": False,
                "session_id": session_id,
            }

        def get_conn_ids(self, session_id):
            return ("conn-1",)

        def get_person_id(self, conn_id):
            return "person-1"

    class CapturingAdapter(WSAdapter):
        def __init__(self):
            super().__init__(Connections())
            self.events = []

        def send_event(self, target, event, payload, **metadata):
            self.events.append((target, event, payload, metadata))

    def forbidden_pcm():
        raise AssertionError("complete music file was expanded to PCM")
        yield b""

    adapter = CapturingAdapter()
    audio = SpeechAudio(
        chunks=forbidden_pcm(),
        codec="pcm_s16",
        sample_rate=44100,
        channels=2,
        media_kind="music",
        title="Track",
        source_ref="outputs/audio/track.mp3",
        file_path=str(path),
        mime_type="audio/mpeg",
        playlist_id="playlist-1",
        playlist_index=1,
        playlist_size=3,
        autoplay=False,
        tool_call_id="tool-play-1",
    )

    assert adapter.send_audio("session-1", audio) is True
    _, event, payload, _ = adapter.events[-1]
    assert event == "embodiment.media.output.started"
    assert payload["media_path"].startswith("/media/")
    assert payload["title"] == "Track"
    assert payload["person_id"] == "person-1"
    assert payload["session_id"] == "session-1"
    assert payload["playlist_id"] == "playlist-1"
    assert payload["playlist_index"] == 1
    assert payload["playlist_size"] == 3
    assert payload["autoplay"] is False
    assert payload["tool_call_id"] == "tool-play-1"
    assert "file_path" not in payload
