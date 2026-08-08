from __future__ import annotations

from pathlib import Path
import json
from types import SimpleNamespace

import pytest

from xiaomei_brain.capabilities import (
    CapabilityManifestLoader,
    CapabilityConfigurationService,
    CapabilityRegistry,
    CapabilityStatus,
    create_capability_tools,
)
from xiaomei_brain.agent.instance import AgentInstance
from xiaomei_brain.plugin.loader import PluginLoader
from xiaomei_brain.plugin.registry import PluginRegistry
from xiaomei_brain.tools.registry import ToolRegistry
from xiaomei_brain.tools.execution_context import bind_tool_execution
from xiaomei_brain.consciousness.event_hub import EventHub


DOCUMENT_PLUGINS = [
    "data_analysis",
    "document_io",
    "document_pdf",
    "document_presentation",
    "document_spreadsheet",
    "document_word",
]

DOCUMENT_SKILLS = [
    "data-analysis",
    "pdf-documents",
    "presentation-documents",
    "spreadsheet-documents",
    "word-documents",
]


class _SkillLoader:
    def __init__(self, names: list[str]) -> None:
        self._names = names

    def list_names(self) -> list[str]:
        return [name for name in self._names if name not in getattr(self, "disabled", set())]

    def set_disabled_names(self, names) -> None:
        self.disabled = set(names)

    def view_skill(self, name: str):
        if name not in self.list_names():
            return None
        return {"name": name, "tool_bindings": []}


class _DynamicLoader:
    def set_disabled_names(self, names) -> None:
        self.disabled = set(names)

    def pin_required_tools(self, scope_id, names):
        self.pinned = (scope_id, list(names))
        return list(names), []


class _ToolServiceConfiguration:
    def __init__(self, *, configured: bool, enabled: bool = True) -> None:
        self.configured = configured
        self.enabled = enabled

    def get(self, service_id: str) -> dict:
        assert service_id == "web_search_baidu"
        return {
            "id": service_id,
            "configured": self.configured,
            "enabled": self.enabled,
        }


def _document_runtime(*, skills: list[str] | None = None):
    plugin_registry = PluginRegistry()
    tools_root = (
        Path(__file__).parents[1]
        / "src"
        / "xiaomei_brain"
        / "plugins"
        / "tools"
    )
    loader = PluginLoader(
        plugin_registry,
        config={"plugins": {"allow": DOCUMENT_PLUGINS}},
        agent_id="test",
    )
    loaded = loader.boot([str(tools_root)])
    assert {
        item.manifest.name
        for item in loaded
        if item.status == "loaded"
    } == set(DOCUMENT_PLUGINS)

    tool_registry = ToolRegistry()
    for tool in plugin_registry.get_agent_tools():
        tool_registry.register(tool)
    capability_registry = CapabilityRegistry(
        plugin_registry=plugin_registry,
        tool_registry=tool_registry,
        skill_loader=_SkillLoader(skills if skills is not None else DOCUMENT_SKILLS),
    )
    return capability_registry


def _configurable_runtime(tmp_path):
    plugin_registry = PluginRegistry()
    tools_root = Path(__file__).parents[1] / "src" / "xiaomei_brain" / "plugins" / "tools"
    loader = PluginLoader(
        plugin_registry,
        config={"plugins": {"allow": DOCUMENT_PLUGINS}},
        agent_id="test",
    )
    loader.boot([str(tools_root)])
    tool_registry = ToolRegistry()
    for tool in plugin_registry.get_agent_tools():
        tool_registry.register(tool)
    skill_loader = _SkillLoader(DOCUMENT_SKILLS)
    dynamic_loader = _DynamicLoader()
    config_path = tmp_path / "test" / "config.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text('{"name": "test", "custom": {"keep": true}}', encoding="utf-8")
    registry = CapabilityRegistry(
        plugin_registry=plugin_registry,
        tool_registry=tool_registry,
        skill_loader=skill_loader,
        dynamic_tool_loader=dynamic_loader,
        configuration=CapabilityConfigurationService(config_path),
    )
    return registry, tool_registry, skill_loader, dynamic_loader, config_path


