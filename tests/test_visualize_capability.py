from pathlib import Path

from xiaomei_brain.capabilities import CapabilityRegistry, CapabilityStatus
from xiaomei_brain.plugin.loader import PluginLoader
from xiaomei_brain.plugin.registry import PluginRegistry
from xiaomei_brain.tools.builtin import present_artifacts_tool
from xiaomei_brain.tools.execution_context import bind_tool_execution
from xiaomei_brain.tools.registry import ToolRegistry


class _SkillLoader:
    def list_names(self):
        return ["visualize"]

    def view_skill(self, name: str):
        if name != "visualize":
            return None
        return {
            "name": name,
            "tool_bindings": ["write_visualization", "present_artifacts"],
        }


def test_visualize_capability_uses_plugin_owned_writer():
    plugin_registry = PluginRegistry()
    tools_root = (
        Path(__file__).parents[1]
        / "src"
        / "xiaomei_brain"
        / "plugins"
        / "tools"
    )
    loaded = PluginLoader(
        plugin_registry,
        config={"plugins": {"allow": ["visualize"]}},
        agent_id="test",
    ).boot([str(tools_root)])
    assert [item.manifest.name for item in loaded if item.status == "loaded"] == [
        "visualize",
    ]

    tools = ToolRegistry()
    for plugin_tool in plugin_registry.get_agent_tools():
        tools.register(plugin_tool)
    tools.register(present_artifacts_tool)
    registry = CapabilityRegistry(
        plugin_registry=plugin_registry,
        tool_registry=tools,
        skill_loader=_SkillLoader(),
    )

    view = registry.get("visualize")

    assert view is not None
    assert view.status == CapabilityStatus.READY
    assert {item.id for item in view.outcomes} == {
        "charts",
        "explainers",
        "simulations",
        "previews",
    }
    assert all(item.available for item in view.outcomes)
    assert tools.get("write_visualization") is not None


def test_write_visualization_normalizes_filename_and_uses_output_root(tmp_path):
    plugin_registry = PluginRegistry()
    tools_root = (
        Path(__file__).parents[1]
        / "src"
        / "xiaomei_brain"
        / "plugins"
        / "tools"
    )
    PluginLoader(
        plugin_registry,
        config={"plugins": {"allow": ["visualize"]}},
        agent_id="test",
    ).boot([str(tools_root)])
    tool = next(
        item for item in plugin_registry.get_agent_tools()
        if item.name == "write_visualization"
    )
    workspace = tmp_path / "workspace"
    output_root = workspace / "outputs"
    output_root.mkdir(parents=True)

    with bind_tool_execution(
        tool_call_id="call-viz",
        tool_name=tool.name,
        arguments={},
        artifact_callback=None,
        workspace_root=str(workspace),
        working_directory=str(workspace),
        output_root=str(output_root),
    ):
        result = tool.execute(
            filename="approval-3d-pipeline.html",
            content='<div id="pipeline">ready</div>',
        )

    assert result["success"] is True
    assert result["name"] == "approval-3d-pipeline.visualization.html"
    assert Path(result["output_path"]).parent == output_root.resolve()
    assert Path(result["output_path"]).read_text(encoding="utf-8") == (
        '<div id="pipeline">ready</div>'
    )

    with bind_tool_execution(
        tool_call_id="call-viz-suffixes",
        tool_name=tool.name,
        arguments={},
        artifact_callback=None,
        workspace_root=str(workspace),
        working_directory=str(workspace),
        output_root=str(output_root),
    ):
        marker_result = tool.execute(
            filename="approval-dashboard-visual.visualization",
            content='<div id="dashboard">ready</div>',
        )
        duplicated_result = tool.execute(
            filename="approval-dashboard-dark.visualization.visualization.html",
            content='<div id="dashboard-dark">ready</div>',
        )

    assert marker_result["name"] == "approval-dashboard-visual.visualization.html"
    assert duplicated_result["name"] == "approval-dashboard-dark.visualization.html"


def test_write_visualization_updates_referenced_artifact_in_place(tmp_path):
    plugin_registry = PluginRegistry()
    tools_root = (
        Path(__file__).parents[1]
        / "src"
        / "xiaomei_brain"
        / "plugins"
        / "tools"
    )
    PluginLoader(
        plugin_registry,
        config={"plugins": {"allow": ["visualize"]}},
        agent_id="test",
    ).boot([str(tools_root)])
    tool = next(
        item for item in plugin_registry.get_agent_tools()
        if item.name == "write_visualization"
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source_path = workspace / "dashboard.visualization.html"
    source_path.write_text('<div id="dashboard">light</div>', encoding="utf-8")
    artifact_id = "a" * 32

    with bind_tool_execution(
        tool_call_id="call-viz-update",
        tool_name=tool.name,
        arguments={},
        artifact_callback=None,
        session_id="session-1",
        attachments=({
            "id": artifact_id,
            "name": source_path.name,
            "kind": "text",
            "source_artifact": {
                "artifact_id": artifact_id,
                "session_id": "session-1",
            },
            "managed_artifact_path": str(source_path),
        },),
        workspace_root=str(workspace),
        working_directory=str(workspace),
        output_root=str(workspace),
    ):
        result = tool.execute(
            filename="ignored-new-name.html",
            content='<div id="dashboard">dark</div>',
            source_attachment_id=artifact_id,
        )

    assert result["success"] is True
    assert result["name"] == "dashboard.visualization.html"
    assert result["updated_artifact"] == {
        "artifact_id": artifact_id,
        "session_id": "session-1",
        "output_path": str(source_path.resolve()),
    }
    assert source_path.read_text(encoding="utf-8") == '<div id="dashboard">dark</div>'
