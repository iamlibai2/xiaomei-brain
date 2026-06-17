# LLM 适配层重构设计

> 日期：2026-06-18
> 参考：OpenClaw multi-provider architecture

## 1. 目标

将 LLM 适配层从单格式硬编码重构为多 provider 通用架构。用户可通过 config.json 配置任意 OpenAI-compatible / Anthropic / Google 等 provider，无需修改代码。

## 2. 模块结构

```
src/xiaomei_brain/llm/
├── types.py              # 类型定义（ModelApi / ProviderConfig / ModelCompat / ModelDefinition）
├── providers.py          # Provider 解析与注册（从 config.json 发现）
├── compat.py             # 模型能力归一化（compat 字段默认值/校验）
├── client.py             # 运行时客户端（chat / chat_stream / 重试 / 退避）
├── stream_adapters.py    # 8 种 API 的流式适配器
└── __init__.py           # 对外暴露 LLMClient + 构建函数
```

### 2.1 `types.py` — 数据结构

**`ModelApi` 枚举** — 8 种 API 接口：

```
openai-completions      # 标准 Chat Completions API（覆盖率 90%+）
openai-responses        # OpenAI Responses API（新版）
openai-codex-responses  # OpenAI Codex
anthropic-messages      # Anthropic Messages API
google-generative-ai    # Google Gemini / Generative AI
bedrock-converse-stream # AWS Bedrock Converse
ollama                  # Ollama（本地）
github-copilot          # GitHub Copilot
```

**`ModelCompatConfig`** — Provider 能力差异：

| 字段 | 类型 | 说明 |
|------|------|------|
| `supports_developer_role` | bool | 是否支持 developer 消息角色 |
| `supports_reasoning_effort` | bool | 是否支持 reasoning_effort 参数 |
| `supports_usage_in_streaming` | bool | 流式响应是否包含 usage |
| `supports_strict_mode` | bool | 工具调用 strict 模式 |
| `supports_tools` | bool | 是否支持 tools |
| `supports_store` | bool | 是否支持服务端存储 |
| `max_tokens_field` | str | 字段名（max_tokens / max_completion_tokens） |
| `thinking_format` | str\|None | 思考标签格式（openrouter / qwen-chat-template） |
| `requires_tool_result_name` | bool | 工具结果是否需要 name |
| `requires_assistant_after_tool_result` | bool | tool result 后是否需要 assistant 消息 |
| `requires_thinking_as_text` | bool | 是否将 thinking 渲染为 text |
| `requires_mistral_tool_ids` | bool | 是否需要 Mistral 格式 tool IDs |

**`ModelDefinition`** — 模型定义：

```python
@dataclass
class ModelDefinition:
    id: str                          # 模型 ID
    name: str                        # 展示名
    api: ModelApi                    # 使用哪种 API 接口
    context_window: int              # 上下文窗口
    max_tokens: int                  # 最大输出 token
    reasoning: bool = False          # 是否支持推理
    input_modes: list[str]           # ["text"] / ["text", "image"]
    cost: dict                       # {input, output, cache_read, cache_write}
    compat: ModelCompatConfig        # 兼容性配置
```

**`ProviderConfig`** — Provider 配置：

```python
@dataclass
class ProviderConfig:
    name: str                        # provider 名称
    base_url: str                    # API 端点
    api: ModelApi                    # 默认 API 类型
    api_key: str = ""                # API 密钥
    headers: dict                    # 自定义请求头
    models: list[ModelDefinition]    # 模型列表
```

### 2.2 `providers.py` — Provider 注册表

**`ProviderRegistry`** 类：

- `from_config(config_path)` — 从 `~/.xiaomei-brain/config.json` 的 `models.providers` 解析所有 provider
- `resolve(provider, model_id)` — 根据 `provider/model_id` 查找 `(ProviderConfig, ModelDefinition)`
- `list_providers()` / `list_models(provider)` — 列出可用 provider / 模型

**API key 解析优先级**：config 显式值 > 环境变量（如 `$DEEPSEEK_API_KEY`）

**baseURL 归一化**：去掉尾部 `/v1`、`/v1/` 等后缀

