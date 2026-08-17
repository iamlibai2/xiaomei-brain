import threading
from types import SimpleNamespace
from unittest.mock import Mock

from xiaomei_brain.consciousness.core import Consciousness
from xiaomei_brain.consciousness.intent import Intent, IntentType
from xiaomei_brain.consciousness.l2_engine import L2Engine
from xiaomei_brain.tools.registry import ToolRegistry


def test_completed_conversations_remain_pending_per_person_and_session():
    consciousness = Consciousness.__new__(Consciousness)
    consciousness._last_interaction_user_id = ""
    consciousness._last_interaction_session_id = ""
    consciousness._intent_scope_lock = threading.Lock()
    consciousness._pending_intent_scopes = {}
    consciousness.self_image = SimpleNamespace(
        update_from_interaction=lambda *_args, **_kwargs: None,
    )

    consciousness.on_user_interaction(
        "做一个 PPT",
        "好",
        user_id="person-1",
        session_id="session-1",
    )
    consciousness.on_user_interaction(
        "写一个 Word",
        "好",
        user_id="person-2",
        session_id="session-2",
    )

    scopes = consciousness.pending_intent_scopes()
    assert [(item["user_id"], item["session_id"]) for item in scopes] == [
        ("person-2", "session-2"),
        ("person-1", "session-1"),
    ]

    consciousness.consume_intent_scope("person-2", "session-2")

    remaining = consciousness.pending_intent_scopes()
    assert [(item["user_id"], item["session_id"]) for item in remaining] == [
        ("person-1", "session-1"),
    ]


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


def test_autonomous_learn_intent_is_temporarily_rejected():
    urgent = {"learn"}
    engine = L2Engine(SimpleNamespace(
        intent_slot=SimpleNamespace(urgent_intents=urgent),
    ))

    prepared = engine._prepare_intent_for_buffer(Intent(
        type=IntentType.LEARN,
        priority=60,
        content="学习推广方法",
        params={"learn_topic": "推广方法"},
    ))

    assert prepared is None
    assert urgent == set()


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


def test_l2_parses_mission_intent_fields():
    engine = L2Engine(SimpleNamespace())
    intent = engine._parse_intent_response(
        """thinking\n---INTENT---
INTENT: ADVANCE_MISSION
REASON: 现在最适合继续准备第一批推广内容
TARGET_USER: -
TARGET_SESSION: -
TOPIC: -
MISSION_ID: mission_123
MISSION_TITLE: -
MISSION_OBJECTIVE: -
"""
    )

    assert intent is not None
    assert intent.type is IntentType.ADVANCE_MISSION
    assert intent.params["mission_id"] == "mission_123"


def test_l2_preserves_multiline_proactive_message():
    engine = L2Engine(SimpleNamespace())
    intent = engine._parse_intent_response(
        """thinking
---INTENT---
INTENT: talk
REASON: 想说几句话
TARGET_USER: person_1
TARGET_SESSION: session-1
MISSION_ID: -
MISSION_TITLE: -
MISSION_OBJECTIVE: -
MESSAGE: 博士，等一下。

我刚才那一下回得太机械了。
这一次把整段话都交给你。"""
    )

    assert intent is not None
    assert intent.params["message"] == (
        "博士，等一下。\n\n"
        "我刚才那一下回得太机械了。\n"
        "这一次把整段话都交给你。"
    )


def test_mission_intent_inherits_durable_person_and_session_scope():
    mission = SimpleNamespace(
        id="mission_123",
        status=SimpleNamespace(value="active"),
        accountable_person_id="person_1",
        origin_session_id="session_1",
    )
    engine = L2Engine(SimpleNamespace(
        intent_slot=SimpleNamespace(urgent_intents=set()),
    ))
    engine._mission_service = SimpleNamespace(
        require=lambda _mission_id: mission,
        due_signals=lambda **_kwargs: [{"mission_id": "mission_123"}],
    )

    prepared = engine._prepare_intent_for_buffer(Intent(
        type=IntentType.ADVANCE_MISSION,
        priority=70,
        content="继续推进",
        params={"mission_id": "mission_123"},
    ))

    assert prepared is not None
    assert prepared.params["user_id"] == "person_1"
    assert prepared.params["session_id"] == "session_1"
    assert prepared.params["scope_type"] == "session"


