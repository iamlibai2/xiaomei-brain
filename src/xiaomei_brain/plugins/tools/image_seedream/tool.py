"""Agent tool exposed by the Seedream image plugin."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from xiaomei_brain.tools.base import tool

from .provider import MAX_IMAGES, VALID_SIZES, SeedreamProvider

logger = logging.getLogger(__name__)

_image_provider: SeedreamProvider | None = None
_output_base: str | None = None


def _get_output_dir() -> str:
    if _output_base:
        return str(Path(_output_base) / "images")
    return str(Path.home() / ".xiaomei-brain" / "global" / "images")


def set_output_base(base_dir: str) -> None:
    global _output_base
    _output_base = base_dir


def set_image_provider(provider: SeedreamProvider) -> None:
    global _image_provider
    _image_provider = provider


@tool(
    name="generate_image_seedream",
    description=(
        "使用豆包 Seedream 模型生成图片。擅长写实风格、高清大图"
        "（2K/4K）。生成可能需要几秒到十几秒。"
    ),
)
def image_generate_seedream(
    prompt: str,
    size: str = "2k",
    n: int = 1,
) -> str:
    """使用豆包 Seedream 生成图片。"""
    if _image_provider is None:
        return (
            "豆包 Seedream 图片生成未配置。"
            "请在 Desktop 的 Agent 设置中配置图片生成服务。"
        )
    if not prompt or not prompt.strip():
        return "图片描述不能为空。"

    n = max(1, min(n, MAX_IMAGES))
    if size not in VALID_SIZES:
        size = VALID_SIZES[0]

    output_dir = _get_output_dir()
    os.makedirs(output_dir, exist_ok=True)
    try:
        paths = _image_provider.generate_to_files(
            prompt=prompt,
            output_dir=output_dir,
            size=size,
            n=n,
        )
        if not paths:
            return "图片生成失败，未返回任何图片。"
        result = f"Seedream 生成了 {len(paths)} 张图片:\n"
        for path in paths:
            result += f"  - {path}\n"
        return result.strip()
    except Exception as exc:
        logger.error("Seedream image generation error: %s", exc)
        return f"Seedream 图片生成失败: {exc}"


image_generate_seedream_tool = image_generate_seedream
