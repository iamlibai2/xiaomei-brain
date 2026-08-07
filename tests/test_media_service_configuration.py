from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from xiaomei_brain.gateway.methods.media import MediaServiceMethods
from xiaomei_brain.media import (
    MediaServiceConfigurationError,
    MediaServiceConfigurationService,
    discover_media_service_specs,
    inspect_media_runtime,
)
from xiaomei_brain.plugin.bootstrap import _extract_plugins_config


def test_catalog_discovers_all_built_in_media_capabilities():
    specs = discover_media_service_specs()

    assert specs["image_minimax"].capability == "image"
    assert specs["image_seedream"].capability == "image"
    assert specs["tts_minimax"].capability == "tts"
    assert specs["tts_voxcpm"].capability == "tts"
    assert specs["tts_voxcpm"].connection_kind == "local"
    assert specs["tts_voxcpm"].default_enabled is True
    assert specs["music_minimax"].capability == "music"
    assert specs["video_minimax"].capability == "video"
    assert specs["video_minimax"].models == (
        "MiniMax-H3",
        "MiniMax-Hailuo-2.3",
    )
    assert specs["tts_minimax"].field("voice_id").default == "female-tianmei"
    assert specs["music_minimax"].field("model").default == "music-3.0"


def test_catalog_discovers_third_party_service_from_manifest(tmp_path):
    plugin_dir = tmp_path / "audio_demo"
    plugin_dir.mkdir()
    (plugin_dir / "plugin.yaml").write_text(
        """
name: audio_demo
version: "1.0.0"
description: Demo TTS
kind: bundle
entry: adapter:register
mediaProvider:
  id: tts_demo
  capability: tts
  vendor: demo
  displayName: Demo TTS
  fields:
    - key: api_key
      label: API Key
      type: secret
      required: true
    - key: base_url
      label: Base URL
      type: text
      default: https://audio.example.com
  test:
    path: /speak
    body: {}
""".strip(),
        encoding="utf-8",
    )

    specs = discover_media_service_specs([str(tmp_path)])

    assert specs["tts_demo"].plugin == "audio_demo"
    assert specs["tts_demo"].field("base_url").default == "https://audio.example.com"


def test_configure_services_preserves_agent_config_and_masks_secrets(tmp_path):
    agent_dir = tmp_path / "xiaomei"
    agent_dir.mkdir()
    (agent_dir / "config.json").write_text(
        json.dumps({"name": "小美", "model": {"primary": "demo/model"}}),
        encoding="utf-8",
    )
    service = MediaServiceConfigurationService("xiaomei", tmp_path)

    image = service.configure(
        "image_minimax",
        config={"api_key": "image-secret"},
    )
    tts = service.configure(
        "tts_minimax",
        config={
            "api_key": "tts-secret",
            "model": "speech-2.8-hd",
            "voice_id": "female-tianmei",
            "speed": 1.2,
        },
    )

    saved = json.loads((agent_dir / "config.json").read_text(encoding="utf-8"))
    assert saved["name"] == "小美"
    assert saved["model"] == {"primary": "demo/model"}
    entries = saved["plugins"]["entries"]
    assert entries["image_minimax"]["api_key"] == "image-secret"
    assert entries["tts_minimax"]["voice_id"] == "female-tianmei"
    assert image["secret_configured"] is True
    assert tts["values"]["speed"] == 1.2
    assert "image-secret" not in str(image)
    assert "tts-secret" not in str(tts)


def test_existing_secret_is_preserved_and_defaults_are_not_duplicated(tmp_path):
    service = MediaServiceConfigurationService("xiaomei", tmp_path)
    service.configure(
        "music_minimax",
        config={"api_key": "keep-secret", "model": "music-2.6"},
    )
    service.configure(
        "music_minimax",
        config={"api_key": "", "format": "wav"},
    )

    raw = service.raw_entry("music_minimax")
    assert raw["api_key"] == "keep-secret"
    assert raw["format"] == "wav"
    assert "base_url" not in raw


