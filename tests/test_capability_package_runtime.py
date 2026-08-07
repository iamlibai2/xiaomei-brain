from __future__ import annotations

from pathlib import Path

from scripts.create_sample_capability_package import create_package
from xiaomei_brain.capabilities.loader import CapabilityManifestLoader
from xiaomei_brain.capabilities.runtime_registry import CapabilityRuntimeRegistry
from xiaomei_brain.capability_packages import CapabilityPackageService
from xiaomei_brain.plugin.loader import PluginLoader
from xiaomei_brain.plugin.registry import PluginRegistry
from xiaomei_brain.skills.loader import SkillLoader


def write_external_plugin(root: Path, *, result: str) -> Path:
    plugin_dir = root / "plugins" / "xmcap_text_statistics"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.yaml").write_text(
        "\n".join([
            "name: xmcap_text_statistics",
            "version: 1.0.0",
            "description: external test plugin",
            "kind: tool",
            "entry: adapter:register",
            "provides_tools:",
            "  - package_text_statistics",
        ]),
        encoding="utf-8",
    )
    (plugin_dir / "tool.py").write_text(
        "from xiaomei_brain.tools.base import tool\n"
        "@tool(name='package_text_statistics', description='test')\n"
        "def package_text_statistics(text: str) -> str:\n"
        f"    return {result!r} + ':' + str(len(text))\n",
        encoding="utf-8",
    )
    (plugin_dir / "adapter.py").write_text(
        "from .tool import package_text_statistics\n"
        "def register(ctx):\n"
        "    package_text_statistics.source = 'plugin:xmcap_text_statistics'\n"
        "    ctx.register_agent_tool(package_text_statistics)\n",
        encoding="utf-8",
    )
    return root / "plugins"


def write_external_runtime_plugin(root: Path) -> Path:
    plugin_dir = root / "plugins" / "xmcap_runtime"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.yaml").write_text(
        "\n".join([
            "name: xmcap_runtime",
            "version: 1.0.0",
            "description: external runtime plugin",
            "kind: runtime",
            "entry: adapter:register",
        ]),
        encoding="utf-8",
    )
    (plugin_dir / "runtime.py").write_text(
        "class Runtime:\n"
        "    capability_id = 'xmcap_runtime'\n"
        "    def __init__(self, agent_dir):\n"
        "        self.agent_dir = str(agent_dir)\n"
        "def create_runtime(*, capability_id, agent_dir, **_dependencies):\n"
        "    assert capability_id == 'xmcap_runtime'\n"
        "    return Runtime(agent_dir)\n",
        encoding="utf-8",
    )
    (plugin_dir / "adapter.py").write_text(
        "from .runtime import create_runtime\n"
        "def register(ctx):\n"
        "    ctx.register_runtime('xmcap_runtime', create_runtime)\n",
        encoding="utf-8",
    )
    return root / "plugins"


def test_external_plugin_supports_relative_imports_without_sys_path(tmp_path: Path):
    plugin_root = write_external_plugin(tmp_path / "package-a", result="package-a")
    registry = PluginRegistry()

    loaded = PluginLoader(registry=registry, agent_id="test").boot([str(plugin_root)])

    assert loaded[0].status == "loaded"
    tool = registry.get_agent_tools()[0]
    assert tool.name == "package_text_statistics"
    assert tool.execute(text="abcd") == "package-a:4"
    assert list(plugin_root.rglob("*.pyc")) == []


def test_external_plugin_namespaces_are_derived_from_install_path(tmp_path: Path):
    first_root = write_external_plugin(tmp_path / "package-a", result="package-a")
    second_root = write_external_plugin(tmp_path / "package-b", result="package-b")
    first_registry = PluginRegistry()
    second_registry = PluginRegistry()

    PluginLoader(first_registry, agent_id="a").boot([str(first_root)])
    PluginLoader(second_registry, agent_id="b").boot([str(second_root)])

    assert first_registry.get_agent_tools()[0].execute(text="x") == "package-a:1"
    assert second_registry.get_agent_tools()[0].execute(text="x") == "package-b:1"


def test_external_plugin_entry_cannot_escape_package_directory(tmp_path: Path):
    plugin_root = write_external_plugin(tmp_path / "package-a", result="package-a")
    manifest = plugin_root / "xmcap_text_statistics" / "plugin.yaml"
    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace(
            "entry: adapter:register",
            "entry: ../../outside:register",
        ),
        encoding="utf-8",
    )
    registry = PluginRegistry()

    loaded = PluginLoader(registry=registry, agent_id="test").boot([str(plugin_root)])

    assert loaded[0].status == "error"
    assert registry.get_agent_tools() == []


def test_external_package_plugin_can_register_managed_runtime(tmp_path: Path):
    plugin_root = write_external_runtime_plugin(tmp_path / "package-runtime")
    plugins = PluginRegistry()

    loaded = PluginLoader(plugins, agent_id="test").boot([str(plugin_root)])
    runtimes = CapabilityRuntimeRegistry()
    runtimes.register_factories(plugins.get_runtime_factories())
    created = runtimes.create_all(agent_dir=tmp_path / "agent")

    assert loaded[0].status == "loaded"
    assert created["xmcap_runtime"].agent_dir == str(tmp_path / "agent")


def test_runnable_sample_package_is_isolated_per_agent(tmp_path: Path):
    archive_path = create_package(tmp_path / "text-statistics.xmcap")
    data = archive_path.read_bytes()
    xiaomei = CapabilityPackageService(base_dir=tmp_path / "host", agent_id="xiaomei")
    xiaoming = CapabilityPackageService(base_dir=tmp_path / "host", agent_id="xiaoming")

    installed = xiaomei.install(data, file_name=archive_path.name)
    xiaomei.activate(
        "xiaomei.text-statistics",
        "1.0.0",
        installed["package"]["sha256"],
    )
    xiaomei_dirs = xiaomei.runtime_directories()
    xiaoming_dirs = xiaoming.runtime_directories()

    registry = PluginRegistry()
    results = PluginLoader(registry, agent_id="xiaomei").boot(xiaomei_dirs["plugins"])
    definitions = CapabilityManifestLoader(xiaomei_dirs["capabilities"]).load()

    assert results[0].status == "loaded"
    assert registry.get_agent_tools()[0].execute(text="hello\n世界") == (
        '{"characters": 8, "non_whitespace_characters": 7, "lines": 2, "words": 3}'
    )
    assert [definition.id for definition in definitions] == ["text_statistics"]
    assert xiaomei_dirs["skills"]
    assert all(not paths for paths in xiaoming_dirs.values())


def test_package_and_capability_skill_filters_are_combined(tmp_path: Path):
    class FakeStorage:
        def import_from_dir(self, _path):
            return 0

        def list_names(self):
            return ["active", "package-disabled", "capability-disabled"]

        def list_skills(self, *, query: str, top_k: int):
            return [{"name": name} for name in self.list_names()][:top_k]

        def view_skill(self, name: str):
            return {"name": name}

    loader = SkillLoader(str(tmp_path / "skills"), str(tmp_path / "brain.db"))
    loader._storage = FakeStorage()
    loader.set_package_disabled_names({"package-disabled"})
    loader.set_disabled_names({"capability-disabled"})

    assert loader.list_names() == ["active"]
    assert loader.list_skills(top_k=10) == [{"name": "active"}]
    assert loader.view_skill("package-disabled") is None
    assert loader.view_skill("capability-disabled") is None
