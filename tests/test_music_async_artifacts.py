from __future__ import annotations

import threading
from pathlib import Path

from xiaomei_brain.plugins.tools.music_minimax import tool as music_tool
from xiaomei_brain.tools.execution_context import bind_tool_execution


class _FakeMusicProvider:
    def generate_to_file(self, *, prompt: str, lyrics: str, output_path: str, **_kwargs) -> None:
        Path(output_path).write_bytes(b"fake music")


def test_background_music_keeps_original_artifact_callback(
    tmp_path: Path,
    monkeypatch,
) -> None:
    published: list[tuple[str, str, dict, str]] = []
    completed = threading.Event()

    monkeypatch.setattr(music_tool, "_music_provider", _FakeMusicProvider())
    monkeypatch.setattr(music_tool, "_output_base", str(tmp_path))
    monkeypatch.setattr(
        music_tool,
        "_on_generation_complete",
        lambda *_args: completed.set(),
    )

    with bind_tool_execution(
        tool_call_id="call-1",
        tool_name="generate_music",
        arguments={"prompt": "calm", "lyrics": "[verse] hello"},
        artifact_callback=lambda *args: published.append(args),
    ):
        result = music_tool.music_generate_tool.execute(
            prompt="calm",
            lyrics="[verse] hello",
            filename="song.mp3",
        )

    assert "后台" in result
    assert str(tmp_path) not in result
    assert completed.wait(timeout=2)
    assert len(published) == 1
    tool_call_id, tool_name, arguments, artifact_result = published[0]
    assert tool_call_id == "call-1"
    assert tool_name == "generate_music"
    assert arguments["prompt"] == "calm"
    assert "- 文件:" in artifact_result
    assert str(tmp_path / "music" / "song.mp3") in artifact_result
    assert (tmp_path / "music" / "song.mp3").read_bytes() == b"fake music"
