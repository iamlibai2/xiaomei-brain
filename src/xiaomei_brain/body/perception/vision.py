"""VisionUnderstanding — 多模态视觉理解。

用多模态 LLM 对图像进行通用场景描述。
与 FaceID（本地 CV 人脸识别）互补：
  - FaceID: 专用识别，检测+匹配已知人脸
  - VisionUnderstanding: 通用理解，描述场景、氛围、物体、活动等

配置通过 set_vision_config() 注入（agent_manager.init_agent() 调用）。
"""

from __future__ import annotations

import base64
import logging

import requests

logger = logging.getLogger(__name__)

# 全局配置（agent_manager.init_agent() 设置）
_VISION_API_KEY: str = ""
_VISION_BASE_URL: str = ""
_VISION_MODEL: str = ""


def set_vision_config(api_key: str, base_url: str, model: str) -> None:
    """设置视觉模型配置（由 agent_manager 调用）。"""
    global _VISION_API_KEY, _VISION_BASE_URL, _VISION_MODEL
    _VISION_API_KEY = api_key
    _VISION_BASE_URL = base_url.rstrip("/")
    _VISION_MODEL = model
    logger.info("[Vision] 配置已设置: model=%s base_url=%s", model, base_url)


class VisionUnderstanding:
    """多模态视觉理解 — 接收图片 bytes，调用多模态 LLM 返回文字描述。

    用法:
        vu = VisionUnderstanding()
        desc = vu.describe(image_bytes, prompt="描述这个画面")
    """

    def __init__(self) -> None:
        pass

    @property
    def is_available(self) -> bool:
        return bool(_VISION_API_KEY and _VISION_BASE_URL and _VISION_MODEL)

    def describe(self, image_bytes: bytes, prompt: str = "描述这个画面") -> str | None:
        """对图片进行多模态理解。

        Args:
            image_bytes: JPEG 图片字节
            prompt: 引导视觉关注什么

        Returns:
            LLM 的文字描述，失败返回 None
        """
        if not self.is_available:
            logger.warning("[Vision] 视觉模型未配置，无法进行视觉理解")
            return None

        data_url = (
            f"data:image/jpeg;base64,"
            f"{base64.b64encode(image_bytes).decode('ascii')}"
        )
        payload = {
            "model": _VISION_MODEL,
            "thinking": {"type": "disabled"},   # 图片理解不需要推理链，省时
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url",
                         "image_url": {"url": data_url}},
                    ],
                }
            ],
        }

        try:
            resp = requests.post(
                f"{_VISION_BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {_VISION_API_KEY}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=60,
            )
            resp.raise_for_status()
            data = resp.json()
            choices = data.get("choices", [])
            if choices:
                content = choices[0].get("message", {}).get("content", "")
                if isinstance(content, list):
                    # 多模态返回可能是数组
                    parts = [p.get("text", "") for p in content
                             if isinstance(p, dict) and p.get("type") == "text"]
                    return "".join(parts).strip() or None
                return content.strip() or None
            return None
        except requests.Timeout:
            logger.error("[Vision] 请求超时 (60s)")
            return None
        except Exception as e:
            logger.error("[Vision] 多模态 LLM 调用失败: %s", e)
            return None
