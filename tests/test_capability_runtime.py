from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from xiaomei_brain.capabilities import (
    CapabilityManifestLoader,
    CapabilityRuntimeRegistry,
)
from xiaomei_brain.external_accounts import ExternalAccountStore
from xiaomei_brain.plugin.context import PluginContext
from xiaomei_brain.plugin.loader import PluginLoader
from xiaomei_brain.plugin.registry import PluginRegistry
from xiaomei_brain.plugins.runtimes.feishu_office.adapter import register as register_feishu_runtime
from xiaomei_brain.plugins.runtimes.feishu_office.runtime import FeishuOfficeRuntime
from xiaomei_brain.plugins.runtimes.gmail_workspace.adapter import register as register_gmail_runtime
from xiaomei_brain.plugins.runtimes.gmail_workspace.runtime import GmailRuntime
from xiaomei_brain.skills.sources.base import SourceBundle


class _Skills:
    def list_names(self):
        return ["lark-shared", "lark-calendar", "unrelated"]


def test_feishu_plugin_registers_runtime_factory(tmp_path):
    plugins = PluginRegistry()
    register_feishu_runtime(PluginContext({}, "feishu-runtime", "test", plugins))
    registry = CapabilityRuntimeRegistry()
    registry.register_factories(plugins.get_runtime_factories())

    runtimes = registry.create_all(agent_dir=tmp_path / "agent")

    assert isinstance(runtimes["feishu_office"], FeishuOfficeRuntime)


def test_gmail_plugin_uses_platform_external_account_store(tmp_path):
    plugins = PluginRegistry()
    register_gmail_runtime(PluginContext({}, "gmail-runtime", "test", plugins))
    registry = CapabilityRuntimeRegistry()
    registry.register_factories(plugins.get_runtime_factories())
    store = ExternalAccountStore(
        tmp_path / "agent" / "memory" / "brain.db",
        tmp_path / "agent" / "secrets" / "external-accounts.key",
    )

    runtimes = registry.create_all(
        agent_dir=tmp_path / "agent",
        external_accounts=store,
    )

    assert isinstance(runtimes["gmail"], GmailRuntime)
    assert runtimes["gmail"].account_store is store


def test_plugin_loader_discovers_feishu_runtime_plugin():
    plugins = PluginRegistry()
    loader = PluginLoader(plugins, agent_id="test")
    runtime_plugins = Path(__file__).parents[1] / "src" / "xiaomei_brain" / "plugins" / "runtimes"

    loaded = loader.boot([str(runtime_plugins)])

    assert [item.manifest.name for item in loaded] == [
        "feishu_office_runtime",
        "gmail_workspace",
    ]
    assert all(item.status == "loaded" for item in loaded)
    assert "feishu_office" in plugins.get_runtime_factories()
    assert "gmail" in plugins.get_runtime_factories()


def test_feishu_capability_only_references_runtime_probe():
    definition = next(
        item for item in CapabilityManifestLoader().load()
        if item.id == "feishu_office"
    )

    assert any(
        component.kind == "runtime_probe"
        and component.target == "feishu_office"
        for component in definition.components
    )


def test_broken_runtime_does_not_prevent_agent_capabilities_from_loading(tmp_path):
    registry = CapabilityRuntimeRegistry()

    def broken_factory(**_dependencies):
        raise RuntimeError("broken factory")

    registry.register_factories({"broken": broken_factory})
    runtimes = registry.create_all(agent_dir=tmp_path / "agent")

    state = runtimes["broken"].inspect("person-a")
    assert state.available is False
    assert state.code == "component_error"


def test_feishu_runtime_reports_missing_shared_executable(tmp_path, monkeypatch):
    runtime = FeishuOfficeRuntime(tmp_path / "agent", skill_loader=_Skills())
    monkeypatch.setattr(runtime, "executable", lambda: None)

    state = runtime.inspect("person-a")

    assert state.available is False
    assert state.code == "runtime_missing"
    assert state.actions == ("install",)
    assert state.details["skill_count"] == 2


def test_feishu_runtime_does_not_claim_host_cli_inside_docker(tmp_path, monkeypatch):
    runtime = FeishuOfficeRuntime(
        tmp_path / "agent",
        skill_loader=_Skills(),
        execution_environment=SimpleNamespace(backend="docker"),
    )
    monkeypatch.setattr(runtime, "executable", lambda: "lark-cli")

    state = runtime.inspect("person-a")

    assert state.available is False
    assert state.code == "runtime_unavailable"
    assert state.actions == ()


def test_feishu_runtime_uses_shared_config_with_person_profiles(tmp_path):
    runtime = FeishuOfficeRuntime(tmp_path / "agent")

    first = runtime.environment("person-a")
    second = runtime.environment("person-b")

    assert first["LARKSUITE_CLI_CONFIG_DIR"] == second["LARKSUITE_CLI_CONFIG_DIR"]
    assert first["LARKSUITE_CLI_PROFILE"] != second["LARKSUITE_CLI_PROFILE"]
    assert Path(first["LARKSUITE_CLI_CONFIG_DIR"]).is_dir()
    assert Path(first["LARKSUITE_CLI_CONFIG_DIR"]).is_relative_to(tmp_path / "agent")


def test_feishu_runtime_commands_always_name_the_person_profile(tmp_path, monkeypatch):
    runtime = FeishuOfficeRuntime(tmp_path / "agent")
    monkeypatch.setattr(runtime, "executable", lambda: "lark-cli")
    profile = runtime.profile_name("person-a")

    assert runtime._command("configure", "person-a")[-2:] == ["--name", profile]
    assert runtime._command("authorize", "person-a")[1:3] == ["--profile", profile]
    assert runtime._command("disconnect", "person-a")[1:3] == ["--profile", profile]


