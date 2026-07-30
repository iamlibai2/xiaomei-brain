from __future__ import annotations

from types import SimpleNamespace

import xiaomei_brain.llm.configuration as model_configuration
from xiaomei_brain.gateway.methods.models import ModelMethods
from xiaomei_brain.llm.configuration import ModelConfigurationService
from xiaomei_brain.llm.client import FatalLLMError, LLMError


class FakeRegistry:
    def __init__(self):
        self.providers = {}

    def get_provider(self, provider_id):
        return self.providers.get(provider_id)

    def register_provider(self, provider_id, provider):
        self.providers[provider_id] = provider


class FakeLlm:
    def __init__(self):
        self._registry = FakeRegistry()
        self.provider = ""
        self.model = ""
        self.base_url = ""
        self.api_key = ""
        self.thinking_enabled = False
        self.thinking_effort = "default"

    def set_provider(self, provider, model=None):
        assert self._registry.get_provider(provider) is not None
        self.provider = provider
        if model:
            self.model = model

    def set_model(self, model, base_url=None, api_key=None):
        self.model = model
        if base_url:
            self.base_url = base_url
        if api_key:
            self.api_key = api_key

    def set_thinking(self, enabled=None, effort="default"):
        if isinstance(enabled, bool):
            self.thinking_enabled = enabled
        self.thinking_effort = effort


def configured_model():
    return {
        "id": "demo-chat",
        "name": "Demo Chat",
        "context_window": 128000,
        "max_tokens": 8192,
        "supports_tools": True,
        "input_modes": ["text"],
    }


def configured_vision_model():
    return {
        "id": "demo-vision",
        "name": "Demo Vision",
        "context_window": 128000,
        "max_tokens": 8192,
        "supports_tools": True,
        "supports_vision": True,
        "input_modes": ["text", "image"],
    }


def test_model_configuration_masks_secret_and_hot_applies_selection(tmp_path):
    llm = FakeLlm()
    agent = SimpleNamespace(
        llm=llm,
        provider="",
        model="",
        vision_model="",
        vision_llm=None,
    )
    configuration_changes = []
    living = SimpleNamespace(
        agent=agent,
        _chatting=False,
        on_model_configuration_changed=lambda: configuration_changes.append(True),
    )
    service = ModelConfigurationService("xiaomei", living=living, base_dir=tmp_path)

    configured = service.configure_provider(
        "demo",
        base_url="https://models.example.test/v1/",
        api_key="super-secret-key",
        models=[configured_model()],
    )
    assert configured["provider"]["secret_configured"] is True
    assert configured["provider"]["secret_hint"] == "••••-key"
    assert "super-secret-key" not in str(configured)

    selected = service.set_selection("demo/demo-chat")
    assert selected["applied"] is True
    assert selected["restart_required"] is False
    assert llm.provider == "demo"
    assert llm.model == "demo-chat"
    assert llm.base_url == "https://models.example.test/v1"
    assert llm.api_key == "super-secret-key"
    assert configuration_changes == [True]

    snapshot = service.get()
    assert snapshot["selection"]["primary"] == "demo/demo-chat"
    assert snapshot["active"]["primary"] == "demo/demo-chat"
    assert "super-secret-key" not in str(snapshot)


def test_model_rpc_uses_shared_service_and_rejects_active_provider_removal(tmp_path):
    living = SimpleNamespace(
        agent=SimpleNamespace(
            llm=FakeLlm(),
            provider="",
            model="",
            vision_model="",
            vision_llm=None,
        ),
        _agent_id="xiaomei",
        _chatting=False,
    )
    living._model_configuration = ModelConfigurationService(
        "xiaomei",
        living=living,
        base_dir=tmp_path,
    )
    methods = ModelMethods(living)

    configured = methods.handle_configure("desktop", "1", {
        "provider_id": "demo",
        "base_url": "https://models.example.test/v1",
        "api_key": "top-secret-123",
        "models": [configured_model()],
    })
    assert configured["result"]["provider"]["id"] == "demo"
    assert "top-secret-123" not in str(configured)

    selected = methods.handle_set_selection("desktop", "2", {
        "primary": "demo/demo-chat",
    })
    assert selected["result"]["active"]["primary"] == "demo/demo-chat"

    removed = methods.handle_remove("desktop", "3", {
        "provider_id": "demo",
    })
    assert removed["error"]["code"] != 0
    assert "正在使用" in removed["error"]["message"]