### 2.3 `compat.py` — 兼容性归一化

`normalize_compat(api, base_url, model_def)` — 根据 API 类型和 baseURL 自动设置 compat 默认值。

核心规则：
- 原生 OpenAI（`api.openai.com`）→ 全部能力默认开
- 非原生 `openai-completions` 端点 → `supports_developer_role`、`supports_usage_in_streaming`、`supports_strict_mode` 默认 `False`
- `anthropic-messages` → thinking 处理、tool schema 模式自动设置
- `google-generative-ai` → Gemini 特有的 thought signature 清理

### 2.4 `client.py` — 运行时客户端

`LLMClient` 重构要点：

- 构造函数接收 `provider` 字符串（如 `"deepseek"`），内部查 ProviderRegistry
- `chat(messages, tools)` — 非流式，保留现有重试/退避逻辑，按 ModelApi 分发
- `chat_stream(messages, tools)` — 流式，按 ModelApi 分发到对应 adapter
- 保留：`FatalLLMError`（致命错误）、`LLMError`（可恢复）、退避/重试/fallback
- 保留：JSONL 日志、token 估算、Interoception 回调

### 2.5 `stream_adapters.py` — API 适配器

每个 `ModelApi` 一个流式处理函数：

| Adapter | API | 流格式 | 实现优先级 |
|---------|-----|--------|-----------|
| `_stream_openai_completions` | openai-completions | SSE `data: {...}` | P0 — 现有逻辑迁移 |
| `_stream_anthropic_messages` | anthropic-messages | SSE `event: content_block_delta` | P1 |
| `_stream_google_generative_ai` | google-generative-ai | JSONL | P1 |
| 其余 5 种 | — | — | P2 — stubbed |

统一接口：
- 输入：`(url, headers, payload, compat)`
- 输出：`Generator[str, None, None]`（逐 chunk yield）
- 结束后返回 `ChatResponse`（content + tool_calls + finish_reason）

### 2.6 `__init__.py` — 对外接口

```python
from xiaomei_brain.llm.client import LLMClient
from xiaomei_brain.llm.types import ModelApi, ProviderConfig, ModelDefinition, ModelCompatConfig
from xiaomei_brain.llm.providers import ProviderRegistry
```

## 3. 与现有代码的关系

| 现有文件 | 处理方式 |
|----------|----------|
| `src/xiaomei_brain/base/llm.py` | 移入 `src/xiaomei_brain/llm/` 并拆分重构 |
| `src/xiaomei_brain/base/config.py` | `from_json()` 解析 `models.providers` 逻辑移交 ProviderRegistry |
| `src/xiaomei_brain/agent/agent_manager.py` | `_DEFAULT_CONFIG_TEMPLATE` 格式不变 |
| 其他调用方 | 只改 import 路径，`LLMClient` 公开 API 保持兼容 |

## 4. LLMClient 公开 API（向后兼容）

```python
# 构造
client = LLMClient(provider="deepseek", model="deepseek-v4-flash")
# 或
client = LLMClient.from_config(model_id="deepseek/deepseek-v4-flash")

# 对话（同现有 API）
response = client.chat(messages=[...], tools=[...])      # ChatResponse
for chunk in client.chat_stream(messages=[...], tools=[...]):   # Generator
    ...

# 切换模型/Provider
client.set_model("glm-5.1")                              # 切换模型
client.set_provider("zhipu", model="glm-5.1")            # 切换 provider

# fallback（保留现有机制）
client.add_fallback("volcengine/doubao-pro-32k")
client.switch_to_fallback()
```

## 5. 不在 scope

- Embedding 适配（继续使用现有 BAAI/bge-m3）
- TTS 适配（继续使用现有 MiniMax）
- Admin REST API 变更
- 向后不兼容的 config.json 格式变更

## 6. 测试策略

- **单元测试**：compat 归一化逻辑、ProviderRegistry 解析、stream adapter 数据转换
- **集成测试**：mock HTTP 响应，验证 chat/chat_stream 完整链路
- **配置测试**：从真实 config.json 加载所有 provider，验证解析不崩溃
