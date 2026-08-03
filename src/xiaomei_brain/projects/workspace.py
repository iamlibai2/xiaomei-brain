"""Filesystem boundaries for Project state and working files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .models import WorkspaceKind


@dataclass(frozen=True)
class ProjectWorkspace:
    state_root: Path
    work_root: Path | None


class ProjectWorkspaceManager:
    """Create Agent-owned state while preserving linked workspace ownership."""

    _STATE_DIRS = ("state", "source", "review", "deliverables")

    def __init__(self, projects_root: str | Path) -> None:
        self.projects_root = Path(projects_root).expanduser().resolve()

    def prepare(
        self,
        project_id: str,
        *,
        kind: WorkspaceKind,
        workspace_uri: str = "",
    ) -> ProjectWorkspace:
        self._validate_project_id(project_id)
        state_root = (self.projects_root / project_id).resolve()
        self._require_within(state_root, self.projects_root)
        state_root.mkdir(parents=True, exist_ok=True)
        for name in self._STATE_DIRS:
            (state_root / name).mkdir(exist_ok=True)

        if kind is WorkspaceKind.MANAGED:
            work_root = state_root / "work"
            work_root.mkdir(exist_ok=True)
        elif kind is WorkspaceKind.LINKED:
            if not workspace_uri.strip():
                raise ValueError("Linked Project requires workspace_uri")
            work_root = Path(workspace_uri).expanduser().resolve()
            if not work_root.is_dir():
                raise ValueError(f"Linked workspace does not exist: {work_root}")
        else:
            work_root = None
        return ProjectWorkspace(state_root=state_root, work_root=work_root)

    def resolve_asset_path(
        self,
        state_root: str | Path,
        relative_uri: str,
    ) -> Path:
        root = Path(state_root).expanduser().resolve()
        if Path(relative_uri).is_absolute():
            raise ValueError("Project asset URI must be relative")
        target = (root / relative_uri).resolve()
        self._require_within(target, root)
        return target

    @staticmethod
    def _validate_project_id(project_id: str) -> None:
        if not project_id.startswith("project_") or not project_id[8:]:
            raise ValueError("Invalid project_id")
        if any(char in project_id for char in ("/", "\\", "..")):
            raise ValueError("Invalid project_id")

    @staticmethod
    def _require_within(target: Path, root: Path) -> None:
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"Path escapes Project root: {target}") from exc

