"""Tests for tui_v2/formatters.py -- duration, timestamp, text formatting."""

import pytest
import time
from xiaomei_brain.tui_v2.formatters import (
    format_duration,
    truncate,
    truncate_middle,
    indent,
)


# ── format_duration ───────────────────────────────────────────────

def test_format_duration_milliseconds():
    assert format_duration(0.5) == "500ms"


def test_format_duration_milliseconds_boundary():
    assert format_duration(0.999) == "999ms"


def test_format_duration_one_second():
    assert format_duration(1.0) == "1s"


def test_format_duration_seconds():
    assert format_duration(5.7) == "6s"  # rounded to integer


def test_format_duration_seconds_exact():
    assert format_duration(30.0) == "30s"


def test_format_duration_minutes():
    assert format_duration(125) == "2m 5s"


def test_format_duration_one_minute():
    assert format_duration(60) == "1m 0s"


def test_format_duration_hours():
    assert format_duration(3661) == "1h 1m 1s"


def test_format_duration_exact_hour():
    # 3600s = 60 min → 60 is not < 60, so goes to hours path → 1h 0m 0s
    assert format_duration(3600) == "1h 0m 0s"


def test_format_duration_two_hours():
    assert format_duration(7201) == "2h 0m 1s"


# ── truncate ──────────────────────────────────────────────────────

def test_truncate_short():
    assert truncate("hello", 10) == "hello"


def test_truncate_exact():
    assert truncate("hello", 5) == "hello"


def test_truncate_long():
    # max_len=5, ellipsis="..." (3 chars) → 5-3=2 chars
    assert truncate("hello world", 5) == "he..."


def test_truncate_custom_ellipsis():
    # max_len=7, ellipsis=".." (2) → text[:5] + ".." = "hello" + ".."
    assert truncate("hello world", 7, "..") == "hello.."


def test_truncate_empty():
    assert truncate("", 5) == ""


# ── truncate_middle ───────────────────────────────────────────────

def test_truncate_middle_short():
    assert truncate_middle("hello", 10) == "hello"


def test_truncate_middle_long():
    # "hello world" = 11 chars, max_len=7, ellipsis="..." (3) → (7-3)//2 = 2
    # text[:2] + "..." + text[-2:] → "he...ld"
    assert truncate_middle("hello world", 7) == "he...ld"


def test_truncate_middle_odd_max():
    # "hello world" = 11, max_len=8, ellipsis=3 → (8-3)//2 = 2
    # text[:2] + "..." + text[-2:] → "he...ld"
    assert truncate_middle("hello world", 8) == "he...ld"


def test_truncate_middle_small_max():
    # max_len=4, ellipsis=3 → (4-3)//2 = 0
    # text[:0] + "..." + text[-0:] → "" + "..." + "hello" (Python: text[-0:] == text[0:])
    assert truncate_middle("hello", 4) == "...hello"


# ── indent ────────────────────────────────────────────────────────

def test_indent_single_line():
    assert indent("hello") == "  hello"


def test_indent_multi_line():
    assert indent("hello\nworld") == "  hello\n  world"


def test_indent_empty():
    # Empty string → split returns [""] → single line gets prefix
    assert indent("") == "  "


def test_indent_custom_prefix():
    assert indent("hello", ">>> ") == ">>> hello"
