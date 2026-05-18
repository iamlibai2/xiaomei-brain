"""TTS (Text-to-Speech) tool using MiniMax API."""

from __future__ import annotations

import logging
import os

from ..base import tool

logger = logging.getLogger(__name__)

# Global TTS player instance (set by integration code)
_tts_player = None
_tts_provider = None

# 默认输出目录（LLM 生成 TTS 音频时如果给相对路径，自动拼接到此目录）
# 可通过 set_output_base() 按 agent 隔离
_output_base: str | None = None


def _get_output_dir() -> str:
    """获取 TTS 输出根目录：agent workspace 优先，否则全局 fallback。"""
    if _output_base:
        return os.path.join(_output_base, "tts")
    return os.path.expanduser("~/.xiaomei-brain/global/tts")


def set_output_base(base_dir: str) -> None:
    """设置 per-agent 输出根目录。由 agent_manager.init_agent() 调用。"""
    global _output_base
    _output_base = base_dir


def set_tts_player(player, provider):
    """Set the global TTS player and provider instances."""
    global _tts_player, _tts_provider
    _tts_player = player
    _tts_provider = provider


@tool(
    name="speak",
    description="将文本转换为语音并播放。适用于用户明确要求朗读、或需要听觉反馈的场景。",
)
def tts_speak(text: str) -> str:
    """Convert text to speech and play it.

    Args:
        text: Text to speak (max 500 chars recommended for best quality).
    """
    global _tts_player, _tts_provider

    if _tts_player is None:
        return "TTS 未启用或未配置。请在 config.json 中启用 tts。"

    if not text or not text.strip():
        return "文本为空，无需朗读。"

    # Limit text length
    text = text[:500]

    try:
        _tts_player.speak_async(text)
        return f"正在朗读: {text[:50]}{'...' if len(text) > 50 else ''}"
    except Exception as e:
        logger.error("TTS speak error: %s", e)
        return f"语音播放失败: {e}"


@tool(
    name="speak_to_file",
    description="将文本转换为语音并保存为音频文件。适用于需要保存录音的场景。",
)
def tts_speak_to_file(text: str, filename: str = "output.mp3") -> str:
    """Convert text to speech and save to a file.

    Args:
        text: Text to convert (max 10000 chars).
        filename: Output audio file path.
    """
    global _tts_provider

    if _tts_provider is None:
        return "TTS 未启用或未配置。请在 config.json 中启用 tts。"

    if not text or not text.strip():
        return "文本为空。"

    try:
        # If filename is relative, save to output dir
        if not os.path.isabs(filename):
            output_dir = _get_output_dir()
            os.makedirs(output_dir, exist_ok=True)
            filename = os.path.join(output_dir, filename)

        _tts_provider.speak_to_file(text[:10000], filename)
        return f"音频已保存: {filename}"
    except Exception as e:
        logger.error("TTS file error: %s", e)
        return f"语音保存失败: {e}"


# Module-level reference to the speak tool for external use
tts_speak_tool = tts_speak
tts_speak_to_file_tool = tts_speak_to_file
