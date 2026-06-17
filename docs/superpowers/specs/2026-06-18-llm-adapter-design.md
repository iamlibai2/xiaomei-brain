# LLM 适配层重构设计

> 日期：2026-06-18
> 参考：OpenClaw multi-provider architecture（8 ModelApi、compat 归一化、配置格式）
> 参考：Hermes Agent provider 架构（ProviderProfile 数据类、Transport 策略、Profile-first）
> 复用：现有 plugin 框架（`src/xiaomei_brain/plugin/`）

## 1. 目标

将 LLM 适配层从单格式硬编码重构为基于插件体系的多 provider 通用架构。用户可通过创建 provider 插件（内置或第三方）支持任意 OpenAI-compatible / Anthropic / Bedrock 等 API，无需修改核心代码。

## 2. 架构概览

```
                 config.json                    PluginLoader
                 (models.providers)             (现有)
                      │                            │
                      ▼                            ▼
              ProviderProfile.build()    →   PluginRegistry._providers
              (配置 + 插件合并)                  │
                                                 ▼
                                         LLMClient(provider, model)
                                              │
                                         Transport dispatch
                                    ┌────────┼────────┐
                                    ▼        ▼        ▼
                            chat_     anthropic  bedrock
                         completions  _messages  _converse
                            (P0)       (P1)      (P2)
                                    │
                                    ▼
                            NormalizedResponse
                            (统一输出类型)
```

### 2.1 核心设计原则（借鉴 Hermes）

- **ProviderProfile 数据类**：一个 `ProviderProfile` 表达一个 provider 的全部信息。90% 的 provider 直接实例化，不写子类
- **Hook 方法**：需要自定义行为（thinking 格式、message 预处理）的 provider 才子类化，只 override 1-2 个 hook
- **Transport 策略模式**：每类 wire 协议一个 Transport，由 provider 的 `api_mode` 字段选择
- **Profile-first, config-fallback**：有 profile → 走 profile；config.json 纯文本 → 自动构建通用 profile

### 2.2 模块结构

```
llm/ 模块（新增）
├── types.py              # ModelApi / ProviderProfile / ModelDefinition / NormalizedResponse
├── transport/            # Wire 协议实现（策略模式）
│   ├── __init__.py       # TransportRegistry: api_mode → Transport 类
│   ├── base.py           # Transport ABC
│   ├── chat_completions.py     # OpenAI-compatible（覆盖 90%+ provider）
│   ├── anthropic_messages.py   # Anthropic Messages API
│   └── bedrock_converse.py     # AWS Bedrock Converse
├── client.py             # LLMClient（从 PluginRegistry 拿 provider，分发到 transport）
├── __init__.py
└── providers/            # 内置 provider 插件
    ├── deepseek/
    │   ├── plugin.yaml   # kind: provider
    │   └── adapter.py    # register(ctx) → ctx.register_provider(...)
    ├── zhipu/
    ├── volcengine/
    ├── openai/
    └── ...               # 按需添加
```

## 3. 模块设计

### 3.1 `types.py` — 数据结构

#### ModelApi 枚举

与 OpenClaw 一致，定义 6 种 API 接口：

| 值 | Transport | 覆盖 |
|------|-----------|------|
| `chat-completions` | ChatCompletionsTransport | OpenAI / DeepSeek / MiniMax / 智谱 / 火山 / Ollama / Gemini(兼容) / 90%+ |
| `anthropic-messages` | AnthropicTransport | Anthropic / Claude API |
| `bedrock-converse` | BedrockConverseTransport | AWS Bedrock |
| `openai-responses` | *stub P2* | OpenAI Responses API（新版） |
| `openai-codex-responses` | *stub P2* | OpenAI Codex |
| `github-copilot` | *stub P2* | GitHub Copilot |

> Hermes 经验：Google Gemini 的 OpenAI 兼容端点也走 `chat-completions`，Ollama 同理。不需要为它们单独写 transport。

#### ProviderProfile — Provider 核心抽象

