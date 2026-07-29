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
    living = SimpleNamespace(agent=agent, _chatting=False)
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