def test_model_test_errors_are_user_friendly():
    format_error = ModelConfigurationService._format_test_error

    assert format_error(FatalLLMError("raw secret response", status_code=401)) == (
        "连接失败：API Key 无效或没有访问权限"
    )
    assert format_error(FatalLLMError("raw provider response", status_code=402)) == (
        "连接失败：模型账户余额不足"
    )
    assert "模型名称不存在" in format_error(LLMError("not found", status_code=404))
    assert "请求超时" in format_error(LLMError("request timeout"))
    assert "网络和 Base URL" in format_error(LLMError("Connection refused"))


def test_selection_rejects_text_only_vision_model(tmp_path):
    service = ModelConfigurationService("xiaomei", base_dir=tmp_path)
    service.configure_provider(
        "demo",
        base_url="https://models.example.test/v1",
        api_key="secret",
        models=[configured_model(), configured_vision_model()],
    )

    try:
        service.set_selection("demo/demo-chat", vision="demo/demo-chat")
    except ValueError as exc:
        assert "不支持图片输入" in str(exc)
    else:
        raise AssertionError("text-only model must not be accepted as vision model")

    selected = service.set_selection("demo/demo-chat", vision="demo/demo-vision")
    assert selected["selection"]["vision"] == "demo/demo-vision"


def test_catalog_can_upgrade_stale_vision_metadata(tmp_path, monkeypatch):
    monkeypatch.setattr(
        model_configuration,
        "get_provider_models",
        lambda provider_id: [
            SimpleNamespace(id="MiniMax-M3", input_modalities=("text", "image", "video")),
        ] if provider_id == "minimax" else [],
    )
    service = ModelConfigurationService("xiaomei", base_dir=tmp_path)
    service.configure_provider(
        "minimax",
        base_url="https://api.minimaxi.com/v1",
        api_key="secret",
        models=[{
            "id": "MiniMax-M3",
            "name": "MiniMax-M3",
            "supports_vision": False,
            "input_modes": ["text"],
        }],
    )

    snapshot = service.get()
    model = snapshot["providers"][0]["models"][0]
    assert model["supports_vision"] is True
    assert "image" in model["input_modes"]
    selected = service.set_selection(
        "minimax/MiniMax-M3",
        vision="minimax/MiniMax-M3",
    )
    assert selected["selection"]["vision"] == "minimax/MiniMax-M3"


def test_glm_5_2_catalog_and_thinking_selection(tmp_path, monkeypatch):
    from xiaomei_brain.llm.model_catalog import ModelInfo

    monkeypatch.setattr(
        model_configuration,
        "get_provider_models",
        lambda provider_id: [
            ModelInfo(
                id="glm-5.2",
                name="GLM-5.2",
                provider_id="zhipu",
                context_window=1_000_000,
                max_output=131_072,
                reasoning=True,
                tool_call=True,
                input_modalities=("text",),
            ),
        ] if provider_id == "zhipu" else [],
    )
    llm = FakeLlm()
    agent = SimpleNamespace(
        llm=llm,
        provider="",
        model="",
        vision_model="",
        vision_llm=None,
    )
    living = SimpleNamespace(agent=agent, _chatting=False)
    service = ModelConfigurationService("xiaomei", living=living, base_dir=tmp_path)

    catalog_model = service.catalog("zhipu")["provider"]["models"][0]
    assert catalog_model["id"] == "glm-5.2"
    assert catalog_model["thinking_toggle"] is True
    assert catalog_model["thinking_efforts"] == [
        "default", "low", "medium", "high", "max",
    ]

    service.configure_provider(
        "zhipu",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        api_key="secret",
        models=[catalog_model],
    )
    selected = service.set_selection(
        "zhipu/glm-5.2",
        thinking={"enabled": True, "effort": "medium"},
    )

    assert selected["selection"]["thinking"] == {
        "enabled": True,
        "effort": "medium",
    }
    assert llm.thinking_enabled is True
    assert llm.thinking_effort == "medium"


