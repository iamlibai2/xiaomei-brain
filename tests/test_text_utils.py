"""Tests for tui_v2/text_utils.py -- text sanitization pipeline."""

import pytest
from xiaomei_brain.tui_v2.text_utils import sanitize, sanitize_streaming, is_binary


# ── sanitize ──────────────────────────────────────────────────────

def test_sanitize_normal_text():
    assert sanitize("hello world") == "hello world"


def test_sanitize_removes_null():
    assert sanitize("he\x00llo") == "hello"


def test_sanitize_removes_control_chars():
    # \x01 through \x08
    for cp in range(1, 9):
        assert sanitize(chr(cp)) == "", f"control char \\x{cp:02x} not removed"
    # \x0b, \x0c
    assert sanitize("\x0b") == ""
    assert sanitize("\x0c") == ""


def test_sanitize_keeps_tab():
    assert sanitize("\t") == "\t"


def test_sanitize_keeps_newline():
    assert sanitize("\n") == "\n"


def test_sanitize_keeps_carriage_return():
    assert sanitize("\r") == "\r"


def test_sanitize_keeps_esc():
    # \x1b (ESC) must be preserved for ANSI rendering
    assert sanitize("\x1b") == "\x1b"


def test_sanitize_surrogate_cleanup():
    # Surrogate chars become \ufffd then no special handling (already cleaned by encode/decode)
    result = sanitize("\ud800hello", min_replacements=1)
    # After encode("utf-8", "replace").decode("utf-8"), surrogates become \ufffd
    # With min_replacements=1, binary detection may trigger
    # Single surrogate in short text won't trigger binary detection (< max_replacement_ratio)
    assert "\ud800" not in result


def test_sanitize_binary_detection():
    # Create text where every line has many replacement chars
    binary_like = ("\ufffd" * 20 + "\n") * 20
    result = sanitize(binary_like, min_replacements=12)
    assert result == "[binary data omitted]"


def test_sanitize_binary_detection_partial():
    # Only some lines are binary, not enough to trigger full replace
    text = "normal line\n" + "\ufffd" * 20 + "\n"
    result = sanitize(text, min_replacements=12)
    # Not all lines are binary → not replaced
    assert result != "[binary data omitted]"


def test_sanitize_below_min_replacements():
    # Fewer than min_replacements replacement chars → binary detection skipped
    text = "\ufffd" * 5
    result = sanitize(text, min_replacements=12)
    # Below threshold, skips binary check entirely
    assert "\ufffd" in result


def test_sanitize_max_replacement_ratio_custom():
    # With very low threshold, even a small ratio triggers
    binary_like = ("\ufffd" * 5 + "\n") * 3
    result = sanitize(binary_like, max_replacement_ratio=0.1, min_replacements=5)
    # replacement_count=15 >= min_replacements=5, and all lines have high ratio > 0.1 → binary
    assert result == "[binary data omitted]"


# ── sanitize_streaming ────────────────────────────────────────────

def test_sanitize_streaming_removes_control():
    assert sanitize_streaming("he\x00llo") == "hello"


def test_sanitize_streaming_surrogates():
    result = sanitize_streaming("te\ud800st")
    assert "\ud800" not in result


def test_sanitize_streaming_keeps_tab_nl():
    assert sanitize_streaming("\t\n\r") == "\t\n\r"


def test_sanitize_streaming_no_binary_detection():
    # streaming version skips binary detection entirely
    text = "\ufffd" * 100
    result = sanitize_streaming(text)
    assert result != "[binary data omitted]"


# ── is_binary ─────────────────────────────────────────────────────

def test_is_binary_empty():
    assert is_binary("") is False


def test_is_binary_normal_text():
    assert is_binary("hello world") is False


def test_is_binary_true():
    # 50% binary chars
    text = "ab" + "\x00" * 4  # 6 chars, 4 non-printable = 66% > 30%
    assert is_binary(text) is True


def test_is_binary_false_low_ratio():
    # Only 25% binary chars
    text = "abc" + "\x00"  # 4 chars, 1 non-printable = 25% < 30%
    assert is_binary(text) is False
