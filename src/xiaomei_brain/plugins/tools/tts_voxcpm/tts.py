"""TTS VoxCPM 工具 — vox_speak / vox_speak_to_file。

vox_speak: 流式生成 PCM → throat.play_stream() → 平台原生流式播放
vox_speak_to_file: 生成 WAV 文件，无时长限制。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from xiaomei_brain.tools.base import tool
from xiaomei_brain.media.audio import SpeechAudio
from xiaomei_brain.tools.execution_context import current_tool_execution
from xiaomei_brain.execution.workspace_layout import workspace_output_directory

logger = logging.getLogger(__name__)

_provider = None


def set_provider(provider) -> None:
    global _provider
    _provider = provider


def _get_throat():
    """通过 body_ref 获取 Throat 感官。"""
    from xiaomei_brain.plugins.body._refs import body_ref
    body = body_ref[0]
    if body is None:
        return None
    return body.throat


def _tts_output_path(filename: str) -> Path:
    """Choose an Agent-owned TTS output path from the sealed tool context."""
    requested = Path(str(filename or "").strip()).name or "output.wav"
    requested = str(Path(requested).with_suffix(".wav"))
    voice_ref_dir = str(getattr(_provider, "_voice_ref_dir", "") or "")
    fallback = Path(voice_ref_dir).expanduser().resolve().parent if voice_ref_dir else ""
    return workspace_output_directory("audio", fallback_agent_root=fallback) / requested


@tool(
    name="vox_speak",
    description="[VoxCPM 本地] 文本转语音并播放。适合短对话（~5s），长文本请用 vox_speak_to_file。",
)
def voxcpm_speak(text: str) -> str:
    global _provider

    if _provider is None:
        return "VoxCPM TTS 未初始化。请检查插件是否已加载。"

    if not text or not text.strip():
        return "文本为空，无需朗读。"

    try:
        sr = _provider.sample_rate
        logger.warning("[vox_speak] 流式播放开始, sr=%d", sr)
        stream = _provider.generate_streaming(text)
        context = current_tool_execution()
        if context is not None and context.speech_callback is not None:
            result = context.publish_speech(SpeechAudio(
                chunks=stream,
                codec="pcm_f32",
                sample_rate=sr,
                initial_buffer_ms=3000,
            ))
            return result or "语音已发送。"
        throat = _get_throat()
        if throat is None:
            return "语音系统未初始化。请确保 body 插件已加载。"
        # play_stream 内部用 producer 线程驱动生成器 + 预填充 + 非阻塞回调，
        # 确保 WASAPI 音频回调永不阻塞。
        throat.play_stream(stream, codec="pcm_f32", sample_rate=sr,
                           initial_buffer_ms=3000)
        return f"已朗读: {text[:50]}{'...' if len(text) > 50 else ''}"
    except Exception as e:
        logger.error("VoxCPM speak error: %s", e)
        return f"语音播放失败: {e}"


@tool(
    name="vox_speak_to_file",
    description="[VoxCPM 本地] 将文本转换为语音并保存为音频文件。无时长限制，适合长文本。",
)
def voxcpm_speak_to_file(text: str, filename: str = "output.wav") -> str:
    global _provider

    if _provider is None:
        return "VoxCPM TTS 未初始化。请检查插件是否已加载。"

    if not text or not text.strip():
        return "文本为空。"

    try:
        output_path = _tts_output_path(filename)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        _provider.generate_to_file(text, str(output_path))
        return f"音频已保存: {output_path}"
    except Exception as e:
        logger.error("VoxCPM speak_to_file error: %s", e)
        return f"语音保存失败: {e}"


voxcpm_speak_tool = voxcpm_speak
voxcpm_speak_to_file_tool = voxcpm_speak_to_file
