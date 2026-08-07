"""Regression tests for hidden blocks in OpenAI-compatible SSE streams."""

import json

from xiaomei_brain.llm.transport.chat_completions import ChatCompletionsTransport


class _StreamingResponse:
    def __init__(self, content_chunks: list[str]) -> None:
        self._content_chunks = content_chunks

    def iter_lines(self):
        for content in self._content_chunks:
            payload = {
                "choices": [{
                    "delta": {"content": content},
                    "finish_reason": None,
                }],
            }
            yield f"data: {json.dumps(payload, ensure_ascii=False)}"
        yield 'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}'
        yield "data: [DONE]"


def _visible_text(chunks: list[str]) -> str:
    outputs = ChatCompletionsTransport().stream_iter(
        _StreamingResponse(chunks),
        None,  # type: ignore[arg-type]
        None,  # type: ignore[arg-type]
    )
    return "".join(text for text, extra in outputs if extra is None)


def test_split_memory_closing_tag_never_leaks_json_tail():
    visible = _visible_text([
        "正常回复。\n\n<MEM",
        'ORY>{"relations": [], "actions": [',
        "]}\n</",
        "MEMORY>",
    ])

    assert visible.strip() == "正常回复。"
    assert "]}" not in visible


def test_split_think_closing_tag_never_leaks_hidden_tail():
    visible = _visible_text([
        "<think>内部推理",
        "不能显示</",
        "think>公开回答。",
    ])

    assert visible.strip() == "公开回答。"
    assert "内部推理" not in visible
    assert "不能显示" not in visible