```python
@dataclass
class ProviderProfile:
    """一个 LLM provider 的完整描述。

    简单 provider（OpenAI 兼容）直接实例化此类。
    需要特殊处理的 provider 才子类化并 override hook 方法。
    """

    # ── 必填字段 ──
    provider_id: str              # "deepseek"（注册 key）
    name: str                     # "DeepSeek"（展示名）
    api_mode: str = "chat-completions"  # 选择 transport
    base_url: str = ""            # API 端点

    # ── 可选字段 ──
    aliases: tuple[str, ...] = ()  # ("deepseek-compat",)
    display_name: str = ""
    description: str = ""
    env_vars: tuple[str, ...] = ()  # ("DEEPSEEK_API_KEY",)
    auth_type: str = "api-key"      # api-key | aws-sdk | oauth
    default_headers: dict = field(default_factory=dict)
    supports_health_check: bool = True
    supports_vision: bool = False
    default_max_tokens: int | None = None
    default_aux_model: str = ""     # 轻量备用模型

    # ── 模型目录 ──
    models: list[ModelDefinition] = field(default_factory=list)

    # ══ Hook 方法（子类按需 override）══

    def get_headers(self, api_key: str) -> dict[str, str]:
        """构建请求头。默认 Bearer token。"""
        return {"Authorization": f"Bearer {api_key}"}

    def prepare_messages(self, messages: list[dict]) -> list[dict]:
        """预处理消息列表。默认直接返回。"""
        return messages

    def build_extra_body(self, *, stream: bool, **context) -> dict:
        """额外请求体字段。如 DeepSeek: {"thinking": {"type": "enabled"}}"""
        return {}

    def build_api_kwargs_extras(self, **context) -> dict[str, Any]:
        """顶层 API 参数。如 DeepSeek: {"reasoning_effort": "medium"}"""
        return {}

    def get_max_tokens(self, model: ModelDefinition) -> int | None:
        """返回此模型的最大 token 数。"""
        return model.max_tokens

    def resolve_model(self, model_id: str) -> ModelDefinition | None:
        """从 models 列表中查找模型。"""
        for m in self.models:
            if m.id == model_id:
                return m
        return None

    @classmethod
    def from_config(cls, provider_id: str, config: dict) -> ProviderProfile:
        """从 config.json 的 models.providers.<id> 构建。"""
        ...
```

#### ModelDefinition — 模型定义

```python
@dataclass
class ModelDefinition:
    id: str                    # "deepseek-v4-flash"
    name: str                  # "DeepSeek V4 Flash"
    context_window: int        # 128000
    max_tokens: int            # 8192
    reasoning: bool = False    # 推理能力
    input_modes: list[str] = field(default_factory=lambda: ["text"])
    cost: dict = field(default_factory=dict)
```

> 注：`ModelCompatConfig` 不再作为独立结构。provider 差异通过 `ProviderProfile` 的 hook 方法处理（profile-first），不需要额外的 compat 字段层。config.json only provider（无插件）构建的通用 profile 行为由 `chat_completions` transport 的默认处理覆盖。

#### NormalizedResponse — 统一输出

```python
@dataclass
class NormalizedResponse:
    """所有 transport 输出的统一响应类型。"""
    content: str | None
    tool_calls: list[ToolCall] | None
    finish_reason: str          # "stop" | "tool_calls" | "length" | "content_filter"
    reasoning: str | None       # 推理内容（DeepSeek/GLM 的 thinking）
    usage: dict | None          # {input_tokens, output_tokens}
    provider_data: dict | None  # 协议特定数据（Anthropic content_blocks 等）

@dataclass
class ToolCall:
    id: str | None
    name: str
    arguments: str              # JSON 字符串
    provider_data: dict | None  # extra_content, call_id 等
```

### 3.2 `transport/` — Wire 协议实现

#### Transport ABC

```python
class Transport(ABC):
    """一种 API 协议的传输实现。"""

    @abstractmethod
    def convert_messages(self, messages: list[dict], profile: ProviderProfile) -> list[dict]: ...

    @abstractmethod
    def convert_tools(self, tools: list[dict], profile: ProviderProfile) -> list[dict]: ...

    @abstractmethod
    def build_kwargs(self, messages: list[dict], tools: list[dict] | None,
                     model: ModelDefinition, profile: ProviderProfile,
                     stream: bool, **context) -> dict: ...

    @abstractmethod
    def normalize_response(self, raw: Any, profile: ProviderProfile) -> NormalizedResponse: ...

    @abstractmethod
    def stream_iter(self, response: requests.Response, profile: ProviderProfile
                    ) -> Generator[tuple[str, dict | None], None, None]: ...
```

