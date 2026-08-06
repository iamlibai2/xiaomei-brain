from types import SimpleNamespace
from unittest.mock import Mock

from xiaomei_brain.consciousness.l2_engine import L2Engine


def test_emergence_reuses_l2_agent_core():
    consciousness = SimpleNamespace()
    engine = L2Engine(consciousness)
    l2_agent = Mock()
    l2_agent.react_nodb.side_effect = lambda **kwargs: (
        kwargs["reasoning_collector"].append("reasoning") or "inner voice"
    )
    engine._l2_agent = l2_agent

    current_llm = Mock()
    content, reasoning = engine._call_emergence_react(
        current_llm,
        "emergence prompt",
        exclude_tools={"being"},
    )

    assert content == "inner voice"
    assert reasoning == ["reasoning"]
    assert l2_agent.llm is current_llm
    call = l2_agent.react_nodb.call_args.kwargs
    assert call["messages"] == [{"role": "user", "content": "emergence prompt"}]
    assert call["max_steps"] == 2
    assert call["quiet"] is True
    assert call["silent"] is True
    assert call["excluded_tool_names"] == {"being"}
