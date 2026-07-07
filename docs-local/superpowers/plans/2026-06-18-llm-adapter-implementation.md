# LLM 适配层重构 — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 LLM 适配层从单格式硬编码重构为基于插件体系的 multi-provider 通用架构（P0：ChatCompletionsTransport + 内置 provider 插件 + 配置合并）

**Architecture:** ProviderProfile 数据类定义 provider 行为 → Transport 策略模式处理 wire 协议 → PluginRegistry 集中注册 → LLMClient 分发。90% provider 直接实例化 ProviderProfile 零子类化。

**Tech Stack:** Python 3.13, dataclasses, requests, PyYAML

---

## File Structure

```
src/xiaomei_brain/llm/                    # 新增模块
├── __init__.py                           # 公开 API: LLMClient, ProviderProfile, ...
├── types.py                              # 所有数据结构
├── transport/
│   ├── __init__.py                       # TransportRegistry
│   ├── base.py                           # Transport ABC
│   └── chat_completions.py               # P0 — 现有 LLMClient 逻辑迁移
├── client.py                             # 新 LLMClient
└── providers/                            # 内置 provider 插件
    ├── deepseek/
    │   ├── plugin.yaml
    │   └── adapter.py
    ├── zhipu/
    │   ├── plugin.yaml
    │   └── adapter.py
    └── openai/
        ├── plugin.yaml
        └── adapter.py

修改文件:
  src/xiaomei_brain/plugin/loader.py      # _default_dirs() 新增 llm/providers/
  src/xiaomei_brain/plugin/context.py     # register_provider() 接受 ProviderProfile
  src/xiaomei_brain/base/config.py        # from_json() → ProviderProfile 构建
  src/xiaomei_brain/agent/agent_manager.py # build_agent() 使用新 LLMClient
  src/xiaomei_brain/agent/core.py         # import 路径更新
  src/xiaomei_brain/memory/context_assembler.py  # 接收 LLMClient 实例
  src/xiaomei_brain/memory/extractor.py   # 接收 LLMClient 实例

删除文件:
  src/xiaomei_brain/base/llm.py           # 逻辑已迁移到 llm/client.py
```

---

### Task 1: 创建 `llm/__init__.py` — 包初始化

**Files:**
- Create: `src/xiaomei_brain/llm/__init__.py`

- [ ] **Step 1: 创建空包文件**

```python
"""LLM 适配层 — 基于插件体系的 multi-provider 通用架构。

使用:
    from xiaomei_brain.llm import LLMClient

    client = LLMClient(provider="deepseek", model="deepseek-v4-flash", registry=registry)
    response = client.chat(messages=[...], tools=[...])
"""
```

- [ ] **Step 2: 验证导入不报错**

Run: `PYTHONPATH=src python3 -c "import xiaomei_brain.llm; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/xiaomei_brain/llm/__init__.py
git commit -m "feat: create llm/ package skeleton"
```

---

### Task 2: 创建 `llm/types.py` — 所有数据结构

**Files:**
- Create: `src/xiaomei_brain/llm/types.py`

- [ ] **Step 1: 写 types.py 完整代码**

