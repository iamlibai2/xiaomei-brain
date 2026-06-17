"""Tests for memory/search.py -- text sanitization and chunking."""

import pytest
from xiaomei_brain.memory.search import sanitize_text, _cosine_similarity, chunk_markdown


# ── sanitize_text ─────────────────────────────────────────────────

def test_sanitize_text_normal():
    assert sanitize_text("hello world") == "hello world"


def test_sanitize_text_nfkc():
    # Fullwidth A (U+FF21) → regular A
    result = sanitize_text("\uff21")
    assert result == "A"


def test_sanitize_text_control_removed():
    assert sanitize_text("he\x00llo") == "hello"


def test_sanitize_text_keeps_tab_nl_cr():
    # Second pass replaces all C-category chars with space → \t\n\r become spaces
    result = sanitize_text("hello\tworld\n!\r")
    assert "\t" not in result
    assert "\n" not in result


def test_sanitize_text_non_printable_to_space():
    # U+200B is ZERO WIDTH SPACE (Cf category)
    result = sanitize_text("he\u200bllo")
    # Cf chars get replaced with space
    assert result == "he llo"


def test_sanitize_text_collapse_spaces():
    result = sanitize_text("hello    world\t\ttest")
    assert result == "hello world test"


def test_sanitize_text_collapse_newlines():
    # Newlines replaced by spaces in second pass, then spaces collapsed
    result = sanitize_text("line1\n\n\n\nline2")
    assert result == "line1 line2"


def test_sanitize_text_strip():
    assert sanitize_text("  hello  ") == "hello"


def test_sanitize_text_mixed():
    text = "\x00hel\u200blo  world\n\n\n\n\n\x01"
    result = sanitize_text(text)
    assert "\x00" not in result
    assert "\x01" not in result
    assert "  " not in result  # spaces collapsed


# ── _cosine_similarity ────────────────────────────────────────────

def test_cosine_similarity_identical():
    assert _cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)


def test_cosine_similarity_orthogonal():
    assert _cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_cosine_similarity_opposite():
    assert _cosine_similarity([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)


def test_cosine_similarity_zero_vector():
    assert _cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0


def test_cosine_similarity_both_zero():
    assert _cosine_similarity([0.0, 0.0], [0.0, 0.0]) == 0.0


def test_cosine_similarity_mixed():
    # cos(45°) = 1/sqrt(2) ≈ 0.707
    result = _cosine_similarity([1.0, 0.0], [1.0, 1.0])
    assert result == pytest.approx(0.707, abs=0.001)


# ── chunk_markdown ────────────────────────────────────────────────

def test_chunk_markdown_empty():
    assert chunk_markdown("") == []


def test_chunk_markdown_short():
    result = chunk_markdown("hello world", max_chunk_chars=500)
    assert len(result) == 1
    assert result[0] == "hello world"


def test_chunk_markdown_by_headers():
    content = "## Section 1\ncontent one\n\n## Section 2\ncontent two"
    result = chunk_markdown(content)
    assert len(result) == 2
    assert "Section 1" in result[0]
    assert "Section 2" in result[1]


def test_chunk_markdown_no_headers():
    content = "just some text\nwithout headers"
    result = chunk_markdown(content)
    assert len(result) == 1


def test_chunk_markdown_oversized_section():
    # Section larger than max_chunk → split by paragraphs (double newlines)
    content = "## Large\n\n" + "\n\n".join(["para " + str(i) * 200 for i in range(5)])
    result = chunk_markdown(content, max_chunk_chars=500)
    assert len(result) > 1


def test_chunk_markdown_custom_max_chars():
    content = "## A\nshort\n\n## B\nalso short"
    result = chunk_markdown(content, max_chunk_chars=1000)
    # Both sections fit within 1000 chars
    assert len(result) == 2
