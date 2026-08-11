"""Tests for the shell-independent file and search tools."""

from __future__ import annotations

from pathlib import Path

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


def test_workspace_prefix_is_a_virtual_root_not_a_nested_directory(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    with _context(workspace):
        result = file_ops.write("workspace/analyze.py", "print('ok')\n")

    assert Path(result["path"]).resolve() == (workspace / "analyze.py").resolve()
    assert not (workspace / "workspace" / "analyze.py").exists()


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


def test_attachment_archive_is_searchable_and_read_only(tmp_path):
    workspace = tmp_path / "workspace"
    attachments = tmp_path / "attachments"
    session = attachments / "session-hash"
    workspace.mkdir()
    session.mkdir(parents=True)
    stored = session / "photo.jpg"
    stored.write_bytes(b"photo")
    note = session / "source.txt"
    note.write_text("from dingtalk", encoding="utf-8")

    with bind_tool_execution(
        tool_call_id="call-assets",
        tool_name="glob",
        arguments={},
        artifact_callback=None,
        workspace_root=str(workspace),
        working_directory=str(workspace),
        output_root=str(workspace),
        read_only_roots=(str(attachments),),
    ):
        found = file_ops.glob("**/*.jpg", path="attachments")
        read = file_ops.read("attachments/session-hash/source.txt")
        write = file_ops.write("attachments/session-hash/new.txt", "no")
        edit = file_ops.edit(
            "attachments/session-hash/source.txt",
            "dingtalk",
            "changed",
        )
        outside = file_ops.glob("**/*", path=str(tmp_path))

    assert found["files"] == ["attachments/session-hash/photo.jpg"]
    assert "from dingtalk" in read["content"]
    assert "read-only" in write["error"]
    assert "read-only" in edit["error"]
    assert "outside this Agent" in outside["error"]
    assert note.read_text(encoding="utf-8") == "from dingtalk"


def test_unified_workspace_outputs_are_addressable_and_inputs_are_read_only(tmp_path):
    workspace = tmp_path / "workspace"
    inputs = workspace / "inputs"
    workspace.mkdir()
    inputs.mkdir()
    (inputs / "source.txt").write_text("source", encoding="utf-8")

    with bind_tool_execution(
        tool_call_id="call-media-assets",
        tool_name="write",
        arguments={},
        artifact_callback=None,
        workspace_root=str(workspace),
        working_directory=str(workspace),
        output_root=str(workspace),
        read_only_roots=(str(inputs),),
    ):
        image_result = file_ops.write("outputs/images/description.txt", "image")
        music_result = file_ops.write("outputs/audio/credits.txt", "music")
        found = file_ops.glob("**/*.txt")
        input_write = file_ops.write("inputs/changed.txt", "no")

    assert image_result["relative_path"] == "outputs/images/description.txt"
    assert music_result["relative_path"] == "outputs/audio/credits.txt"
    assert set(found["files"]) == {
        "inputs/source.txt", "outputs/images/description.txt", "outputs/audio/credits.txt",
    }
    assert "read-only" in input_write["error"]


def test_glob_supports_brace_alternatives_across_workspace(tmp_path):
    workspace = tmp_path / "workspace"
    music = workspace / "outputs" / "audio"
    workspace.mkdir()
    music.mkdir(parents=True)
    (music / "song.mp3").write_bytes(b"mp3")
    (music / "voice.wav").write_bytes(b"wav")
    (music / "notes.txt").write_text("not audio", encoding="utf-8")

    with bind_tool_execution(
        tool_call_id="call-brace-glob",
        tool_name="glob",
        arguments={},
        artifact_callback=None,
        workspace_root=str(workspace),
        working_directory=str(workspace),
        output_root=str(workspace),
    ):
        found = file_ops.glob("**/*.{mp3,wav,m4a}")

    assert set(found["files"]) == {
        "outputs/audio/song.mp3", "outputs/audio/voice.wav",
    }
    assert found["count"] == 2


def test_empty_workspace_glob_returns_plain_empty_result(tmp_path):
    with _context(tmp_path):
        found = file_ops.glob("**/*.{mp3,wav}")

    assert found["files"] == []
    assert "hint" not in found
