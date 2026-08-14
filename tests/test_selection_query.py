from __future__ import annotations

import pytest

from xiaomei_brain.base.selection_query import (
    SelectionQuery,
    embed_selection_query,
)
from xiaomei_brain.tools.dynamic import build_tool_selection_context


def test_tool_selection_query_separates_current_intent_from_recent_context():
    query = build_tool_selection_context(
        [
            {"role": "user", "content": "演示文稿会写吗"},
            {"role": "user", "content": "随便写一页"},
        ],
        [{"kind": "file", "mime_type": "text/plain", "name": "要求.txt"}],
    )

    assert isinstance(query, SelectionQuery)
    assert "随便写一页" in query.primary
    assert "要求.txt" in query.primary
    assert query.context == "演示文稿会写吗"


def test_weighted_selection_embedding_prefers_current_intent():
    class _Embedder:
        @staticmethod
        def embed_batch(_texts, *, source):
            assert source == "tool.prefetch"
            return [[1.0, 0.0], [0.0, 1.0]]

    vector = embed_selection_query(
        _Embedder(),
        SelectionQuery("当前输入", "附近输入"),
        source="tool.prefetch",
    )

    assert vector[0] == pytest.approx(0.948683, abs=1e-6)
    assert vector[1] == pytest.approx(0.316228, abs=1e-6)
    assert vector[0] > vector[1]

