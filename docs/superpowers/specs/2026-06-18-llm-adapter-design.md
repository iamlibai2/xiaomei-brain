# LLM 适配层重构设计

> 日期：2026-06-18
> 参考：OpenClaw multi-provider architecture
> 复用：现有 plugin 框架（`src/xiaomei_brain/plugin/`）

## 1. 目标

将 LLM 适配层从单格式硬编码重构为基于插件体系的多 provider 通用架构。用户可通过创建 provider 插件（内置或第三方）支持任意 OpenAI-compatible / Anthropic / Google 等 API，无需修改核心代码。

## 2. 架构

### 2.1 与现有插件系统的关系

项目已有完整的 plugin 框架，provider 全部纳入其中：

```
plugin 框架（现有）
├── manifest.py     # PluginManifest（kind=provider 是合法类型）
├── context.py      # PluginContext.register_provider(provider)
├── loader.py       # PluginLoader 3阶段: 发现 → 校验 → 加载
├── registry.py     # PluginRegistry._providers 字典已就绪
├── bootstrap.py    # boot_plugins() 自动发现所有插件
└── ...

llm/ 模块（新增）
├── types.py              # ModelApi / ModelDefinition / ModelCompatConfig
├── provider_base.py      # ProviderPlugin ABC
├── compat.py             # normalize_compat()
├── client.py             # LLMClient（从 PluginRegistry 拿 provider）
├── stream_adapters.py    # 8 种 API 流式适配器
├── __init__.py
└── providers/            # 内置 provider 插件
    ├── deepseek/
    │   ├── plugin.yaml   # kind: provider
    │   └── adapter.py    # register(ctx) → ctx.register_provider(...)
    ├── zhipu/
    │   ├── plugin.yaml
    │   └── adapter.py
    ├── volcengine/
    │   ├── plugin.yaml
    │   └── adapter.py
    ├── openai/
    │   ├── plugin.yaml
    │   └── adapter.py
    └── ...               # 按需添加更多
```

### 2.2 PluginLoader 发现 provider 的路径

```
PluginLoader.boot()
  ├── src/xiaomei_brain/llm/providers/     ← 内置 provider（新目录）
  ├── src/xiaomei_brain/channels/          ← 现有 channel 插件
  ├── ~/.xiaomei-brain/plugins/            ← 用户/第三方 provider
  └── entry_points                         ← pip 包
```

Loader 的发现目录列表扩展为 3 项（原为 2 项）：channels、llm/providers、用户 plugins。

### 2.3 完整数据流

```
启动时：
  boot_plugins(agent_id)
    → 扫描 llm/providers/*/plugin.yaml
    → 校验 kind=provider, requires_env
    → 调用 adapter.register(ctx)
    → ctx.register_provider(provider_instance)
    → PluginRegistry._providers["deepseek"] = provider_instance

运行时：
  LLMClient(provider="deepseek", model="deepseek-v4-flash", registry=...)
    → registry.get_provider("deepseek")
    → provider.resolve_model("deepseek-v4-flash")  → ModelDefinition
    → normalize_compat(api, base_url, model_def)   → ModelCompatConfig
    → 构建 endpoint + headers
    → chat/chat_stream → 按 api 分发到 stream_adapter
```

## 3. 模块设计

### 3.1 `types.py` — 数据结构

**`ModelApi` 枚举** — 8 种 API 接口（与 OpenClaw 一致）：

| 值 | 覆盖 |
|------|------|
| `openai-completions` | OpenAI / DeepSeek / MiniMax / 智谱 / 火山 / 等 90%+ 的 provider |
| `openai-responses` | OpenAI Responses API（新版）|
| `openai-codex-responses` | OpenAI Codex |
| `anthropic-messages` | Anthropic / AWS Bedrock / GCP Vertex |
| `google-generative-ai` | Google Gemini |
| `bedrock-converse-stream` | AWS Bedrock Converse |
| `ollama` | Ollama 本地模型 |
| `github-copilot` | GitHub Copilot |

**`ModelCompatConfig`** — Provider 能力差异：

```python
@dataclass
class ModelCompatConfig:
    supports_developer_role: bool = True
    supports_reasoning_effort: bool = False
    supports_usage_in_streaming: bool = True
    supports_strict_mode: bool = True
    supports_tools: bool = True
    supports_store: bool = False
    max_tokens_field: str = "max_tokens"
    thinking_format: str | None = None        # "openrouter" / "qwen-chat-template"
    requires_tool_result_name: bool = False
    requires_assistant_after_tool_result: bool = False
    requires_thinking_as_text: bool = False
    requires_mistral_tool_ids: bool = False
    tool_schema_profile: str | None = None    # "xai"
    tool_call_arguments_encoding: str | None = None  # "html-entities"
```