def test_builtin_manifests_describe_user_facing_capabilities():
    definitions = CapabilityManifestLoader().load()

    assert [definition.id for definition in definitions] == [
        "data_analysis",
        "feishu_office",
        "gmail",
        "office_documents",
        "qq_mail",
        "visualize",
        "web_search",
    ]
    office = next(item for item in definitions if item.id == "office_documents")
    assert office.name == "办公文档"
    assert {outcome.id for outcome in office.outcomes} == {
        "word",
        "spreadsheet",
        "presentation",
        "pdf",
    }
    assert len({component.id for component in office.components}) == len(office.components)
    data = next(item for item in definitions if item.id == "data_analysis")
    assert [(item.kind, item.target, item.required) for item in data.requirements] == [
        ("capability", "office_documents", False),
    ]


def test_data_analysis_capability_is_backed_by_real_plugin_tool_and_skill():
    registry = _document_runtime()

    view = registry.get("data_analysis")

    assert view is not None
    assert view.status == CapabilityStatus.READY
    assert {outcome.id for outcome in view.outcomes} == {
        "profile",
        "grouped_summary",
        "charts",
    }
    assert all(outcome.available for outcome in view.outcomes)


def test_configurable_capability_explains_setup_and_links_existing_settings():
    plugin_registry = PluginRegistry()
    tools_root = Path(__file__).parents[1] / "src" / "xiaomei_brain" / "plugins" / "tools"
    loader = PluginLoader(
        plugin_registry,
        config={"plugins": {"allow": ["web_search_baidu"]}},
        agent_id="test",
    )
    loader.boot([str(tools_root)])
    registry = CapabilityRegistry(
        plugin_registry=plugin_registry,
        tool_registry=ToolRegistry(),
        skill_loader=_SkillLoader([]),
        tool_service_configuration=_ToolServiceConfiguration(configured=False),
    )

    view = registry.get("web_search")
    public = view.to_dict() if view else {}

    assert view is not None and view.status == CapabilityStatus.NEEDS_SETUP
    assert public["issues"]
    action_issue = next(issue for issue in public["issues"] if "action" in issue)
    assert action_issue["action"] == {
        "type": "open_settings",
        "section": "search",
        "target": "web_search_baidu",
        "label": "配置联网搜索服务",
    }
    assert public["actions"] == [{
        "type": "open_settings",
        "section": "search",
        "target": "web_search_baidu",
        "label": "配置联网搜索服务",
    }]
    context = registry.build_context("搜索今天的行业新闻")
    assert "联网搜索 [需要完善]" in context
    assert "联网搜索服务尚未配置" in context
    assert "完善入口：Agent 设置 > 联网搜索" in context
    assert "调用 request_capability_setup" in context
    assert "capability_id 使用 web_search" in context

    configured_registry = CapabilityRegistry(
        plugin_registry=plugin_registry,
        tool_registry=ToolRegistry(),
        skill_loader=_SkillLoader([]),
        tool_service_configuration=_ToolServiceConfiguration(configured=True),
    )
    configured = configured_registry.get("web_search")
    assert configured is not None
    assert configured.to_dict()["actions"][0]["label"] == "管理联网搜索服务"


def test_capability_resolver_exposes_only_task_relevant_business_facts():
    registry = _document_runtime()

    data_views = registry.resolve("分析这份销售数据，按地区汇总并画柱状图")
    office_views = registry.resolve("制作一个项目汇报 PPT")
    context = registry.build_context("检查 Excel 的缺失值")

    assert data_views[0].id == "data_analysis"
    assert office_views[0].id == "office_documents"
    assert "数据分析与可视化 [可用]" in context
    assert "plugin" not in context.lower()
    assert "analyze_data" not in context


