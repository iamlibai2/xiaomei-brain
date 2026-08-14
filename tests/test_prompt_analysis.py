from __future__ import annotations

from xiaomei_brain.llm.prompt_analysis import analyze_prompt_trace
from xiaomei_brain.llm.trace_store import ModelTraceStore


def _record(trace_id: str, created_at: float, system: str) -> dict:
    return {
        "id": trace_id,
        "created_at": created_at,
        "session_id": "session-1",
        "request": {
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": "你好"},
            ],
        },
    }


def test_prompt_analysis_reuses_top_level_tags_and_exposes_text_metadata():
    record = _record(
        "trace-2",
        2.0,
        "基础规则\n<身份>我是小美</身份>\n"
        "<历史摘要><summary index=\"1\">旧对话</summary></历史摘要>",
    )
    result = analyze_prompt_trace(record)
    sections = {item["key"]: item for item in result["sections"]}

    assert sections["身份"]["text"] == "<身份>我是小美</身份>"
    assert sections["身份"]["source"].endswith("render_consciousness_v3.py")
    assert sections["身份"]["injection"] == "always"
    assert sections["历史摘要"]["tokens"] > 0
    assert "summary" not in sections
    assert sections["__other__"]["text"] == "基础规则"
    assert round(sum(item["percentage"] for item in result["sections"]), 0) == 100


def test_prompt_analysis_compares_with_previous_call():
    previous = _record("trace-1", 1.0, "<身份>我是小美</身份><长期记忆>成都</长期记忆>")
    current = _record("trace-2", 2.0, "<身份>我是小美</身份><短期记忆>膝盖受伤</短期记忆>")
    result = analyze_prompt_trace(current, previous)
    sections = {item["key"]: item for item in result["sections"]}

    assert sections["身份"]["change"] == "unchanged"
    assert sections["短期记忆"]["change"] == "added"
    assert sections["长期记忆"]["change"] == "removed"
    assert sections["长期记忆"]["previous_text"]
    assert sections["长期记忆"]["present"] is False


def test_trace_store_returns_previous_call_from_same_session(tmp_path):
    store = ModelTraceStore(tmp_path / "traces")
    first = _record("trace-1", 1.0, "<身份>一</身份>")
    second = _record("trace-2", 2.0, "<身份>二</身份>")
    other_session = {**_record("trace-other", 1.5, "<身份>其他</身份>"), "session_id": "session-2"}
    for record in (first, other_session, second):
        store.begin(record)

    previous = store.get_previous(store.get("trace-2") or {})
    assert previous is not None
    assert previous["id"] == "trace-1"
