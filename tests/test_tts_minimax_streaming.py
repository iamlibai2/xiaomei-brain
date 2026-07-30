"""Tests for MiniMax streaming TTS response handling."""

from __future__ import annotations

import json

from xiaomei_brain.plugins.tools.tts_minimax.provider import TTSProvider


class _StreamingResponse:
    def __init__(self, frames: list[dict]) -> None:
        self._frames = frames

    def raise_for_status(self) -> None:
        pass

    def iter_lines(self):
        for frame in self._frames:
            yield f"data: {json.dumps(frame)}".encode()


def _frame(audio_hex: str, status: int) -> dict:
    return {
        "data": {"audio": audio_hex, "status": status},
        "base_resp": {"status_code": 0},
    }


def test_streaming_ignores_aggregate_completion_audio(monkeypatch) -> None:
    response = _StreamingResponse([
        _frame("0102", 1),
        _frame("0304", 1),
        _frame("01020304", 2),
    ])
    monkeypatch.setattr(
        "xiaomei_brain.plugins.tools.tts_minimax.provider.requests.post",
        lambda *args, **kwargs: response,
    )
    chunks: list[bytes] = []

    TTSProvider("test-key").speak_streaming("测试", chunks.append)

    assert chunks == [b"\x01\x02", b"\x03\x04"]


def test_streaming_accepts_completion_only_audio(monkeypatch) -> None:
    response = _StreamingResponse([_frame("01020304", 2)])
    monkeypatch.setattr(
        "xiaomei_brain.plugins.tools.tts_minimax.provider.requests.post",
        lambda *args, **kwargs: response,
    )
    chunks: list[bytes] = []

    TTSProvider("test-key").speak_streaming("测试", chunks.append)

    assert chunks == [b"\x01\x02\x03\x04"]
