"""Capability-aware routing for chat image attachments."""

from __future__ import annotations

import logging
import re
from typing import Any

from xiaomei_brain.agent.message_utils import build_multimodal_content

logger = logging.getLogger(__name__)


class VisionRoutingError(RuntimeError):
    """Raised when an image message has no usable vision path."""


_IMAGE_ANALYSIS_PATTERN = re.compile(
    r"分析|识别|描述|解释|看图|读图|理解图片|提取文字|ocr|图片里|图中|根据图片内容",
    re.IGNORECASE,
)
_IMAGE_ASSET_PATTERN = re.compile(
    r"插入|嵌入|放入|放到|添加到|作为(?:封面|插图|配图)|原样|"
    r"用(?:这个|这张|该)图片|使用(?:这个|这张|该)图片",
    re.IGNORECASE,
)
_DOCUMENT_TARGET_PATTERN = re.compile(
    r"word|docx|ppt|pptx|幻灯片|文档|报告|文件",
    re.IGNORECASE,
)


def _is_asset_only_image_request(user_input: str) -> bool:
    """Detect requests that only move an image into a deliverable.

    In that case the model needs the durable attachment id, not an expensive
    semantic analysis of the image pixels.
    """
    text = (user_input or "").strip()
    if not text or _IMAGE_ANALYSIS_PATTERN.search(text):
        return False
    if not _IMAGE_ASSET_PATTERN.search(text):
        return False
    return bool(
        _DOCUMENT_TARGET_PATTERN.search(text)
        or re.search(r"用(?:这个|这张|该)图片|使用(?:这个|这张|该)图片", text)
    )


def route_chat_images(
    agent_instance: Any,
    user_input: str,
    image_paths: list[str] | None,
) -> tuple[list[str], str]:
    """Return images for the primary model and optional fallback analysis.

    A vision-capable primary receives the original images. Otherwise the
    configured fallback vision model analyzes all images once and the primary
    receives that analysis as text.
    """
    images = image_paths or []
    if not images:
        return [], ""
    if _is_asset_only_image_request(user_input):
        logger.info("[VisionRoute] image is used as an asset; skip semantic analysis")
        return [], ""

    primary_llm = getattr(agent_instance, "llm", None)
    if primary_llm is not None and primary_llm.supports_vision:
        logger.info(
            "[VisionRoute] primary model accepts images: %s/%s",
            primary_llm.provider, primary_llm.model,
        )
        return images, ""

    vision_llm = getattr(agent_instance, "vision_llm", None)
    configured_model = getattr(agent_instance, "vision_model", "")
    if vision_llm is None:
        primary_name = (
            f"{primary_llm.provider}/{primary_llm.model}" if primary_llm is not None else "current primary model"
        )
        if configured_model:
            raise VisionRoutingError(f"视觉模型 {configured_model} 未能初始化，请检查 Provider 和 API Key 配置")
        raise VisionRoutingError(
            f"主模型 {primary_name} 不支持图片输入，且当前 Agent 未配置 model.vision"
        )

    prompt = (
        "请分析用户附带的全部图片，保留与用户问题相关的细节、文字、结构和图片之间的关系。"
        "你的分析会交给另一个主模型继续回答，请只输出准确、充分的图片分析，不要假装已经完成用户的后续任务。\n\n"
        f"用户问题：{user_input or '请理解这些图片。'}"
    )
    logger.info("[VisionRoute] using fallback vision model: %s", configured_model)
    try:
        response = vision_llm.chat(messages=[{
            "role": "user",
            "content": build_multimodal_content(prompt, images),
        }])
    except Exception as exc:
        raise VisionRoutingError(f"视觉模型 {configured_model} 调用失败: {exc}") from exc
    analysis = (response.content or "").strip()
    if not analysis:
        raise VisionRoutingError(f"视觉模型 {configured_model} 没有返回有效的图片分析")

    logger.info("[VisionRoute] fallback vision analysis complete: %s", configured_model)
    return [], analysis