**`ModelDefinition`** — 一条模型定义：

```python
@dataclass
class ModelDefinition:
    id: str                          # "deepseek-v4-flash"
    name: str                        # "DeepSeek V4 Flash"
    api: ModelApi                    # 使用的 API 接口
    context_window: int              # 128000
    max_tokens: int                  # 8192
    reasoning: bool = False          # 推理能力
    input_modes: list[str] = field(default_factory=lambda: ["text"])
    cost: dict = field(default_factory=dict)  # {input, output, cache_read, cache_write}
    compat: ModelCompatConfig | None = None   # None 则由 compat.py 自动归一化
```

### 3.2 `provider_base.py` — ProviderPlugin ABC

```python
class ProviderPlugin(ABC):
    """每个 provider 插件必须实现此接口。

    最小实现只需 4 个类属性 + 1 个类方法。
    非标准 provider 可 override 更多方法。
    """

    # ── 必须设置 ──
    provider_id: str          # "deepseek"（注册 key）
    name: str                 # "DeepSeek"（展示名）
    api: ModelApi             # 默认 API 接口
    base_url: str             # API 端点

    # ── 必须实现 ──
    @classmethod
    def models(cls) -> list[ModelDefinition]: ...

    # ── 可选 override ──
    @classmethod
    def env_key(cls) -> str | None: ...           # "DEEPSEEK_API_KEY"
    @classmethod
    def compat_overrides(cls, model_id: str) -> dict | None: ...
    @classmethod
    def headers(cls) -> dict: ...
    @classmethod
    def auth_header(cls) -> str: ...              # 默认 "Bearer"
    @classmethod
    def build_payload(cls, messages, tools, stream, compat) -> dict: ...
    @classmethod
    def parse_chunk(cls, line, compat) -> Delta | None: ...
```

### 3.3 `compat.py` — 兼容性归一化

`normalize_compat(api, base_url, model_compat)` — 根据 API 类型和 baseURL 自动设置 compat 默认值。

核心规则（沿用 OpenClaw 经验）：
- 原生 OpenAI（`api.openai.com`）→ 全部能力默认 `True`
- 非原生 `openai-completions` 端点 → `supports_developer_role`、`supports_usage_in_streaming`、`supports_strict_mode` 默认 `False`
- `anthropic-messages` → 自动处理 thinking block / tool schema 互转
- `google-generative-ai` → Gemini thought signature 清理

如果 model 定义的 `compat` 字段不为 None，则用 model 值覆盖归一化后的默认值。

### 3.4 `client.py` — 运行时客户端

`LLMClient` 从 `PluginRegistry` 获取 provider，不再直接读 config.json：

```python
class LLMClient:
    def __init__(self, provider: str, model: str, registry: PluginRegistry):
        self._provider = registry.get_provider(provider)
        self._model_def = self._provider.resolve_model(model)
        self._compat = normalize_compat(
            self._provider.api,
            self._provider.base_url,
            self._model_def.compat,
        )
```

- `chat(messages, tools)` — 非流式，保留现有重试/退避逻辑
- `chat_stream(messages, tools)` — 流式，按 `model_def.api` 分发到 stream adapter
- 保留：`FatalLLMError`、`LLMError`、退避/重试/fallback、JSONL 日志、token 估算、Interoception 回调

### 3.5 `stream_adapters.py` — API 适配器

每个 `ModelApi` 一个流式处理函数：

| Adapter | API | 流格式 | 优先级 |
|---------|-----|--------|--------|
| `_stream_openai_completions` | openai-completions | SSE `data: {...}` | P0 |
| `_stream_anthropic_messages` | anthropic-messages | SSE `event: content_block_delta` | P1 |
| `_stream_google_generative_ai` | google-generative-ai | JSONL | P1 |
| `_stream_bedrock_converse` | bedrock-converse-stream | AWS SSE | P2 |
| 其余 4 种 | — | — | P2 stubbed |

统一签名：`(provider, model_def, compat, url, headers, payload) → Generator[str] + ChatResponse`

### 3.6 Provider 插件示例

**`llm/providers/deepseek/plugin.yaml`**：

```yaml
name: deepseek
version: "1.0.0"
description: DeepSeek LLM provider
kind: provider
requires_env: []
```

**`llm/providers/deepseek/adapter.py`**：