```python
"""LLM 适配层数据结构 — ModelApi / ProviderProfile / ModelDefinition / NormalizedResponse."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ModelApi(str, Enum):
    """API 接口类型 — 决定使用哪个 Transport。"""
    CHAT_COMPLETIONS = "chat-completions"
    ANTHROPIC_MESSAGES = "anthropic-messages"
    BEDROCK_CONVERSE = "bedrock-converse"
    OPENAI_RESPONSES = "openai-responses"
    OPENAI_CODEX_RESPONSES = "openai-codex-responses"
    GITHUB_COPILOT = "github-copilot"


@dataclass
class ModelDefinition:
    """单个模型的定义 — 描述其能力和约束。

    per-model 能力字段设为 None 时沿用 transport 默认值。
    """
    id: str
    name: str
    context_window: int
    max_tokens: int
    reasoning: bool = False
    input_modes: list[str] = field(default_factory=lambda: ["text"])
    cost: dict = field(default_factory=dict)

    # Per-model 能力覆盖（None = 沿用 transport 默认值）
    supports_vision: bool | None = None
    supports_tools: bool | None = None
    supports_developer_role: bool | None = None
    supports_strict_mode: bool | None = None
    supports_usage_in_streaming: bool | None = None
    max_tokens_field: str | None = None  # "max_tokens" | "max_completion_tokens"


@dataclass
class ToolCall:
    """统一的工具调用表示。"""
    id: str | None
    name: str
    arguments: str              # JSON 字符串
    provider_data: dict | None = None


@dataclass
class NormalizedResponse:
    """所有 transport 输出的统一响应类型。"""
    content: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str = ""
    reasoning: str | None = None
    usage: dict | None = None
    provider_data: dict | None = None


@dataclass
class ProviderProfile:
    """一个 LLM provider 的完整描述。

    简单 provider（OpenAI 兼容）直接实例化此类。
    需要特殊处理的 provider 才子类化并 override hook 方法。
    """

    # ── 必填字段 ──
    provider_id: str
    name: str
    api_mode: str = "chat-completions"
    base_url: str = ""

    # ── 可选字段 ──
    aliases: tuple[str, ...] = ()
    display_name: str = ""
    description: str = ""
    env_vars: tuple[str, ...] = ()
    auth_type: str = "api-key"
    default_headers: dict = field(default_factory=dict)
    supports_health_check: bool = True
    supports_vision: bool = False
    default_max_tokens: int | None = None
    default_aux_model: str = ""

    # ── 模型目录 ──
    models: list[ModelDefinition] = field(default_factory=list)

    # ══ Hook 方法（子类按需 override）══

    def get_headers(self, api_key: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {api_key}"}

    def prepare_messages(self, messages: list[dict], model: ModelDefinition) -> list[dict]:
        return messages

    def build_extra_body(self, model: ModelDefinition, *, stream: bool, **context) -> dict:
        return {}

    def build_api_kwargs_extras(self, model: ModelDefinition, **context) -> dict[str, Any]:
        return {}

    def get_max_tokens(self, model: ModelDefinition) -> int | None:
        return model.max_tokens

    def resolve_model(self, model_id: str) -> ModelDefinition | None:
        for m in self.models:
            if m.id == model_id:
                return m
        return None

    @classmethod
    def from_config(cls, provider_id: str, config: dict) -> ProviderProfile:
        """从 config.json models.providers.<id> 构建 ProviderProfile。

        config 格式（OpenClaw 兼容）:
          {
            "baseUrl": "https://api.example.com/v1",
            "apiKey": "sk-xxx",
            "apiMode": "chat-completions",
            "models": [{"id": "...", "name": "...", "contextWindow": 128000, "maxTokens": 8192}]
          }
        """
        models = []
        for m in config.get("models", []):
            models.append(ModelDefinition(
                id=m.get("id", ""),
                name=m.get("name", m.get("id", "")),
                context_window=m.get("contextWindow", 4096),
                max_tokens=m.get("maxTokens", 4096),
                reasoning=m.get("reasoning", False),
                input_modes=m.get("inputModes", ["text"]),
                cost=m.get("cost", {}),
                supports_vision=m.get("supportsVision"),
                supports_tools=m.get("supportsTools"),
                supports_developer_role=m.get("supportsDeveloperRole"),
                supports_strict_mode=m.get("supportsStrictMode"),
                supports_usage_in_streaming=m.get("supportsUsageInStreaming"),
                max_tokens_field=m.get("maxTokensField"),
            ))

        return cls(
            provider_id=provider_id,
            name=config.get("name", provider_id),
            api_mode=config.get("apiMode", "chat-completions"),
            base_url=config.get("baseUrl", ""),
            aliases=tuple(config.get("aliases", [])),
            display_name=config.get("displayName", ""),
            description=config.get("description", ""),
            env_vars=tuple(config.get("envVars", [])),
            auth_type=config.get("authType", "api-key"),
            default_headers=config.get("defaultHeaders", {}),
            supports_health_check=config.get("supportsHealthCheck", True),
            supports_vision=config.get("supportsVision", False),
            default_max_tokens=config.get("defaultMaxTokens"),
            default_aux_model=config.get("defaultAuxModel", ""),
            models=models,
        )

    @classmethod
    def merge_or_create(cls, provider_id: str, config: dict,
                        existing: ProviderProfile | None) -> ProviderProfile:
        """合并 config.json 到已有 profile（或新建）。

        当 existing 不为 None 时，config.json 中的显式值覆盖 existing 字段。
        models 按 id 合并：config.json 中同 id 覆盖 existing。
        """
        if existing is None:
            return cls.from_config(provider_id, config)

        # 字段级合并：config.json 显式值优先
        if config.get("baseUrl"):
            existing.base_url = config["baseUrl"]
        if config.get("apiMode"):
            existing.api_mode = config["apiMode"]
        if config.get("name"):
            existing.name = config["name"]
        if config.get("displayName"):
            existing.display_name = config["displayName"]
        if config.get("aliases"):
            existing.aliases = tuple(config["aliases"])
        if config.get("authType"):
            existing.auth_type = config["authType"]
        if config.get("envVars"):
            existing.env_vars = tuple(config["envVars"])
        if config.get("supportsVision") is not None:
            existing.supports_vision = config["supportsVision"]

        # models 合并
        config_models = config.get("models", [])
        if config_models:
            existing_map = {m.id: m for m in existing.models}
            for m_cfg in config_models:
                mid = m_cfg.get("id", "")
                md = ModelDefinition(
                    id=mid,
                    name=m_cfg.get("name", mid),
                    context_window=m_cfg.get("contextWindow", 4096),
                    max_tokens=m_cfg.get("maxTokens", 4096),
                    reasoning=m_cfg.get("reasoning", False),
                    input_modes=m_cfg.get("inputModes", ["text"]),
                    cost=m_cfg.get("cost", {}),
                    supports_vision=m_cfg.get("supportsVision"),
                    supports_tools=m_cfg.get("supportsTools"),
                    supports_developer_role=m_cfg.get("supportsDeveloperRole"),
                    supports_strict_mode=m_cfg.get("supportsStrictMode"),
                    supports_usage_in_streaming=m_cfg.get("supportsUsageInStreaming"),
                    max_tokens_field=m_cfg.get("maxTokensField"),
                )
                existing_map[mid] = md  # 覆盖或新增
            existing.models = list(existing_map.values())

        return existing


def load_config_providers(registry, config: dict) -> None:
    """从 config.json models.providers 构建/合并 ProviderProfile 到 registry。

    调用时机：boot_plugins() 之后，在 boot_plugins() 返回的 registry 上调用。
    """
    models_cfg = config.get("models", {})
    if not isinstance(models_cfg, dict):
        return
    providers_cfg = models_cfg.get("providers", {})
    if not isinstance(providers_cfg, dict):
        return

    for provider_id, prov_cfg in providers_cfg.items():
        if not isinstance(prov_cfg, dict):
            continue
        existing = registry.get_provider(provider_id)
        merged = ProviderProfile.merge_or_create(provider_id, prov_cfg, existing)
        registry.register_provider(provider_id, merged)
```

- [ ] **Step 2: 验证导入和基本使用**

Run: `PYTHONPATH=src python3 -c "
from xiaomei_brain.llm.types import ProviderProfile, ModelDefinition, ModelApi
p = ProviderProfile(provider_id='test', name='Test', base_url='https://api.test.com/v1')
m = ModelDefinition(id='m1', name='Model 1', context_window=4096, max_tokens=2048)
p.models.append(m)
assert p.resolve_model('m1') is m
assert p.resolve_model('nope') is None
print('OK')
"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/xiaomei_brain/llm/types.py
git commit -m "feat: add llm/types.py — ProviderProfile, ModelDefinition, NormalizedResponse, ToolCall"
```

---

### Task 3: 创建 `llm/transport/__init__.py` 和 `llm/transport/base.py`

**Files:**
- Create: `src/xiaomei_brain/llm/transport/__init__.py`
- Create: `src/xiaomei_brain/llm/transport/base.py`

- [ ] **Step 1: 写 transport/__init__.py**

```python
"""Transport 注册与获取。"""

from __future__ import annotations

from .base import Transport

_transports: dict[str, type[Transport]] = {}


def register_transport(api_mode: str, transport_cls: type[Transport]) -> None:
    """注册一个 transport 类。"""
    _transports[api_mode] = transport_cls


def get_transport(api_mode: str) -> Transport:
    """获取 transport 实例。"""
    cls = _transports.get(api_mode)
    if cls is None:
        raise ValueError(f"Unknown api_mode: {api_mode}. Available: {list(_transports.keys())}")
    return cls()


def get_transport_cls(api_mode: str) -> type[Transport] | None:
    """获取 transport 类（不实例化）。"""
    return _transports.get(api_mode)
```

- [ ] **Step 2: 写 transport/base.py**

```python
"""Transport ABC — 每种 wire 协议一个子类。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Generator

from xiaomei_brain.llm.types import ModelDefinition, ProviderProfile, NormalizedResponse


class Transport(ABC):
    """一种 API 协议的传输实现。

    所有方法接收 model 和 profile，per-model 能力字段决定传输层行为。
    """

    @abstractmethod
    def convert_messages(self, messages: list[dict],
                         model: ModelDefinition, profile: ProviderProfile) -> list[dict]:
        """将内部消息格式转换为本协议的请求格式。"""
        ...

    @abstractmethod
    def convert_tools(self, tools: list[dict],
                      model: ModelDefinition, profile: ProviderProfile) -> list[dict]:
        """将内部工具定义转换为本协议的请求格式。"""
        ...

    @abstractmethod
    def build_kwargs(self, messages: list[dict], tools: list[dict] | None,
                     model: ModelDefinition, profile: ProviderProfile,
                     stream: bool, **context) -> dict:
        """构建完整的 API 请求参数。"""
        ...

    @abstractmethod
    def normalize_response(self, raw: Any,
                           model: ModelDefinition, profile: ProviderProfile) -> NormalizedResponse:
        """将 API 原始响应归一化为 NormalizedResponse。"""
        ...

    @abstractmethod
    def stream_iter(self, response,
                    model: ModelDefinition, profile: ProviderProfile
                    ) -> Generator[tuple[str, dict | None], None, None]:
        """迭代 SSE 流，产出 (delta_content, extra_info | None) 元组。

        delta_content: 本次 chunk 的文本增量（可能为空字符串 ""）
        extra_info:   附加信息 dict，None 表示本次 chunk 无额外信息。
                       chat_completions: {"finish_reason": str, "tool_calls": [...], "reasoning": str}
        """
        ...
```

