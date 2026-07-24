from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from jsonschema import validate

from xiaomei_brain.channels import ChannelConfigurationService


def test_configure_feishu_preserves_other_agent_config(tmp_path):
    agent_dir = tmp_path / "xiaomei"
    agent_dir.mkdir()
    (agent_dir / "config.json").write_text(
        json.dumps({"name": "小美", "model": {"primary": "demo/model"}}),
        encoding="utf-8",
    )
    service = ChannelConfigurationService("xiaomei", tmp_path)

    result = service.configure_feishu(
        "cli_app",
        "secret-value",
        display_name="小美飞书机器人",
    )

    saved = json.loads((agent_dir / "config.json").read_text(encoding="utf-8"))
    assert saved["name"] == "小美"
    assert saved["model"] == {"primary": "demo/model"}
    assert saved["channels"]["feishu"]["accounts"]["default"]["appSecret"] == "secret-value"
    assert saved["bindings"] == [{
        "agentId": "xiaomei",
        "match": {"channel": "feishu", "accountId": "default"},
    }]
    assert result["secret_configured"] is True
    assert "app_secret" not in result


def test_same_feishu_app_cannot_be_bound_to_two_agents(tmp_path):
    first = ChannelConfigurationService("xiaomei", tmp_path)
    second = ChannelConfigurationService("xiaoming", tmp_path)
    first.configure_feishu("cli_shared", "one")

    with pytest.raises(ValueError, match="xiaomei"):
        second.configure_feishu("cli_shared", "two")


def test_remove_channel_preserves_unrelated_bindings(tmp_path):
    service = ChannelConfigurationService("xiaomei", tmp_path)
    service.configure_feishu("cli_app", "secret")
    path = tmp_path / "xiaomei" / "config.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["bindings"].append({
        "agentId": "xiaomei",
        "match": {"channel": "dingtalk", "accountId": "default"},
    })
    path.write_text(json.dumps(data), encoding="utf-8")

    assert service.remove("feishu") is True
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert "feishu" not in saved["channels"]
    assert saved["bindings"] == [{
        "agentId": "xiaomei",
        "match": {"channel": "dingtalk", "accountId": "default"},
    }]


def test_desktop_feishu_config_matches_plugin_schema(tmp_path):
    service = ChannelConfigurationService("xiaomei", tmp_path)
    service.configure_feishu(
        "cli_app",
        "secret",
        display_name="小美飞书机器人",
        account_id="default",
    )
    manifest_path = (
        Path(__file__).parents[1]
        / "src/xiaomei_brain/plugins/channels/feishu/plugin.yaml"
    )
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))

    validate(
        instance=service.raw_account("feishu"),
        schema=manifest["configSchema"],
    )
