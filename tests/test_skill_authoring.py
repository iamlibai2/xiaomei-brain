from __future__ import annotations

import json
from pathlib import Path

import pytest

from xiaomei_brain.skills.authoring import install_authored_skill
from xiaomei_brain.skills.tools import create_skill_tools
from xiaomei_brain.tools.base import Tool
from xiaomei_brain.tools.execution_context import bind_tool_execution
from xiaomei_brain.tools.registry import ToolRegistry


def _write_skill(root: Path, *, name: str = "baidu-hotboard") -> Path:
    source = root / "work" / "skills" / name
    source.mkdir(parents=True)
    (source / "SKILL.md").write_text(
        "---\n"
        f"name: {name}\n"
        "description: 定期读取并整理百度热榜\n"
        "version: 1.0.0\n"
        "requires_tools:\n"
        "  - powershell\n"
        "---\n"
        "读取榜单，保留抓取时间和来源；遇到失败时如实记录。\n",
        encoding="utf-8",
    )
    return source


def _registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(Tool(
        name="powershell",
        description="run command",
        parameters={"type": "object", "properties": {}},
        func=lambda: "ok",
    ))
    return registry


def test_install_authored_skill_copies_resources_and_replaces_old_files(tmp_path: Path):
    workspace = tmp_path / "workspace"
    source = _write_skill(workspace)
    (source / "references").mkdir()
    (source / "references" / "format.md").write_text("v1", encoding="utf-8")
    skills_dir = tmp_path / "agent" / "skills"

    installed = install_authored_skill(
        source_dir=source,
        workspace_root=workspace,
        skills_dir=skills_dir,
        tool_registry=_registry(),
    )
    stale = installed.install_dir / "stale.txt"
    stale.write_text("old", encoding="utf-8")
    (source / "references" / "format.md").write_text("v2", encoding="utf-8")

    installed = install_authored_skill(
        source_dir=source,
        workspace_root=workspace,
        skills_dir=skills_dir,
        tool_registry=_registry(),
    )

    assert installed.name == "baidu-hotboard"
    assert (installed.install_dir / "references" / "format.md").read_text(encoding="utf-8") == "v2"
    assert not stale.exists()


def test_install_authored_skill_rejects_missing_tools(tmp_path: Path):
    workspace = tmp_path / "workspace"
    source = _write_skill(workspace)

    with pytest.raises(ValueError, match="powershell"):
        install_authored_skill(
            source_dir=source,
            workspace_root=workspace,
            skills_dir=tmp_path / "skills",
            tool_registry=ToolRegistry(),
        )


def test_create_skill_hot_loads_and_binds_preparing_mission(tmp_path: Path):
    workspace = tmp_path / "workspace"
    _write_skill(workspace)
    skills_dir = tmp_path / "agent" / "skills"

    class Loader:
        def __init__(self):
            self.skills_dir = skills_dir
            self.refreshed = False

        def refresh_if_changed(self):
            self.refreshed = True
            return True

        def view_skill(self, name):
            path = self.skills_dir / name / "SKILL.md"
            return {"name": name} if path.is_file() else None

        def resource_roots(self):
            return [str(skills_dir / "baidu-hotboard")]

    class Mission:
        def to_dict(self):
            return {"id": "mission-1", "skill_name": "baidu-hotboard", "status": "preparing"}

    class MissionService:
        def __init__(self):
            self.calls = []

        def update_definition(self, mission_id, **changes):
            self.calls.append((mission_id, changes))
            return Mission()

    class Agent:
        def __init__(self):
            self._skill_loader = Loader()
            self.mission_service = MissionService()
            self.path_updates = []

        def agent_dir(self):
            return str(tmp_path / "agent")

        def configure_tool_paths(self, base_dir, *, extra_read_only_roots=()):
            self.path_updates.append((base_dir, list(extra_read_only_roots)))

    agent = Agent()
    create = next(tool for tool in create_skill_tools(agent) if tool.name == "create_skill")
    with bind_tool_execution(
        tool_call_id="call-1",
        tool_name="create_skill",
        arguments={},
        artifact_callback=None,
        workspace_root=str(workspace),
        tool_registry=_registry(),
    ):
        result = json.loads(create.execute(
            source_dir="work/skills/baidu-hotboard",
            mission_id="mission-1",
        ))

    assert result["success"] is True
    assert result["hot_loaded"] is True
    assert result["restart_required"] is False
    assert result["mission"]["status"] == "preparing"
    assert agent._skill_loader.refreshed is True
    assert agent.mission_service.calls == [
        ("mission-1", {"skill_name": "baidu-hotboard"})
    ]
    assert agent.path_updates
