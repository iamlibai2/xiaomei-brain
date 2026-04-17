"""Image generation tool using MiniMax API."""

from __future__ import annotations

import logging
import os

from ..base import tool

logger = logging.getLogger(__name__)

# Global image provider instance (set by integration code)
_image_provider = None


def set_image_provider(provider) -> None:
    """Set the global image provider instance."""
    global _image_provider
    _image_provider = provider


@tool(
    name="generate_image",
    description="根据文字描述生成图片。模型可选 image-01（写实）或 image-01-live（插画风，支持漫画/元气/中世纪/水彩风格）。宽高比: 1:1, 16:9, 4:3, 3:2, 2:3, 3:4, 9:16, 21:9。生成可能需要几秒到十几秒。",
)
def image_generate(
    prompt: str,
    model: str = "image-01",
    aspect_ratio: str = "1:1",
    n: int = 1,
    prompt_optimizer: bool = False,
    style: str | None = None,
    style_weight: float | None = None,
) -> str:
    """Generate images from text description.

    Args:
        prompt: Image description in Chinese or English (max 1500 chars).
        model: Model - "image-01" (photorealistic) or "image-01-live" (illustration).
        aspect_ratio: Aspect ratio: 1:1, 16:9, 4:3, 3:2, 2:3, 3:4, 9:16, 21:9.
        n: Number of images (1-9).
        prompt_optimizer: Whether to optimize prompt.
        style: Style for image-01-live only: 漫画, 元气, 中世纪, 水彩.
        style_weight: Style weight (0, 1] for image-01-live.
    """
    global _image_provider

    if _image_provider is None:
        return "图片生成未启用或未配置。请在 config.json 中启用 image。"

    if not prompt or not prompt.strip():
        return "图片描述不能为空。"

    if n > 9:
        n = 9
    if n < 1:
        n = 1

    output_dir = os.path.expanduser("~/.xiaomei-brain/images")
    os.makedirs(output_dir, exist_ok=True)

    try:
        paths = _image_provider.generate_to_files(
            prompt=prompt,
            output_dir=output_dir,
            model=model,
            n=n,
            aspect_ratio=aspect_ratio,
            prompt_optimizer=prompt_optimizer,
            style=style,
            style_weight=style_weight,
        )

        if not paths:
            return "图片生成失败，未返回任何图片。"

        result = f"生成了 {len(paths)} 张图片:\n"
        for p in paths:
            result += f"  - {p}\n"
        return result.strip()

    except Exception as e:
        logger.error("Image generation error: %s", e)
        return f"图片生成失败: {e}"


@tool(
    name="list_image_options",
    description="列出可用的图片模型、宽高比、风格选项。",
)
def image_list_options() -> str:
    """List available image options."""
    from ...image import get_available_models, get_available_aspect_ratios, get_available_styles

    models = get_available_models()
    ratios = get_available_aspect_ratios()
    styles = get_available_styles()
    return (
        f"可用模型: {', '.join(models)}\n"
        f"可用宽高比: {', '.join(ratios)}\n"
        f"可用风格(image-01-live): {', '.join(styles)}"
    )


image_generate_tool = image_generate
image_list_options_tool = image_list_options
