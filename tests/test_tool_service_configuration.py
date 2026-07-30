from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from xiaomei_brain.gateway.methods.tools import ToolServiceMethods
from xiaomei_brain.tool_services import (
    ToolServiceConfigurationError,
    ToolServiceConfigurationService,
    discover_tool_service_specs,
)


def test_catalog_discovers_baidu_web_search_service():
    specs = discover_tool_service_specs()

    assert specs["web_search_baidu"].capability == "web_search"
    assert specs["web_search_baidu"].plugin == "web_search_baidu"
    assert (
        specs["web_search_baidu"].field("base_url").default
        == "https://qianfan.baidubce.com/v2/ai_search"
    )


def test_config_is_agent_owned_and_secret_is_never_returned(tmp_path):
    agent_dir = tmp_path / "xiaomei"
    agent_dir.mkdir()
    (agent_dir / "config.json").write_text(
        json.dumps({"name": "小美"}),
        encoding="utf-8",
    )
    service = ToolServiceConfigurationService("xiaomei", tmp_path)

    configured = service.configure(
        "web_search_baidu",
        config={"api_key": "baidu-secret"},
    )

    saved = json.loads((agent_dir / "config.json").read_text(encoding="utf-8"))
    entry = saved["plugins"]["entries"]["web_search_baidu"]
    assert saved["name"] == "小美"
    assert entry["api_key"] == "baidu-secret"
    assert "base_url" not in entry
    assert configured["secret_configured"] is True
    assert "baidu-secret" not in str(configured)


def test_existing_secret_is_preserved_when_editing(tmp_path):
    service = ToolServiceConfigurationService("xiaomei", tmp_path)
    service.configure(
        "web_search_baidu",
        config={"api_key": "keep-secret"},
    )
    service.configure(
        "web_search_baidu",
        config={"api_key": "", "base_url": "https://search.example.com"},
    )

    entry = service.raw_entry("web_search_baidu")
    assert entry["api_key"] == "keep-secret"
    assert entry["base_url"] == "https://search.example.com"


def test_legacy_root_search_moves_to_each_known_agent(tmp_path):
    for agent_id in ("xiaomei", "xiaoming"):
        agent_dir = tmp_path / agent_id
        agent_dir.mkdir()
        (agent_dir / "identity.md").write_text(agent_id, encoding="utf-8")
    (tmp_path / "config.json").write_text(
        json.dumps({
            "xiaomei_brain": {
                "web_search": {
                    "enabled": True,
                    "baidu_api_key": "legacy-secret",
                },
            },
        }),
        encoding="utf-8",
    )

    ToolServiceConfigurationService("xiaomei", tmp_path)

    for agent_id in ("xiaomei", "xiaoming"):
        saved = json.loads(
            (tmp_path / agent_id / "config.json").read_text(encoding="utf-8"),
        )
        entry = saved["plugins"]["entries"]["web_search_baidu"]
        assert entry == {"enabled": True, "api_key": "legacy-secret"}
    global_saved = json.loads(
        (tmp_path / "config.json").read_text(encoding="utf-8"),
    )
    assert "web_search" not in global_saved["xiaomei_brain"]


def test_connection_test_uses_manifest_endpoint(tmp_path, monkeypatch):
    calls = []
    service = ToolServiceConfigurationService("xiaomei", tmp_path)

    def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return SimpleNamespace(status_code=200, text='{"references": []}')

    monkeypatch.setattr(
        "xiaomei_brain.tool_services.configuration.requests.request",
        fake_request,
    )
    result = service.test(
        "web_search_baidu",
        config={"api_key": "secret"},
    )

    assert result["ok"] is True
    assert calls[0][0] == "POST"
    assert calls[0][1].endswith("/v2/ai_search/web_search")
    assert calls[0][2]["json"]["resource_type_filter"][0]["top_k"] == 1


def test_connection_test_rejects_bad_credentials(tmp_path, monkeypatch):
    service = ToolServiceConfigurationService("xiaomei", tmp_path)
    monkeypatch.setattr(
        "xiaomei_brain.tool_services.configuration.requests.request",
        lambda *args, **kwargs: SimpleNamespace(status_code=401, text=""),
    )

    with pytest.raises(ToolServiceConfigurationError, match="API Key"):
        service.test("web_search_baidu", config={"api_key": "bad"})


def test_connection_test_rejects_provider_error_in_success_response(
    tmp_path,
    monkeypatch,
):
    service = ToolServiceConfigurationService("xiaomei", tmp_path)
    monkeypatch.setattr(
        "xiaomei_brain.tool_services.configuration.requests.request",
        lambda *args, **kwargs: SimpleNamespace(
            status_code=200,
            text='{"code": 100, "message": "invalid credential"}',
        ),
    )

    with pytest.raises(ToolServiceConfigurationError, match="invalid credential"):
        service.test("web_search_baidu", config={"api_key": "bad"})


def test_gateway_tool_service_methods_never_return_secret(tmp_path):
    living = SimpleNamespace(
        _agent_id="xiaomei",
        _tool_service_configuration=ToolServiceConfigurationService(
            "xiaomei",
            tmp_path,
        ),
    )
    methods = ToolServiceMethods(living)

    configured = methods.handle_configure("desktop", "1", {
        "service_id": "web_search_baidu",
        "config": {"api_key": "rpc-secret"},
        "enabled": True,
    })
    listed = methods.handle_list("desktop", "2", {"capability": "web_search"})

    assert configured["result"]["restart_required"] is True
    assert "rpc-secret" not in str(configured)
    assert "rpc-secret" not in str(listed)