#### TransportRegistry

```python
# transport/__init__.py
_transports: dict[str, type[Transport]] = {}

def register_transport(api_mode: str, transport_cls: type[Transport]) -> None: ...
def get_transport(api_mode: str) -> Transport: ...
```

#### 实现优先级

| Transport | 文件 | 流格式 | 优先级 |
|-----------|------|--------|--------|
| `ChatCompletionsTransport` | `chat_completions.py` | SSE `data: {...}` | P0 — 现有逻辑迁移 |
| `AnthropicTransport` | `anthropic_messages.py` | SSE `event: content_block_delta` | P1 |
| `BedrockConverseTransport` | `bedrock_converse.py` | AWS JSONL stream | P2 |

**ChatCompletionsTransport 的关键行为**（来自 Hermes 经验）：

- **消息清理**：剥离内部字段（`tool_name`、`_`-prefixed），输出纯净 OpenAI 格式
- **Profile 路径**：有 profile → 调用 hook 方法（`profile.prepare_messages()`、`profile.build_extra_body()`、`profile.build_api_kwargs_extras()`）
- **Fallback 路径**：无 profile（config.json only provider）→ 走默认 OpenAI 兼容逻辑
- **思考标签处理**：`<think>...</think>` 过滤（现有逻辑保留）

### 3.3 `client.py` — 运行时客户端

```python
class LLMClient:
    """LLM API 客户端。

    从 PluginRegistry 获取 provider profile，按 api_mode 分发到对应 transport。
    """

    def __init__(self, provider: str, model: str, registry: PluginRegistry):
        self._profile = registry.get_provider(provider)
        if self._profile is None:
            raise ValueError(f"Unknown provider: {provider}")
        self._model_def = self._profile.resolve_model(model)
        if self._model_def is None:
            raise ValueError(f"Unknown model: {provider}/{model}")
        self._transport = get_transport(self._profile.api_mode)
```

- `chat(messages, tools)` — 非流式，保留现有重试/退避逻辑
- `chat_stream(messages, tools)` — 流式，按 transport 分发
- 保留：`FatalLLMError`、`LLMError`、退避/重试/fallback、JSONL 日志、token 估算、Interoception 回调

### 3.4 Provider 插件示例

#### 简单 provider（DeepSeek — 需要 hook）

**`llm/providers/deepseek/adapter.py`**：

```python
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

    # ── 唯一需要 override 的 hook：V4 thinking 格式 ──
    def build_extra_body(self, *, stream: bool, **context) -> dict:
        return {"thinking": {"type": "enabled"}}

    def build_api_kwargs_extras(self, **context) -> dict[str, Any]:
        return {"reasoning_effort": "medium"}

def register(ctx):
    ctx.register_provider(DeepSeekProfile)
```

#### 更简单的 provider（OpenAI — 不需要 hook）

```python
from xiaomei_brain.llm.types import ProviderProfile, ModelDefinition

openai = ProviderProfile(
    provider_id="openai",
    name="OpenAI",
    base_url="https://api.openai.com/v1",
    env_vars=("OPENAI_API_KEY",),
    models=[
        ModelDefinition(id="gpt-4o", name="GPT-4o",
                        context_window=128000, max_tokens=16384),
        ModelDefinition(id="gpt-5-mini", name="GPT-5 Mini",
                        context_window=256000, max_tokens=16384),
    ],
)

def register(ctx):
    ctx.register_provider(openai)
```

> Hermes 经验：32 个 provider 中，大部分就是这样一个 `ProviderProfile(...)` 实例，零子类化。

## 4. 完整数据流

