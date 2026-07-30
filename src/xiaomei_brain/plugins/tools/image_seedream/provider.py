"""豆包 Seedream 图片生成 API 客户端（火山引擎方舟平台）。"""

from __future__ import annotations

import logging
import os
import time
import uuid
from typing import Any

import requests

logger = logging.getLogger(__name__)

VALID_SIZES = ["2k", "4k"]
MAX_IMAGES = 4


class SeedreamProvider:
    """豆包 Seedream 图片生成 provider。

    直接通过 HTTP POST 调用火山引擎方舟 API（OpenAI 兼容接口）。
    """

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
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


