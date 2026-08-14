from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from xiaomei_brain.capability_packages import CapabilityPackageError
from xiaomei_brain.plugins.tools.capability_development.tool import (
    create_build_capability_tool,
)
from xiaomei_brain.plugin.loader import PluginLoader
from xiaomei_brain.plugin.registry import PluginRegistry
from xiaomei_brain.tools.execution_context import bind_tool_execution
from xiaomei_brain.tools.base import Tool
from xiaomei_brain.tools.registry import ToolRegistry


def _source(workspace: Path, *, version: str = "0.1.0") -> Path:
    source = workspace / "work" / "capabilities" / "sample"
    files = {
        "capability.yaml": {
            "schema_version": 1,
            "package": {
                "id": "local.sample-capability",
                "name": "样板能力",
                "version": version,
            },
            "capabilities": [{"id": "sample_capability", "name": "样板能力"}],
            "contents": {
                "capabilities": ["capabilities/sample_capability.yaml"],
                "skills": ["skills/sample-capability/SKILL.md"],
            },
        },
        "capabilities/sample_capability.yaml": {
            "id": "sample_capability",
            "name": "样板能力",
            "summary": "完成样板工作",
            "category": "productivity",
            "components": [{
                "id": "sample_skill",
                "kind": "skill",
                "target": "sample-capability",
                "required": True,
            }],
            "outcomes": [{
                "id": "sample_result",
                "name": "样板结果",
                "components": ["sample_skill"],
            }],
        },
    }
    for relative, value in files.items():
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(value, allow_unicode=True, sort_keys=False), encoding="utf-8")
    skill = source / "skills" / "sample-capability" / "SKILL.md"
    skill.parent.mkdir(parents=True, exist_ok=True)
    skill.write_text("---\nname: sample-capability\ndescription: 样板能力\n---\n\n# 样板\n", encoding="utf-8")
    return source


def _execute(tool, workspace: Path, *, tool_registry: ToolRegistry | None = None, **arguments):
    outputs = workspace / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)
    with bind_tool_execution(
        tool_call_id="call-1",
        tool_name="build_capability",
        arguments=arguments,
        artifact_callback=None,
        workspace_root=str(workspace),
        working_directory=str(workspace),
        output_root=str(outputs),
        tool_registry=tool_registry or ToolRegistry(),
    ):
        return json.loads(tool.execute(**arguments))


def test_build_capability_exports_checked_workspace_artifact(tmp_path: Path):
    agent_dir = tmp_path / "test"
    workspace = agent_dir / "workspace"
    _source(workspace)
    tool = create_build_capability_tool(
        agent_id="test",
        agent_dir=agent_dir,
        restart_scheduler=lambda _agent_id, _delay: None,
    )

    result = _execute(
        tool,
        workspace,
        source_dir="work/capabilities/sample",
    )

    assert result["success"] is True
    assert result["activated"] is False
    assert result["output_path"] == "outputs/local.sample-capability-0.1.0.xmcap"
    assert (workspace / result["output_path"]).is_file()
    assert result["tool_contracts"]["valid"] is True


def test_build_capability_can_activate_only_current_agent_and_schedule_restart(tmp_path: Path):
    agent_dir = tmp_path / "test"
    workspace = agent_dir / "workspace"
    _source(workspace)
    scheduled: list[tuple[str, float]] = []
    tool = create_build_capability_tool(
        agent_id="test",
        agent_dir=agent_dir,
        restart_scheduler=lambda agent_id, delay: scheduled.append((agent_id, delay)),
    )

    result = _execute(
        tool,
        workspace,
        source_dir="work/capabilities/sample",
        activate=True,
    )

    assert result["activated"] is True
    assert result["restart_required"] is True
    assert scheduled == [("test", 8.0)]
    lock = json.loads((agent_dir / "capabilities.lock").read_text(encoding="utf-8"))
    assert lock["packages"]["local.sample-capability"]["enabled"] is True


def test_build_capability_rejects_paths_outside_workspace(tmp_path: Path):
    agent_dir = tmp_path / "test"
    workspace = agent_dir / "workspace"
    workspace.mkdir(parents=True)
    tool = create_build_capability_tool(
        agent_id="test",
        agent_dir=agent_dir,
        restart_scheduler=lambda _agent_id, _delay: None,
    )

    with pytest.raises(ValueError, match="不能越过"):
        _execute(tool, workspace, source_dir="../outside")


