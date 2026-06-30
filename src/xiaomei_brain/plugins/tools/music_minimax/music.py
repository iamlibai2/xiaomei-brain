"""Music generation tool using MiniMax API."""

from __future__ import annotations

import logging
import os
import threading
from typing import Callable

from xiaomei_brain.tools.base import tool

logger = logging.getLogger(__name__)

# Global music provider instance (set by integration code)
_music_provider = None

# 默认输出目录（LLM 生成音乐时如果给相对路径，自动拼接到此目录）
# 可通过 set_output_base() 按 agent 隔离
_output_base: str | None = None

# 生成完成回调 → living.put_message()
# cb(filename: str, success: bool, message: str)
_on_generation_complete: Callable[[str, bool, str], None] | None = None


def set_generation_callback(cb: Callable[[str, bool, str], None]) -> None:
    """注册生成完成回调。由 CLI/Gateway 层在 living 就绪后调用。"""
    global _on_generation_complete
    _on_generation_complete = cb


def _get_output_dir() -> str:
    """获取音乐输出根目录：agent workspace 优先，否则全局 fallback。"""
    if _output_base:
        return os.path.join(_output_base, "music")
    return os.path.expanduser("~/.xiaomei-brain/global/music")


def set_output_base(base_dir: str) -> None:
    """设置 per-agent 输出根目录。由 agent_manager.init_agent() 调用。"""
    global _output_base
    _output_base = base_dir


def set_music_provider(provider) -> None:
    """Set the global music provider instance."""
    global _music_provider
    _music_provider = provider


@tool(
    name="generate_music",
    description="根据文字描述和歌词生成音乐。必须提供歌词（支持 [verse], [chorus], [bridge] 等标签）。filename 必须带扩展名（如 .mp3、.wav）。生成在后台进行，不会阻塞对话。",
)
def music_generate(
    prompt: str,
    lyrics: str,
    filename: str = "generated_music.mp3",
) -> str:
    """Generate music from text description (non-blocking, background).

    Args:
        prompt: Music description including style, mood, instruments, tempo etc.
                Examples: "独立民谣,忧郁,内省", "欢快电子乐,节拍强劲"
        lyrics: Optional lyrics in [verse], [chorus], [bridge] format.
        filename: Output audio file path. 必须带扩展名。
    """
    global _music_provider

    if _music_provider is None:
        return "音乐生成未启用或未配置。请在 config.json 中启用 music。"

    if not prompt or not prompt.strip():
        return "音乐描述不能为空。"

    # If filename is relative, save to output dir
    if not os.path.isabs(filename):
        output_dir = _get_output_dir()
        os.makedirs(output_dir, exist_ok=True)
        filename = os.path.join(output_dir, os.path.basename(filename))

    def _generate():
        try:
            _music_provider.generate_to_file(
                prompt=prompt,
                lyrics=lyrics,
                output_path=filename,
            )
            size = os.path.getsize(filename)
            logger.info("Music generated: %s (%d KB)", filename, size // 1024)
            if _on_generation_complete:
                _on_generation_complete(filename, True,
                                        f"音乐生成完成: {os.path.basename(filename)} ({size // 1024} KB)")
        except Exception as e:
            logger.error("Music generation error: %s", e)
            if _on_generation_complete:
                _on_generation_complete(filename, False, f"音乐生成失败: {e}")

    t = threading.Thread(target=_generate, daemon=True)
    t.start()

    return f"音乐正在后台生成，预计需要较长时间。完成后保存为: {filename}。生成期间可以继续正常对话。"


@tool(
    name="list_music_models",
    description="列出可用的音乐生成模型。",
)
def music_list_models() -> str:
    """List available music generation models."""
    from xiaomei_brain.speech.music import get_available_models

    models = get_available_models()
    return "可用音乐模型: " + ", ".join(models)


music_generate_tool = music_generate
music_list_models_tool = music_list_models