def test_l2_sees_relevant_waiting_mission_and_may_choose_it_without_due_signal():
    mission = SimpleNamespace(
        id="mission_waiting",
        title="持续推广小美",
        objective="持续获得第一批真实用户",
        status=SimpleNamespace(value="waiting"),
        priority=0.8,
        accountable_person_id="person_1",
        origin_session_id="session_1",
        progress_summary="Day1 文案已经完成",
        waiting_reason="等待博士选择发布方式",
        waiting_for=({"type": "choice", "key": "publish_mode", "description": "选择 A 或 B"},),
        next_run_at=None,
        updated_at=100.0,
    )
    engine = L2Engine(SimpleNamespace(
        agent=SimpleNamespace(people_service=None),
        intent_slot=SimpleNamespace(urgent_intents=set()),
    ))
    engine._mission_service = SimpleNamespace(
        list=lambda **_kwargs: [mission],
        due_signals=lambda **_kwargs: [],
        require=lambda _mission_id: mission,
    )

    prompt = engine._build_intent_prompt(
        "",
        context_user_id="person_1",
        context_session_id="session_1",
    )

    assert "MISSION_ID: mission_waiting" in prompt
    assert "状态: waiting" in prompt
    assert "等待博士选择发布方式" in prompt
    assert "选择 A 或 B" in prompt
    assert "一次性自主工作" in prompt
    assert "即使行动由刚收到的对话触发" in prompt

    prepared = engine._prepare_intent_for_buffer(Intent(
        type=IntentType.ADVANCE_MISSION,
        priority=70,
        content="博士已经选择 A，继续推进推广工作",
        params={"mission_id": mission.id},
    ))

    assert prepared is not None
    assert prepared.params["mission_id"] == mission.id
    assert prepared.params["user_id"] == "person_1"
    assert prepared.params["session_id"] == "session_1"


def test_l2_sees_active_missions_owned_by_other_people_without_context_leakage():
    def mission(identifier, person_id, session_id, priority):
        return SimpleNamespace(
            id=identifier,
            title=f"Mission {identifier}",
            objective=f"Objective {identifier}",
            status=SimpleNamespace(value="active"),
            priority=priority,
            accountable_person_id=person_id,
            origin_session_id=session_id,
            progress_summary="等待推进",
            waiting_reason="",
            waiting_for=(),
            next_run_at=None,
            updated_at=100.0,
        )

    current = mission("mission_current", "person_1", "session_1", 0.4)
    other = mission("mission_other", "person_2", "session_2", 0.9)
    engine = L2Engine(SimpleNamespace(
        agent=SimpleNamespace(people_service=None),
        intent_slot=SimpleNamespace(urgent_intents=set()),
    ))
    engine._mission_service = SimpleNamespace(
        list=lambda **_kwargs: [other, current],
        due_signals=lambda **_kwargs: [
            {"mission_id": current.id},
            {"mission_id": other.id},
        ],
    )

    candidates = engine._mission_decision_candidates(
        context_user_id="person_1",
        context_session_id="session_1",
    )
    prompt = engine._build_intent_prompt(
        "",
        context_user_id="person_1",
        context_session_id="session_1",
    )

    assert [item.id for item in candidates] == ["mission_current", "mission_other"]
    assert "MISSION_ID: mission_current" in prompt
    assert "MISSION_ID: mission_other" in prompt
    # Only durable Mission metadata is shared at decision time. Conversation
    # messages remain isolated and are loaded after one Mission is selected.
    assert "session_1" in prompt
    assert "session_2" in prompt


def test_person_directed_intent_keeps_the_conversation_that_fueled_decision():
    person = SimpleNamespace(person_id="person_1", display_name="博士")
    store = SimpleNamespace(list_people=lambda **_kwargs: [person])
    agent = SimpleNamespace(people_service=SimpleNamespace(store=store))
    consciousness = SimpleNamespace(
        agent=agent,
        intent_slot=SimpleNamespace(urgent_intents={"work"}),
    )
    engine = L2Engine(consciousness)
    intent = Intent(
        type=IntentType.WORK,
        priority=70,
        content="继续完善这个 PPT",
        params={"user_id": "person_1"},
    )

    resolved = engine._prepare_intent_for_buffer(
        intent,
        context_user_id="person_1",
        context_session_id="desktop-session-1",
    )

    assert resolved is not None
    assert resolved.params["scope_type"] == "session"
    assert resolved.params["user_id"] == "person_1"
    assert resolved.params["session_id"] == "desktop-session-1"