def test_glm_5_2_provider_maps_normalized_thinking_options():
    from xiaomei_brain.llm.transport.chat_completions import ChatCompletionsTransport
    from xiaomei_brain.llm.types import ProviderProfile

    profile = ProviderProfile.from_config("zhipu", {
        "baseUrl": "https://open.bigmodel.cn/api/paas/v4",
        "models": [{
            "id": "glm-5.2",
            "name": "GLM-5.2",
            "reasoning": True,
        }],
    })
    model = profile.resolve_model("glm-5.2")
    assert model is not None

    payload = ChatCompletionsTransport().build_kwargs(
        [],
        None,
        model,
        profile,
        stream=False,
        thinking={"enabled": True, "effort": "medium"},
    )
    assert payload["thinking"] == {"type": "enabled"}
    assert payload["reasoning_effort"] == "high"

    disabled = ChatCompletionsTransport().build_kwargs(
        [],
        None,
        model,
        profile,
        stream=False,
        thinking={"enabled": False, "effort": "max"},
    )
    assert disabled["thinking"] == {"type": "disabled"}
    assert "reasoning_effort" not in disabled


def test_thinking_controls_follow_declared_model_capabilities():
    from xiaomei_brain.llm.types import resolve_thinking_capabilities

    unsupported = resolve_thinking_capabilities(
        "custom",
        "reasoning-model",
        reasoning=True,
    )
    toggle_only = resolve_thinking_capabilities("zhipu", "glm-5.1")
    toggle_and_effort = resolve_thinking_capabilities("zhipu", "glm-5.2")

    assert unsupported["thinking_toggle"] is False
    assert unsupported["thinking_efforts"] == []
    assert toggle_only["thinking_toggle"] is True
    assert toggle_only["thinking_efforts"] == []
    assert toggle_and_effort["thinking_efforts"] == [
        "default", "low", "medium", "high", "max",
    ]


def test_glm_5_2_round_trips_reasoning_only_for_tool_calls():
    from xiaomei_brain.llm.transport.chat_completions import ChatCompletionsTransport
    from xiaomei_brain.llm.types import ProviderProfile

    profile = ProviderProfile.from_config("zhipu", {
        "baseUrl": "https://open.bigmodel.cn/api/paas/v4",
        "models": [{
            "id": "glm-5.2",
            "name": "GLM-5.2",
            "reasoning": True,
        }],
    })
    model = profile.resolve_model("glm-5.2")
    assert model is not None

    messages = ChatCompletionsTransport().convert_messages(
        [
            {
                "role": "assistant",
                "content": "ordinary answer",
                "reasoning_content": "private ordinary reasoning",
            },
            {
                "role": "assistant",
                "content": "",
                "reasoning_content": "reasoning needed by the tool call",
                "tool_calls": [{
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "lookup", "arguments": "{}"},
                }],
            },
            {
                "role": "tool",
                "tool_call_id": "call_1",
                "content": "result",
            },
        ],
        model,
        profile,
        thinking={"enabled": True, "effort": "high"},
    )

    assert "reasoning_content" not in messages[0]
    assert messages[1]["reasoning_content"] == "reasoning needed by the tool call"


def test_glm_5_2_is_available_when_remote_catalog_is_unavailable(monkeypatch):
    import xiaomei_brain.llm.model_catalog as catalog

    monkeypatch.setattr(catalog, "_fetch", lambda: {})
    models = catalog.get_provider_models("zhipu")
    glm = next(model for model in models if model.id == "glm-5.2")

    assert glm.context_window == 1_000_000
    assert glm.max_output == 131_072
    assert glm.reasoning is True
    assert glm.tool_call is True