- [ ] **Step 3: 验证导入**

Run: `PYTHONPATH=src python3 -c "from xiaomei_brain.llm.transport import Transport; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add src/xiaomei_brain/llm/transport/__init__.py src/xiaomei_brain/llm/transport/base.py
git commit -m "feat: add transport ABC and TransportRegistry"
```

---

### Task 4: 创建 `llm/transport/chat_completions.py` — ChatCompletionsTransport

**Files:**
- Create: `src/xiaomei_brain/llm/transport/chat_completions.py`

这是整个重构的核心。将 `base/llm.py` 中的消息构建、SSE 解析、标签过滤逻辑提取到这里。

- [ ] **Step 1: 写 chat_completions.py**

```python
"""ChatCompletionsTransport — OpenAI-compatible 协议（覆盖 90%+ provider）。"""

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

# ── 流式标签缓冲 ──
_TAG_PREFIXES = sorted(
    ["</MEMORY", "</MEMOR", "</MEMO", "</MEM", "</ME", "</M", "</", "<",
     "<MEMORY", "<MEMOR", "<MEMO", "<MEM", "<ME", "<M",
     "</think", "</thin", "</thi", "</th", "</t",
     "<think", "<thin", "<thi", "<th", "<t"],
    key=len, reverse=True,
)


class ChatCompletionsTransport(Transport):
    """OpenAI Chat Completions API 兼容传输。

    接管原 LLMClient 中的：
    - _build_messages() → convert_messages()
    - SSE 流解析 → stream_iter()
    - _parse_response() → normalize_response()
    - 思考标签过滤
    """

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
            if msg.get("reasoning_content") and "glm" in model.id.lower():
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

        # 调用 profile hook
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

        接管原 LLMClient.chat_stream() 的 SSE 解析 + 标签过滤逻辑。
        """
        in_think = False
        in_memory = False
        reasoning_yielded = False
        reasoning_end_yielded = False
        _tag_buffer = ""
        content_parts = []
        reasoning_parts = []
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

                # reasoning
                if delta.get("reasoning_content"):
                    rc = delta["reasoning_content"]
                    reasoning_parts.append(rc)
                    if not reasoning_yielded:
                        yield "\n\033[2m", {"reasoning": rc}
                        reasoning_yielded = True
                    else:
                        yield rc, None

                # content
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

                # tool_calls
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

        # 冲刷缓冲
        if _tag_buffer and not in_think and not in_memory:
            yield _tag_buffer, None

        if reasoning_yielded and not reasoning_end_yielded:
            yield "\033[0m", None

        # 构建最终 extra_info
        tool_calls = []
        for idx in sorted(tool_calls_acc):
            tc = tool_calls_acc[idx]
            tool_calls.append({
                "id": tc["id"],
                "name": tc["name"],
                "arguments": tc["arguments"],
            })

        yield "\n", None
        yield "", {
            "finish_reason": finish_reason,
            "tool_calls": tool_calls if tool_calls else None,
            "reasoning": "".join(reasoning_parts) if reasoning_parts else None,
            "content_parts": content_parts,
        }

    # ── helpers ───────────────────────────────────────────────

    @staticmethod
    def _strip_thinking(text: str | None) -> str | None:
        if not text:
            return text
        return re.sub(r'<think\b[^>]*>.*?</think\s*>', '', text, flags=re.DOTALL).strip() or None


# ── stream helper functions (module level, shared with client.py) ──

def _save_partial_tag(text: str) -> str:
    for prefix in _TAG_PREFIXES:
        if text.endswith(prefix):
            return prefix
    return ""


def _save_partial_closing_tag(text: str, tag: str) -> str:
    for n in range(len(tag) - 1, 0, -1):
        prefix = tag[:n]
        if text.endswith(prefix):
            return prefix
    return ""
```

- [ ] **Step 2: 验证导入**

Run: `PYTHONPATH=src python3 -c "from xiaomei_brain.llm.transport.chat_completions import ChatCompletionsTransport; print('OK')"`
Expected: `OK`

- [ ] **Step 3: 在 transport/__init__.py 中注册 ChatCompletionsTransport**

在文件末尾添加:

```python
# 自动注册内置 transport
from .chat_completions import ChatCompletionsTransport
register_transport("chat-completions", ChatCompletionsTransport)
```

- [ ] **Step 4: Commit**

```bash
git add src/xiaomei_brain/llm/transport/
git commit -m "feat: add ChatCompletionsTransport — SSE parsing, think/memory tag filtering, message conversion"
```

---

### Task 5: 创建 `llm/client.py` — 新 LLMClient

**Files:**
- Create: `src/xiaomei_brain/llm/client.py`

- [ ] **Step 1: 写 client.py**

