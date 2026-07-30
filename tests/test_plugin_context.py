from pathlib import Path

from xiaomei_brain.plugin.context import PluginContext


def test_agent_dir_uses_platform_native_path(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    context = PluginContext(
        config={},
        plugin_name="test-plugin",
        agent_id="xiaomei",
        registry=object(),
    )

    assert context.agent_dir == str(tmp_path / ".xiaomei-brain" / "xiaomei")