def test_intent_react_receives_person_and_session_context(monkeypatch):
    captured = {}
    person = SimpleNamespace(person_id="person_1", display_name="博士")
    store = SimpleNamespace(list_people=lambda **_kwargs: [person])
    agent = SimpleNamespace(
        longterm_memory=None,
        people_service=SimpleNamespace(store=store),
    )
    consciousness = SimpleNamespace(
        agent=agent,
        purpose=None,
        _agent_id="test",
        _cancel_check=lambda: False,
        self_image=SimpleNamespace(body=SimpleNamespace(
            desire_belonging=0.0,
            desire_cognition=0.0,
            desire_achievement=0.0,
            desire_expression=0.0,
            desire_significance=1.0,
        )),
    )
    engine = L2Engine(consciousness)
    def react_nodb(**kwargs):
        captured["messages"] = kwargs["messages"]
        return ""

    runtime = SimpleNamespace(react_nodb=react_nodb)
    engine._get_l2_agent = lambda: runtime

    def fake_context(*_args, **kwargs):
        captured["context_kwargs"] = kwargs
        return "scoped-system"

    monkeypatch.setattr(
        "xiaomei_brain.consciousness.l2_engine.build_simple_context",
        fake_context,
    )

    engine._call_intent_react(
        "periodic",
        user_id="person_1",
        session_id="desktop-session-1",
    )

    assert captured["context_kwargs"]["user_id"] == "person_1"
    assert captured["context_kwargs"]["session_id"] == "desktop-session-1"
    assert "desktop-session-1" in captured["messages"][1]["content"]


def test_intent_react_reviews_multiple_conversations_without_preselecting_user(monkeypatch):
    captured = {}
    people = [
        SimpleNamespace(person_id="person_1", display_name="博士"),
        SimpleNamespace(person_id="person_2", display_name="小帅"),
    ]
    store = SimpleNamespace(list_people=lambda **_kwargs: people)

    class FakeConversationDB:
        def get_recent(self, _count, *, session_id, user_id):
            return [{
                "role": "user",
                "content": f"work from {user_id} in {session_id}",
            }]

    agent = SimpleNamespace(
        longterm_memory=None,
        conversation_db=FakeConversationDB(),
        people_service=SimpleNamespace(store=store),
    )
    consciousness = SimpleNamespace(
        agent=agent,
        purpose=None,
        _agent_id="test",
        _cancel_check=lambda: False,
        self_image=SimpleNamespace(body=SimpleNamespace(
            desire_belonging=0.0,
            desire_cognition=0.0,
            desire_achievement=0.0,
            desire_expression=0.0,
            desire_significance=1.0,
        )),
    )
    engine = L2Engine(consciousness)

    def react_nodb(**kwargs):
        captured["messages"] = kwargs["messages"]
        return ""

    engine._get_l2_agent = lambda: SimpleNamespace(react_nodb=react_nodb)

    def fake_context(*_args, **kwargs):
        captured["context_kwargs"] = kwargs
        return "agent-system"

    monkeypatch.setattr(
        "xiaomei_brain.consciousness.l2_engine.build_simple_context",
        fake_context,
    )
    scopes = [
        {"user_id": "person_2", "session_id": "session-2"},
        {"user_id": "person_1", "session_id": "session-1"},
    ]

    engine._call_intent_react("pending_conversations", decision_scopes=scopes)

    assert captured["context_kwargs"]["user_id"] is None
    assert captured["context_kwargs"]["session_id"] is None
    prompt = captured["messages"][1]["content"]
    assert "session-1" in prompt
    assert "session-2" in prompt
    assert "work from person_1" in prompt
    assert "work from person_2" in prompt


def test_intent_uses_the_session_selected_from_multiple_candidates():
    people = [
        SimpleNamespace(person_id="person_1", display_name="博士"),
        SimpleNamespace(person_id="person_2", display_name="小帅"),
    ]
    store = SimpleNamespace(list_people=lambda **_kwargs: people)
    consumed = []
    consciousness = SimpleNamespace(
        agent=SimpleNamespace(people_service=SimpleNamespace(store=store)),
        intent_slot=SimpleNamespace(urgent_intents=set()),
        consume_intent_scope=lambda user_id, session_id: consumed.append((user_id, session_id)),
    )
    engine = L2Engine(consciousness)
    scopes = [
        {"user_id": "person_2", "session_id": "session-2"},
        {"user_id": "person_1", "session_id": "session-1"},
    ]
    parsed = engine._parse_intent_response(
        "---INTENT---\n"
        "INTENT: work\n"
        "REASON: continue the promised document\n"
        "TARGET_USER: person_1\n"
        "TARGET_SESSION: session-1\n"
    )

    prepared = engine._prepare_intent_for_buffer(parsed, decision_scopes=scopes)
    engine._finalize_decision_scopes(prepared, scopes)

    assert prepared.params["scope_type"] == "session"
    assert prepared.params["user_id"] == "person_1"
    assert prepared.params["session_id"] == "session-1"
    assert consumed == [("person_1", "session-1")]


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
