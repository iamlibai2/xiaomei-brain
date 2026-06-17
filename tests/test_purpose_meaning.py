"""Tests for purpose/meaning.py -- Meaning dataclass."""

import pytest
from xiaomei_brain.purpose.meaning import Meaning


# ── Defaults ──────────────────────────────────────────────────────────

def test_meaning_defaults():
    m = Meaning()
    assert m.identity == ""
    assert len(m.values) == 5
    assert len(m.constraints) == 3
    assert len(m.aspirations) == 3


def test_meaning_custom():
    m = Meaning(
        identity="小美",
        values=["善良", "诚实"],
        constraints=["不伤害"],
        aspirations=["成为更好的自己"],
    )
    assert m.identity == "小美"
    assert m.values == ["善良", "诚实"]


# ── to_dict / from_dict ───────────────────────────────────────────────

def test_meaning_to_dict():
    m = Meaning(identity="小美")
    d = m.to_dict()
    assert d["identity"] == "小美"
    assert "values" in d
    assert "constraints" in d
    assert "aspirations" in d


def test_meaning_from_dict():
    m = Meaning()
    m.from_dict({
        "identity": "test",
        "values": ["v1"],
        "constraints": ["c1"],
        "aspirations": ["a1"],
    })
    assert m.identity == "test"
    assert m.values == ["v1"]


def test_meaning_from_dict_partial():
    m = Meaning(identity="original")
    m.from_dict({})
    assert m.identity == ""  # from_dict overwrites with default
    assert m.values == []


# ── get_summary ───────────────────────────────────────────────────────

def test_meaning_get_summary():
    m = Meaning(identity="小美")
    summary = m.get_summary()
    assert "小美" in summary
    assert "核心价值观" in summary
    assert "行为底线" in summary


# ── to_strategic_goal ─────────────────────────────────────────────────

def test_meaning_to_strategic_goal():
    m = Meaning(identity="小美")
    goal = m.to_strategic_goal()
    assert goal["id"] == "meaning-root"
    assert "小美" in goal["description"]
    assert goal["priority"] == 0.1
    assert "values" in goal["metadata"]
