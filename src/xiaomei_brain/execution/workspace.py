"""Host-side workspace broker shared by execution backends."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


def protected_host_roots() -> tuple[Path, ...]:
    values = [
        "~/.ssh",
        "~/.gnupg",
        "~/.aws",
        "~/.config/gcloud",
        "~/.azure",
        "~/.kube",
        "~/.docker",
        "~/.bash_history",
        "~/.zsh_history",
    ]
    if sys.platform == "win32":
        values.extend([
            os.environ.get("SystemRoot", r"C:\Windows"),
            os.environ.get("ProgramFiles", r"C:\Program Files"),
            os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
            os.environ.get("ProgramData", r"C:\ProgramData"),
        ])
    else:
        values.extend(["/etc", "/proc", "/sys", "/boot", "/root/.ssh"])
    return tuple(Path(value).expanduser().resolve() for value in values if value)


def _is_within(path: Path, root: Path) -> bool:
    try:
        Path(os.path.normcase(str(path))).relative_to(
            Path(os.path.normcase(str(root))),
        )
        return True
    except ValueError:
        return False


@dataclass(frozen=True)
class WorkspaceBroker:
    """Resolve virtual tool paths against an explicit workspace boundary."""

    workspace_root: Path
    working_directory: Path
    allowed_roots: tuple[Path, ...]
    protected_roots: tuple[Path, ...]

    @classmethod
    def create(
        cls,
        *,
        workspace_root: str | Path,
        working_directory: str | Path,
        extra_allowed_roots: Iterable[str | Path] = (),
        protected_roots: Iterable[str | Path] = (),
    ) -> "WorkspaceBroker":
        workspace = Path(workspace_root).expanduser().resolve()
        working = Path(working_directory).expanduser().resolve()
        allowed = [workspace]
        allowed.extend(Path(item).expanduser().resolve() for item in extra_allowed_roots)
        return cls(
            workspace_root=workspace,
            working_directory=working,
            allowed_roots=tuple(dict.fromkeys(allowed)),
            protected_roots=tuple(
                Path(item).expanduser().resolve() for item in protected_roots
            ),
        )

    def resolve(self, path: str, *, exists: bool = False) -> tuple[Path | None, str]:
        if not isinstance(path, str) or not path.strip():
            return None, "Error: path cannot be empty"
        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            first = candidate.parts[0].lower() if candidate.parts else ""
            base = (
                self.workspace_root
                if first in {"inputs", "work", "outputs"}
                else self.working_directory
            )
            candidate = base / candidate
        try:
            resolved = candidate.resolve(strict=False)
        except (OSError, RuntimeError, ValueError) as exc:
            return None, f"Error: cannot resolve path: {exc}"
        if any(_is_within(resolved, root) for root in self.protected_roots):
            return None, "Error: access denied. The path is in a protected location."
        if not any(_is_within(resolved, root) for root in self.allowed_roots):
            return None, (
                "Error: access denied. The path is outside this Agent's workspace "
                "and configured allowed directories."
            )
        if exists and not resolved.exists():
            return None, f"Error: path not found: {path}"
        return resolved, ""
