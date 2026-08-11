from pathlib import Path
from types import SimpleNamespace

from xiaomei_brain.agent.render_execution_context import (
    _render_explicit_workspace_files,
)


def _agent(workspace: Path) -> SimpleNamespace:
    return SimpleNamespace(tool_workspace_root=str(workspace))


def test_renders_existing_explicit_workspace_file_without_glob(tmp_path: Path) -> None:
    target = tmp_path / "music-player.visualization.html"
    target.write_text("<html></html>", encoding="utf-8")

    rendered = _render_explicit_workspace_files(
        _agent(tmp_path),
        "修改 music-player.visualization.html，让它使用 window.xiaomei.media。",
    )

    assert "music-player.visualization.html" in rendered
    assert "无需先 glob" in rendered
    assert "window.xiaomei.media" not in rendered


def test_accepts_workspace_virtual_prefix(tmp_path: Path) -> None:
    nested = tmp_path / "drafts"
    nested.mkdir()
    (nested / "report.md").write_text("draft", encoding="utf-8")

    rendered = _render_explicit_workspace_files(
        _agent(tmp_path),
        "请修改 workspace/drafts/report.md",
    )

    assert "- drafts/report.md" in rendered


def test_does_not_guess_missing_or_nested_basename(tmp_path: Path) -> None:
    nested = tmp_path / "archive"
    nested.mkdir()
    (nested / "report.md").write_text("old", encoding="utf-8")

    rendered = _render_explicit_workspace_files(
        _agent(tmp_path),
        "请修改 report.md 和 missing.html",
    )

    assert rendered == ""


def test_does_not_expose_file_outside_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (tmp_path / "secret.txt").write_text("secret", encoding="utf-8")

    rendered = _render_explicit_workspace_files(
        _agent(workspace),
        "请读取 ../secret.txt",
    )

    assert rendered == ""
