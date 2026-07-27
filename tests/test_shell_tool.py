"""Tests for robust shell command output handling."""

from pathlib import Path
import subprocess

from xiaomei_brain.tools.builtin import shell
from xiaomei_brain.tools.builtin import file_ops


def test_shell_decodes_utf8_output(monkeypatch):
    monkeypatch.setattr(
        shell.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout="你好".encode("utf-8"),
            stderr=b"",
        ),
    )

    assert shell.run_shell.execute(command="echo test") == "你好"


def test_shell_replaces_undecodable_output(monkeypatch):
    monkeypatch.setattr(shell.locale, "getpreferredencoding", lambda _do_setlocale=False: "gbk")
    monkeypatch.setattr(
        shell.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=b"result: \xaa",
            stderr=b"",
        ),
    )

    output = shell.run_shell.execute(command="echo test")

    assert output.startswith("result: ")
    assert "\ufffd" in output


def test_shell_defaults_to_current_agent_workspace(tmp_path, monkeypatch):
    agent_dir = tmp_path / "agent"
    monkeypatch.setattr(file_ops, "_output_base", str(agent_dir))
    observed = {}

    def fake_run(*args, **kwargs):
        observed.update(kwargs)
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=b"ok",
            stderr=b"",
        )

    monkeypatch.setattr(shell.subprocess, "run", fake_run)

    assert shell.run_shell.execute(command="echo test") == "ok"
    assert Path(observed["cwd"]) == agent_dir / "workspace"
    assert (agent_dir / "workspace").is_dir()


def test_shell_keeps_explicit_assignment_workspace(tmp_path, monkeypatch):
    assignment_work = tmp_path / "assignments" / "assignment-1" / "work"
    assignment_work.mkdir(parents=True)
    observed = {}

    def fake_run(*args, **kwargs):
        observed.update(kwargs)
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=b"ok",
            stderr=b"",
        )

    monkeypatch.setattr(shell.subprocess, "run", fake_run)

    assert shell.run_shell_command("echo test", cwd=str(assignment_work)) == "ok"
    assert Path(observed["cwd"]) == assignment_work