```python
"""LLMClient — 从 PluginRegistry 获取 provider，按 api_mode 分发到 transport。"""

from __future__ import annotations

import datetime
import json
import logging
import os
import time
from typing import Any, Generator

import requests

from xiaomei_brain.llm.types import ProviderProfile, ModelDefinition, NormalizedResponse, ToolCall
from xiaomei_brain.llm.transport import get_transport

logger = logging.getLogger(__name__)

# ── Per-agent log directory ──
_log_agent_id: str | None = None


def set_log_agent(agent_id: str) -> None:
    global _log_agent_id
    _log_agent_id = agent_id


class LLMError(Exception):
    def __init__(self, message: str, retryable: bool = False, status_code: int = 0) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.status_code = status_code


class FatalLLMError(BaseException):
    def __init__(self, message: str, status_code: int = 0) -> None:
        super().__init__(message)
        self.status_code = status_code


class LLMClient:
    """LLM API 客户端 — 从 registry 获取 profile，分发到 transport。

    Usage:
        client = LLMClient(provider="deepseek", model="deepseek-v4-flash", registry=registry)
        response = client.chat(messages=[...], tools=[...])
    """

    RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
    FATAL_STATUS_CODES = {401, 402, 403}
    DEFAULT_MAX_RETRIES = 3
    DEFAULT_TIMEOUT = 60
    MAX_CONSECUTIVE_FAILURES = 10

    def __init__(
        self,
        provider: str,
        model: str,
        registry,  # PluginRegistry
        api_key: str = "",
        max_retries: int = DEFAULT_MAX_RETRIES,
        timeout: int = DEFAULT_TIMEOUT,
        fallback_configs: list[dict[str, str]] | None = None,
        interoception: Any = None,
    ) -> None:
        self._registry = registry
        self._profile = registry.get_provider(provider)
        if self._profile is None:
            raise ValueError(f"Unknown provider: {provider}")

        self._model_id = model
        self._model_def = self._profile.resolve_model(model)
        if self._model_def is None:
            # 模型不在 profile 目录中，手动构造一个最小定义
            self._model_def = ModelDefinition(id=model, name=model,
                                              context_window=128000, max_tokens=8192)
            logger.debug("Model '%s' not in provider '%s' catalog, using defaults", model, provider)

        self._transport = get_transport(self._profile.api_mode)
        self._max_retries = max_retries
        self._timeout = timeout

        # API key
        self._api_key = api_key or self._resolve_api_key()

        # Fallback
        self._fallback_configs = fallback_configs or []
        self._fallback_index = -1
        self._interoception = interoception

        # Token callback
        self._token_callback: Any = None

        # Tracking
        self._last_call_latency_ms: float = 0.0
        self._last_call_error: bool = False
        self._backoff_until: float = 0.0
        self._consecutive_failures: int = 0
        self._reasoning_end_yielded: bool = False
        self._last_stream_response: NormalizedResponse | None = None

    def _resolve_api_key(self) -> str:
        for env_var in self._profile.env_vars:
            val = os.getenv(env_var)
            if val:
                return val
        return ""

    @property
    def provider(self) -> str:
        return self._profile.provider_id

    @property
    def model(self) -> str:
        return self._model_id

    # ── Chat ──────────────────────────────────────────────

    def chat(self, messages: list[dict[str, Any]],
             tools: list[dict[str, Any]] | None = None,
             log_level: int | None = None) -> NormalizedResponse:
        """非流式对话。"""
        api_messages = self._transport.convert_messages(messages, self._model_def, self._profile)
        api_tools = self._transport.convert_tools(tools or [], self._model_def, self._profile) if tools else None

        payload = self._transport.build_kwargs(
            api_messages, api_tools, self._model_def, self._profile, stream=False,
        )

        headers = self._profile.get_headers(self._api_key)
        headers["Content-Type"] = "application/json"

        resp = self._request_with_retry(payload, headers, log_level)

        # Token estimation
        tokens = self._estimate_call_tokens(api_messages, resp.content)
        self._record_call(self._last_call_latency_ms, False, tokens)

        self._save_llm_log(payload, resp)
        return resp

    def chat_stream(self, messages: list[dict[str, Any]],
                    tools: list[dict[str, Any]] | None = None
                    ) -> Generator[str, None, None]:
        """流式对话 — 逐个 yield chunk。生成器结束后 _last_stream_response 可用。"""
        api_messages = self._transport.convert_messages(messages, self._model_def, self._profile)
        api_tools = self._transport.convert_tools(tools or [], self._model_def, self._profile) if tools else None

        payload = self._transport.build_kwargs(
            api_messages, api_tools, self._model_def, self._profile, stream=True,
        )

        headers = self._profile.get_headers(self._api_key)
        headers["Content-Type"] = "application/json"

        self._save_llm_log(payload)

        t0 = time.time()
        content_parts = []
        reasoning_text = ""
        tool_calls_list = None
        finish_reason = ""

        response = requests.post(
            f"{self._profile.base_url}/chat/completions",
            headers=headers,
            json=payload,
            timeout=self._timeout,
            stream=True,
        )

        if response.status_code in self.FATAL_STATUS_CODES:
            raise FatalLLMError(
                f"LLM API 致命错误 (HTTP {response.status_code}): {response.text[:200]}",
                status_code=response.status_code,
            )
        if response.status_code >= 400:
            logger.warning(
                "[LLM DEBUG] HTTP %d | msgs=%d roles=%s",
                response.status_code,
                len(api_messages),
                [m.get("role") for m in api_messages],
            )
        response.raise_for_status()

        try:
            for text, extra in self._transport.stream_iter(response, self._model_def, self._profile):
                if text:
                    content_parts.append(text)
                    yield text
                if extra:
                    if extra.get("finish_reason"):
                        finish_reason = extra["finish_reason"]
                    if extra.get("tool_calls"):
                        tool_calls_list = extra["tool_calls"]
                    if extra.get("reasoning"):
                        reasoning_text = extra["reasoning"]
        except Exception as e:
            logger.warning("[LLM] Stream error: %s", e)
            raise

        # Build final response
        content = "".join(c for c in content_parts if c not in ("\n", "\033[0m", "\033[0m\n\n", "\033[2m"))
        content = ChatCompletionsTransport._strip_thinking(content)

        tool_calls = []
        if tool_calls_list:
            for tc in tool_calls_list:
                try:
                    args = json.loads(tc["arguments"]) if tc.get("arguments") else {}
                except json.JSONDecodeError:
                    args = {}
                tool_calls.append(ToolCall(
                    id=tc.get("id", ""),
                    name=tc.get("name", ""),
                    arguments=json.dumps(args),
                ))

        self._last_stream_response = NormalizedResponse(
            content=content,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            reasoning=reasoning_text or None,
        )

        tokens = self._estimate_call_tokens(api_messages, content)
        self._record_call((time.time() - t0) * 1000, False, tokens)
        self._save_llm_log(payload, self._last_stream_response)

    # ── Retry logic ────────────────────────────────────────

    def _request_with_retry(self, payload: dict, headers: dict,
                            log_level: int | None = None) -> NormalizedResponse:
        url = f"{self._profile.base_url}/chat/completions"
        t0 = time.time()

        if self._interoception:
            backoff = getattr(self._interoception, 'backoff_seconds', 0.0)
            if backoff > 0:
                logger.warning("[LLM] Interoception 退避 %.1fs", backoff)
                time.sleep(backoff)

        last_error = None
        for attempt in range(self._max_retries + 1):
            try:
                response = requests.post(url, headers=headers, json=payload, timeout=self._timeout)

                if response.status_code in self.RETRYABLE_STATUS_CODES:
                    retry_after = self._calc_retry_after(response)
                    if attempt < self._max_retries:
                        logger.warning("API 返回 %d，%.1fs 后重试（第 %d/%d 次）",
                                       response.status_code, retry_after, attempt + 1, self._max_retries)
                        time.sleep(retry_after)
                        continue
                    raise LLMError(f"API 返回 {response.status_code}，重试耗尽", retryable=False)

                if response.status_code in self.FATAL_STATUS_CODES:
                    raise FatalLLMError(
                        f"LLM API 致命错误 (HTTP {response.status_code}): {response.text[:200]}",
                        status_code=response.status_code,
                    )

                if response.status_code >= 400:
                    logger.warning("[LLM] HTTP %d: %s", response.status_code, response.text[:500])
                response.raise_for_status()

                data = response.json()
                if "choices" not in data or not data["choices"]:
                    raise LLMError("API 响应缺少 choices 字段", retryable=True)

                elapsed = (time.time() - t0) * 1000
                self._last_call_latency_ms = elapsed
                return self._transport.normalize_response(data, self._model_def, self._profile)

            except requests.Timeout:
                last_error = LLMError(f"请求超时（{self._timeout}s）", retryable=True)
                if attempt < self._max_retries:
                    time.sleep(2 ** attempt)
                    continue
                raise last_error

            except requests.ConnectionError as e:
                last_error = LLMError(f"连接错误：{e}", retryable=True)
                if attempt < self._max_retries:
                    time.sleep(2 ** attempt)
                    continue
                raise last_error

            except (FatalLLMError, LLMError):
                raise
            except requests.RequestException as e:
                http_status = e.response.status_code if hasattr(e, 'response') and e.response else 0
                raise LLMError(f"请求失败：{e}", retryable=False, status_code=http_status)

        raise last_error or LLMError("未知错误", retryable=False)

    def _calc_retry_after(self, response) -> float:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return float(retry_after)
            except ValueError:
                pass
        if response.status_code == 429:
            return 2.0
        return min(4.0, 2.0)

    # ── Helpers ────────────────────────────────────────────

    def _estimate_call_tokens(self, messages: list[dict], response_content: str | None) -> int:
        from xiaomei_brain.base.message_utils import estimate_tokens
        total = 0
        for m in messages:
            content = m.get("content", "")
            if isinstance(content, str):
                total += estimate_tokens(content)
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict):
                        total += estimate_tokens(part.get("text", ""))
        if response_content:
            total += estimate_tokens(response_content)
        return total

    def _record_call(self, latency_ms: float, is_error: bool, tokens: int = 0,
                     status_code: int = 0) -> None:
        self._last_call_latency_ms = latency_ms
        self._last_call_error = is_error
        if self._interoception:
            try:
                self._interoception.record_llm_call(latency_ms, is_error)
            except Exception as e:
                logger.warning("Interoception failed: %s", e)
        if self._token_callback and tokens > 0:
            try:
                self._token_callback(tokens)
            except Exception as e:
                logger.warning("Token callback failed: %s", e)

    def _save_llm_log(self, payload: dict, response: NormalizedResponse | None = None) -> None:
        log_dir = os.path.expanduser(
            f"~/.xiaomei-brain/{_log_agent_id}/logs/llm" if _log_agent_id
            else "~/.xiaomei-brain/global/logs"
        )
        os.makedirs(log_dir, exist_ok=True)
        now = datetime.datetime.now()
        log_file = os.path.join(log_dir, f"{now.strftime('%Y%m%d')}.jsonl")
        try:
            entry = {
                "timestamp": now.isoformat(),
                "model": self._model_id,
                "payload": {"messages": payload.get("messages", []), "tools": payload.get("tools")},
                "response": {
                    "content": response.content,
                    "tool_calls": [{"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                                   for tc in (response.tool_calls or [])],
                    "finish_reason": response.finish_reason,
                    "reasoning": response.reasoning,
                } if response else None,
            }
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning("[LLM] Failed to save log: %s", e)

    # ── Fallback ───────────────────────────────────────────

    def switch_to_fallback(self) -> bool:
        self._fallback_index += 1
        if self._fallback_index >= len(self._fallback_configs):
            return False
        cfg = self._fallback_configs[self._fallback_index]
        logger.warning("[LLM] 切换到备用: %s", cfg.get("name", "unknown"))
        return True

    def reset_to_primary(self) -> None:
        self._fallback_index = -1
```

