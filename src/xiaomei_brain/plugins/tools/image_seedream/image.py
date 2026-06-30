"""豆包 Seedream 图片生成（火山引擎方舟平台）。
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from typing import Any

import requests

logger = logging.getLogger(__name__)

# Global image provider instance (set by adapter)
_image_provider = None

# 输出目录
_output_base: str | None = None

DEFAULT_MODEL = "doubao-seedream-5-0-260128"
DEFAULT_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
VALID_SIZES = ["2k", "4k"]
MAX_IMAGES = 4


def _get_output_dir() -> str:
    if _output_base:
        return os.path.join(_output_base, "images")
    return os.path.expanduser("~/.xiaomei-brain/global/images")


def set_output_base(base_dir: str) -> None:
    global _output_base
    _output_base = base_dir


def set_image_provider(provider) -> None:
    global _image_provider
    _image_provider = provider


class SeedreamProvider:
    """豆包 Seedream 图片生成 provider。

    直接通过 HTTP POST 调用火山引擎方舟 API（OpenAI 兼容接口）。
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        model: str = DEFAULT_MODEL,
        watermark: bool = False,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.watermark = watermark

    def generate(
        self,
        prompt: str,
        size: str = "2k",
        n: int = 1,
        response_format: str = "url",
    ) -> list[dict]:
        """生成图片。

        Args:
            prompt: 图片描述。
            size: "2k" 或 "4k"。
            n: 生成数量 1-4。
            response_format: "url" 或 "b64_json"。

        Returns:
            [{"url": "...", "b64_json": "..."}, ...]
        """
        if size not in VALID_SIZES:
            size = VALID_SIZES[0]
        n = max(1, min(n, MAX_IMAGES))

        url = f"{self.base_url}/images/generations"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "model": self.model,
            "prompt": prompt,
            "size": size,
            "n": n,
            "response_format": response_format,
            "watermark": self.watermark,
        }

        r = requests.post(url, json=body, headers=headers, timeout=300)
        r.raise_for_status()
        data = r.json()

        images = []
        for img in data.get("data", []):
            image_data = {}
            if img.get("url"):
                image_data["url"] = img["url"]
            if img.get("b64_json"):
                image_data["b64_json"] = img["b64_json"]
            images.append(image_data)

        return images

    def generate_to_files(
        self,
        prompt: str,
        output_dir: str,
        size: str = "2k",
        n: int = 1,
    ) -> list[str]:
        """生成图片并保存到文件。

        Returns:
            保存的文件路径列表。
        """
        images = self.generate(prompt, size=size, n=n, response_format="url")

        os.makedirs(output_dir, exist_ok=True)
        timestamp = int(time.time())
        paths = []

        for i, img in enumerate(images):
            url = img.get("url", "")
            if not url:
                continue

            filename = f"seedream_{timestamp}_{uuid.uuid4().hex[:8]}.png"
            filepath = os.path.join(output_dir, filename)

            try:
                r = requests.get(url, timeout=120)
                r.raise_for_status()
                with open(filepath, "wb") as f:
                    f.write(r.content)
                paths.append(filepath)
                logger.info("Seedream 图片已保存: %s (%d bytes)", filepath, len(r.content))
            except Exception as e:
                logger.error("Seedream 图片下载失败: %s", e)

        return paths


# ── Tool 函数 ────────────────────────────────────────────────────

from xiaomei_brain.tools.base import tool


@tool(
    name="generate_image_seedream",
    description="使用豆包 Seedream 模型生成图片。擅长写实风格、高清大图（2K/4K）。生成可能需要几秒到十几秒。",
)
def image_generate_seedream(
    prompt: str,
    size: str = "2k",
    n: int = 1,
) -> str:
    """使用豆包 Seedream 生成图片。

    Args:
        prompt: 图片描述（中文或英文）。
        size: 图片尺寸 — "2k"（默认）或 "4k"。
        n: 生成数量 1-4。
    """
    global _image_provider

    if _image_provider is None:
        return "豆包 Seedream 图片生成未配置。请设置 VOLCENGINE_API_KEY 环境变量。"

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
        for p in paths:
            result += f"  - {p}\n"
        return result.strip()

    except Exception as e:
        logger.error("Seedream image generation error: %s", e)
        return f"Seedream 图片生成失败: {e}"


image_generate_seedream_tool = image_generate_seedream
