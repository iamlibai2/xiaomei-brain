"""play_music 工具插件 — 调用 body.throat 音频输出。"""

from xiaomei_brain.tools.base import Tool
from xiaomei_brain.plugins.body._refs import body_ref
from xiaomei_brain.media.audio import SpeechAudio, stream_audio_file_as_pcm
from xiaomei_brain.tools.execution_context import current_tool_execution


def play_music(audio_path: str) -> dict:
    """播放音频文件。

    Args:
        audio_path: 音频文件路径
    Returns:
        {"played": "..."}
    """
    context = current_tool_execution()
    resolved_audio_path = audio_path
    if context is not None:
        # File tools expose canonical paths such as ``music/song.mp3``. Resolve
        # that same virtual path through the common Agent workspace broker so
        # playback does not reinterpret it relative to the Python process cwd.
        from xiaomei_brain.tools.builtin.file_ops import resolve_readable_path

        resolved, error = resolve_readable_path(audio_path, exists=True)
        if resolved is None:
            return {"error": error or f"音频文件不存在：{audio_path}"}
        resolved_audio_path = str(resolved)
    if context is not None and context.speech_callback is not None:
        result = context.publish_speech(SpeechAudio(
            chunks=stream_audio_file_as_pcm(resolved_audio_path),
            codec="pcm_s16",
            sample_rate=44100,
            channels=2,
            initial_buffer_ms=1000,
        ))
        return {"played": audio_path, "through": result or "当前身体"}

    # CLI and route-less internal turns retain the local-body fallback.
    b = body_ref[0]
    if not b or not b.throat or not b.throat.is_available():
        return {"error": "喉咙不可用"}
    b.throat.play(resolved_audio_path)
    return {"played": audio_path}


def register(ctx):
    tool = Tool(
        name="play_music",
        description="通过当前会话对应的身体播放已有音频文件。仅在用户明确要求播放时调用；不要在生成音乐后自动调用。",
        parameters={
            "type": "object",
            "properties": {
                "audio_path": {
                    "type": "string",
                    "description": "音频文件路径。优先原样使用 glob 返回的 music/... 相对路径，不要推测或重建 Agent 数据目录的绝对路径。",
                },
            },
            "required": ["audio_path"],
        },
        func=play_music,
        source="plugin:play_music",
        optional=True,
        category="body",
    )
    ctx.register_agent_tool(tool)
