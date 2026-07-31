"""Tests for the shell-independent file and search tools."""

from __future__ import annotations

from xiaomei_brain.tools.builtin import file_ops
from xiaomei_brain.tools.execution_context import bind_tool_execution


def _context(root):
    return bind_tool_execution(
        tool_call_id="call-1",
        tool_name="test",
        arguments={},
        artifact_callback=None,
        workspace_root=str(root),
        working_directory=str(root),
        output_root=str(root),
    )


def test_write_read_edit_round_trip(tmp_path):
    with _context(tmp_path):
        written = file_ops.write("notes/example.txt", "first\nsecond\n")
        read = file_ops.read("notes/example.txt")
        edited = file_ops.edit("notes/example.txt", "second", "changed")

    assert written["created"] is True
    assert "1|first" in read["content"]
    assert edited["replacements"] == 1
    assert (tmp_path / "notes/example.txt").read_text() == "first\nchanged\n"


def test_edit_diff_keeps_changed_lines_separate_without_final_newline(tmp_path):
    with _context(tmp_path):
        file_ops.write("notes.txt", "old")
        edited = file_ops.edit("notes.txt", "old", "new")

    assert "-old\n+new\n" in edited["diff"]


def test_relative_parent_escape_is_rejected(tmp_path):
    with _context(tmp_path):
        result = file_ops.write("../outside.txt", "no")

    assert "error" in result
    assert not (tmp_path.parent / "outside.txt").exists()


def test_protected_path_stays_denied_when_extra_root_is_broad(tmp_path, monkeypatch):
    protected = tmp_path / ".ssh"
    protected.mkdir()
    monkeypatch.setattr(file_ops, "_PROTECTED_ROOTS", (protected.resolve(),))
    monkeypatch.setenv("XIAOMEI_ALLOWED_PATHS", str(tmp_path))
    with _context(tmp_path):
        result = file_ops.read(str(protected / "id_rsa"))

    assert "protected location" in result["error"]


def test_glob_and_grep(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src/a.py").write_text("alpha\nneedle\n", encoding="utf-8")
    (tmp_path / "src/b.txt").write_text("needle\n", encoding="utf-8")
    with _context(tmp_path):
        found = file_ops.glob("**/*.py")
        matches = file_ops.grep("needle", glob="*.py")

    assert found["files"] == ["src/a.py"]
    assert matches["total_matches"] == 1
    assert matches["matches"][0]["path"] == "src/a.py"


def test_assignment_named_directories_resolve_from_workspace_root(tmp_path):
    work = tmp_path / "work"
    outputs = tmp_path / "outputs"
    work.mkdir()
    outputs.mkdir()
    with bind_tool_execution(
        tool_call_id="call-assignment",
        tool_name="write",
        arguments={},
        artifact_callback=None,
        workspace_root=str(tmp_path),
        working_directory=str(work),
        output_root=str(outputs),
    ):
        helper = file_ops.write("helper.py", "work")
        deliverable = file_ops.write("outputs/result.md", "final")

    assert helper["path"] == str(work / "helper.py")
    assert deliverable["path"] == str(outputs / "result.md")
