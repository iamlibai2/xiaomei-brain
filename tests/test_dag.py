"""Tests for DAG summary graph."""

import os
import tempfile
import pytest
from unittest.mock import Mock

from xiaomei_brain.memory.dag import DAGSummaryGraph


@pytest.fixture
def dag(mock_llm):
    """Create a DAG with a temp SQLite and mock LLM."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "brain.db")
        g = DAGSummaryGraph(db_path=db_path, llm_client=mock_llm)
        yield g


@pytest.fixture
def mock_llm():
    """LLM that returns a short summary."""
    llm = Mock()
    llm.chat.return_value.content = "用户和小美讨论了Python。"
    return llm


def test_empty_has_no_summaries(dag):
    """Fresh instance has no summaries."""
    result = dag.expand(1)
    assert result == []


def test_compact_creates_leaf_node(dag):
    """Compact messages into a leaf summary."""
    messages = [
        {"id": i, "role": "user", "content": f"消息{i}"}
        for i in range(8)
    ]
    node = dag.compact("s1", list(range(8)), messages, user_id="u1")

    assert node is not None
    assert node.content == "用户和小美讨论了Python。"
    assert node.depth == 0
    assert len(node.message_ids) == 8


def test_expand_retrieves_node(dag):
    """Stored leaf node is retrievable via get_higher_summaries.

    Note: expand() on a leaf node requires the messages table (managed by
    ConversationDB), which doesn't exist in this isolated test. We verify
    the node is queryable through the summary-level API instead.
    """
    messages = [{"id": i, "role": "user", "content": f"消息{i}"} for i in range(8)]
    node = dag.compact("s2", list(range(8)), messages, user_id="u1")

    # Verify node is queryable through higher-summaries API
    summaries = dag.get_higher_summaries("s2", user_id="u1")
    assert len(summaries) == 1
    assert summaries[0].id == node.id
    assert summaries[0].depth == 0
    assert len(summaries[0].message_ids) == 8


def test_get_higher_summaries_empty(dag):
    """No higher-level summaries exist initially."""
    result = dag.get_higher_summaries("s3")
    assert len(result) == 0


def test_promote_creates_parent_level(dag):
    """After 4+ leaves in same session, auto-promote creates a parent summary.

    compact() internally calls _check_promote(), so the 4th compact triggers
    automatic promotion — no need to call promote() explicitly.
    """
    session_id = "s4"
    for batch in range(4):
        messages = [
            {"id": batch * 8 + i, "role": "user", "content": f"批次{batch}-消息{i}"}
            for i in range(8)
        ]
        dag.compact(
            session_id,
            list(range(batch * 8, batch * 8 + 8)),
            messages,
            user_id="u1",
        )

    # After 4 compacts, auto-promotion should have created a depth >= 1 node
    higher = dag.get_higher_summaries(session_id, user_id="u1")
    assert len(higher) > 0
    parent = higher[0]
    assert parent.depth >= 1
    assert len(parent.child_ids) >= 4
