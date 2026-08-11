"""Canonical filesystem layout for one deployed Agent."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AgentWorkspaceLayout:
    """The only user-operable file tree owned by an Agent."""

    agent_root: Path
    root: Path
    inputs: Path
    work: Path
    outputs: Path
    images: Path
    audio: Path
    video: Path
    documents: Path
    projects: Path
    attachments: Path

    @classmethod
    def create(cls, agent_root: str | Path) -> "AgentWorkspaceLayout":
        base = Path(agent_root).expanduser().resolve()
        root = base / "workspace"
        outputs = root / "outputs"
        layout = cls(
            agent_root=base,
            root=root,
            inputs=root / "inputs",
            work=root / "work",
            outputs=outputs,
            images=outputs / "images",
            audio=outputs / "audio",
            video=outputs / "video",
            documents=outputs / "documents",
            projects=root / "projects",
            attachments=root / "inputs" / "attachments",
        )
        for directory in (
            layout.root, layout.inputs, layout.work, layout.outputs,
            layout.images, layout.audio, layout.video, layout.documents,
            layout.projects, layout.attachments,
        ):
            directory.mkdir(parents=True, exist_ok=True)
        return layout


def workspace_output_directory(kind: str, *, fallback_agent_root: str | Path = "") -> Path:
    """Resolve a generated-file directory from the sealed tool context."""
    from xiaomei_brain.tools.execution_context import current_tool_execution

    context = current_tool_execution()
    if context is not None and context.output_root:
        root = Path(context.output_root).expanduser().resolve()
    elif context is not None and context.workspace_root:
        root = Path(context.workspace_root).expanduser().resolve() / "outputs"
    elif fallback_agent_root:
        root = AgentWorkspaceLayout.create(fallback_agent_root).outputs
    else:
        root = AgentWorkspaceLayout.create(
            Path.home() / ".xiaomei-brain" / "global"
        ).outputs
    names = {
        "image": "images",
        "audio": "audio",
        "video": "video",
        "document": "documents",
    }
    if kind not in names:
        raise ValueError(f"Unsupported workspace output kind: {kind}")
    destination = root / names[kind]
    destination.mkdir(parents=True, exist_ok=True)
    return destination
