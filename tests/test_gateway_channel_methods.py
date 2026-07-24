from __future__ import annotations

from types import SimpleNamespace

from xiaomei_brain.channels import ChannelConfigurationService
from xiaomei_brain.gateway.methods.channels import ChannelMethods
from xiaomei_brain.people import IdentityLinkService, PeopleService, PeopleStore


class FakeAdapter:
    def status(self):
        return {"state": "running", "error": ""}


class FakeRuntime:
    def __init__(self):
        self.applied = None

    def apply_feishu(self, config):
        self.applied = config
        return FakeAdapter()

    def status(self, _channel):
        return {"state": "running" if self.applied else "stopped", "error": ""}

    def remove(self, _channel):
        removed = self.applied is not None
        self.applied = None
        return removed


def test_channel_rpc_configures_current_agent_and_begins_person_link(tmp_path):
    people = PeopleService(PeopleStore(tmp_path / "brain.db"))
    person = people.create_person("测试人物")
    living = SimpleNamespace(
        _channel_configuration=ChannelConfigurationService("xiaomei", tmp_path),
        _channel_runtime=FakeRuntime(),
        _identity_link_service=IdentityLinkService(people),
        _people_service=people,
    )
    methods = ChannelMethods(
        living,
        {"desktop": SimpleNamespace(person_id=person.person_id)},
    )

    configured = methods.handle_configure("desktop", "1", {
        "channel": "feishu",
        "app_id": "cli_demo",
        "app_secret": "secret",
        "display_name": "小美飞书机器人",
        "account_id": "default",
    })
    assert configured["result"]["configured"] is True
    assert living._channel_runtime.applied["appSecret"] == "secret"
    assert "appSecret" not in configured["result"]["config"]

    link = methods.handle_link_begin("desktop", "2", {"provider": "feishu"})
    assert link["result"]["command"].startswith("绑定 ")
    assert link["result"]["status"] == "pending"

    code = link["result"]["command"].split()[-1]
    living._identity_link_service.consume(
        "feishu",
        "feishu:app:cli_demo",
        "ou_sender_1234567890",
        code,
    )
    listed = methods.handle_link_list("desktop", "3", {"provider": "feishu"})
    assert len(listed["result"]["bindings"]) == 1
    binding = listed["result"]["bindings"][0]
    assert binding["subject_hint"] == "ou_sen…7890"
    assert "ou_sender_1234567890" not in str(listed)

    revoked = methods.handle_link_revoke("desktop", "4", {
        "provider": "feishu",
        "binding_id": binding["binding_id"],
    })
    assert revoked["result"]["revoked"] is True
    assert methods.handle_link_list(
        "desktop", "5", {"provider": "feishu"},
    )["result"]["bindings"] == []


def test_channel_rpc_does_not_return_configured_secret(tmp_path):
    living = SimpleNamespace(
        _channel_configuration=ChannelConfigurationService("xiaomei", tmp_path),
        _channel_runtime=FakeRuntime(),
        _identity_link_service=None,
        _people_service=None,
    )
    living._channel_configuration.configure_feishu("cli_demo", "do-not-return")
    methods = ChannelMethods(living, {})

    response = methods.handle_get("desktop", "1", {"channel": "feishu"})
    config = response["result"]["config"]
    assert config["secret_configured"] is True
    assert "do-not-return" not in str(response)
