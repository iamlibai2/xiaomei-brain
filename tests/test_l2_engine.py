from types import SimpleNamespace
from unittest.mock import Mock

from xiaomei_brain.consciousness.intent import Intent, IntentType
from xiaomei_brain.consciousness.l2_engine import L2Engine
from xiaomei_brain.tools.registry import ToolRegistry


def test_l2_core_inherits_and_refreshes_execution_context():
    first_environment = object()
    main_core = SimpleNamespace(
        llm=Mock(),
        tool_execution_environment=first_environment,
        tool_workspace_root="C:/agent/workspace",
        tool_working_directory="C:/agent/workspace/work",
        tool_output_root="C:/agent/workspace/outputs",
    )
    agent_instance = SimpleNamespace(
        tools=ToolRegistry(),
        _get_agent=lambda: main_core,
    )
    engine = L2Engine(SimpleNamespace(agent=agent_instance, _agent_id="test"))

    runtime = engine._get_l2_agent()

    assert runtime.tool_execution_environment is first_environment
    assert runtime.tool_workspace_root == "C:/agent/workspace"
    assert runtime.tool_working_directory == "C:/agent/workspace/work"
    assert runtime.tool_output_root == "C:/agent/workspace/outputs"

    replacement_environment = object()
    main_core.tool_execution_environment = replacement_environment
    assert engine._get_l2_agent() is runtime
    assert runtime.tool_execution_environment is replacement_environment


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


def test_desire_starvation_marks_original_intent_urgent_without_rewriting_it():
    urgent = set()
    engine = L2Engine(SimpleNamespace(
        intent_slot=SimpleNamespace(urgent_intents=urgent),
    ))
    intent = Intent(
        type=IntentType.LEARN,
        priority=60,
        content="learn calendar API",
        params={"learn_topic": "calendar API"},
    )

    engine._mark_desire_intent_urgent(
        "desire_starvation_achievement",
        intent,
    )

    assert intent.type is IntentType.LEARN
    assert intent.params == {"learn_topic": "calendar API"}
    assert urgent == {"learn"}


def test_person_directed_intent_resolves_display_name_to_person_id():
    person = SimpleNamespace(person_id="person_1", display_name="博士")
    store = SimpleNamespace(list_people=lambda **_kwargs: [person])
    agent = SimpleNamespace(people_service=SimpleNamespace(store=store))
    consciousness = SimpleNamespace(
        agent=agent,
        intent_slot=SimpleNamespace(urgent_intents={"greet"}),
    )
    engine = L2Engine(consciousness)
    intent = Intent(
        type=IntentType.GREET,
        priority=80,
        content="想跟博士聊几句",
        params={"user_id": "博士", "message": "博士，最近怎么样？"},
    )

    resolved = engine._prepare_intent_for_buffer(intent)

    assert resolved is not None
    assert resolved.params["user_id"] == "person_1"
    assert resolved.params["scope_type"] == "person"
    assert resolved.params["session_id"] == ""


def test_person_directed_intent_without_valid_target_is_not_buffered():
    store = SimpleNamespace(list_people=lambda **_kwargs: [])
    agent = SimpleNamespace(people_service=SimpleNamespace(store=store))
    urgent = {"greet"}
    engine = L2Engine(SimpleNamespace(
        agent=agent,
        intent_slot=SimpleNamespace(urgent_intents=urgent),
    ))

    result = engine._prepare_intent_for_buffer(Intent(
        type=IntentType.GREET,
        priority=80,
        content="想问候某个人",
    ))

    assert result is None
    assert "greet" not in urgent
