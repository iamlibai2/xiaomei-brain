"""Masked text input — ported from Hermes (hermes_cli/secret_prompt.py).

Uses tty.setraw() + sys.stdin.read(1) for password masking,
NOT curses — so it works safely between curses.wrapper() calls.
"""

from __future__ import annotations

import sys


_BACKSPACE_CHARS = {"\b", "\x7f"}
_ENTER_CHARS = {"\r", "\n"}


def masked_input(prompt: str, *, mask: str = "*") -> str:
    """Prompt for text while showing masked typing feedback.

    Returns an empty string if the user presses Enter without typing.
    Falls back to input() when stdin/stdout are not interactive.
    """
    if not _stream_is_tty(sys.stdin) or not _stream_is_tty(sys.stdout):
        return input(prompt)

    try:
        import termios
        import tty

        fd = sys.stdin.fileno()
        old_attrs = termios.tcgetattr(fd)

        def read_char() -> str:
            return sys.stdin.read(1)

        def write(text: str) -> None:
            sys.stdout.write(text)
            sys.stdout.flush()

        try:
            tty.setraw(fd)
            return _collect_masked_input(read_char, write, prompt, mask=mask)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_attrs)

    except Exception:
        return input(prompt)


def _stream_is_tty(stream) -> bool:
    try:
        return bool(stream.isatty())
    except Exception:
        return False


def _collect_masked_input(
    read_char,
    write,
    prompt: str,
    *,
    mask: str = "*",
) -> str:
    """Read one line while writing a mask character per typed char."""
    value: list[str] = []
    write(prompt)

    while True:
        ch = read_char()
        if ch == "":
            write("\n")
            return ""
        if ch in _ENTER_CHARS:
            write("\n")
            return "".join(value)
        if ch == "\x03":  # Ctrl+C
            write("\n")
            raise KeyboardInterrupt
        if ch == "\x04":  # Ctrl+D
            write("\n")
            return "".join(value)
        if ch in _BACKSPACE_CHARS:
            if value:
                value.pop()
                write("\b \b")
            continue
        if ch == "\x1b":  # ESC — ignore escape sequences
            write("\n")
            return ""  # ESC cancels
        if len(ch) != 1:
            continue

        value.append(ch)
        if mask:
            write(mask)
