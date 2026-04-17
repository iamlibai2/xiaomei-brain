"""Image generation using MiniMax API."""

from __future__ import annotations

import logging
import os
import time
import uuid
from dataclasses import dataclass

import requests

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "image-01"
DEFAULT_RESPONSE_FORMAT = "url"
DEFAULT_PROMPT_OPTIMIZER = False
DEFAULT_AIGC_WATERMARK = False


@dataclass
class ImageConfig:
    """Image generation configuration."""
    aspect_ratio: str = "1:1"
    response_format: str = DEFAULT_RESPONSE_FORMAT
    prompt_optimizer: bool = DEFAULT_PROMPT_OPTIMIZER
    aigc_watermark: bool = DEFAULT_AIGC_WATERMARK


class ImageProvider:
    """MiniMax Image Generation API.

    Generates images from text prompts.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.minimaxi.com",
        config: ImageConfig | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.config = config or ImageConfig()

    def generate(
        self,
        prompt: str,
        model: str = DEFAULT_MODEL,
        n: int = 1,
        width: int | None = None,
        height: int | None = None,
        seed: int | None = None,
        style: str | None = None,
        style_weight: float | None = None,
        response_format: str | None = None,
        aigc_watermark: bool | None = None,
        timeout: int = 120,
        **kwargs,
    ) -> list[bytes]:
        """Generate images from text prompt.

        Args:
            prompt: Image description (max 1500 chars).
            model: Model name - "image-01" or "image-01-live".
            n: Number of images to generate (1-9).
            width: Image width in pixels [512, 2048], must be multiple of 8.
            height: Image height in pixels [512, 2048], must be multiple of 8.
            seed: Random seed for reproducibility.
            style: Style for image-01-live: "漫画", "元气", "中世纪", "水彩".
            style_weight: Style weight (0, 1], only for image-01-live.
            response_format: "url" (24h expiry) or "base64".
            aigc_watermark: Whether to add AIGC watermark.
            timeout: Request timeout in seconds.

        Returns:
            List of image data as bytes.
        """
        if len(prompt) > 1500:
            prompt = prompt[:1500]

        payload = {
            "model": model,
            "prompt": prompt,
            "n": min(max(1, n), 9),
            "response_format": response_format or self.config.response_format,
        }

        # aspect_ratio and width/height are mutually exclusive; width/height takes priority
        if width is not None and height is not None:
            payload["width"] = width
            payload["height"] = height
        else:
            payload["aspect_ratio"] = kwargs.get("aspect_ratio", self.config.aspect_ratio)

        if seed is not None:
            payload["seed"] = seed

        opt = kwargs.get("prompt_optimizer", self.config.prompt_optimizer)
        if opt:
            payload["prompt_optimizer"] = True

        wm = aigc_watermark if aigc_watermark is not None else self.config.aigc_watermark
        if wm:
            payload["aigc_watermark"] = True

        # Style only works with image-01-live
        if model == "image-01-live" and style:
            payload["style"] = {"style_type": style}
            if style_weight is not None:
                payload["style"]["style_weight"] = style_weight

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        response = requests.post(
            f"{self.base_url}/v1/image_generation",
            headers=headers,
            json=payload,
            timeout=timeout,
        )
        response.raise_for_status()
        data = response.json()

        base_resp = data.get("base_resp", {})
        status = base_resp.get("status_code", 0)
        if status != 0:
            msg = base_resp.get("status_msg", "unknown error")
            raise RuntimeError(f"Image generation failed: {msg}")

        # Download images
        images = []
        if payload["response_format"] == "base64":
            b64_images = data.get("data", {}).get("image_base64", [])
            for b64 in b64_images:
                import base64 as b64mod
                images.append(b64mod.b64decode(b64))
        else:
            image_urls = data.get("data", {}).get("image_urls", [])
            for url in image_urls:
                img_data = self._download_image(url, timeout=timeout)
                if img_data:
                    images.append(img_data)

        return images

    def generate_to_files(
        self,
        prompt: str,
        output_dir: str,
        n: int = 1,
        width: int | None = None,
        height: int | None = None,
        seed: int | None = None,
        style: str | None = None,
        style_weight: float | None = None,
        response_format: str | None = None,
        aigc_watermark: bool | None = None,
        timeout: int = 120,
        **kwargs,
    ) -> list[str]:
        """Generate images and save to files.

        Args:
            prompt: Image description.
            output_dir: Directory to save images.
            n: Number of images.
            width: Image width in pixels.
            height: Image height in pixels.
            seed: Random seed.
            style: Style type for image-01-live.
            style_weight: Style weight.
            response_format: "url" or "base64".
            aigc_watermark: Whether to add watermark.
            timeout: Request timeout.

        Returns:
            List of saved file paths.
        """
        images = self.generate(
            prompt, n=n, width=width, height=height, seed=seed,
            style=style, style_weight=style_weight,
            response_format=response_format, aigc_watermark=aigc_watermark,
            timeout=timeout, **kwargs,
        )

        os.makedirs(output_dir, exist_ok=True)
        timestamp = int(time.time())
        fmt = "jpeg"
        if response_format == "base64" or (response_format is None and self.config.response_format == "base64"):
            fmt = "png"
        paths = []

        for i, img_data in enumerate(images):
            filename = f"img_{timestamp}_{uuid.uuid4().hex[:8]}.{fmt}"
            filepath = os.path.join(output_dir, filename)
            with open(filepath, "wb") as f:
                f.write(img_data)
            paths.append(filepath)
            logger.info("Saved image: %s (%d bytes)", filepath, len(img_data))

        return paths

    def _download_image(self, url: str, timeout: int = 60) -> bytes | None:
        """Download image from URL."""
        try:
            r = requests.get(url, timeout=timeout)
            r.raise_for_status()
            return r.content
        except Exception as e:
            logger.error("Failed to download image from %s: %s", url, e)
            return None

    def generate_with_retry(self, prompt: str, **kwargs) -> list[bytes]:
        """Generate images with retry on failure."""
        max_retries = kwargs.pop("max_retries", 3)
        for attempt in range(max_retries):
            try:
                return self.generate(prompt, **kwargs)
            except Exception as e:
                logger.warning("Image generation attempt %d failed: %s", attempt + 1, e)
                if attempt < max_retries - 1:
                    time.sleep(2 * (attempt + 1))
        raise RuntimeError(f"Image generation failed after {max_retries} attempts")


def get_available_aspect_ratios() -> list[str]:
    """Return list of available aspect ratios."""
    return ["1:1", "16:9", "4:3", "3:2", "2:3", "3:4", "9:16", "21:9"]


def get_available_models() -> list[str]:
    """Return list of available image models."""
    return ["image-01", "image-01-live"]


def get_available_styles() -> list[str]:
    """Return list of available styles for image-01-live."""
    return ["漫画", "元气", "中世纪", "水彩"]