def test_legacy_root_media_settings_move_to_each_known_agent(tmp_path):
    for agent_id in ("xiaomei", "xiaoming"):
        agent_dir = tmp_path / agent_id
        agent_dir.mkdir()
        (agent_dir / "identity.md").write_text(f"# {agent_id}", encoding="utf-8")
    (tmp_path / "config.json").write_text(
        json.dumps({
            "xiaomei_brain": {
                "image": {
                    "enabled": True,
                    "api_key": "image-secret",
                    "base_url": "https://api.minimaxi.com",
                },
                "tts": {
                    "enabled": True,
                    "api_key": "audio-secret",
                    "voice_id": "voice-demo",
                },
                "music": {
                    "enabled": True,
                    "api_key": "",
                    "format": "wav",
                },
            },
        }),
        encoding="utf-8",
    )

    MediaServiceConfigurationService("xiaomei", tmp_path)

    for agent_id in ("xiaomei", "xiaoming"):
        saved = json.loads(
            (tmp_path / agent_id / "config.json").read_text(encoding="utf-8"),
        )
        entries = saved["plugins"]["entries"]
        assert entries["image_minimax"]["api_key"] == "image-secret"
        assert "base_url" not in entries["image_minimax"]
        assert entries["tts_minimax"]["api_key"] == "audio-secret"
        assert entries["tts_minimax"]["voice_id"] == "voice-demo"
        assert entries["music_minimax"]["api_key"] == "audio-secret"
        assert entries["music_minimax"]["format"] == "wav"

    global_saved = json.loads(
        (tmp_path / "config.json").read_text(encoding="utf-8"),
    )
    root = global_saved["xiaomei_brain"]
    assert "image" not in root
    assert "tts" not in root
    assert "music" not in root


def test_list_can_filter_by_capability(tmp_path):
    service = MediaServiceConfigurationService("xiaomei", tmp_path)

    result = service.list("tts")

    assert [item["id"] for item in result["services"]] == [
        "tts_minimax",
        "tts_voxcpm",
    ]


def test_local_media_service_uses_defaults_and_can_be_disabled(tmp_path):
    service = MediaServiceConfigurationService("xiaomei", tmp_path)

    current = service.get("tts_voxcpm")
    assert current["configured"] is True
    assert current["enabled"] is True
    assert current["secret_configured"] is False
    assert current["connection_kind"] == "local"

    assert service.remove("tts_voxcpm") is True
    disabled = service.get("tts_voxcpm")
    assert disabled["enabled"] is False
    assert disabled["configured"] is False


def test_local_media_service_accepts_running_local_server(tmp_path, monkeypatch):
    service = MediaServiceConfigurationService("xiaomei", tmp_path)
    monkeypatch.setattr(
        "xiaomei_brain.media.configuration.requests.request",
        lambda *args, **kwargs: SimpleNamespace(status_code=200, text="ok"),
    )

    result = service.test("tts_voxcpm", config={})

    assert result["ok"] is True
    assert result["mode"] == "local_service"


def test_numeric_fields_are_validated(tmp_path):
    service = MediaServiceConfigurationService("xiaomei", tmp_path)

    with pytest.raises(MediaServiceConfigurationError, match="语速"):
        service.configure(
            "tts_minimax",
            config={"api_key": "secret", "speed": 9},
        )


def test_connection_test_uses_plugin_owned_endpoint(tmp_path, monkeypatch):
    service = MediaServiceConfigurationService("xiaomei", tmp_path)
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return SimpleNamespace(status_code=400, text="")

    monkeypatch.setattr(
        "xiaomei_brain.media.configuration.requests.request",
        fake_request,
    )
    result = service.test(
        "tts_minimax",
        config={"api_key": "secret"},
    )

    assert result["ok"] is True
    assert calls[0][0] == "POST"
    assert calls[0][1] == "https://api.minimaxi.com/v1/t2a_v2"
    assert calls[0][2]["json"]["model"] == "speech-2.8-hd"


