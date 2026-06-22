"""ChatCompletionsTransport — OpenAI-compatible 协议（覆盖 90%+ provider）。

迁移自 base/llm.py 的：
- _build_messages() → convert_messages()
- SSE 流解析 → stream_iter()
- _parse_response() → normalize_response()
- 思考标签 / MEMORY 标签过滤
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Generator

from xiaomei_brain.llm.transport.base import Transport
from xiaomei_brain.llm.types import ModelDefinition, ProviderProfile, NormalizedResponse, ToolCall

logger = logging.getLogger(__name__)

# ── 非原生端点默认值 ──
_NON_NATIVE_DEFAULTS = {
    "supports_developer_role": False,
    "supports_usage_in_streaming": False,
    "supports_strict_mode": False,
}
_NATIVE_DEFAULTS = {
    "supports_developer_role": True,
    "supports_usage_in_streaming": True,
    "supports_strict_mode": True,
}

# ── 流式标签缓冲（跨 chunk 防止标签被分割）──────────────────────
_TAG_PREFIXES = sorted(
    ["</MEMORY", "</MEMOR", "</MEMO", "</MEM", "</ME", "</M", "</", "<",
     "<MEMORY", "<MEMOR", "<MEMO", "<MEM", "<ME", "<M",
     "</think", "</thin", "</thi", "</th", "</t",
     "<think", "<thin", "<thi", "<th", "<t"],
    key=len, reverse=True,
)


def _save_partial_tag(text: str) -> str:
    """检测 text 末尾是否是一个被截断的标签开头，返回应缓冲的部分。"""
    for prefix in _TAG_PREFIXES:
        if text.endswith(prefix):
            return prefix
    return ""


def _save_partial_closing_tag(text: str, tag: str) -> str:
    """检测 text 末尾是否是指定闭合标签的被截断前缀。"""
    for n in range(len(tag) - 1, 0, -1):
        prefix = tag[:n]
        if text.endswith(prefix):
            return prefix
    return ""


class ChatCompletionsTransport(Transport):
    """OpenAI Chat Completions API 兼容传输。"""

    def _is_native_openai(self, profile: ProviderProfile) -> bool:
        return "api.openai.com" in profile.base_url

    def _resolve_cap(self, model: ModelDefinition, profile: ProviderProfile,
                     field: str) -> bool:
        """解析 per-model 能力：model 显式值 > transport 默认值。"""
        val = getattr(model, field, None)
        if val is not None:
            return val
        defaults = _NATIVE_DEFAULTS if self._is_native_openai(profile) else _NON_NATIVE_DEFAULTS
        return defaults.get(field, False)

    # ── convert_messages ─────────────────────────────────────

    def convert_messages(self, messages: list[dict],
                         model: ModelDefinition, profile: ProviderProfile) -> list[dict]:
        """内部消息 → OpenAI API 格式。调用 profile.prepare_messages() hook。"""
        result = []
        for msg in messages:
            api_msg: dict[str, Any] = {"role": msg["role"]}
            if msg.get("content") is not None:
                api_msg["content"] = msg["content"]
            if msg.get("tool_calls"):
                api_msg["tool_calls"] = msg["tool_calls"]
            # reasoning_content: GLM/DeepSeek 原生支持
            if msg.get("reasoning_content") and ("glm" in model.id.lower() or "deepseek" in model.id.lower()):
                api_msg["reasoning_content"] = msg["reasoning_content"]
            if msg.get("tool_call_id"):
                api_msg["tool_call_id"] = msg["tool_call_id"]
            if msg.get("name"):
                api_msg["name"] = msg["name"]
            result.append(api_msg)

        # DeepSeek thinking mode: 所有 assistant 消息必须有 reasoning_content
        if "deepseek" in model.id.lower():
            for m in result:
                if m.get("role") == "assistant" and "reasoning_content" not in m:
                    m["reasoning_content"] = " "

        # hook
        return profile.prepare_messages(result, model)

    # ── convert_tools ─────────────────────────────────────────

    def convert_tools(self, tools: list[dict],
                      model: ModelDefinition, profile: ProviderProfile) -> list[dict]:
        """工具定义直接透传（OpenAI 兼容）。"""
        return tools

    # ── build_kwargs ──────────────────────────────────────────

    def build_kwargs(self, messages: list[dict], tools: list[dict] | None,
                     model: ModelDefinition, profile: ProviderProfile,
                     stream: bool, **context) -> dict:
        """构建 API 请求参数。"""
        payload: dict[str, Any] = {
            "model": model.id,
            "messages": messages,
        }
        if stream:
            payload["stream"] = True
        if tools:
            payload["tools"] = tools

        # max_tokens field
        max_tok_field = model.max_tokens_field or "max_tokens"
        max_tok = profile.get_max_tokens(model)
        if max_tok:
            payload[max_tok_field] = max_tok

        # Profile hooks
        extra = profile.build_extra_body(model, stream=stream, **context)
        if extra:
            payload.update(extra)

        extras = profile.build_api_kwargs_extras(model, **context)
        if extras:
            for k, v in extras.items():
                if k not in payload:
                    payload[k] = v

        return payload

    # ── normalize_response ───────────────────────────────────

    def normalize_response(self, raw: dict,
                           model: ModelDefinition, profile: ProviderProfile
                           ) -> NormalizedResponse:
        """API JSON 响应 → NormalizedResponse。"""
        choice = raw.get("choices", [{}])[0]
        message = choice.get("message", {})

        content = message.get("content")
        content = self._strip_thinking(content)

        tool_calls = []
        if message.get("tool_calls"):
            for tc in message["tool_calls"]:
                fn = tc.get("function", {})
                tool_calls.append(ToolCall(
                    id=tc.get("id", ""),
                    name=fn.get("name", ""),
                    arguments=fn.get("arguments", "{}"),
                ))

        usage_raw = raw.get("usage", {})
        usage = None
        if usage_raw:
            usage = {
                "input_tokens": usage_raw.get("prompt_tokens", 0),
                "output_tokens": usage_raw.get("completion_tokens", 0),
            }

        return NormalizedResponse(
            content=content,
            tool_calls=tool_calls,
            finish_reason=choice.get("finish_reason", ""),
            reasoning=message.get("reasoning_content"),
            usage=usage,
        )

    # ── stream_iter ───────────────────────────────────────────

    def stream_iter(self, response,
                    model: ModelDefinition, profile: ProviderProfile
                    ) -> Generator[tuple[str, dict | None], None, None]:
        """迭代 SSE 流，产出 (delta_content, extra_info | None)。

        文本 chunk 通过第一元素产出。流结束时通过 extra_info 产出汇总数据。
        extra_info 中包含 finish_reason、tool_calls、reasoning 等。
        """
        in_think = False
        in_memory = False
        reasoning_yielded = False
        reasoning_end_yielded = False
        _tag_buffer = ""
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        tool_calls_acc: dict[int, dict] = {}
        finish_reason = ""

        try:
            for line in response.iter_lines():
                if not line:
                    continue
                if isinstance(line, bytes):
                    try:
                        line = line.decode("utf-8")
                    except UnicodeDecodeError:
                        line = line.decode("utf-8", errors="replace")
                if not line.startswith("data: "):
                    continue
                data = line[6:]
                if data.strip() == "[DONE]":
                    break

                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue

                choices = chunk.get("choices")
                if not choices:
                    continue
                choice = choices[0]
                delta = choice.get("delta", {})
                finish_reason = choice.get("finish_reason", "") or finish_reason

                # reasoning content
                if delta.get("reasoning_content"):
                    rc = delta["reasoning_content"]
                    reasoning_parts.append(rc)
                    if not reasoning_yielded:
                        yield "\n\033[2m", {"is_reasoning": True}
                        reasoning_yielded = True
                    yield rc, {"is_reasoning": True}

                # regular content
                if "content" in delta and delta["content"] and not delta.get("reasoning_content"):
                    content_parts.append(delta["content"])
                    text = _tag_buffer + delta["content"]
                    _tag_buffer = ""

                    if in_think:
                        end_idx = text.find("</think>")
                        if end_idx != -1:
                            in_think = False
                            text = text[end_idx + 8:]
                        else:
                            _tag_buffer = _save_partial_closing_tag(text, "</think>")
                            text = "" if not _tag_buffer else text[:-len(_tag_buffer)]

                    if not in_think:
                        start_idx = text.find("<think")
                        if start_idx != -1:
                            end_idx = text.find("</think>", start_idx)
                            if end_idx != -1:
                                text = text[:start_idx] + text[end_idx + 8:]
                            else:
                                text = text[:start_idx]
                                in_think = True

                    if in_memory:
                        end_idx = text.find("</MEMORY>")
                        if end_idx != -1:
                            in_memory = False
                            text = text[end_idx + 9:]
                        else:
                            _tag_buffer = _save_partial_closing_tag(text, "</MEMORY>")
                            text = "" if not _tag_buffer else text[:-len(_tag_buffer)]

                    if not in_memory:
                        start_idx = text.find("<MEMORY>")
                        if start_idx != -1:
                            end_idx = text.find("</MEMORY>", start_idx)
                            if end_idx != -1:
                                text = text[:start_idx] + text[end_idx + 9:]
                            else:
                                text = text[:start_idx]
                                in_memory = True

                    if text and not in_think and not in_memory:
                        _tag_buffer = _save_partial_tag(text)
                        if _tag_buffer:
                            text = text[:-len(_tag_buffer)]

                    if text:
                        if reasoning_yielded and not reasoning_end_yielded:
                            yield "\033[0m\n\n", None
                            reasoning_end_yielded = True
                        yield text, None

                # tool_calls accumulation
                if "tool_calls" in delta and delta["tool_calls"]:
                    for tc_delta in delta["tool_calls"]:
                        idx = tc_delta.get("index", 0)
                        if idx not in tool_calls_acc:
                            tool_calls_acc[idx] = {"id": "", "name": "", "arguments": ""}
                        if tc_delta.get("id"):
                            tool_calls_acc[idx]["id"] = tc_delta["id"]
                        fn = tc_delta.get("function", {})
                        if fn.get("name"):
                            tool_calls_acc[idx]["name"] = fn["name"]
                        if fn.get("arguments"):
                            tool_calls_acc[idx]["arguments"] += fn["arguments"] or ""
        except Exception:
            raise

        # 冲刷缓冲的截断标签前缀
        if _tag_buffer and not in_think and not in_memory:
            yield _tag_buffer, None

        # 补发 ANSI 重置
        if reasoning_yielded and not reasoning_end_yielded:
            yield "\033[0m", None

        yield "\n", None

        # 构建最终 extra_info
        tool_calls_raw = []
        for idx in sorted(tool_calls_acc):
            tc = tool_calls_acc[idx]
            tool_calls_raw.append({
                "id": tc["id"],
                "name": tc["name"],
                "arguments": tc["arguments"],
            })

        yield "", {
            "finish_reason": finish_reason,
            "tool_calls": tool_calls_raw if tool_calls_raw else None,
            "reasoning": "".join(reasoning_parts) if reasoning_parts else None,
            "content_raw": "".join(content_parts),
        }

    # ── helpers ───────────────────────────────────────────────

    @staticmethod
    def _strip_thinking(text: str | None) -> str | None:
        if not text:
            return text
        return re.sub(r'<think\b[^>]*>.*?</think\s*>', '', text, flags=re.DOTALL).strip() or None