```
启动时：
  boot_plugins(agent_id)
    → 扫描 llm/providers/*/plugin.yaml
    → 校验 kind=provider, requires_env
    → 调用 adapter.register(ctx)
    → ctx.register_provider(DeepSeekProfile)    # ProviderProfile 实例/类
    → PluginRegistry._providers["deepseek"] = profile

  # config.json 也有 provider 但无插件 → 自动构建通用 profile
  → from_config("volcengine", config.models.providers.volcengine)
    → ProviderProfile(provider_id="volcengine", base_url="...", ...)
    → registry._providers["volcengine"] = profile

运行时：
  LLMClient(provider="deepseek", model="deepseek-v4-flash", registry)
    → registry.get_provider("deepseek")        → DeepSeekProfile
    → profile.resolve_model("deepseek-v4-flash") → ModelDefinition
    → get_transport("chat-completions")         → ChatCompletionsTransport

  client.chat(messages, tools)
    → transport.convert_messages(messages, profile)   # profile.prepare_messages()
    → transport.convert_tools(tools, profile)
    → transport.build_kwargs(...)
        → profile.build_extra_body(stream=False)       # {"thinking": {...}}
        → profile.build_api_kwargs_extras()            # {"reasoning_effort": "medium"}
    → HTTP POST → normalize_response(raw)              # NormalizedResponse
```

## 5. 与现有代码的关系

| 现有文件 | 处理方式 |
|----------|----------|
| `src/xiaomei_brain/base/llm.py` | 移入 `src/xiaomei_brain/llm/client.py`，核心逻辑保留 |
| `src/xiaomei_brain/base/config.py` | `from_json()` 中 `models.providers` 解析逻辑改为构建 ProviderProfile |
| `src/xiaomei_brain/plugin/loader.py` | 发现目录列表新增 `llm/providers/` |
| `src/xiaomei_brain/plugin/context.py` | `register_provider()` 接受 ProviderProfile |
| `src/xiaomei_brain/agent/agent_manager.py` | `_DEFAULT_CONFIG_TEMPLATE` 格式不变 |
| `src/xiaomei_brain/consciousness/conscious_living.py` | `boot_plugins()` 保持不变，自动包含 provider |
| 其他调用方 | 只改 import 路径 |

## 6. 配置覆盖与合并

插件提供"出厂默认值"，`config.json` 的 `models.providers` 可覆盖：

```
DeepSeekProfile.base_url = "https://api.deepseek.com/v1"
  ↳ config.json models.providers.deepseek.baseUrl = "https://my-proxy/v1"  ← 覆盖

DeepSeekProfile.models = [v4-flash, v4-pro]
  ↳ config.json models.providers.deepseek.models = [...]  ← 追加/覆盖
```

合并规则：
- `baseUrl`：config.json 优先，否则用 profile 默认
- `apiKey`：config.json 优先，否则用 profile 的 `env_vars` 对应环境变量
- `models`：合并，config.json 中相同 id 的字段覆盖 profile 默认

**config.json only provider**（无对应插件）：自动从 config.json 构建 `ProviderProfile`，`api_mode` 默认 `chat-completions`。

## 7. 第三方 Provider 插件

```
# 方式 1：放入 ~/.xiaomei-brain/plugins/
~/.xiaomei-brain/plugins/my_llm/
├── plugin.yaml           # kind: provider
└── adapter.py            # ProviderProfile(...) → ctx.register_provider()

# 方式 2：pip 包 entry point
# pyproject.toml:
#   [project.entry-points."xiaomei_brain.plugins"]
#   my_provider = "my_package.my_provider.adapter"
```

## 8. LLMClient 公开 API（向后兼容）

```python
from xiaomei_brain.llm import LLMClient

client = LLMClient(provider="deepseek", model="deepseek-v4-flash", registry=registry)

response = client.chat(messages=[...], tools=[...])
for chunk in client.chat_stream(messages=[...], tools=[...]):
    ...

client.set_provider("zhipu", model="glm-5.1")
client.add_fallback("volcengine/doubao-pro-32k")
client.switch_to_fallback()
```

## 9. 不在 scope

- Embedding 适配（继续使用现有 BAAI/bge-m3）
- TTS 适配（继续使用现有 MiniMax）

## 10. 测试策略

- **unit**：ProviderProfile 构建/合并、TransportRegistry 分发
- **integration**：mock HTTP 验证 chat/chat_stream 完整链路（profile → transport → response）
- **plugin test**：创建临时 provider 插件目录，验证 boot_plugins() 自动发现并注册
