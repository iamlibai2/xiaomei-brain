"""Regression tests for LLM pattern-response parsing."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from xiaomei_brain.memory.pattern import PatternExtractor


def _extractor() -> PatternExtractor:
    return PatternExtractor(MagicMock(), None, None, None)


def test_pattern_update_accepts_hash_prefixed_existing_id() -> None:
    raw = json.dumps({
        "patterns": [{
            "action": "UPDATE",
            "existing_pattern_id": "#12",
            "content": "夜间更偏好简洁回复",
            "category": "user_behavior",
            "subcategory": "temporal_rhythm",
            "confidence": 0.8,
        }],
    }, ensure_ascii=False)

    patterns = _extractor()._parse_response(raw)

    assert len(patterns) == 1
    assert patterns[0].memory_id == 12


def test_pattern_update_ignores_invalid_existing_id_instead_of_adding() -> None:
    raw = json.dumps({
        "patterns": [{
            "action": "UPDATE",
            "existing_pattern_id": "pattern twelve",
            "content": "无效更新不应变成新增模式",
            "confidence": 0.8,
        }],
    }, ensure_ascii=False)

    assert _extractor()._parse_response(raw) == []