def test_capability_selection_pins_outcome_tools_and_required_skill():
    registry = _document_runtime()
    dynamic = _DynamicLoader()
    registry.bind_dynamic_tool_loader(dynamic)

    skills = registry.prepare_execution_selection(
        "制作一份项目汇报 PPT",
        scope_id="desktop-session",
        person_id="person-1",
    )

    assert "presentation-documents" in skills
    assert dynamic.pinned[0] == "desktop-session"
    assert "read_document" in dynamic.pinned[1]
    assert "write_document" in dynamic.pinned[1]
    assert "manage_document_template" not in dynamic.pinned[1]


def test_agent_can_inspect_business_capabilities_without_technical_leakage():
    registry = _document_runtime()
    agent = AgentInstance(id="test", name="测试")
    agent._capability_registry = registry
    capability_tool = create_capability_tools(agent)[0]

    result = json.loads(capability_tool.execute(query="制作项目汇报 PPT"))

    assert result["matched"][0]["id"] == "office_documents"
    assert result["matched"][0]["status_label"] == "可用"
    assert "PowerPoint 演示文稿" in result["matched"][0]["available_outcomes"]
    assert "plugin" not in json.dumps(result, ensure_ascii=False).lower()


def test_capability_status_uses_person_from_sealed_tool_context():
    calls = []

    class _Registry:
        def resolve(self, query, *, limit, person_id):
            calls.append((query, limit, person_id))
            return []

    agent = AgentInstance(id="test", name="测试")
    agent._capability_registry = _Registry()
    capability_tool = create_capability_tools(agent)[0]

    with bind_tool_execution(
        tool_call_id="call-1",
        tool_name="capability_status",
        arguments={"query": "飞书文档"},
        artifact_callback=None,
        person_id="person-verified",
    ):
        capability_tool.execute(query="飞书文档")

    assert calls == [("飞书文档", 5, "person-verified")]


def test_capability_setup_uses_person_from_sealed_tool_context():
    calls = []
    ready_view = SimpleNamespace(status=SimpleNamespace(value="ready"), id="feishu_office")

    class _Registry:
        def get(self, capability_id, *, person_id):
            calls.append((capability_id, person_id))
            return ready_view

    agent = AgentInstance(id="test", name="测试")
    agent._capability_registry = _Registry()
    setup_tool = next(
        item for item in create_capability_tools(agent)
        if item.name == "request_capability_setup"
    )

    with bind_tool_execution(
        tool_call_id="call-2",
        tool_name="request_capability_setup",
        arguments={"capability_id": "feishu_office"},
        artifact_callback=None,
        person_id="person-verified",
    ):
        result = json.loads(setup_tool.execute(capability_id="feishu_office"))

    assert calls == [("feishu_office", "person-verified")]
    assert result["status"] == "ready"


def test_agent_can_publish_non_mutating_capability_setup_request(tmp_path):
    plugin_registry = PluginRegistry()
    tools_root = Path(__file__).parents[1] / "src" / "xiaomei_brain" / "plugins" / "tools"
    PluginLoader(
        plugin_registry,
        config={"plugins": {"allow": ["web_search_baidu"]}},
        agent_id="test",
    ).boot([str(tools_root)])
    registry = CapabilityRegistry(
        plugin_registry=plugin_registry,
        tool_registry=ToolRegistry(),
        skill_loader=_SkillLoader([]),
        tool_service_configuration=_ToolServiceConfiguration(configured=False),
    )
    hub = EventHub()
    events = []
    hub.subscribe(events.append)
    agent = AgentInstance(id="test", name="测试")
    agent._capability_registry = registry
    agent._agent = SimpleNamespace(
        session_id="desktop-session",
        turn_id="turn-1",
        user_id="person-1",
        _last_all_messages=[{"role": "user", "content": "搜索新闻", "id": 42}],
    )
    metadata_updates = []
    agent.conversation_db = SimpleNamespace(
        update_message_metadata=lambda message_id, updates: metadata_updates.append(
            (message_id, updates),
        ),
    )
    agent._living = SimpleNamespace(_event_hub=hub)

    setup_tool = next(
        item for item in create_capability_tools(agent)
        if item.name == "request_capability_setup"
    )
    result = json.loads(setup_tool.execute(
        capability_id="web_search",
        reason="需要先配置联网搜索服务。",
    ))

    assert result["message"] == "已在当前 Desktop 会话中展示配置入口"
    assert len(events) == 1
    event = events[0]
    assert event.name == "capability.setup.requested"
    assert event.session_id == "desktop-session"
    assert event.turn_id == "turn-1"
    assert event.payload["kind"] == "capability_setup"
    assert event.payload["capability_id"] == "web_search"
    assert event.payload["source_message_id"] == 42
    assert event.payload["action"] == {
        "type": "open_settings",
        "section": "search",
        "target": "web_search_baidu",
        "label": "配置联网搜索服务",
    }
    assert metadata_updates[0][0] == 42
    assert metadata_updates[0][1]["capability_blocked"]["capability_id"] == "web_search"
    assert metadata_updates[0][1]["capability_blocked"]["active"] is True