- [ ] **Step 2: 验证导入**

Run: `PYTHONPATH=src python3 -c "from xiaomei_brain.llm.client import LLMClient; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/xiaomei_brain/llm/client.py
git commit -m "feat: add new LLMClient — registry-based provider dispatch to transport"
```

---

### Task 6: 创建内置 provider 插件 — DeepSeek

**Files:**
- Create: `src/xiaomei_brain/llm/providers/__init__.py`
- Create: `src/xiaomei_brain/llm/providers/deepseek/plugin.yaml`
- Create: `src/xiaomei_brain/llm/providers/deepseek/adapter.py`

- [ ] **Step 1: 创建 providers 包文件**

```python
# llm/providers/__init__.py
"""Built-in LLM provider plugins."""
```

- [ ] **Step 2: 写 plugin.yaml**

```yaml
name: deepseek
version: "1.0.0"
description: DeepSeek provider — V4 thinking mode support
kind: provider
requires_env:
  - DEEPSEEK_API_KEY
entry: adapter:register
```

- [ ] **Step 2: 写 adapter.py**

```python
"""DeepSeek provider — 需要 override thinking hook。"""

from xiaomei_brain.llm.types import ProviderProfile, ModelDefinition


class DeepSeekProfile(ProviderProfile):
    provider_id = "deepseek"
    name = "DeepSeek"
    api_mode = "chat-completions"
    base_url = "https://api.deepseek.com/v1"
    env_vars = ("DEEPSEEK_API_KEY",)

    models = [
        ModelDefinition(id="deepseek-v4-flash", name="DeepSeek V4 Flash",
                        context_window=128000, max_tokens=8192, reasoning=True),
        ModelDefinition(id="deepseek-v4-pro", name="DeepSeek V4 Pro",
                        context_window=128000, max_tokens=8192, reasoning=True),
    ]

    def build_extra_body(self, model, *, stream: bool, **context) -> dict:
        if model.reasoning:
            return {"thinking": {"type": "enabled"}}
        return {}

    def build_api_kwargs_extras(self, model, **context) -> dict:
        if model.reasoning:
            return {"reasoning_effort": "medium"}
        return {}


def register(ctx):
    ctx.register_provider(DeepSeekProfile)
```

- [ ] **Step 3: 验证（不需要 API key，只验证注册）**

Run: `PYTHONPATH=src python3 -c "
from xiaomei_brain.plugin.registry import PluginRegistry
from xiaomei_brain.plugin.context import PluginContext
from xiaomei_brain.llm.providers.deepseek.adapter import register

reg = PluginRegistry()
ctx = PluginContext(config={}, plugin_name='deepseek', agent_id='test', registry=reg)
register(ctx)
p = reg.get_provider('deepseek')
assert p is not None
assert p.provider_id == 'deepseek'
m = p.resolve_model('deepseek-v4-flash')
assert m is not None
assert m.reasoning is True
print('OK')
"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add src/xiaomei_brain/llm/providers/deepseek/
git commit -m "feat: add DeepSeek provider plugin — thinking mode hooks"
```

---

### Task 7: 创建内置 provider 插件 — 智谱 & OpenAI

**Files:**
- Create: `src/xiaomei_brain/llm/providers/zhipu/plugin.yaml`
- Create: `src/xiaomei_brain/llm/providers/zhipu/adapter.py`
- Create: `src/xiaomei_brain/llm/providers/openai/plugin.yaml`
- Create: `src/xiaomei_brain/llm/providers/openai/adapter.py`

