"""Message sanitization utilities.

Pure functions for repairing message lists before sending to LLM APIs,
plus character-level input cleaning.
Extracted from core.py to keep Agent focused on ReAct loop logic.
"""

from __future__ import annotations

import logging
from typing import Any, Generator

from xiaomei_brain.memory.extractor import MemoryExtractor


# ── Character-level input cleaning ─────────────────────────────

def clean_input(text: str) -> str:
    """字符级输入清洗。

    只过滤控制字符和代理字符，不做退格模拟。
    终端/TUI/WebSocket 已在客户端完成编辑，退格无需服务端重复处理。
    """
    buf: list[str] = []
    for ch in text:
        cp = ord(ch)
        # 代理字符（\ud800-\udfff）：跳过
        if 0xD800 <= cp <= 0xDFFF:
            continue
        # 替换字符：跳过
        if cp == 0xFFFD:
            continue
        # 控制字符（不含 \t \n \r）：跳过
        if cp < 0x20 and ch not in ("\t", "\n", "\r"):
            continue
        buf.append(ch)
    return "".join(buf)


# ── Message repair ─────────────────────────────────────────────

logger = logging.getLogger(__name__)


def strip_memory_stream(chunks: list[str]) -> Generator[str, None, None]:
    """Strip <MEMORY> blocks from streaming chunks.

    Joins chunks and strips MEMORY block using the same logic as extract_memory_block.
    Yields in a streaming manner for compatibility.
    """
    if not chunks:
        return
    full_text = "".join(chunks)
    _, clean = MemoryExtractor.extract_memory_block(full_text)
    if clean:
        yield clean


