"""Tests for host-native command execution and background processes."""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

from xiaomei_brain.tools.builtin import command, file_ops
from xiaomei_brain.tools.builtin.process import manage_process
from xiaomei_brain.tools.execution_context import bind_tool_execution


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

    assert isinstance(result, str)
    assert Path(result.strip()).resolve() == agent_dir / "workspace"


def test_command_preserves_utf8_output(tmp_path, monkeypatch):
    monkeypatch.setattr(file_ops, "_output_base", str(tmp_path / "agent"))
    expression = (
        "[Console]::Write('你好')"
        if sys.platform == "win32"
        else "printf '你好'"
    )

    result = command.run_command(expression)

    assert result == "你好"


def test_command_nonzero_exit_is_an_explicit_error(tmp_path, monkeypatch):
    monkeypatch.setattr(file_ops, "_output_base", str(tmp_path / "agent"))
    expression = "exit 7"

    result = command.run_command(expression)

    assert isinstance(result, str)
    assert result.startswith("Error: command exited with code 7")


def test_command_can_be_cancelled_during_execution(tmp_path, monkeypatch):
    monkeypatch.setattr(file_ops, "_output_base", str(tmp_path / "agent"))
    cancelled = threading.Event()
    timer = threading.Timer(0.2, cancelled.set)
    expression = (
        "Start-Sleep -Seconds 5"
        if sys.platform == "win32"
        else "sleep 5"
    )

    timer.start()
    started = time.monotonic()
    try:
        with bind_tool_execution(
            tool_call_id="cancel-test",
            tool_name=command.command_tool_name(),
            arguments={"command": expression},
            artifact_callback=None,
            cancel_check=cancelled.is_set,
        ):
            result = command.run_command(expression)
    finally:
        timer.cancel()

    assert isinstance(result, str)
    assert result.startswith("Error: command cancelled")
    assert time.monotonic() - started < 4


def test_command_timeout_stops_the_process_tree(tmp_path, monkeypatch):
    monkeypatch.setattr(file_ops, "_output_base", str(tmp_path / "agent"))
    expression = (
        "Start-Sleep -Seconds 5"
        if sys.platform == "win32"
        else "sleep 5"
    )

    started = time.monotonic()
    result = command.run_command(expression, timeout=0.2)

    assert isinstance(result, str)
    assert result.startswith("Error: command timed out after 0.2 seconds")
    assert time.monotonic() - started < 4


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