- [ ] **Step 1: 写 智谱 plugin.yaml**

```yaml
name: zhipu
version: "1.0.0"
description: 智谱AI GLM series
kind: provider
requires_env:
  - ZHIPU_API_KEY
entry: adapter:register
```

- [ ] **Step 2: 写 智谱 adapter.py**

```python
"""智谱AI provider — 简单 chat-completions 兼容，不需要 hook。"""

from xiaomei_brain.llm.types import ProviderProfile, ModelDefinition


zhipu = ProviderProfile(
    provider_id="zhipu",
    name="智谱AI",
    base_url="https://open.bigmodel.cn/api/paas/v4",
    env_vars=("ZHIPU_API_KEY",),
    models=[
        ModelDefinition(id="glm-5.1", name="GLM-5.1",
                        context_window=128000, max_tokens=8192, reasoning=True),
        ModelDefinition(id="glm-5", name="GLM-5",
                        context_window=128000, max_tokens=4096),
    ],
)


def register(ctx):
    ctx.register_provider(zhipu)
```

- [ ] **Step 3: 写 OpenAI plugin.yaml**

```yaml
name: openai
version: "1.0.0"
description: OpenAI GPT series
kind: provider
requires_env:
  - OPENAI_API_KEY
entry: adapter:register
```

- [ ] **Step 4: 写 OpenAI adapter.py**

```python
"""OpenAI provider — 零子类化，直接 ProviderProfile 实例。"""

from xiaomei_brain.llm.types import ProviderProfile, ModelDefinition


openai = ProviderProfile(
    provider_id="openai",
    name="OpenAI",
    base_url="https://api.openai.com/v1",
    env_vars=("OPENAI_API_KEY",),
    models=[
        ModelDefinition(id="gpt-4o", name="GPT-4o",
                        context_window=128000, max_tokens=16384,
                        supports_vision=True),
        ModelDefinition(id="gpt-5-mini", name="GPT-5 Mini",
                        context_window=256000, max_tokens=16384),
    ],
)


def register(ctx):
    ctx.register_provider(openai)
```

- [ ] **Step 5: 验证智谱注册**

Run: `PYTHONPATH=src python3 -c "
from xiaomei_brain.plugin.registry import PluginRegistry
from xiaomei_brain.plugin.context import PluginContext
from xiaomei_brain.llm.providers.zhipu.adapter import register
reg = PluginRegistry()
ctx = PluginContext(config={}, plugin_name='zhipu', agent_id='test', registry=reg)
register(ctx)
assert reg.get_provider('zhipu').resolve_model('glm-5.1') is not None
print('OK')
"`
Expected: `OK`

- [ ] **Step 6: 验证 OpenAI 注册**

Run: `PYTHONPATH=src python3 -c "
from xiaomei_brain.plugin.registry import PluginRegistry
from xiaomei_brain.plugin.context import PluginContext
from xiaomei_brain.llm.providers.openai.adapter import register
reg = PluginRegistry()
ctx = PluginContext(config={}, plugin_name='openai', agent_id='test', registry=reg)
register(ctx)
assert reg.get_provider('openai').resolve_model('gpt-4o') is not None
print('OK')
"`
Expected: `OK`

- [ ] **Step 7: Commit**

```bash
git add src/xiaomei_brain/llm/providers/zhipu/ src/xiaomei_brain/llm/providers/openai/
git commit -m "feat: add zhipu and openai provider plugins"
```

---

### Task 8: 更新 PluginLoader 发现 llm/providers/

**Files:**
- Modify: `src/xiaomei_brain/plugin/loader.py:49-66`

- [ ] **Step 1: 在 `_default_dirs()` 中添加 llm/providers/ 目录**

```python
def _default_dirs(self) -> list[str]:
    """默认插件扫描目录。"""
    dirs: list[str] = []

    # 内置频道
    import xiaomei_brain.channels as _channels
    channels_root = Path(_channels.__file__).parent
    dirs.append(str(channels_root))

    # 内置 provider（新增）
    import xiaomei_brain.llm.providers as _providers
    providers_root = Path(_providers.__file__).parent
    dirs.append(str(providers_root))

    # 用户插件
    user_plugins = Path.home() / ".xiaomei-brain" / "plugins"
    dirs.append(str(user_plugins))

    # 项目插件
    project_plugins = Path(".xiaomei-brain") / "plugins"
    if project_plugins.is_dir():
        dirs.append(str(project_plugins.resolve()))

    return dirs
```

- [ ] **Step 2: 确保 llm/providers/ 有 `__init__.py`**

```bash
ls src/xiaomei_brain/llm/providers/__init__.py 2>/dev/null || echo "# Provider plugins package" > src/xiaomei_brain/llm/providers/__init__.py
```

- [ ] **Step 3: 验证发现逻辑**

Run: `PYTHONPATH=src python3 -c "
from xiaomei_brain.plugin.loader import PluginLoader
from xiaomei_brain.plugin.registry import PluginRegistry
reg = PluginRegistry()
loader = PluginLoader(registry=reg, agent_id='test')
dirs = loader._default_dirs()
# Check that llm/providers/ is in the list
provider_dirs = [d for d in dirs if 'llm/providers' in d or 'providers' in d]
print(f'Provider dirs: {provider_dirs}')
assert len(provider_dirs) > 0, 'llm/providers/ not in discovery dirs!'
print('OK')
"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add src/xiaomei_brain/plugin/loader.py src/xiaomei_brain/llm/providers/__init__.py
git commit -m "feat: add llm/providers/ to PluginLoader discovery path"
```

---

### Task 9: 更新 PluginContext.register_provider() 接受 ProviderProfile

**Files:**
- Modify: `src/xiaomei_brain/plugin/context.py:70-78`

- [ ] **Step 1: 更新 register_provider 类型签名**

当前代码：
```python
def register_provider(self, provider: Any) -> None:
    provider_id = getattr(provider, "provider_id", "unknown")
    self._registry.register_provider(provider_id, provider)
    self.logger.info("Provider 已注册: %s", provider_id)
```

不变——已经用 `getattr(provider, "provider_id", "unknown")` 从对象上取 ID，对 ProviderProfile 实例和类都适用。

无需修改。验证即可：

Run: `PYTHONPATH=src python3 -c "
from xiaomei_brain.plugin.registry import PluginRegistry
from xiaomei_brain.plugin.context import PluginContext
from xiaomei_brain.llm.types import ProviderProfile
reg = PluginRegistry()
ctx = PluginContext(config={}, plugin_name='test', agent_id='test', registry=reg)
p = ProviderProfile(provider_id='test', name='Test', base_url='https://api.test.com')
ctx.register_provider(p)
assert reg.get_provider('test') is p
print('OK')
"`
Expected: `OK`

- [ ] **Step 2: Commit**

```bash
git commit --allow-empty -m "feat: verify PluginContext.register_provider accepts ProviderProfile"
```
(如果无代码变更，用 `--allow-empty` 标记验证通过。)

