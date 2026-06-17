"""Tests for purpose/purpose_engine.py -- pure markdown parsers."""

import pytest
from xiaomei_brain.purpose.purpose_engine import _parse_identity_sections, _parse_identity_list


# ── _parse_identity_sections ──────────────────────────────────────

def test_parse_sections_single():
    md = "# Identity\n小美的身份"
    sections = _parse_identity_sections(md)
    assert sections == {"Identity": "小美的身份"}


def test_parse_sections_multiple():
    md = "# Identity\n小美\n\n# Values\n诚实\n善良"
    sections = _parse_identity_sections(md)
    assert sections["Identity"] == "小美"
    assert sections["Values"] == "诚实\n善良"


def test_parse_sections_no_headers():
    md = "just some text\nwithout any headers"
    sections = _parse_identity_sections(md)
    assert sections == {}


def test_parse_sections_empty():
    assert _parse_identity_sections("") == {}


def test_parse_sections_trailing_text():
    md = "# Goals\n- goal 1\n- goal 2"
    sections = _parse_identity_sections(md)
    assert sections["Goals"] == "- goal 1\n- goal 2"


def test_parse_sections_multi_line_content():
    # regex r"^#\s+(.+)" captures everything after "# " → key is "Section A" for "# Section A"
    # but for "## Section A" → key is "# Section A"
    md = "# Section A\nline1\nline2\nline3"
    sections = _parse_identity_sections(md)
    assert sections["Section A"] == "line1\nline2\nline3"


# ── _parse_identity_list ──────────────────────────────────────────

def test_parse_list_simple():
    text = "- item1\n- item2\n- item3"
    items = _parse_identity_list(text)
    assert items == ["item1", "item2", "item3"]


def test_parse_list_mixed():
    text = "- item1\nsome text\n- item2\nmore text"
    items = _parse_identity_list(text)
    assert items == ["item1", "item2"]


def test_parse_list_empty():
    assert _parse_identity_list("") == []


def test_parse_list_no_matches():
    assert _parse_identity_list("just some text\nno list items") == []


def test_parse_list_strips_whitespace():
    text = "  -   item with spaces   "
    items = _parse_identity_list(text)
    assert items == ["item with spaces"]


# ── Round-trip ────────────────────────────────────────────────────

def test_roundtrip_sections_to_list():
    md = "# Identity\n小美\n\n# Interests\n- AI\n- 心理学\n- 文学\n\n# Values\n诚实\n善良"
    sections = _parse_identity_sections(md)
    assert "Interests" in sections
    interests = _parse_identity_list(sections["Interests"])
    assert interests == ["AI", "心理学", "文学"]