def strip_orphaned_tool_messages(
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Remove tool messages whose preceding assistant doesn't have tool_calls.

    This handles cases where:
    - tool messages exist in agent.messages but the corresponding
      assistant(tool_calls) was filtered out by DAG compression
    - tool messages were loaded from DB but their assistant was not persisted
    """
    result = []
    for m in messages:
        if m.get("role") == "tool":
            tc_id = m.get("tool_call_id", "")
            valid = False
            if tc_id:
                # Find the most recent assistant in result (not just result[-1],
                # since there may be multiple tool messages for one assistant)
                for prev in reversed(result):
                    if prev.get("role") == "assistant":
                        for tc in prev.get("tool_calls", []):
                            if tc.get("id") == tc_id:
                                valid = True
                                break
                        break
            if not valid:
                logger.debug(
                    "[Message] Stripped orphaned tool message: tc_id=%s",
                    tc_id,
                )
                continue
        result.append(m)
    return result


def strip_orphaned_assistant_tool_calls(
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Remove tool_calls from assistant messages where matching tool responses are missing.

    This is the reverse of strip_orphaned_tool_messages: when tool messages
    are individually compressed by DAG but their parent assistant(tool_calls)
    survives, the API rejects the malformed request.
    """
    result = []
    n = len(messages)
    for i, m in enumerate(messages):
        if m.get("role") == "assistant" and m.get("tool_calls"):
            tool_calls = m["tool_calls"]
            required_ids = [tc.get("id", "") for tc in tool_calls if tc.get("id")]
            valid = len(required_ids) > 0
            if valid and i + len(required_ids) < n:
                for j, tc_id in enumerate(required_ids):
                    next_m = messages[i + j + 1]
                    if next_m.get("role") != "tool" or next_m.get("tool_call_id") != tc_id:
                        valid = False
                        break
            elif required_ids:
                valid = False
            if not valid and required_ids:
                logger.warning(
                    "[Message] Stripped orphaned assistant tool_calls: "
                    "assistant at pos %d has %d tool_calls but matching tools not found",
                    i, len(required_ids),
                )
                m = dict(m)
                m.pop("tool_calls", None)
        result.append(m)
    return result


def clean_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Clean surrogate characters from message content (supports str and array content)."""
    cleaned = []
    for m in messages:
        m = dict(m)  # shallow copy
        content = m.get("content")
        if isinstance(content, str):
            try:
                content = content.encode("utf-8", "surrogatepass").decode("utf-8", "replace")
            except Exception as e:
                logger.debug("消息内容 surrogate 字符清洗失败（保留原文）: %s", e)
            m["content"] = content
        elif isinstance(content, list):
            # 多模态 content 数组：只清洗 text 类型的内容
            cleaned_parts = []
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    text = part.get("text", "")
                    try:
                        text = text.encode("utf-8", "surrogatepass").decode("utf-8", "replace")
                    except Exception as e:
                        logger.debug("多模态内容 surrogate 字符清洗失败（保留原文）: %s", e)
                    cleaned_parts.append({**part, "text": text})
                else:
                    cleaned_parts.append(part)
            m["content"] = cleaned_parts
        cleaned.append(m)
    return cleaned


# ── 图片编码 ────────────────────────────────────────────

import base64
from pathlib import Path

_IMAGE_MIME_MAP = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
}


def image_to_data_url(image_path: str) -> str:
    """将本地图片文件转为 base64 data URL。

    Args:
        image_path: 图片文件路径

    Returns:
        data:image/<type>;base64,<data> 格式的字符串

    Raises:
        FileNotFoundError: 文件不存在
        ValueError: 不支持的图片格式
    """
    # 处理 Windows 风格路径（WSL 下反斜杠不合法）
    image_path = image_path.replace("\\", "/")
    p = Path(image_path).expanduser().resolve()
    if not p.is_file():
        # 尝试补前导 / （用户可能漏了绝对路径前缀）
        if not image_path.startswith("/"):
            p = Path("/" + image_path).expanduser().resolve()
    if not p.is_file():
        raise FileNotFoundError(f"图片不存在: {image_path} → 尝试过: {p}")

    suffix = p.suffix.lower()
    mime = _IMAGE_MIME_MAP.get(suffix)
    if not mime:
        raise ValueError(f"不支持的图片格式: {suffix}，支持: {list(_IMAGE_MIME_MAP.keys())}")

    with open(p, "rb") as f:
        data = base64.b64encode(f.read()).decode("ascii")

    return f"data:{mime};base64,{data}"


def build_multimodal_content(text: str, image_paths: list[str]) -> list[dict]:
    """构建多模态 content 数组。

    Args:
        text: 文本内容
        image_paths: 图片路径或 URL 列表

    Returns:
        OpenAI 多模态 content 数组: [{"type": "text", "text": ...}, {"type": "image_url", "image_url": {"url": ...}}]
    """
    content = [{"type": "text", "text": text}]
    for img in image_paths:
        # 如果是 URL（http/https/data），直接使用
        if img.startswith(("http://", "https://", "data:")):
            url = img
        else:
            url = image_to_data_url(img)
        content.append({
            "type": "image_url",
            "image_url": {"url": url},
        })
    return content


def estimate_content_tokens(content: str | list[dict] | None) -> int:
    """估算 content 的 token 数（兼容纯文本和多模态数组）。"""
    if not content:
        return 0
    if isinstance(content, str):
        from xiaomei_brain.base.message_utils import estimate_tokens
        return estimate_tokens(content)
    if isinstance(content, list):
        from xiaomei_brain.base.message_utils import estimate_tokens
        tokens = 0
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                tokens += estimate_tokens(part.get("text", ""))
            elif isinstance(part, dict) and part.get("type") == "image_url":
                tokens += 85  # OpenAI 经验值
        return tokens
    return 0


def append_to_content(content: str | list[dict], text: str) -> str | list[dict]:
    """向 content 追加文本（兼容纯文本 和 多模态数组）。

    纯文本 → 字符串拼接。
    多模态数组 → 找到最后一个 text 类型元素追加文本。
    """
    if isinstance(content, str):
        return content + text
    if isinstance(content, list):
        # 从后往前找最后一个 text 类型的元素
        for part in reversed(content):
            if isinstance(part, dict) and part.get("type") == "text":
                part["text"] = part.get("text", "") + text
                return content
        # 没有 text 元素，在开头插入一个
        content.insert(0, {"type": "text", "text": text})
        return content
    return content  # fallback
