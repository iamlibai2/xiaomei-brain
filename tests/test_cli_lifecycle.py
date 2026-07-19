"""Tests for CLI PID validation across supported launch forms."""

from __future__ import annotations

import psutil
import pytest

from xiaomei_brain.cli.lifecycle import _build_restart_args, _is_process_alive


class _FakeProcess:
    def __init__(self, command: list[str], running: bool = True) -> None:
        self._command = command
        self._running = running

    def is_running(self) -> bool:
        return self._running

    def cmdline(self) -> list[str]:
        return self._command


@pytest.mark.parametrize(
    "command",
    [
        ["python.exe", "-m", "xiaomei_brain", "run", "xiaoming"],
        [r"C:\venv\Scripts\xiaomei-brain.exe", "run", "xiaoming"],
        ["python.exe", r"C:\venv\Scripts\xiaomei-brain", "run", "xiaoming"],
    ],
)
def test_is_process_alive_accepts_supported_launch_forms(monkeypatch, command: list[str]) -> None:
    monkeypatch.setattr(psutil, "Process", lambda _pid: _FakeProcess(command))

    assert _is_process_alive(1234, "xiaoming") is True


def test_is_process_alive_rejects_unrelated_python_process(monkeypatch) -> None:
    command = ["python.exe", "worker.py", "xiaoming"]
    monkeypatch.setattr(psutil, "Process", lambda _pid: _FakeProcess(command))

    assert _is_process_alive(1234, "xiaoming") is False


def test_is_process_alive_rejects_wrong_agent(monkeypatch) -> None:
    command = ["python.exe", "-m", "xiaomei_brain", "run", "xiaomei"]
    monkeypatch.setattr(psutil, "Process", lambda _pid: _FakeProcess(command))

    assert _is_process_alive(1234, "xiaoming") is False


def test_build_restart_args_drops_cli_and_preserves_supported_modes() -> None:
    old_args = [
        "python.exe", "-m", "xiaomei_brain", "run", "xiaoming",
        "--cli", "--no-consciousness", "--legacy",
    ]

    assert _build_restart_args("xiaoming", old_args) == [
        "xiaoming", "--no-consciousness", "--legacy",
    ]