---

### Task 10: 更新 base/config.py — models.providers 构建 ProviderProfile

**Files:**
- Modify: `src/xiaomei_brain/base/config.py:260-295`

- [ ] **Step 1: 更新 from_json() 中 providers 解析逻辑**

在 `base/config.py` 的 `from_json()` 中，`_provider_configs` 的构建方式从存储裸 dict 改为存储 ProviderProfile：

```python
# 旧逻辑（约 L260-295）
providers = models_cfg.get("providers", {})
for name, prov in providers.items():
    ...
    "_provider_configs": provider_configs,

# 新逻辑
from xiaomei_brain.llm.types import ProviderProfile

providers_cfg = models_cfg.get("providers", {})
provider_profiles: dict[str, ProviderProfile] = {}
for name, prov in providers_cfg.items():
    if isinstance(prov, dict):
        provider_profiles[name] = ProviderProfile.from_config(name, prov)

# ...
"_provider_configs": provider_profiles,  # dict[str, ProviderProfile]
```

同时更新 Config 类的类型注解：`_provider_configs: dict[str, ProviderProfile]`

- [ ] **Step 2: 更新 Config 类中引用 _provider_configs 的代码**

找到所有 `self._provider_configs.get(...)` 调用，适配新的 ProviderProfile 类型：

```python
# agent_manager.py L701-707 旧逻辑:
if provider and provider in global_config._provider_configs:
    prov_cfg = global_config._provider_configs[provider]
    api_key = agent.api_key or prov_cfg.get("api_key", "") or global_config.api_key
    base_url = agent.base_url or prov_cfg.get("base_url", "") or global_config.base_url
```

改为从 ProviderProfile 上取：

```python
if provider and provider in global_config._provider_configs:
    prov_profile = global_config._provider_configs[provider]
    api_key = agent.api_key or global_config.api_key
    base_url = agent.base_url or prov_profile.base_url or global_config.base_url
```

- [ ] **Step 3: Commit**

```bash
git add src/xiaomei_brain/base/config.py src/xiaomei_brain/agent/agent_manager.py
git commit -m "feat: build ProviderProfile from config.json models.providers"
```

---

### Task 11: 更新 agent_manager.py 使用新 LLMClient

**Files:**
- Modify: `src/xiaomei_brain/agent/agent_manager.py:709-714`

- [ ] **Step 1: 重写 LLMClient 构造逻辑**

```python
# 旧:
from xiaomei_brain.base.llm import LLMClient
llm = LLMClient(model=model, api_key=api_key, base_url=base_url, provider=provider)

# 新:
from xiaomei_brain.llm.client import LLMClient
llm = LLMClient(
    provider=provider,
    model=model,
    registry=agent._registry,  # 需要 agent 持有 registry
)
```

需要确保 `AgentInstance` 持有 `PluginRegistry`。在 `build_agent()` 中传递：

```python
agent._registry = registry  # 启动时注入
```

- [ ] **Step 2: 更新 agent/core.py import**

```python
# 旧:
from xiaomei_brain.base.llm import LLMClient

# 新:
from xiaomei_brain.llm.client import LLMClient  # (Agent 不再直接 import LLMClient)
```

实际上 `Agent.__init__` 接收的是 LLMClient 实例，不直接 import。只需确保传递给 Agent 的 LLMClient 实例的来源正确。

- [ ] **Step 3: 处理 ChatResponse → NormalizedResponse 的类型适配**

`core.py` 大量使用 `response.content`, `response.tool_calls`, `response.reasoning_content`, `response.finish_reason`。

对比新旧类型：
| 旧 ChatResponse | 新 NormalizedResponse |
|---|---|
| `.content: str \| None` | `.content: str \| None` |
| `.tool_calls: list[ToolCall]` (arguments是dict) | `.tool_calls: list[ToolCall]` (arguments是str) |
| `.reasoning_content` | `.reasoning` |
| `.finish_reason` | `.finish_reason` |
| `.has_tool_calls` (property) | 无 |

关键差异：旧的 `ToolCall.arguments` 是 `dict[str, Any]`，新的 `ToolCall.arguments` 是 `str`（JSON 字符串）。

需要适配 `core.py:266-273`:
```python
# 旧（arguments 已经是 dict，直接存）:
tool_calls_data = [
    {
        "id": tc.id,
        "type": "function",
        "function": {
            "name": tc.name,
            "arguments": json.dumps(tc.arguments),  # dict → JSON string
        },
    }
    for tc in response.tool_calls
]

# 新（arguments 已经是 JSON string）:
tool_calls_data = [
    {
        "id": tc.id,
        "type": "function",
        "function": {
            "name": tc.name,
            "arguments": tc.arguments,  # 已经是 JSON string
        },
    }
    for tc in response.tool_calls
]
```

以及 `core.py:299-301`:
```python
# 旧:
idx = self.tool_call_buffer.add(tc.name, tc.arguments, "")  # arguments 是 dict

# 新:
import json as _json
idx = self.tool_call_buffer.add(tc.name, _json.loads(tc.arguments), "")  # 需要 parse
```

**决策**：为减少对 core.py 的改动面，在 `NormalizedResponse.tool_calls` 中保持 `arguments` 为 `str`（JSON 字符串），然后在消费处 parse。这符合 spec 定义。

- [ ] **Step 4: 适配 `reasoning_content` → `reasoning`**

`core.py:280-281`:
```python
# 旧:
if response.reasoning_content:
    msg["reasoning_content"] = response.reasoning_content

# 新:
if response.reasoning:
    msg["reasoning_content"] = response.reasoning
```

对 `core.py` 做全局替换：`response.reasoning_content` → `response.reasoning`

- [ ] **Step 5: Commit**

```bash
git add src/xiaomei_brain/agent/agent_manager.py src/xiaomei_brain/agent/core.py
git commit -m "feat: migrate agent to new LLMClient — ChatResponse → NormalizedResponse"
```

---

### Task 12: 更新 extractor.py — 适配新 LLMClient

**Files:**
- Modify: `src/xiaomei_brain/memory/extractor.py`

注：`context_assembler.py` 已在源码树中不存在（仅剩 `__pycache__`），无需迁移。

- [ ] **Step 1: 确认 extractor.py 的 LLM 使用方式**

`MemoryExtractor.__init__` 接收 `llm_client: Any = None` 并赋值给 `self.llm`（L44-53）。
所有 LLM 调用都是 `self.llm.chat(messages=[...], tools=None, log_level=logging.DEBUG)`（L74, L115, L160, L210, L925）。

`chat()` 返回旧 `ChatResponse`，通过 `.content` 取文本。

- [ ] **Step 2: 无需代码修改**

`MemoryExtractor` 不 import LLMClient，只接收实例。新旧 `chat()` 返回的 `.content` 字段相同（都是 `str | None`）。
**此行无需修改。** 只要传递给 MemoryExtractor 的 LLMClient 实例是新的 `llm.client.LLMClient` 即可。