```python
from xiaomei_brain.llm.provider_base import ProviderPlugin
from xiaomei_brain.llm.types import ModelApi, ModelDefinition

class DeepSeekProvider(ProviderPlugin):
    provider_id = "deepseek"
    name = "DeepSeek"
    api = ModelApi.OPENAI_COMPLETIONS
    base_url = "https://api.deepseek.com/v1"

    @classmethod
    def env_key(cls) -> str:
        return "DEEPSEEK_API_KEY"

    @classmethod
    def models(cls) -> list[ModelDefinition]:
        return [
            ModelDefinition(
                id="deepseek-v4-flash",
                name="DeepSeek V4 Flash",
                context_window=128000,
                max_tokens=8192,
                reasoning=True,
            ),
            ModelDefinition(
                id="deepseek-v4-pro",
                name="DeepSeek V4 Pro",
                context_window=128000,
                max_tokens=8192,
                reasoning=True,
            ),
        ]

def register(ctx):
    ctx.register_provider(DeepSeekProvider)
```

## 4. 与现有代码的关系

| 现有文件 | 处理方式 |
|----------|----------|
| `src/xiaomei_brain/base/llm.py` | 移入 `src/xiaomei_brain/llm/client.py`，核心逻辑保留 |
| `src/xiaomei_brain/base/config.py` | `from_json()` 中 `models.providers` 解析逻辑改为构建 provider 插件 |
| `src/xiaomei_brain/plugin/loader.py` | 发现目录列表新增 `llm/providers/` |
| `src/xiaomei_brain/agent/agent_manager.py` | `_DEFAULT_CONFIG_TEMPLATE` 格式不变 |
| `src/xiaomei_brain/consciousness/conscious_living.py` | `boot_plugins()` 保持不变，自动包含 provider |
| 其他调用方 | 只改 import 路径 |

## 5. LLMClient 公开 API（向后兼容）

```python
from xiaomei_brain.llm import LLMClient

# 构造
client = LLMClient(
    provider="deepseek",
    model="deepseek-v4-flash",
    registry=registry,       # 从 boot_plugins() 返回的 PluginRegistry
)

# 对话（同现有 API）
response = client.chat(messages=[...], tools=[...])
for chunk in client.chat_stream(messages=[...], tools=[...]):
    ...

# 切换模型/Provider
client.set_model("glm-5.1")
client.set_provider("zhipu", model="glm-5.1")

# fallback
client.add_fallback("volcengine/doubao-pro-32k")
client.switch_to_fallback()
```

## 6. 配置覆盖与合并

插件提供"出厂默认值"（baseUrl、model 目录），`config.json` 的 `models.providers` 可覆盖或追加：

```
ProviderPlugin.base_url = "https://api.deepseek.com/v1"    ← 插件默认
  ↳ config.json models.providers.deepseek.baseUrl = "..."  ← 用户覆盖（优先）

ProviderPlugin.models() = [deepseek-v4-flash, ...]         ← 插件默认
  ↳ config.json models.providers.deepseek.models = [...]    ← 用户追加/覆盖
```

合并规则：
- `baseUrl`：config.json 值优先，否则用插件默认
- `apiKey`：config.json 值优先，否则用插件 `env_key()` 对应的环境变量
- `models`：config.json 的 models 列表与插件 models 合并，config.json 中相同 id 的字段覆盖插件默认

**config.json only provider**（无对应插件目录）：如果 `models.providers` 里有、但没有对应插件目录，系统自动从 config.json 构建一个通用 provider（`api` 默认为 `openai-completions`）。

## 8. 第三方 Provider 插件

用户或第三方可创建自己的 provider 插件：

```
# 方式 1：放入 ~/.xiaomei-brain/plugins/
~/.xiaomei-brain/plugins/my_internal_llm/
├── plugin.yaml           # kind: provider
└── adapter.py            # class MyLLMProvider(ProviderPlugin): ...

# 方式 2：pip 包 entry point
# pyproject.toml:
#   [project.entry-points."xiaomei_brain.plugins"]
#   my_provider = "my_package.my_provider.adapter"
```

插件加载时自动通过现有 pipeline 发现、校验、注册到 `PluginRegistry`，`LLMClient` 即可使用。

## 9. 不在 scope

- Embedding 适配（继续使用现有 BAAI/bge-m3）
- TTS 适配（继续使用现有 MiniMax）

## 10. 测试策略

- **unit**：compat 归一化、PluginLoader 发现 provider 插件、stream adapter 转换
- **integration**：mock HTTP 响应验证 chat/chat_stream 完整链路
- **plugin test**：创建临时 provider 插件目录，验证 `boot_plugins()` 自动发现并注册