def test_capability_setup_tool_does_not_request_setup_when_ready():
    registry = _document_runtime()
    hub = EventHub()
    events = []
    hub.subscribe(events.append)
    agent = AgentInstance(id="test", name="测试")
    agent._capability_registry = registry
    agent._agent = SimpleNamespace(session_id="s", turn_id="t", user_id="p")
    agent._living = SimpleNamespace(_event_hub=hub)
    setup_tool = next(
        item for item in create_capability_tools(agent)
        if item.name == "request_capability_setup"
    )

    result = json.loads(setup_tool.execute(capability_id="office_documents"))

    assert result["status"] == "ready"
    assert events == []


def test_office_capability_is_ready_when_real_components_are_loaded():
    registry = _document_runtime()

    view = registry.get("office_documents")

    assert view is not None
    assert view.status == CapabilityStatus.READY
    assert all(outcome.available for outcome in view.outcomes)
    assert view.issues == ()


def test_one_missing_format_degrades_instead_of_disabling_other_formats():
    skills = [name for name in DOCUMENT_SKILLS if name != "pdf-documents"]
    registry = _document_runtime(skills=skills)

    view = registry.get("office_documents")

    assert view is not None
    assert view.status == CapabilityStatus.DEGRADED
    outcomes = {outcome.id: outcome for outcome in view.outcomes}
    assert outcomes["pdf"].available is False
    assert "PDF 工作方法尚未就绪" in outcomes["pdf"].limitations
    assert outcomes["word"].available is True
    assert outcomes["spreadsheet"].available is True
    assert outcomes["presentation"].available is True


def test_missing_shared_document_tools_makes_capability_unavailable():
    plugin_registry = PluginRegistry()
    registry = CapabilityRegistry(
        plugin_registry=plugin_registry,
        tool_registry=ToolRegistry(),
        skill_loader=_SkillLoader([]),
    )

    view = registry.get("office_documents")

    assert view is not None
    assert view.status == CapabilityStatus.UNAVAILABLE
    assert not any(outcome.available for outcome in view.outcomes)


def test_normal_serialization_hides_internal_component_names():
    registry = _document_runtime()

    public = registry.get("office_documents").to_dict()
    technical = registry.get("office_documents").to_dict(include_technical=True)

    assert "components" not in public
    assert "components" in technical
    assert any(component["target"] == "document_word" for component in technical["components"])


def test_agent_exposes_read_only_capability_queries():
    capability_registry = _document_runtime()
    agent = AgentInstance(id="test", name="测试")
    agent._capability_registry = capability_registry

    listed = agent.list_capabilities()
    office = agent.get_capability("office_documents")

    assert [item["id"] for item in listed] == [
        "data_analysis",
        "feishu_office",
        "gmail",
        "office_documents",
        "qq_mail",
        "visualize",
        "web_search",
    ]
    assert office is not None
    assert office["status"] == "ready"
    assert "components" not in office
    assert agent.get_capability("missing") is None