- [ ] **Step 3: 验证 extractor.py 无 import 问题**

Run: `PYTHONPATH=src python3 -c "from xiaomei_brain.memory.extractor import MemoryExtractor; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git commit --allow-empty -m "feat: verify extractor.py compatible with new LLMClient — no changes needed"
```

---

### Task 13: 删除 base/llm.py，更新剩余引用

**Files:**
- Delete: `src/xiaomei_brain/base/llm.py`

- [ ] **Step 1: 全局搜索 base.llm 残留引用**

Run: `grep -rn "from xiaomei_brain.base.llm import\|from xiaomei_brain.base import llm" src/`

- [ ] **Step 2: 更新所有残留引用**

逐一更新为 `from xiaomei_brain.llm.client import LLMClient, LLMError, FatalLLMError`

- [ ] **Step 3: 删除文件**

```bash
rm src/xiaomei_brain/base/llm.py
```

- [ ] **Step 4: 运行 import 检查**

Run: `PYTHONPATH=src python3 -c "from xiaomei_brain.llm.client import LLMClient, LLMError, FatalLLMError; print('OK')"`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git rm src/xiaomei_brain/base/llm.py
git add <其他修改的文件>
git commit -m "feat: remove old base/llm.py — migrated to llm/client.py"
```

---

### Task 14: 集成测试 — boot_plugins 完整链路

**Files:**
- Create: `tests/test_llm_adapter_integration.py`

- [ ] **Step 1: 写集成测试**

```python
"""集成测试：PluginLoader 发现 → ProviderProfile 注册 → LLMClient 构造。"""

import os
import tempfile
from pathlib import Path

import pytest


def test_provider_plugin_discovery_and_registration():
    """验证 boot_plugins 能发现 llm/providers/ 下的 provider 插件。"""
    from xiaomei_brain.plugin.bootstrap import boot_plugins

    # boot_plugins 需要 env vars (requires_env)，先临时设置
    os.environ["DEEPSEEK_API_KEY"] = "test-key"
    os.environ["ZHIPU_API_KEY"] = "test-key"
    os.environ["OPENAI_API_KEY"] = "test-key"

    try:
        registry = boot_plugins(agent_id="test")

        # 检查 provider 是否注册
        deepseek = registry.get_provider("deepseek")
        assert deepseek is not None, "deepseek provider not found"
        assert deepseek.provider_id == "deepseek"
        assert deepseek.base_url == "https://api.deepseek.com/v1"

        zhipu = registry.get_provider("zhipu")
        assert zhipu is not None, "zhipu provider not found"
        assert zhipu.base_url == "https://open.bigmodel.cn/api/paas/v4"

        openai_p = registry.get_provider("openai")
        assert openai_p is not None, "openai provider not found"
        assert openai_p.base_url == "https://api.openai.com/v1"

    finally:
        for k in ["DEEPSEEK_API_KEY", "ZHIPU_API_KEY", "OPENAI_API_KEY"]:
            os.environ.pop(k, None)


def test_llm_client_from_registry():
    """验证 LLMClient 能从 registry 正常构造。"""
    from xiaomei_brain.llm.client import LLMClient
    from xiaomei_brain.plugin.registry import PluginRegistry
    from xiaomei_brain.plugin.context import PluginContext
    from xiaomei_brain.llm.providers.deepseek.adapter import register

    reg = PluginRegistry()
    ctx = PluginContext(config={}, plugin_name="deepseek", agent_id="test", registry=reg)
    register(ctx)

    os.environ["DEEPSEEK_API_KEY"] = "test-key"
    try:
        client = LLMClient(provider="deepseek", model="deepseek-v4-flash", registry=reg)
        assert client.provider == "deepseek"
        assert client.model == "deepseek-v4-flash"
    finally:
        os.environ.pop("DEEPSEEK_API_KEY", None)


def test_provider_from_config_merge():
    """验证 config.json provider 合并逻辑。"""
    from xiaomei_brain.llm.types import ProviderProfile, ModelDefinition, load_config_providers
    from xiaomei_brain.plugin.registry import PluginRegistry

    reg = PluginRegistry()

    # 模拟插件先注册
    from xiaomei_brain.llm.providers.deepseek.adapter import DeepSeekProfile
    reg.register_provider("deepseek", DeepSeekProfile)

    # 模拟 config.json 覆盖 base_url
    config = {
        "models": {
            "providers": {
                "deepseek": {
                    "baseUrl": "https://my-proxy.example.com/v1",
                }
            }
        }
    }
    load_config_providers(reg, config)

    p = reg.get_provider("deepseek")
    assert p.base_url == "https://my-proxy.example.com/v1"  # config 覆盖
    # models 应保留（config 未设置 models）
    assert p.resolve_model("deepseek-v4-flash") is not None


def test_normalized_response_and_tool_call():
    """验证 NormalizedResponse 和 ToolCall 数据结构。"""
    from xiaomei_brain.llm.types import NormalizedResponse, ToolCall

    tc = ToolCall(id="1", name="test_tool", arguments='{"key": "value"}')
    resp = NormalizedResponse(
        content="Hello",
        tool_calls=[tc],
        finish_reason="stop",
    )
    assert resp.content == "Hello"
    assert len(resp.tool_calls) == 1
    assert resp.tool_calls[0].name == "test_tool"


def test_model_definition_per_model_capabilities():
    """验证 per-model 能力字段覆盖逻辑。"""
    from xiaomei_brain.llm.types import ModelDefinition

    m = ModelDefinition(id="test", name="Test", context_window=4096, max_tokens=1024,
                        supports_vision=True, supports_tools=False)
    assert m.supports_vision is True
    assert m.supports_tools is False
    assert m.supports_developer_role is None  # 未设置 → 沿用 transport 默认
```

- [ ] **Step 2: 运行测试**

Run: `PYTHONPATH=src python3 -m pytest tests/test_llm_adapter_integration.py -v --no-header -q`
Expected: 5 passed

- [ ] **Step 3: Commit**

```bash
git add tests/test_llm_adapter_integration.py
git commit -m "test: add llm adapter integration tests"
```

---

### Task 15: 端到端验证

- [ ] **Step 1: 运行所有现有测试确保无回归**

Run: `PYTHONPATH=src python3 -m pytest tests/ -x --no-header -q 2>&1 | tail -20`

- [ ] **Step 2: 验证 import 链完整**

Run: `PYTHONPATH=src python3 -c "
from xiaomei_brain.plugin import boot_plugins
from xiaomei_brain.llm import LLMClient
from xiaomei_brain.llm.types import ProviderProfile, ModelDefinition, ModelApi, NormalizedResponse, ToolCall
from xiaomei_brain.llm.transport import Transport, get_transport, register_transport
from xiaomei_brain.llm.transport.chat_completions import ChatCompletionsTransport
print('All imports OK')
"`
Expected: `All imports OK`

- [ ] **Step 3: Commit**

```bash
git commit --allow-empty -m "feat: end-to-end import validation — llm adapter module fully wired"
```
