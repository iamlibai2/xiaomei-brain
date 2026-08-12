"""play_music 工具插件 — 调用 body.throat 音频输出。"""

from pathlib import Path
import mimetypes
import uuid

from xiaomei_brain.tools.base import Tool
from xiaomei_brain.plugins.body._refs import body_ref
from xiaomei_brain.media.audio import SpeechAudio, stream_audio_file_as_pcm
from xiaomei_brain.tools.execution_context import current_tool_execution


def play_music(audio_paths: list[str] | str) -> dict:
    """播放一首或按顺序播放多首音频文件。

    Args:
        audio_paths: 音频文件路径列表
    Returns:
        {"played": [...], "queue_size": 1}
    """
    requested = [audio_paths] if isinstance(audio_paths, str) else list(audio_paths or [])
    requested = list(dict.fromkeys(str(path).strip() for path in requested if str(path).strip()))
    if not requested:
        return {"error": "至少需要一个音频文件"}
    if len(requested) > 30:
        return {"error": "一次最多播放 30 首音频"}

    context = current_tool_execution()
    resolved_paths: list[tuple[str, str]] = []
    if context is not None:
        # File tools expose canonical paths such as ``music/song.mp3``. Resolve
        # that same virtual path through the common Agent workspace broker so
        # playback does not reinterpret it relative to the Python process cwd.
        from xiaomei_brain.tools.builtin.file_ops import resolve_readable_path

        for audio_path in requested:
            resolved, error = resolve_readable_path(audio_path, exists=True)
            if resolved is None:
                return {"error": error or f"音频文件不存在：{audio_path}"}
            resolved_paths.append((audio_path, str(resolved)))
    else:
        resolved_paths = [(path, path) for path in requested]

    if context is not None and context.speech_callback is not None:
        playlist_id = uuid.uuid4().hex
        result = None
        for index, (source_ref, resolved_audio_path) in enumerate(resolved_paths):
            result = context.publish_speech(SpeechAudio(
                chunks=stream_audio_file_as_pcm(resolved_audio_path),
                codec="pcm_s16",
                sample_rate=44100,
                channels=2,
                initial_buffer_ms=1000,
                media_kind="music",
                title=Path(resolved_audio_path).stem,
                source_ref=source_ref,
                file_path=resolved_audio_path,
                mime_type=mimetypes.guess_type(resolved_audio_path)[0] or "audio/mpeg",
                playlist_id=playlist_id,
                playlist_index=index,
                playlist_size=len(resolved_paths),
                autoplay=index == 0,
                tool_call_id=context.tool_call_id,
            ))
        return {
            "played": requested,
            "queue_size": len(requested),
            "through": result or "当前身体",
        }

    # CLI and route-less internal turns retain the local-body fallback.
    b = body_ref[0]
    if not b or not b.throat or not b.throat.is_available():
        return {"error": "喉咙不可用"}
    for _, resolved_audio_path in resolved_paths:
        b.throat.play(resolved_audio_path)
    return {"played": requested, "queue_size": len(requested)}


def register(ctx):
    tool = Tool(
        name="play_music",
        description=(
            "通过当前会话对应的身体播放已有音频文件。"
            "用户要求播放多首时，必须在 audio_paths 中一次传入完整列表，"
            "Desktop 才能建立播放列表并使用上一首、下一首。"
            "仅在用户明确要求播放时调用；不要在生成音乐后自动调用。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "audio_paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                    "maxItems": 30,
                    "description": (
                        "按播放顺序排列的音频文件路径。即使只播放一首也传列表。"
                        "优先原样使用 glob 返回的 workspace 相对路径，"
                        "不要推测或重建 Agent 数据目录的绝对路径。"
                    ),
                },
            },
            "required": ["audio_paths"],
        },
        func=play_music,
        source="plugin:play_music",
        optional=True,
        category="body",
    )
    ctx.register_agent_tool(tool)
