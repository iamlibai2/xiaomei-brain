from types import SimpleNamespace

import pytest

from xiaomei_brain.agent.vision_routing import VisionRoutingError, route_chat_images
from xiaomei_brain.llm.client import LLMClient
from xiaomei_brain.llm.model_catalog import ModelInfo
from xiaomei_brain.llm.types import ModelDefinition, ProviderProfile


def make_client(model: ModelDefinition, provider_vision: bool = False) -> LLMClient:
    client = object.__new__(LLMClient)
    client._model_def = model
    client._model_id = model.id
    client._profile = ProviderProfile(
        provider_id="test", name="Test", supports_vision=provider_vision,
    )
    return client


def test_explicit_model_vision_capability_wins(monkeypatch):
    monkeypatch.setattr(
        "xiaomei_brain.llm.model_catalog.get_provider_models",
        lambda _provider: pytest.fail("catalog should not be queried"),
    )
    client = make_client(ModelDefinition(
        id="model", name="Model", context_window=1000, max_tokens=100,
        supports_vision=True,
    ))
    assert client.supports_vision is True


def test_model_catalog_fills_old_config_capability(monkeypatch):
    monkeypatch.setattr(
        "xiaomei_brain.llm.model_catalog.get_provider_models",
        lambda _provider: [ModelInfo(
            id="old-model", name="Old", provider_id="test",
            input_modalities=("text", "image"),
        )],
    )
    client = make_client(ModelDefinition(
        id="old-model", name="Old", context_window=1000, max_tokens=100,
    ))
    assert client.supports_vision is True


def test_vision_capable_primary_receives_original_images():
    primary = SimpleNamespace(supports_vision=True, provider="test", model="vision-primary")
    agent = SimpleNamespace(llm=primary, vision_llm=None, vision_model="")
    images, analysis = route_chat_images(agent, "看图", ["one.png"])
    assert images == ["one.png"]
    assert analysis == ""


@pytest.mark.parametrize("prompt_text", [
    "把这张图片原样插入 Word 文档",
    "用这个图片",
])
def test_asset_only_request_skips_image_analysis(prompt_text):
    primary = SimpleNamespace(supports_vision=False, provider="test", model="text-primary")

    class UnexpectedVisionLLM:
        def chat(self, messages):
            pytest.fail("asset-only requests must not invoke a vision model")

    agent = SimpleNamespace(
        llm=primary,
        vision_llm=UnexpectedVisionLLM(),
        vision_model="test/vision",
    )

    assert route_chat_images(agent, prompt_text, ["one.png"]) == ([], "")


def test_document_request_that_needs_image_understanding_still_uses_vision(tmp_path):
    image_path = tmp_path / "one.png"
    image_path.write_bytes(b"image")

    class VisionLLM:
        def chat(self, messages):
            return SimpleNamespace(content="图中是系统架构")

    primary = SimpleNamespace(supports_vision=False, provider="test", model="text-primary")
    agent = SimpleNamespace(llm=primary, vision_llm=VisionLLM(), vision_model="test/vision")

    images, analysis = route_chat_images(
        agent,
        "先分析图片内容，再写进 Word 报告",
        [str(image_path)],
    )

    assert images == []
    assert analysis == "图中是系统架构"


def test_text_primary_uses_configured_fallback_vision_model(tmp_path):
    image_path = tmp_path / "one.png"
    image_path.write_bytes(b"not-a-real-png-but-routing-only-needs-bytes")

    class VisionLLM:
        def __init__(self):
            self.messages = None

        def chat(self, messages):
            self.messages = messages
            return SimpleNamespace(content="图片中有一张架构图")

    vision = VisionLLM()
    primary = SimpleNamespace(supports_vision=False, provider="test", model="text-primary")
    agent = SimpleNamespace(llm=primary, vision_llm=vision, vision_model="test/vision")

    images, analysis = route_chat_images(agent, "解释架构", [str(image_path)])

    assert images == []
    assert analysis == "图片中有一张架构图"
    content = vision.messages[0]["content"]
    assert content[0]["type"] == "text" and "解释架构" in content[0]["text"]
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_image_message_fails_clearly_without_any_vision_model():
    primary = SimpleNamespace(supports_vision=False, provider="test", model="text-primary")
    agent = SimpleNamespace(llm=primary, vision_llm=None, vision_model="")
    with pytest.raises(VisionRoutingError, match="未配置 model.vision"):
        route_chat_images(agent, "看图", ["one.png"])


def test_fallback_provider_error_identifies_the_vision_model(tmp_path):
    image_path = tmp_path / "one.png"
    image_path.write_bytes(b"image")

    class FailedVisionLLM:
        def chat(self, messages):
            raise RuntimeError("API 429")

    primary = SimpleNamespace(supports_vision=False, provider="test", model="text-primary")
    agent = SimpleNamespace(
        llm=primary, vision_llm=FailedVisionLLM(), vision_model="minimax/MiniMax-M3",
    )
    with pytest.raises(VisionRoutingError, match="视觉模型 minimax/MiniMax-M3 调用失败: API 429"):
        route_chat_images(agent, "看图", [str(image_path)])