def test_capability_development_plugin_registers_tool_and_skill_source():
    registry = PluginRegistry()
    plugin_root = (
        Path(__file__).parents[1]
        / "src"
        / "xiaomei_brain"
        / "plugins"
        / "tools"
    )

    loaded = PluginLoader(
        registry,
        config={"plugins": {"allow": ["capability_development"]}},
        agent_id="test",
    ).boot([str(plugin_root)])

    assert [item.manifest.name for item in loaded if item.status == "loaded"] == [
        "capability_development"
    ]
    assert [tool.name for tool in registry.get_agent_tools()] == ["build_capability"]
    assert registry.get_skill_directories() == [
        str((plugin_root / "capability_development").resolve())
    ]


def _workspace_tool_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(Tool(
        name="define_collection",
        description="Define one Collection.",
        parameters={
            "type": "object",
            "properties": {
                "workspace_id": {"type": "string"},
                "name": {"type": "string"},
                "label": {"type": "string"},
                "purpose": {"type": "string"},
                "fields": {"type": "array"},
            },
            "required": ["workspace_id", "name", "label", "purpose", "fields"],
        },
        func=lambda **_kwargs: "ok",
    ))
    registry.register(Tool(
        name="create_surface",
        description="Create one Surface.",
        parameters={
            "type": "object",
            "properties": {
                "workspace_id": {"type": "string"},
                "name": {"type": "string"},
                "purpose": {"type": "string"},
                "definition": {"type": "object"},
            },
            "required": ["workspace_id", "name", "purpose", "definition"],
        },
        func=lambda **_kwargs: "ok",
    ))
    return registry


def test_build_capability_rejects_wrong_required_parameter_table(tmp_path: Path):
    agent_dir = tmp_path / "test"
    workspace = agent_dir / "workspace"
    source = _source(workspace)
    (source / "skills" / "sample-capability" / "SKILL.md").write_text(
        """---
name: sample-capability
description: sample
requires_tools: [define_collection]
---

| 工具名 | 必传参数 |
|---|---|
| `define_collection` | `name`, `purpose`, `items` |
""",
        encoding="utf-8",
    )
    tool = create_build_capability_tool(
        agent_id="test",
        agent_dir=agent_dir,
        restart_scheduler=lambda _agent_id, _delay: None,
    )

    with pytest.raises(CapabilityPackageError, match="工具契约检查失败") as caught:
        _execute(
            tool,
            workspace,
            source_dir="work/capabilities/sample",
            tool_registry=_workspace_tool_registry(),
        )

    message = str(caught.value)
    assert "items" in message
    assert "workspace_id" in message
    assert "fields" in message


def test_build_capability_rejects_wrong_inline_invocation_parameter(tmp_path: Path):
    agent_dir = tmp_path / "test"
    workspace = agent_dir / "workspace"
    source = _source(workspace)
    (source / "skills" / "sample-capability" / "SKILL.md").write_text(
        """---
name: sample-capability
description: sample
requires_tools: [create_surface]
---

调用 `create_surface`，传入 `workspace_id`、`dataset_bindings` 和 `layout`。
""",
        encoding="utf-8",
    )
    tool = create_build_capability_tool(
        agent_id="test",
        agent_dir=agent_dir,
        restart_scheduler=lambda _agent_id, _delay: None,
    )

    with pytest.raises(CapabilityPackageError, match="工具契约检查失败") as caught:
        _execute(
            tool,
            workspace,
            source_dir="work/capabilities/sample",
            tool_registry=_workspace_tool_registry(),
        )

    message = str(caught.value)
    assert "dataset_bindings" in message
    assert "layout" in message
    assert "definition" in message


def test_build_capability_returns_live_tool_contracts(tmp_path: Path):
    agent_dir = tmp_path / "test"
    workspace = agent_dir / "workspace"
    source = _source(workspace)
    (source / "skills" / "sample-capability" / "SKILL.md").write_text(
        """---
name: sample-capability
description: sample
requires_tools: [define_collection]
---

| Tool | Required parameters |
|---|---|
| `define_collection` | `workspace_id`, `name`, `label`, `purpose`, `fields` |
""",
        encoding="utf-8",
    )
    tool = create_build_capability_tool(
        agent_id="test",
        agent_dir=agent_dir,
        restart_scheduler=lambda _agent_id, _delay: None,
    )

    result = _execute(
        tool,
        workspace,
        source_dir="work/capabilities/sample",
        tool_registry=_workspace_tool_registry(),
    )

    assert result["tool_contracts"]["referenced_tools"] == ["define_collection"]
    contract = result["tool_contracts"]["contracts"][0]
    assert contract["required"] == [
        "fields", "label", "name", "purpose", "workspace_id",
    ]