def test_capability_activation_is_persisted_and_applied_without_restart(tmp_path):
    registry, tools, skills, dynamic, config_path = _configurable_runtime(tmp_path)

    disabled = registry.set_enabled("data_analysis", False)

    assert disabled is not None
    assert disabled.status == CapabilityStatus.DISABLED
    assert disabled.enabled is False
    assert not any(outcome.available for outcome in disabled.outcomes)
    assert tools.get("analyze_data") is not None
    assert "analyze_data" not in {tool.name for tool in tools.list_tools()}
    assert "data-analysis" not in skills.list_names()
    assert dynamic.disabled == {"analyze_data"}
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved["custom"] == {"keep": True}
    assert saved["capabilities"]["entries"]["data_analysis"]["enabled"] is False

    enabled = registry.set_enabled("data_analysis", True)

    assert enabled is not None and enabled.status == CapabilityStatus.READY
    assert "analyze_data" in {tool.name for tool in tools.list_tools()}
    assert "data-analysis" in skills.list_names()
    assert dynamic.disabled == set()


def test_agent_can_change_capability_activation(tmp_path):
    capability_registry, *_ = _configurable_runtime(tmp_path)
    agent = AgentInstance(id="test", name="测试")
    agent._capability_registry = capability_registry

    changed = agent.set_capability_enabled("office_documents", False)

    assert changed is not None
    assert changed["enabled"] is False
    assert changed["status"] == "disabled"


def test_manifest_rejects_outcome_with_unknown_component(tmp_path):
    manifest = tmp_path / "broken.yaml"
    manifest.write_text(
        """
id: broken
name: 损坏能力
summary: 用于测试
category: test
components: []
outcomes:
  - id: impossible
    name: 无法完成
    components: [missing]
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="未知 component"):
        CapabilityManifestLoader.load_file(manifest)


def test_manifest_parses_targeted_runtime_requirements(tmp_path):
    manifest = tmp_path / "runtime-requirements.yaml"
    manifest.write_text(
        """
id: media_example
name: 媒体样例
summary: 验证运行依赖
category: test
requirements:
  tools:
    - create_project
  executables:
    - target: ffmpeg
      label: FFmpeg
      outcomes: [delivery]
components: []
outcomes:
  - id: planning
    name: 策划
  - id: delivery
    name: 交付
""".strip(),
        encoding="utf-8",
    )

    definition = CapabilityManifestLoader.load_file(manifest)

    assert [(item.kind, item.target) for item in definition.requirements] == [
        ("executable", "ffmpeg"),
        ("tool", "create_project"),
    ]
    ffmpeg = next(item for item in definition.requirements if item.target == "ffmpeg")
    assert ffmpeg.outcomes == ("delivery",)


def test_missing_targeted_executable_only_degrades_affected_outcome(tmp_path, monkeypatch):
    manifest = tmp_path / "runtime-requirements.yaml"
    manifest.write_text(
        """
id: media_example
name: 媒体样例
summary: 验证运行依赖
category: test
requirements:
  executables:
    - target: missing-media-binary
      label: 媒体处理程序
      outcomes: [delivery]
components: []
outcomes:
  - id: planning
    name: 策划
  - id: delivery
    name: 交付
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setattr("xiaomei_brain.capabilities.registry.shutil.which", lambda _name: None)
    registry = CapabilityRegistry(
        plugin_registry=PluginRegistry(),
        definitions=[CapabilityManifestLoader.load_file(manifest)],
    )

    view = registry.get("media_example")

    assert view is not None and view.status == CapabilityStatus.DEGRADED
    outcomes = {item.id: item for item in view.outcomes}
    assert outcomes["planning"].available is True
    assert outcomes["delivery"].available is False
    assert outcomes["delivery"].limitations == ("未找到运行依赖：媒体处理程序",)
    technical = view.to_dict(include_technical=True)["components"]
    requirement = next(item for item in technical if item["target"] == "missing-media-binary")
    assert requirement["kind"] == "requirement.executable"
    assert requirement["outcomes"] == ["delivery"]
