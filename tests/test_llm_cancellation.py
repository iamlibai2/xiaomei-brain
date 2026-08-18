from __future__ import annotations

import threading

from xiaomei_brain.agent.core import Agent
from xiaomei_brain.llm.client import LLMCancelled, LLMClient


def test_established_response_is_closed_when_cancelled():
    cancelled = threading.Event()
    closed = threading.Event()

    class Response:
        def close(self):
            closed.set()

    with LLMClient._cancel_response_on_signal(Response(), cancelled.is_set):
        cancelled.set()
        assert closed.wait(0.5)


def test_stream_cancellation_does_not_fall_back_to_second_request():
    class LLM:
        _reasoning_end_yielded = False
        _last_stream_response = None

        def chat_stream(self, _messages, _tools, cancel_check=None):
            assert cancel_check is not None
            raise LLMCancelled()
            yield "unreachable"

        def chat(self, **_kwargs):
            raise AssertionError("cancelled streaming request must not fall back")

    agent = Agent(llm=LLM(), tools=None)
    chunks = list(agent._call_llm([], None, cancel_check=lambda: True))
    assert chunks == []
