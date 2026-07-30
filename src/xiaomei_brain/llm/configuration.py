"""Agent-facing model configuration shared by RPC, CLI, and conversation commands."""

from __future__ import annotations

import copy
import os
import re
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlparse

from xiaomei_brain.base.config_provider import ConfigProvider
from xiaomei_brain.llm.client import FatalLLMError, LLMClient, LLMError
from xiaomei_brain.llm.model_catalog import PROVIDER_META, get_provider_models
from xiaomei_brain.llm.types import (
    ProviderProfile,
    resolve_thinking_capabilities,
)


class ModelConfigurationError(ValueError):
    """A model setting cannot be validated or applied."""


class ModelConfigurationBusy(ModelConfigurationError):
    """The active model cannot be mutated during a conversation turn."""


class ModelConfigurationService:
    """Own model-provider resources and one Agent's model selection.

    Provider credentials are host resources stored in the global config.
    Primary and vision selections belong to a single Agent.
    """

    _PROVIDER_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
    _API_MODES = {"chat-completions", "openai-completions", "anthropic-messages"}

    def __init__(
        self,
        agent_id: str,
        living: Any | None = None,
        base_dir: str | Path | None = None,
    ) -> None:
        self.agent_id = agent_id
        self.living = living
        self.base_dir = Path(base_dir or Path.home() / ".xiaomei-brain")
        self.global_config = ConfigProvider(str(self.base_dir / "config.json"))
        self.agent_config = ConfigProvider(
            str(self.base_dir / agent_id / "config.json"),
        )
        self._lock = threading.RLock()

    def get(self) -> dict[str, Any]:
        global_data = self.global_config.config
        agent_data = self.agent_config.config
        providers = global_data.get("models", {}).get("providers", {})
        if not isinstance(providers, dict):
            providers = {}
        result = {
            "agent_id": self.agent_id,
            "selection": self._selection(global_data, agent_data),
            "active": self._active_selection(),
            "providers": [
                self._public_provider(provider_id, config)
                for provider_id, config in providers.items()
                if isinstance(config, dict)
            ],
            "hashes": {
                "global": self.global_config.hash,
                "agent": self.agent_config.hash,
            },
        }
        health_snapshot = getattr(
            self.living,
            "model_service_health_snapshot",
            None,
        )
        if callable(health_snapshot):
            result["service_health"] = health_snapshot()
        return result

    def catalog(self, provider_id: str = "") -> dict[str, Any]:
        if provider_id:
            self._validate_provider_id(provider_id)
            meta = PROVIDER_META.get(provider_id, {})
            return {
                "provider": self._catalog_provider(provider_id, meta, include_models=True),
            }
        return {
            "providers": [
                self._catalog_provider(pid, meta, include_models=False)
                for pid, meta in PROVIDER_META.items()
            ],
        }

    def configure_provider(
        self,
        provider_id: str,
        *,
        base_url: str,
        api_key: str = "",
        api_mode: str = "openai-completions",
        models: list[dict[str, Any]] | None = None,
        base_hash: str = "",
    ) -> dict[str, Any]:
        self._validate_provider_id(provider_id)
        base_url = self._validate_base_url(base_url)
        if api_mode not in self._API_MODES:
            raise ModelConfigurationError(f"不支持的 API 类型: {api_mode}")
        normalized_models = [
            self._normalize_model(item) for item in (models or [])
        ]
        if not normalized_models:
            raise ModelConfigurationError("请至少配置一个模型")

        with self._lock:
            data = self.global_config.config
            providers = data.setdefault("models", {}).setdefault("providers", {})
            existing = providers.get(provider_id, {})
            secret = api_key.strip() or (
                existing.get("apiKey", "") if isinstance(existing, dict) else ""
            )
            provider = {
                "baseUrl": base_url,
                "api": api_mode,
                "models": normalized_models,
            }
            if secret:
                provider["apiKey"] = secret
            providers[provider_id] = provider
            self.global_config.patch(
                {"models": {"providers": providers}},
                base_hash=base_hash,
            )
            apply_result = self._refresh_active_provider(provider_id)
            return {
                "provider": self._public_provider(provider_id, provider),
                "hash": self.global_config.hash,
                **apply_result,
            }

    def remove_provider(self, provider_id: str, *, base_hash: str = "") -> dict[str, Any]:
        self._validate_provider_id(provider_id)
        selection = self._selection(
            self.global_config.config,
            self.agent_config.config,
        )
        selected = {selection.get("primary", ""), selection.get("vision", "")}
        if any(value.startswith(f"{provider_id}/") for value in selected):
            raise ModelConfigurationError("当前 Agent 正在使用此 Provider，请先切换模型")

        with self._lock:
            data = self.global_config.config
            providers = data.setdefault("models", {}).setdefault("providers", {})
            removed = providers.pop(provider_id, None) is not None
            self.global_config.patch(
                {"models": {"providers": providers}},
                base_hash=base_hash,
            )
            return {"removed": removed, "hash": self.global_config.hash}

    def set_selection(
        self,
        primary: str,
        *,
        vision: str = "",
        thinking: dict[str, Any] | None = None,
        base_hash: str = "",
    ) -> dict[str, Any]:
        primary_provider, primary_model = self._split_selection(primary)
        if vision:
            self._split_selection(vision)
        providers = self._provider_configs()
        self._require_configured_model(providers, primary_provider, primary_model)
        normalized_thinking = self._normalize_thinking_selection(
            providers,
            primary_provider,
            primary_model,
            thinking,
        )
        if vision:
            vision_provider, vision_model = self._split_selection(vision)
            self._require_configured_model(providers, vision_provider, vision_model)
            self._require_vision_model(providers, vision_provider, vision_model)

        if self.living is not None and getattr(self.living, "_chatting", False):
            raise ModelConfigurationBusy("Agent 正在处理对话，请在本轮结束后切换模型")

        with self._lock:
            self.agent_config.patch(
                {
                    "model": {
                        "primary": primary,
                        "vision": vision or None,
                        "thinking": normalized_thinking or None,
                    },
                },
                base_hash=base_hash,
            )
            applied = self._apply_selection(
                primary,
                vision,
                normalized_thinking,
            )
            return {
                "selection": {
                    "primary": primary,
                    "vision": vision,
                    "thinking": normalized_thinking,
                },
                "active": self._active_selection(),
                "applied": applied,
                "restart_required": self.living is None,
                "hash": self.agent_config.hash,
            }

    def test_provider(
        self,
        provider_id: str,
        *,
        base_url: str,
        api_key: str = "",
        api_mode: str = "openai-completions",
        model_id: str,
    ) -> dict[str, Any]:
        self._validate_provider_id(provider_id)
        base_url = self._validate_base_url(base_url)
        if api_mode not in self._API_MODES:
            raise ModelConfigurationError(f"不支持的 API 类型: {api_mode}")
        if not model_id.strip():
            raise ModelConfigurationError("请选择用于测试的模型")

        stored = self._provider_configs().get(provider_id, {})
        secret = api_key.strip() or (
            stored.get("apiKey", "") if isinstance(stored, dict) else ""
        )
        if not secret:
            raise ModelConfigurationError("请输入 API Key")

        config = {
            "baseUrl": base_url,
            "api": api_mode,
            "models": [{"id": model_id, "name": model_id}],
        }
        existing = self._existing_profile(provider_id)
        profile = ProviderProfile.merge_or_create(
            provider_id,
            config,
            copy.deepcopy(existing) if existing is not None else None,
        )
        registry = SimpleNamespace(get_provider=lambda pid: profile if pid == provider_id else None)
        client = LLMClient(
            provider=provider_id,
            model=model_id,
            registry=registry,
            api_key=secret,
            max_retries=0,
            timeout=20,
        )
        try:
            response = client.chat(messages=[{
                "role": "user",
                "content": "Reply with OK.",
            }])
        except BaseException as exc:
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            raise ModelConfigurationError(self._format_test_error(exc)) from exc
        return {
            "ok": True,
            "provider_id": provider_id,
            "model_id": model_id,
            "response_received": bool(response.content or response.tool_calls),
        }

    @staticmethod
    def _format_test_error(exc: BaseException) -> str:
        """Turn transport failures into messages useful from the settings UI."""
        status_code = int(getattr(exc, "status_code", 0) or 0)
        raw = str(exc).strip()
        lowered = raw.lower()
        if status_code == 402:
            return "连接失败：模型账户余额不足"
        if status_code in {401, 403}:
            return "连接失败：API Key 无效或没有访问权限"
        if status_code == 404:
            return "连接失败：接口地址或模型名称不存在，请检查 Base URL 和模型 ID"
        if status_code == 429:
            return "连接失败：请求过于频繁或账户额度不足，请稍后重试"
        if status_code >= 500:
            return f"连接失败：模型服务暂时不可用（HTTP {status_code}）"
        if isinstance(exc, (TimeoutError,)) or "timeout" in lowered or "超时" in raw:
            return "连接失败：请求超时，请检查网络和 Base URL"
        if (
            "connection" in lowered
            or "connect" in lowered
            or "name resolution" in lowered
            or "无法解析" in raw
        ):
            return "连接失败：无法访问模型服务，请检查网络和 Base URL"
        if isinstance(exc, (LLMError, FatalLLMError)) and raw:
            return f"连接失败：{raw}"
        return f"模型连接测试失败：{raw or exc.__class__.__name__}"

    def _provider_configs(self) -> dict[str, dict[str, Any]]:
        providers = self.global_config.get("models.providers") or {}
        return providers if isinstance(providers, dict) else {}

    def _selection(self, global_data: dict, agent_data: dict) -> dict[str, Any]:
        defaults = global_data.get("agents", {}).get("defaults", {}).get("model", {})
        model = agent_data.get("model", {})
        if isinstance(model, str):
            return {"primary": model, "vision": "", "thinking": {}}
        if not isinstance(model, dict):
            model = {}
        if not isinstance(defaults, dict):
            defaults = {}
        return {
            "primary": str(model.get("primary") or defaults.get("primary") or ""),
            "vision": str(model.get("vision") or defaults.get("vision") or ""),
            "thinking": (
                dict(model.get("thinking", {}))
                if isinstance(model.get("thinking"), dict)
                else {}
            ),
        }

    def _active_selection(self) -> dict[str, Any]:
        agent = getattr(self.living, "agent", None)
        llm = getattr(agent, "llm", None)
        primary = ""
        if llm is not None:
            primary = f"{llm.provider}/{llm.model}"
        return {
            "primary": primary,
            "vision": str(getattr(agent, "vision_model", "") or ""),
            "thinking": {
                "enabled": bool(getattr(llm, "thinking_enabled", False)),
                "effort": str(getattr(llm, "thinking_effort", "default")),
            } if llm is not None else {},
        }

    def _apply_selection(
        self,
        primary: str,
        vision: str,
        thinking: dict[str, Any] | None = None,
    ) -> bool:
        if self.living is None:
            return False
        agent = getattr(self.living, "agent", None)
        llm = getattr(agent, "llm", None)
        if agent is None or llm is None:
            return False

        provider_id, model_id = self._split_selection(primary)
        provider_config = self._provider_configs()[provider_id]
        self._register_provider(llm, provider_id, provider_config)
        llm.set_provider(provider_id, model=model_id)
        llm.set_model(
            model_id,
            base_url=provider_config.get("baseUrl", ""),
            api_key=provider_config.get("apiKey", ""),
        )
        set_thinking = getattr(llm, "set_thinking", None)
        if callable(set_thinking):
            set_thinking(
                enabled=(thinking or {}).get("enabled"),
                effort=str((thinking or {}).get("effort", "default")),
            )
        agent.provider = provider_id
        agent.model = model_id

        if vision:
            vision_provider, vision_model = self._split_selection(vision)
            vision_config = self._provider_configs()[vision_provider]
            self._register_provider(llm, vision_provider, vision_config)
            agent.vision_llm = LLMClient(
                provider=vision_provider,
                model=vision_model,
                registry=llm._registry,
                api_key=vision_config.get("apiKey", ""),
            )
            agent.vision_model = vision
        else:
            agent.vision_llm = None
            agent.vision_model = ""
        configuration_changed = getattr(
            self.living,
            "on_model_configuration_changed",
            None,
        )
        if callable(configuration_changed):
            configuration_changed()
        return True

    def _refresh_active_provider(self, provider_id: str) -> dict[str, Any]:
        if self.living is None:
            return {"applied": False, "restart_required": True}
        selection = self._selection(
            self.global_config.config,
            self.agent_config.config,
        )
        selected_models = (
            selection.get("primary", ""),
            selection.get("vision", ""),
        )
        if not any(
            value.startswith(f"{provider_id}/")
            for value in selected_models
            if isinstance(value, str) and value
        ):
            return {"applied": True, "restart_required": False}
        if getattr(self.living, "_chatting", False):
            return {"applied": False, "restart_required": True}
        self._apply_selection(
            selection["primary"],
            selection["vision"],
            selection.get("thinking", {}),
        )
        return {"applied": True, "restart_required": False}

    def _register_provider(self, llm: Any, provider_id: str, config: dict) -> None:
        registry = llm._registry
        existing = registry.get_provider(provider_id)
        profile = ProviderProfile.merge_or_create(provider_id, config, existing)
        registry.register_provider(provider_id, profile)

    def _existing_profile(self, provider_id: str) -> ProviderProfile | None:
        agent = getattr(self.living, "agent", None)
        llm = getattr(agent, "llm", None)
        registry = getattr(llm, "_registry", None)
        return registry.get_provider(provider_id) if registry is not None else None

    def _catalog_provider(
        self,
        provider_id: str,
        meta: dict,
        *,
        include_models: bool,
    ) -> dict[str, Any]:
        result = {
            "id": provider_id,
            "base_url": meta.get("base_url", ""),
            "api_mode": meta.get("api_mode", "openai-completions"),
        }
        if include_models:
            result["models"] = [
                self._catalog_model(provider_id, model)
                for model in get_provider_models(provider_id)
            ]
        return result

    @staticmethod
    def _catalog_model(provider_id: str, model: Any) -> dict[str, Any]:
        thinking = resolve_thinking_capabilities(
            provider_id,
            model.id,
            reasoning=model.reasoning,
        )
        return {
            "id": model.id,
            "name": model.name,
            "context_window": model.context_window,
            "max_tokens": model.max_output or 8192,
            "reasoning": model.reasoning,
            "supports_tools": model.tool_call,
            "input_modes": list(model.input_modalities) or ["text"],
            "supports_vision": "image" in model.input_modalities,
            **thinking,
        }

    def _public_provider(self, provider_id: str, config: dict) -> dict[str, Any]:
        secret = str(config.get("apiKey", ""))
        return {
            "id": provider_id,
            "base_url": str(config.get("baseUrl", "")),
            "api_mode": str(config.get("api") or config.get("apiMode") or "chat-completions"),
            "secret_configured": bool(secret),
            "secret_hint": f"••••{secret[-4:]}" if secret else "",
            "models": [
                self._public_model(provider_id, model)
                for model in config.get("models", [])
                if isinstance(model, dict)
            ],
        }

    def _public_model(self, provider_id: str, model: dict[str, Any]) -> dict[str, Any]:
        input_modes = model.get("inputModes", ["text"])
        normalized_modes = input_modes if isinstance(input_modes, list) else ["text"]
        supports_vision = self._model_supports_vision(provider_id, model)
        if supports_vision and "image" not in normalized_modes:
            normalized_modes = [*normalized_modes, "image"]
        return {
            "id": str(model.get("id", "")),
            "name": str(model.get("name") or model.get("id") or ""),
            "context_window": int(model.get("contextWindow") or 0),
            "max_tokens": int(model.get("maxTokens") or 0),
            "reasoning": bool(model.get("reasoning", False)),
            **self._model_thinking_capabilities(provider_id, model),
            "supports_tools": bool(model.get("supportsTools", False)),
            "input_modes": normalized_modes,
            "supports_vision": supports_vision,
        }

    def _normalize_model(self, model: dict[str, Any]) -> dict[str, Any]:
        model_id = str(model.get("id", "")).strip()
        if not model_id or len(model_id) > 200:
            raise ModelConfigurationError("模型 ID 不能为空且不能超过 200 个字符")
        input_modes = model.get("input_modes", model.get("inputModes", ["text"]))
        if not isinstance(input_modes, list):
            input_modes = ["text"]
        return {
            "id": model_id,
            "name": str(model.get("name") or model_id)[:200],
            "contextWindow": max(0, int(model.get("context_window", model.get("contextWindow", 0)) or 0)),
            "maxTokens": max(1, int(model.get("max_tokens", model.get("maxTokens", 8192)) or 8192)),
            "reasoning": bool(model.get("reasoning", False)),
            "thinkingToggle": bool(
                model.get("thinking_toggle", model.get("thinkingToggle", False))
            ),
            "thinkingEfforts": [
                str(effort)
                for effort in model.get(
                    "thinking_efforts",
                    model.get("thinkingEfforts", []),
                )
                if str(effort) in {"default", "low", "medium", "high", "max"}
            ],
            "thinkingDefaultEnabled": bool(
                model.get(
                    "thinking_default_enabled",
                    model.get("thinkingDefaultEnabled", True),
                )
            ),
            "thinkingDefaultEffort": str(
                model.get(
                    "thinking_default_effort",
                    model.get("thinkingDefaultEffort", "default"),
                )
            ),
            "requiresReasoningContentForTools": bool(
                model.get(
                    "requires_reasoning_content_for_tools",
                    model.get("requiresReasoningContentForTools", False),
                )
            ),
            "inputModes": [str(mode) for mode in input_modes],
            "supportsVision": bool(
                model.get("supports_vision", model.get("supportsVision", False))
                or "image" in input_modes
            ),
            "supportsTools": bool(model.get("supports_tools", model.get("supportsTools", False))),
        }

    @staticmethod
    def _model_thinking_capabilities(
        provider_id: str,
        model: dict[str, Any],
    ) -> dict[str, Any]:
        defaults = resolve_thinking_capabilities(
            provider_id,
            str(model.get("id", "")),
            reasoning=bool(model.get("reasoning", False)),
        )
        efforts = model.get("thinkingEfforts", defaults["thinking_efforts"])
        return {
            "thinking_toggle": bool(
                model.get("thinkingToggle", defaults["thinking_toggle"])
            ),
            "thinking_efforts": [
                str(effort)
                for effort in efforts
                if str(effort) in {"default", "low", "medium", "high", "max"}
            ] if isinstance(efforts, list) else [],
            "thinking_default_enabled": bool(
                model.get(
                    "thinkingDefaultEnabled",
                    defaults["thinking_default_enabled"],
                )
            ),
            "thinking_default_effort": str(
                model.get(
                    "thinkingDefaultEffort",
                    defaults["thinking_default_effort"],
                )
            ),
            "requires_reasoning_content_for_tools": bool(
                model.get(
                    "requiresReasoningContentForTools",
                    defaults["requires_reasoning_content_for_tools"],
                )
            ),
        }

    def _normalize_thinking_selection(
        self,
        providers: dict[str, dict[str, Any]],
        provider_id: str,
        model_id: str,
        thinking: dict[str, Any] | None,
    ) -> dict[str, Any]:
        provider = providers.get(provider_id, {})
        model = next(
            (
                item for item in provider.get("models", [])
                if isinstance(item, dict) and str(item.get("id", "")) == model_id
            ),
            {},
        )
        capabilities = self._model_thinking_capabilities(provider_id, model)
        supports_controls = bool(
            capabilities["thinking_toggle"]
            or capabilities["thinking_efforts"]
        )
        if not supports_controls:
            return {}

        options = thinking if isinstance(thinking, dict) else {}
        enabled = options.get(
            "enabled",
            capabilities["thinking_default_enabled"],
        )
        if not isinstance(enabled, bool):
            raise ModelConfigurationError("思考模式开关必须是布尔值")
        effort = str(options.get(
            "effort",
            capabilities["thinking_default_effort"],
        ))
        allowed = capabilities["thinking_efforts"]
        if allowed and effort not in allowed:
            raise ModelConfigurationError(
                f"当前模型不支持思考强度: {effort}"
            )
        if not allowed:
            effort = "default"
        return {"enabled": enabled, "effort": effort}

    def _require_configured_model(
        self,
        providers: dict[str, dict[str, Any]],
        provider_id: str,
        model_id: str,
    ) -> None:
        provider = providers.get(provider_id)
        if not isinstance(provider, dict):
            raise ModelConfigurationError(f"Provider 尚未配置: {provider_id}")
        configured = {
            str(model.get("id", ""))
            for model in provider.get("models", [])
            if isinstance(model, dict)
        }
        if model_id not in configured:
            raise ModelConfigurationError(f"模型尚未配置: {provider_id}/{model_id}")

    def _require_vision_model(
        self,
        providers: dict[str, dict[str, Any]],
        provider_id: str,
        model_id: str,
    ) -> None:
        provider = providers.get(provider_id, {})
        model = next(
            (
                item for item in provider.get("models", [])
                if isinstance(item, dict) and str(item.get("id", "")) == model_id
            ),
            None,
        )
        supports_vision = bool(
            isinstance(model, dict)
            and self._model_supports_vision(provider_id, model)
        )
        if not supports_vision:
            raise ModelConfigurationError(
                f"模型不支持图片输入，不能设为视觉模型: {provider_id}/{model_id}"
            )

    @staticmethod
    def _model_supports_vision(provider_id: str, model: dict[str, Any]) -> bool:
        input_modes = model.get("inputModes", [])
        if model.get("supportsVision", False) or (
            isinstance(input_modes, list) and "image" in input_modes
        ):
            return True
        model_id = str(model.get("id", ""))
        try:
            catalog_model = next(
                (
                    item for item in get_provider_models(provider_id)
                    if item.id == model_id
                ),
                None,
            )
        except Exception:
            catalog_model = None
        return bool(
            catalog_model is not None
            and "image" in catalog_model.input_modalities
        )

    def _validate_provider_id(self, provider_id: str) -> None:
        if not self._PROVIDER_ID.fullmatch(provider_id):
            raise ModelConfigurationError("Provider ID 只能包含小写字母、数字、横线和下划线")

    @staticmethod
    def _validate_base_url(base_url: str) -> str:
        value = base_url.strip().rstrip("/")
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ModelConfigurationError("请输入有效的 HTTP 或 HTTPS Base URL")
        return value

    @staticmethod
    def _split_selection(value: str) -> tuple[str, str]:
        if "/" not in value:
            raise ModelConfigurationError("模型必须使用 provider/model 格式")
        provider_id, model_id = value.split("/", 1)
        if not provider_id or not model_id:
            raise ModelConfigurationError("模型必须使用 provider/model 格式")
        return provider_id, model_id
