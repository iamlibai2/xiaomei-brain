"""LLM 适配层数据结构 — ModelApi / ProviderProfile / ModelDefinition / NormalizedResponse."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


THINKING_EFFORTS = ("default", "low", "medium", "high", "max")


def resolve_thinking_capabilities(
    provider_id: str,
    model_id: str,
    *,
    reasoning: bool = False,
) -> dict[str, Any]:
    """Return built-in thinking capabilities for a known model.

    The values are declarative compatibility data. Adding another model that
    uses an existing wire format should only require catalog data, not another
    Provider subclass.
    """
    provider = provider_id.lower()
    model = model_id.lower()
    if provider == "deepseek" and model in {"deepseek-v4-flash", "deepseek-v4-pro"}:
        return {
            "thinking_toggle": True,
            "thinking_efforts": list(THINKING_EFFORTS),
            "thinking_default_enabled": True,
            "thinking_default_effort": "default",
            "requires_reasoning_content_for_tools": True,
        }
    if provider == "zhipu" and model == "glm-5.2":
        return {
            "thinking_toggle": True,
            "thinking_efforts": list(THINKING_EFFORTS),
            "thinking_default_enabled": True,
            "thinking_default_effort": "default",
            "requires_reasoning_content_for_tools": True,
        }
    if provider == "zhipu" and model in {
        "glm-5.1", "glm-5", "glm-5-turbo", "glm-5v-turbo",
        "glm-4.7", "glm-4.6", "glm-4.5",
    }:
        return {
            "thinking_toggle": True,
            "thinking_efforts": [],
            "thinking_default_enabled": True,
            "thinking_default_effort": "default",
            "requires_reasoning_content_for_tools": True,
        }
    return {
        "thinking_toggle": False,
        "thinking_efforts": [],
        "thinking_default_enabled": bool(reasoning),
        "thinking_default_effort": "default",
        "requires_reasoning_content_for_tools": False,
    }


def resolve_provider_thinking_mapping(provider_id: str) -> tuple[str, dict[str, str]]:
    """Return the request format and canonical-effort mapping for a provider."""
    if provider_id.lower() in {"deepseek", "zhipu"}:
        return (
            "openai-thinking",
            {
                "low": "high",
                "medium": "high",
                "high": "high",
                "max": "max",
            },
        )
    return "", {}


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
    thinking_toggle: bool = False
    thinking_efforts: list[str] = field(default_factory=list)
    thinking_default_enabled: bool = True
    thinking_default_effort: str = "default"
    requires_reasoning_content_for_tools: bool = False

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
    thinking_format: str = ""
    thinking_effort_map: dict[str, str] = field(default_factory=dict)

    # ── 模型目录 ──
    models: list[ModelDefinition] = field(default_factory=list)

    # ══ Hook 方法（子类按需 override）══

    def get_headers(self, api_key: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {api_key}"}

    @staticmethod
    def _thinking_enabled(model: ModelDefinition, context: dict[str, Any]) -> bool:
        options = context.get("thinking")
        if isinstance(options, dict) and isinstance(options.get("enabled"), bool):
            return options["enabled"]
        return model.thinking_default_enabled

    def prepare_messages(
        self,
        messages: list[dict],
        model: ModelDefinition,
        **context,
    ) -> list[dict]:
        if (
            not model.requires_reasoning_content_for_tools
            or not self._thinking_enabled(model, context)
        ):
            return messages

        # Old rows may contain tool calls created before reasoning_content was
        # persisted. Never fabricate it: omit the invalid tool exchange so the
        # provider does not reject the whole request.
        invalid_tool_call_ids: set[str] = set()
        prepared: list[dict] = []
        for message in messages:
            if message.get("role") == "assistant" and message.get("tool_calls"):
                if not message.get("reasoning_content"):
                    invalid_tool_call_ids.update(
                        str(call.get("id", ""))
                        for call in message["tool_calls"]
                        if call.get("id")
                    )
                    continue
            if (
                message.get("role") == "tool"
                and message.get("tool_call_id") in invalid_tool_call_ids
            ):
                continue
            prepared.append(message)
        return prepared

    def prepare_message_extras(
        self,
        message: dict,
        model: ModelDefinition,
        **context,
    ) -> dict:
        """Return provider-specific fields for one outbound message.

        The generic Chat Completions transport deliberately knows nothing
        about provider-specific message extensions such as DeepSeek's
        ``reasoning_content`` round-trip requirement.
        """
        if (
            model.requires_reasoning_content_for_tools
            and self._thinking_enabled(model, context)
            and message.get("role") == "assistant"
            and message.get("tool_calls")
            and message.get("reasoning_content")
        ):
            return {"reasoning_content": message["reasoning_content"]}
        return {}

    def build_request_extras(
        self,
        model: ModelDefinition,
        *,
        stream: bool,
        **context,
    ) -> dict[str, Any]:
        """Map normalized thinking options to provider request fields."""
        if not self.thinking_format or not (
            model.thinking_toggle or model.thinking_efforts
        ):
            return {}

        enabled = self._thinking_enabled(model, context)
        if self.thinking_format != "openai-thinking":
            return {}

        result: dict[str, Any] = {}
        if model.thinking_toggle:
            result["thinking"] = {
                "type": "enabled" if enabled else "disabled",
            }
        if not enabled or not model.thinking_efforts:
            return result

        options = context.get("thinking")
        effort = (
            str(options.get("effort", "default"))
            if isinstance(options, dict)
            else model.thinking_default_effort
        )
        if effort != "default":
            result["reasoning_effort"] = self.thinking_effort_map.get(effort, effort)
        return result

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
            capabilities = resolve_thinking_capabilities(
                provider_id,
                str(m.get("id", "")),
                reasoning=bool(m.get("reasoning", False)),
            )
            models.append(ModelDefinition(
                id=m.get("id", ""),
                name=m.get("name", m.get("id", "")),
                context_window=m.get("contextWindow", 4096),
                max_tokens=m.get("maxTokens", 4096),
                reasoning=m.get("reasoning", False),
                input_modes=m.get("inputModes", ["text"]),
                cost=m.get("cost", {}),
                thinking_toggle=m.get(
                    "thinkingToggle",
                    capabilities["thinking_toggle"],
                ),
                thinking_efforts=list(m.get(
                    "thinkingEfforts",
                    capabilities["thinking_efforts"],
                )),
                thinking_default_enabled=m.get(
                    "thinkingDefaultEnabled",
                    capabilities["thinking_default_enabled"],
                ),
                thinking_default_effort=m.get(
                    "thinkingDefaultEffort",
                    capabilities["thinking_default_effort"],
                ),
                requires_reasoning_content_for_tools=m.get(
                    "requiresReasoningContentForTools",
                    capabilities["requires_reasoning_content_for_tools"],
                ),
                supports_vision=m.get("supportsVision"),
                supports_tools=m.get("supportsTools"),
                supports_developer_role=m.get("supportsDeveloperRole"),
                supports_strict_mode=m.get("supportsStrictMode"),
                supports_usage_in_streaming=m.get("supportsUsageInStreaming"),
                max_tokens_field=m.get("maxTokensField"),
            ))

        default_thinking_format, default_effort_map = (
            resolve_provider_thinking_mapping(provider_id)
        )
        return cls(
            provider_id=provider_id,
            name=config.get("name", provider_id),
            api_mode=config.get("api") or config.get("apiMode", "chat-completions"),
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
            thinking_format=config.get(
                "thinkingFormat",
                default_thinking_format,
            ),
            thinking_effort_map=dict(config.get(
                "thinkingEffortMap",
                default_effort_map,
            )),
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
        if config.get("api") or config.get("apiMode"):
            existing.api_mode = config.get("api") or config["apiMode"]
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
        if config.get("thinkingFormat"):
            existing.thinking_format = config["thinkingFormat"]
        if config.get("thinkingEffortMap"):
            existing.thinking_effort_map = dict(config["thinkingEffortMap"])

        # models 合并：config.json 中同 id 覆盖，新 model 追加
        config_models = config.get("models", [])
        if config_models:
            existing_map = {m.id: m for m in existing.models}
            for m_cfg in config_models:
                mid = m_cfg.get("id", "")
                capabilities = resolve_thinking_capabilities(
                    provider_id,
                    str(mid),
                    reasoning=bool(m_cfg.get("reasoning", False)),
                )
                md = ModelDefinition(
                    id=mid,
                    name=m_cfg.get("name", mid),
                    context_window=m_cfg.get("contextWindow", 4096),
                    max_tokens=m_cfg.get("maxTokens", 4096),
                    reasoning=m_cfg.get("reasoning", False),
                    input_modes=m_cfg.get("inputModes", ["text"]),
                    cost=m_cfg.get("cost", {}),
                    thinking_toggle=m_cfg.get(
                        "thinkingToggle",
                        capabilities["thinking_toggle"],
                    ),
                    thinking_efforts=list(m_cfg.get(
                        "thinkingEfforts",
                        capabilities["thinking_efforts"],
                    )),
                    thinking_default_enabled=m_cfg.get(
                        "thinkingDefaultEnabled",
                        capabilities["thinking_default_enabled"],
                    ),
                    thinking_default_effort=m_cfg.get(
                        "thinkingDefaultEffort",
                        capabilities["thinking_default_effort"],
                    ),
                    requires_reasoning_content_for_tools=m_cfg.get(
                        "requiresReasoningContentForTools",
                        capabilities["requires_reasoning_content_for_tools"],
                    ),
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