def test_feishu_runtime_removes_other_agent_detection_markers(tmp_path):
    runtime = FeishuOfficeRuntime(tmp_path / "agent")
    environment = {
        "HERMES_HOME": "hermes-root",
        "OPENCLAW_HOME": "openclaw-root",
        "LARK_CHANNEL": "1",
        "PATH": "keep-me",
    }

    runtime._remove_foreign_agent_context(environment)

    assert environment == {"PATH": "keep-me"}


def test_feishu_runtime_reuses_configured_channel_app_without_exposing_secret(tmp_path, monkeypatch):
    runtime = FeishuOfficeRuntime(
        tmp_path / "agent",
        app_config={"appId": "cli_shared", "appSecret": "private-secret"},
    )
    monkeypatch.setattr(runtime, "executable", lambda: "lark-cli")

    command = runtime._command("configure", "person-a")

    assert command[:3] == ["lark-cli", "config", "init"]
    assert command[command.index("--app-id") + 1] == "cli_shared"
    assert "private-secret" not in command
    assert runtime._command_stdin("configure") == "private-secret\n"


def test_feishu_runtime_prefers_desktop_bundled_executable(tmp_path, monkeypatch):
    executable = tmp_path / "lark-cli.exe"
    executable.write_bytes(b"binary")
    monkeypatch.setenv("XIAOMEI_BRAIN_LARK_CLI", str(executable))

    assert FeishuOfficeRuntime.executable() == str(executable.resolve())


def test_feishu_runtime_writes_skill_bundle_atomically(tmp_path):
    root = tmp_path / "skills"
    root.mkdir()
    bundle = SourceBundle(
        content="---\nname: lark-shared\n---\nUse lark-cli.",
        source="github",
        identifier="larksuite/cli/skills/lark-shared:v1.0.84",
        resolved_url="https://example.test/SKILL.md",
        files={"references/auth.md": "Authenticate first."},
    )

    FeishuOfficeRuntime._write_skill_bundle(root, "lark-shared", bundle)

    assert (root / "lark-shared" / "SKILL.md").read_text(encoding="utf-8").endswith("Use lark-cli.")
    assert (root / "lark-shared" / "references" / "auth.md").read_text(encoding="utf-8") == "Authenticate first."


def test_feishu_runtime_reads_authenticated_json_status(tmp_path, monkeypatch):
    runtime = FeishuOfficeRuntime(tmp_path / "agent", skill_loader=_Skills())
    runtime.workspace.mkdir(parents=True)
    monkeypatch.setattr(runtime, "executable", lambda: "lark-cli")

    payload = {
        "authenticated": True,
        "name": "李白",
        "email": "libai@example.com",
        "scopes": ["calendar:calendar:read"],
    }
    completed = SimpleNamespace(
        returncode=0,
        stdout=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
    )
    commands = []
    environments = []
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "foreign-hermes"))

    def run(command, **kwargs):
        commands.append(command)
        environments.append(kwargs["env"])
        return completed

    monkeypatch.setattr("subprocess.run", run)

    state = runtime.inspect("person-a")

    assert state.available is True
    assert state.code == "ready"
    assert state.details["authenticated"] is True
    assert state.details["name"] == "李白"
    assert state.details["scopes"] == ["calendar:calendar:read"]
    assert commands[0][1:3] == ["--profile", runtime.profile_name("person-a")]
    assert commands[0][-1] == "--json"
    assert "HERMES_HOME" not in environments[0]


def test_feishu_runtime_does_not_treat_error_json_as_authenticated(tmp_path, monkeypatch):
    runtime = FeishuOfficeRuntime(tmp_path / "agent", skill_loader=_Skills())
    runtime.workspace.mkdir(parents=True)
    monkeypatch.setattr(runtime, "executable", lambda: "lark-cli")
    completed = SimpleNamespace(
        returncode=0,
        stdout=b'{"authenticated": false, "reason": "no local token"}',
    )
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: completed)

    state = runtime.inspect("person-a")

    assert state.available is False
    assert state.code == "authorization_required"
    assert state.details["authenticated"] is False


def test_feishu_runtime_reads_current_nested_identity_status(tmp_path, monkeypatch):
    runtime = FeishuOfficeRuntime(tmp_path / "agent", skill_loader=_Skills())
    runtime.workspace.mkdir(parents=True)
    monkeypatch.setattr(runtime, "executable", lambda: "lark-cli")
    completed = SimpleNamespace(
        returncode=0,
        stdout=json.dumps({
            "appId": "cli_demo",
            "identities": {
                "bot": {"status": "not_configured", "available": False},
                "user": {
                    "status": "ready",
                    "available": True,
                    "openId": "ou_demo",
                    "userName": "李白",
                    "tokenStatus": "valid",
                    "scope": "docs:document.content:read offline_access",
                    "expiresAt": "2026-08-07T06:44:38+08:00",
                },
            },
            "identity": "user",
        }, ensure_ascii=False).encode("utf-8"),
    )
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: completed)

    state = runtime.inspect("person-a")

    assert state.available is True
    assert state.code == "ready"
    assert state.details["name"] == "李白"
    assert state.details["user_id"] == "ou_demo"
    assert state.details["scopes"] == [
        "docs:document.content:read",
        "offline_access",
    ]
