"""Tests for robust shell command output handling."""

import subprocess

from xiaomei_brain.tools.builtin import shell


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
