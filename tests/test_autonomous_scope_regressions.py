from __future__ import annotations

from types import SimpleNamespace

from xiaomei_brain.consciousness.action_dispatcher import ActionDispatcher, ActionExecutor
from xiaomei_brain.consciousness.action_item import ActionItem, ActionType
from xiaomei_brain.consciousness.conscious_living import ConsciousLiving
from xiaomei_brain.consciousness.intent import Intent, IntentType
from xiaomei_brain.consciousness.l2_engine import L2Engine
from xiaomei_brain.learn.queue import LearningQueue
from xiaomei_brain.schedule.cron import CronScheduler, create_cron_tools
from xiaomei_brain.tools.execution_context import bind_tool_execution


def _tool(tools, name):
    return next(item for item in tools if item.name == name)


def _tool_context(person_id: str, session_id: str):
    return bind_tool_execution(
        tool_call_id="call-test",
        tool_name="schedule_alarm",
        arguments={},
        artifact_callback=None,
        person_id=person_id,
        session_id=session_id,
    )


def test_alarm_keeps_creator_scope_and_hides_it_from_other_people(tmp_path):
    scheduler = CronScheduler("test", base_dir=tmp_path)
    tools = create_cron_tools(SimpleNamespace(_cron_scheduler=scheduler))
    schedule = _tool(tools, "schedule_alarm")
    list_alarms = _tool(tools, "list_alarms")
    cancel = _tool(tools, "cancel_alarm")

    with _tool_context("person-a", "session-a"):
        schedule.execute(when="2小时后", reason="甲的提醒", action="继续甲的工作")

    job = scheduler.list_all()[0]
    assert job.scope_type == "session"
    assert job.person_id == "person-a"
    assert job.session_id == "session-a"

    with _tool_context("person-b", "session-b"):
        assert "甲的提醒" not in list_alarms.execute()
        assert "未找到" in cancel.execute(alarm_id=job.id)

    with _tool_context("person-a", "session-a"):
        assert "甲的提醒" in list_alarms.execute()
        assert "已取消" in cancel.execute(alarm_id=job.id)


def test_person_alarm_is_consumed_only_after_delivery(monkeypatch):
    deliveries = []
    living = SimpleNamespace(
        consciousness=object(),
        drive=None,
        _send_proactive=lambda content, **target: deliveries.append((content, target)) or True,
    )
    dispatcher = ActionDispatcher()
    dispatcher._conscious_living = living
    executor = ActionExecutor(dispatcher)
    consumed = []
    executor._consume_intent = lambda item: consumed.append(item.metadata["intent_id"])
    runtime = SimpleNamespace(
        react_nodb=lambda **_kwargs: "提醒已经处理",
        exp_stream=None,
    )
    item = ActionItem(
        action_type=ActionType.ALARM,
        priority=0.8,
        content="甲的闹钟",
        reason="继续工作",
        source="intent",
        cooldown_key="intent_alarm",
        metadata={
            "intent_type": "ALARM",
            "intent_id": "alarm-intent",
            "scope_type": "session",
            "user_id": "person-a",
            "session_id": "session-a",
        },
    )
    monkeypatch.setattr(
        "xiaomei_brain.consciousness.action_dispatcher.build_simple_context",
        lambda *_args, **_kwargs: "system",
    )

    assert executor.execute(item, runtime=runtime) is True
    assert deliveries == [(
        "提醒已经处理",
        {"user_id": "person-a", "session_id": "session-a"},
    )]
    assert consumed == ["alarm-intent"]


def test_wake_preserves_durable_intents(monkeypatch):
    pending = [{"intent_id": "intent-a", "type": "work"}]
    intent_slot = SimpleNamespace(intent_buffer=pending, urgent_intents={"work"})
    self_image = SimpleNamespace(contribute_perception=lambda **_kwargs: None)
    consciousness = SimpleNamespace(
        _last_intent_time=0.0,
        _last_emerge_time=0.0,
        _last_l3_time=0.0,
        intent_slot=intent_slot,
        on_wake=lambda: None,
        get_self_image=lambda: self_image,
    )
    core = SimpleNamespace(session_id="old")
    living = ConsciousLiving.__new__(ConsciousLiving)
    living._assignment_scheduler = None
    living.session_id = "old"
    living._attention = None
    living.agent = SimpleNamespace(_get_agent=lambda: core)
    living._load_consciousness = True
    living.consciousness = consciousness
    living._dispatcher = SimpleNamespace(tick=lambda _si: None, process_queue=lambda: None)
    living.drive = None
    living.body = None

    monkeypatch.setattr("time.time", lambda: 1234.0)
    living._on_wake()

    assert intent_slot.intent_buffer == pending
    assert intent_slot.urgent_intents == {"work"}


def test_targeted_work_is_resolved_to_person_scope():
    engine = L2Engine.__new__(L2Engine)
    engine._person_candidates = lambda: [
        SimpleNamespace(person_id="person-a", display_name="甲")
    ]
    intent = Intent(
        type=IntentType.WORK,
        priority=55,
        content="继续甲的 PPT",
        params={"user_id": "person-a"},
    )

    prepared = engine._prepare_intent_for_buffer(intent)
    record = prepared.to_dict()
    assert record["scope_type"] == "person"
    assert record["user_id"] == "person-a"


def test_learning_queue_can_consume_the_selected_topic():
    self_image = SimpleNamespace(
        mind=SimpleNamespace(learning_queue=[
            {"topic": "主题甲", "priority": 0.2},
            {"topic": "主题乙", "priority": 0.9},
        ])
    )
    queue = LearningQueue(self_image)

    selected = queue.pop_topic("主题甲")

    assert selected["topic"] == "主题甲"
    assert [item["topic"] for item in self_image.mind.learning_queue] == ["主题乙"]
