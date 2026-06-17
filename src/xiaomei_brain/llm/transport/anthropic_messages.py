"""AnthropicMessagesTransport — Anthropic Messages API 协议。

支持 Claude 系列模型：
- 端点: /messages
- 认证: x-api-key + anthropic-version
- 消息: system 作为顶层字段，content 为 block 数组
- 工具: {name, description, input_schema} 格式
- SSE: 命名 event 字段
"""

from __future__ import annotations

import json
import logging
from typing import Any, Generator

from xiaomei_brain.llm.transport.base import Transport
from xiaomei_brain.llm.types import ModelDefinition, ProviderProfile, NormalizedResponse, ToolCall

logger = logging.getLogger(__name__)


class AnthropicMessagesTransport(Transport):
    """Anthropic Messages API 传输。"""

    # ── Concrete method overrides ──

    def get_endpoint(self, base_url: str) -> str:
        return f"{base_url}/messages"

    def get_headers(self, api_key: str) -> dict[str, str]:
        return {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        }

    def validate_raw_response(self, data: dict) -> None:
        if "content" not in data:
            raise ValueError("API response missing 'content' field")

    # ── Abstract method implementations ──

    def convert_messages(self, messages: list[dict],
                         model: ModelDefinition, profile: ProviderProfile) -> list[dict]:
        """内部消息 → Anthropic Messages 格式。

        关键转换：
        - role="system" 的消息保留 role="system"，由 build_kwargs 提取到顶层
        - content 从字符串转为 block 数组 [{"type":"text","text":"..."}]
        - tool_calls → content block 中的 tool_use
        - tool 结果 → content block 中的 tool_result
        """
        result = []
        for msg in messages:
            role = msg["role"]
            content = msg.get("content")

            # system 消息保留，由 build_kwargs 提取到顶层
            if role == "system":
                result.append({"role": role, "content": content})
                continue

            api_msg: dict[str, Any] = {"role": role}

            # content → block 数组
            blocks = []
            if content:
                if isinstance(content, str):
                    blocks.append({"type": "text", "text": content})
                elif isinstance(content, list):
                    blocks = content  # 已经是 block 数组
            api_msg["content"] = blocks

            # tool_calls → tool_use blocks
            if msg.get("tool_calls"):
                for tc in msg["tool_calls"]:
                    try:
                        args = json.loads(tc["function"]["arguments"]) if isinstance(tc["function"]["arguments"], str) else tc["function"]["arguments"]
                    except (json.JSONDecodeError, KeyError):
                        args = {}
                    api_msg.setdefault("content", []).append({
                        "type": "tool_use",
                        "id": tc.get("id", ""),
                        "name": tc["function"]["name"],
                        "input": args,
                    })

            # tool 结果 → tool_result blocks
            if role == "tool":
                api_msg["content"] = [{
                    "type": "tool_result",
                    "tool_use_id": msg.get("tool_call_id", ""),
                    "content": content if isinstance(content, str) else json.dumps(content),
                }]

            result.append(api_msg)

        return profile.prepare_messages(result, model)

    def convert_tools(self, tools: list[dict],
                      model: ModelDefinition, profile: ProviderProfile) -> list[dict]:
        """OpenAI 工具格式 → Anthropic 工具格式。

        OpenAI: {type:"function", function:{name, description, parameters}}
        Anthropic: {name, description, input_schema}
        """
        result = []
        for tool in tools:
            fn = tool.get("function", tool)
            anthropic_tool = {
                "name": fn.get("name", ""),
                "description": fn.get("description", ""),
                "input_schema": fn.get("parameters", {"type": "object", "properties": {}}),
            }
            result.append(anthropic_tool)
        return result

    def build_kwargs(self, messages: list[dict], tools: list[dict] | None,
                     model: ModelDefinition, profile: ProviderProfile,
                     stream: bool, **context) -> dict:
        """构建 Anthropic Messages API 请求参数。

        system 消息从 messages 中提取，放入顶层 system 字段。
        """
        # 提取 system 消息
        system_messages = [m for m in messages if m.get("role") == "system"]
        non_system = [m for m in messages if m.get("role") != "system"]

        # 合并 system prompt
        system_text = ""
        for sm in system_messages:
            content = sm.get("content", "")
            if isinstance(content, list):
                content = "".join(b.get("text", "") for b in content if b.get("type") == "text")
            if content:
                system_text += content + "\n\n"
        system_text = system_text.strip()

        payload: dict[str, Any] = {
            "model": model.id,
            "messages": non_system,
            "max_tokens": model.max_tokens,
        }

        if system_text:
            payload["system"] = system_text

        if stream:
            payload["stream"] = True

        if tools:
            payload["tools"] = tools

        # Profile hooks
        extra = profile.build_extra_body(model, stream=stream, **context)
        if extra:
            payload.update(extra)

        return payload

    def normalize_response(self, raw: dict,
                           model: ModelDefinition, profile: ProviderProfile
                           ) -> NormalizedResponse:
        """Anthropic 响应 → NormalizedResponse。

        Anthropic 响应结构:
        {
          "id": "msg_xxx",
          "content": [{"type":"text","text":"Hello"}, {"type":"tool_use",...}],
          "stop_reason": "end_turn",
          "usage": {"input_tokens": N, "output_tokens": M}
        }
        """
        content_blocks = raw.get("content", [])

        # 提取文本
        text_parts = []
        tool_calls = []
        for block in content_blocks:
            if block.get("type") == "text":
                text_parts.append(block.get("text", ""))
            elif block.get("type") == "tool_use":
                tool_calls.append(ToolCall(
                    id=block.get("id", ""),
                    name=block.get("name", ""),
                    arguments=json.dumps(block.get("input", {}), ensure_ascii=False),
                ))

        content = "".join(text_parts) if text_parts else None

        usage_raw = raw.get("usage", {})
        usage = None
        if usage_raw:
            usage = {
                "input_tokens": usage_raw.get("input_tokens", 0),
                "output_tokens": usage_raw.get("output_tokens", 0),
            }

        return NormalizedResponse(
            content=content,
            tool_calls=tool_calls,
            finish_reason=raw.get("stop_reason", ""),
            usage=usage,
        )

    def stream_iter(self, response,
                    model: ModelDefinition, profile: ProviderProfile
                    ) -> Generator[tuple[str, dict | None], None, None]:
        """迭代 Anthropic SSE 流。

        Anthropic SSE 格式:
        event: message_start
        data: {"message": {...}}

        event: content_block_delta
        data: {"index": 0, "delta": {"type": "text_delta", "text": "Hello"}}

        event: message_delta
        data: {"delta": {"stop_reason": "end_turn"}, "usage": {...}}

        event: message_stop
        data: {}
        """
        content_parts: list[str] = []
        tool_calls_acc: dict[int, dict] = {}
        finish_reason = ""
        usage = None

        current_event = None

        try:
            for line in response.iter_lines():
                if not line:
                    current_event = None
                    continue
                if isinstance(line, bytes):
                    try:
                        line = line.decode("utf-8")
                    except UnicodeDecodeError:
                        line = line.decode("utf-8", errors="replace")

                # 解析 event: 行
                if line.startswith("event: "):
                    current_event = line[7:].strip()
                    continue

                # 解析 data: 行
                if not line.startswith("data: "):
                    continue
                data_str = line[6:]

                try:
                    data = json.loads(data_str)
                except json.JSONDecodeError:
                    continue

                if current_event == "content_block_delta":
                    delta = data.get("delta", {})
                    if delta.get("type") == "text_delta":
                        text = delta.get("text", "")
                        content_parts.append(text)
                        yield text, None
                    elif delta.get("type") == "input_json_delta":
                        # 工具参数增量
                        idx = data.get("index", 0)
                        if idx not in tool_calls_acc:
                            tool_calls_acc[idx] = {"id": "", "name": "", "arguments": ""}
                        tool_calls_acc[idx]["arguments"] += delta.get("partial_json", "")

                elif current_event == "content_block_start":
                    block = data.get("content_block", {})
                    if block.get("type") == "tool_use":
                        idx = data.get("index", 0)
                        tool_calls_acc[idx] = {
                            "id": block.get("id", ""),
                            "name": block.get("name", ""),
                            "arguments": "",
                        }

                elif current_event == "message_delta":
                    delta = data.get("delta", {})
                    if delta.get("stop_reason"):
                        finish_reason = delta["stop_reason"]
                    usage_raw = data.get("usage", {})
                    if usage_raw:
                        usage = {
                            "input_tokens": usage_raw.get("input_tokens", 0),
                            "output_tokens": usage_raw.get("output_tokens", 0),
                        }

                elif current_event == "message_stop":
                    pass

                elif current_event == "error":
                    error_msg = data.get("error", {}).get("message", "Unknown error")
                    logger.error("[Anthropic] Stream error: %s", error_msg)
                    raise RuntimeError(f"Anthropic stream error: {error_msg}")

        except Exception:
            raise

        # 流结束 — yield 汇总 extra_info
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
            "content_raw": "".join(content_parts),
            "usage": usage,
        }
