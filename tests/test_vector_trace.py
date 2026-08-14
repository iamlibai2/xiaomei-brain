from __future__ import annotations

from xiaomei_brain.base.vector_trace import (
    VectorTraceStore,
    record_vector_trace,
    set_vector_trace_callback,
    vector_trace_context,
)
from xiaomei_brain.gateway.methods.vector_traces import VectorTraceMethods


def test_vector_trace_jsonl_keeps_context_and_omits_vectors(tmp_path) -> None:
    store = VectorTraceStore(tmp_path / "vector-traces.jsonl")
    set_vector_trace_callback(store.append)
    try:
        with vector_trace_context(person_id="person-a", session_id="session-a", turn_id="turn-a"):
            record_vector_trace(
                source="tool.prefetch",
                phase="retrieval",
                query="write a report",
                candidates=[{
                    "id": "write_document",
                    "score": 0.82,
                    "selected": True,
                    "vector": [0.1, 0.2],
                }],
                selected=["write_document"],
                threshold=0.68,
            )
    finally:
        set_vector_trace_callback(None)

    result = store.list_records(session_id="session-a")
    assert result["total"] == 1
    trace = result["items"][0]
    assert trace["person_id"] == "person-a"
    assert trace["turn_id"] == "turn-a"
    assert trace["candidates"][0]["score"] == 0.82
    assert "vector" not in trace["candidates"][0]


def test_vector_trace_store_rotates_and_rpc_reads_tail(tmp_path) -> None:
    store = VectorTraceStore(
        tmp_path / "vector-traces.jsonl",
        max_bytes=256 * 1024,
        backups=2,
    )
    for index in range(4):
        store.append({
            "id": f"trace-{index}",
            "created_at": float(index),
            "source": "memory.recall",
            "phase": "retrieval",
            "session_id": "session-a",
            "query": "x" * 70_000,
        })

    class Living:
        vector_trace_store = store

    response = VectorTraceMethods(Living()).handle_list(
        "conn",
        "req",
        {"session_id": "session-a", "limit": 10},
    )
    assert response["result"]["items"][0]["id"] == "trace-3"
    assert response["result"]["total"] == 4
