from __future__ import annotations

from types import SimpleNamespace

class FakePluginContext:
    def __init__(self, config, tmp_path):
        self.config = config
        self.agent_dir = str(tmp_path)
        self.agent_id = "xiaomei"
        self.summary = ""
        self.tools = []
        self.providers = []
        self.logger = SimpleNamespace(info=lambda *args, **kwargs: None)

    def register_agent_tool(self, tool):
        self.tools.append(tool)

    def register_web_search_provider(self, provider):
        self.providers.append(provider)


def test_minimax_tts_plugin_owns_provider_and_tools(tmp_path):
    from xiaomei_brain.plugins.tools.tts_minimax import adapter
    from xiaomei_brain.plugins.tools.tts_minimax import tool

    context = FakePluginContext({
        "enabled": True,
        "api_key": "tts-secret",
        "base_url": "https://tts.example.com",
        "voice_id": "voice-demo",
    }, tmp_path)

    adapter.register(context)

    assert {item.name for item in context.tools} == {
        "speak",
        "speak_to_file",
    }
    assert tool._tts_provider is not None
    assert tool._tts_provider.base_url == "https://tts.example.com"
    assert tool._tts_provider.voice_config.voice_id == "voice-demo"


def test_minimax_music_plugin_owns_provider_and_tool(tmp_path):
    from xiaomei_brain.plugins.tools.music_minimax import adapter
    from xiaomei_brain.plugins.tools.music_minimax import tool

    context = FakePluginContext({
        "enabled": True,
        "api_key": "music-secret",
        "base_url": "https://music.example.com",
        "format": "wav",
    }, tmp_path)

    adapter.register(context)

    assert [item.name for item in context.tools] == ["generate_music"]
    assert tool._music_provider is not None
    assert tool._music_provider.base_url == "https://music.example.com"
    assert tool._music_provider._audio_config.format == "wav"


def test_baidu_search_plugin_registers_provider_without_agent_manager(tmp_path):
    from xiaomei_brain.plugins.tools.web_search_baidu import adapter

    context = FakePluginContext({
        "enabled": True,
        "api_key": "baidu-secret",
    }, tmp_path)

    adapter.register(context)

    assert len(context.providers) == 1
    assert context.providers[0].provider_id == "baidu"


def test_baidu_search_plugin_uses_agent_owned_base_url(tmp_path):
    from xiaomei_brain.plugins.tools.web_search_baidu import adapter

    context = FakePluginContext({
        "enabled": True,
        "api_key": "baidu-secret",
        "base_url": "https://search.example.com/",
    }, tmp_path)

    adapter.register(context)

    assert context.providers[0].base_url == "https://search.example.com"


def test_disabled_provider_plugins_register_nothing(tmp_path):
    from xiaomei_brain.plugins.tools.music_minimax import adapter as music
    from xiaomei_brain.plugins.tools.tts_minimax import adapter as tts
    from xiaomei_brain.plugins.tools.web_search_baidu import adapter as baidu

    tts_context = FakePluginContext({"enabled": False}, tmp_path)
    music_context = FakePluginContext({"enabled": False}, tmp_path)
    baidu_context = FakePluginContext({"enabled": False}, tmp_path)

    tts.register(tts_context)
    music.register(music_context)
    baidu.register(baidu_context)

    assert tts_context.tools == []
    assert music_context.tools == []
    assert baidu_context.providers == []
