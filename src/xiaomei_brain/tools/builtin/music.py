"""Music generation tool using MiniMax API."""

from __future__ import annotations

import logging
import os
import tempfile

from ..base import tool

logger = logging.getLogger(__name__)

# Global music provider instance (set by integration code)
_music_provider = None


def set_music_provider(provider) -> None:
    """Set the global music provider instance."""
    global _music_provider
    _music_provider = provider


@tool(
    name="generate_music",
    description="根据文字描述和歌词生成音乐。必须提供歌词（支持 [verse], [chorus], [bridge] 等标签）。生成可能需要较长时间，请耐心等待。",
)
def music_generate(
    prompt: str,
    lyrics: str,
    filename: str = "generated_music.mp3",
) -> str:
    """Generate music from text description.

    Args:
        prompt: Music description including style, mood, instruments, tempo etc.
                Examples: "独立民谣,忧郁,内省", "欢快电子乐,节拍强劲"
        lyrics: Optional lyrics in [verse], [chorus], [bridge] format.
        filename: Output audio file path.
    """
    global _music_provider

    if _music_provider is None:
        return "音乐生成未启用或未配置。请在 config.json 中启用 music。"

    if not prompt or not prompt.strip():
        return "音乐描述不能为空。"

    try:
        # If filename is relative, save to memory dir
        if not os.path.isabs(filename):
            memory_dir = os.path.expanduser("~/.xiaomei-brain/music")
            os.makedirs(memory_dir, exist_ok=True)
            filename = os.path.join(memory_dir, os.path.basename(filename))

        _music_provider.generate_to_file(
            prompt=prompt,
            lyrics=lyrics,
            output_path=filename,
        )
        size = os.path.getsize(filename)
        return f"音乐已生成并保存: {filename} ({size // 1024}KB)"
    except Exception as e:
        logger.error("Music generation error: %s", e)
        return f"音乐生成失败: {e}"


@tool(
    name="list_music_models",
    description="列出可用的音乐生成模型。",
)
def music_list_models() -> str:
    """List available music generation models."""
    from ..speech.music import get_available_models

    models = get_available_models()
    return "可用音乐模型: " + ", ".join(models)


music_generate_tool = music_generate
music_list_models_tool = music_list_models
