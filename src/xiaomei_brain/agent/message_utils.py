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
    """Clean surrogate characters from message content."""
    cleaned = []
    for m in messages:
        m = dict(m)  # shallow copy
        content = m.get("content")
        if isinstance(content, str):
            try:
                content = content.encode("utf-8", "surrogatepass").decode("utf-8", "replace")
            except Exception:
                pass
            m["content"] = content
        cleaned.append(m)
    return cleaned