def test_connection_test_rejects_unauthorized_credentials(tmp_path, monkeypatch):
    service = MediaServiceConfigurationService("xiaomei", tmp_path)
    monkeypatch.setattr(
        "xiaomei_brain.media.configuration.requests.request",
        lambda *args, **kwargs: SimpleNamespace(status_code=401, text=""),
    )

    with pytest.raises(MediaServiceConfigurationError, match="API Key"):
        service.test("image_seedream", config={"api_key": "bad"})


def test_gateway_media_methods_never_return_secret(tmp_path):
    living = SimpleNamespace(
        _agent_id="xiaomei",
        _media_service_configuration=MediaServiceConfigurationService(
            "xiaomei",
            tmp_path,
        ),
    )
    methods = MediaServiceMethods(living)

    configured = methods.handle_configure("desktop", "1", {
        "service_id": "music_minimax",
        "config": {"api_key": "rpc-secret", "model": "music-2.6"},
        "enabled": True,
    })
    listed = methods.handle_list("desktop", "2", {})

    assert configured["result"]["restart_required"] is True
    assert "rpc-secret" not in str(configured)
    assert "rpc-secret" not in str(listed)


def test_media_runtime_reports_deterministic_tool_status(monkeypatch):
    monkeypatch.setattr(
        "xiaomei_brain.media.runtime.shutil.which",
        lambda command: f"/tools/{command}",
    )
    monkeypatch.setattr(
        "xiaomei_brain.media.runtime.subprocess.run",
        lambda args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout=f"{args[0]} version 1.0\n",
        ),
    )

    result = inspect_media_runtime()

    assert result["ready"] is True
    assert [item["id"] for item in result["tools"]] == ["ffmpeg", "ffprobe"]
    assert all(item["available"] for item in result["tools"])


def test_media_runtime_does_not_treat_version_timeout_as_missing(monkeypatch):
    import subprocess

    monkeypatch.setattr(
        "xiaomei_brain.media.runtime.shutil.which",
        lambda command: f"/tools/{command}",
    )
    monkeypatch.setattr(
        "xiaomei_brain.media.runtime.subprocess.run",
        lambda args, **kwargs: (_ for _ in ()).throw(
            subprocess.TimeoutExpired(args, kwargs.get("timeout", 0)),
        ),
    )

    result = inspect_media_runtime()

    assert result["ready"] is True
    assert all(item["available"] for item in result["tools"])
    assert all(item["error"] == "版本检测超时" for item in result["tools"])


def test_plugin_bootstrap_passes_explicit_media_entries(monkeypatch):
    monkeypatch.setattr(
        "xiaomei_brain.plugin.bootstrap._read_merged_config",
        lambda _agent_id="": {
            "plugins": {
                "entries": {
                    "tts_minimax": {
                        "enabled": True,
                        "api_key": "plugin-secret",
                    },
                },
            },
        },
    )

    config = _extract_plugins_config("")

    assert config["entries"]["tts_minimax"]["api_key"] == "plugin-secret"


@pytest.mark.parametrize(
    ("module_name", "expected_tool"),
    [
        ("xiaomei_brain.plugins.tools.image_minimax.adapter", "generate_image_minimax"),
        ("xiaomei_brain.plugins.tools.image_seedream.adapter", "generate_image_seedream"),
        ("xiaomei_brain.plugins.tools.music_minimax.adapter", "generate_music"),
        ("xiaomei_brain.plugins.tools.video_minimax.adapter", "generate_video_minimax"),
    ],
)
def test_configured_media_service_registers_its_tool(
    tmp_path,
    module_name,
    expected_tool,
):
    import importlib

    registered = []
    context = SimpleNamespace(
        config={"enabled": True, "api_key": "secret"},
        agent_dir=str(tmp_path),
        logger=SimpleNamespace(info=lambda *args, **kwargs: None),
        register_agent_tool=registered.append,
    )

    importlib.import_module(module_name).register(context)

    assert expected_tool in [tool.name for tool in registered]
