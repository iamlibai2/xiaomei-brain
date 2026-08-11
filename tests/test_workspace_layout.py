from __future__ import annotations

from xiaomei_brain.execution.workspace_layout import AgentWorkspaceLayout


def test_agent_workspace_layout_creates_canonical_directories(tmp_path) -> None:
    agent_root = tmp_path / "test"
    layout = AgentWorkspaceLayout.create(agent_root)

    assert layout.root == agent_root.resolve() / "workspace"
    assert layout.attachments == layout.inputs / "attachments"
    assert layout.projects == layout.root / "projects"
    for directory in (
        layout.inputs, layout.work, layout.outputs, layout.images,
        layout.audio, layout.video, layout.documents, layout.projects,
        layout.attachments,
    ):
        assert directory.is_dir()
