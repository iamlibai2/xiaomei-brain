"""Tests for host-native command execution and background processes."""

from __future__ import annotations

import sys
from pathlib import Path

from xiaomei_brain.tools.builtin import command, file_ops
from xiaomei_brain.tools.builtin.process import manage_process


def test_command_name_matches_agent_host():
    expected = "powershell" if sys.platform == "win32" else "bash"
    assert command.command_tool.name == expected


def test_command_runs_in_agent_workspace(tmp_path, monkeypatch):
    agent_dir = tmp_path / "agent"
    monkeypatch.setattr(file_ops, "_output_base", str(agent_dir))
    expression = (
        "[System.IO.Directory]::GetCurrentDirectory()"
        if sys.platform == "win32"
        else "pwd"
    )

    result = command.run_command(expression)

    assert result["status"] == "completed"
    assert Path(result["cwd"]) == agent_dir / "workspace"
    assert str(agent_dir / "workspace").lower() in result["output"].strip().lower()


def test_command_preserves_utf8_output(tmp_path, monkeypatch):
    monkeypatch.setattr(file_ops, "_output_base", str(tmp_path / "agent"))
    expression = (
        "[Console]::Write('你好')"
        if sys.platform == "win32"
        else "printf '你好'"
    )

    result = command.run_command(expression)

    assert result["status"] == "completed"
    assert result["output"] == "你好"


def test_background_command_can_be_waited_for(tmp_path, monkeypatch):
    monkeypatch.setattr(file_ops, "_output_base", str(tmp_path / "agent"))
    expression = (
        "Start-Sleep -Milliseconds 50; [Console]::Write('done')"
        if sys.platform == "win32"
        else "sleep 0.05; printf done"
    )

    started = command.run_command(expression, run_in_background=True)
    result = manage_process("wait", started["process_id"], timeout=5)

    assert result["status"] == "completed"
    assert result["output"] == "done"


def test_catastrophic_commands_are_blocked():
    assert command.check_command("rm -rf /") is not None
    assert command.check_command("echo ok") is None
