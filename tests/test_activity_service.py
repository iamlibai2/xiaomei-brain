from __future__ import annotations

import sqlite3
from types import SimpleNamespace

import pytest

from xiaomei_brain.activity import (
    ActivityCategory,
    ActivityConflictError,
    ActivityRunContext,
    ActivityService,
    ActivityStatus,
    ActivityStep,
    ActivityStore,
    InvalidActivityTransition,
    PauseReason,
)
from xiaomei_brain.memory.experience_stream import ExperienceStream
from xiaomei_brain.consciousness.conscious_living import ConsciousLiving
from xiaomei_brain.consciousness.internal_processing import (
    InternalProcessingReport,
    record_internal_processing_activity,
)
from xiaomei_brain.consciousness.internal_display import InternalDisplay
from xiaomei_brain.consciousness.living import LivingState


class Clock:
    def __init__(self, value: float = 1000.0) -> None:
        self.value = value

    def __call__(self) -> float:
        self.value += 1.0
        return self.value


def _service(tmp_path, *, publish=None):
    db_path = tmp_path / "brain.db"
    store = ActivityStore(db_path)
    stream = ExperienceStream(db_path)
    return (
        ActivityService(
            store,
            experience_stream=stream,
            publish=publish,
            clock=Clock(),
        ),
        store,
        stream,
    )


def test_activity_lifecycle_persists_steps_and_timeline(tmp_path) -> None:
    published: list[tuple[str, dict]] = []
    service, store, stream = _service(
        tmp_path,
        publish=lambda name, payload: published.append((name, payload)),
    )
    steps = (
        ActivityStep("collect", "Collect system load"),
        ActivityStep("report", "Write report"),
    )

    created = service.create(
        category=ActivityCategory.WORK,
        kind="alarm_action",
        title="Inspect system load",
        source_type="alarm",
        source_id="alarm_1",
        origin_session_id="desktop-person-1",
        origin_turn_id="turn_1",
        steps=steps,
        checkpoint_type="alarm",
        checkpoint_ref="alarm_1",
        activity_id="activity_test",
    )
    running = service.start(
        created.id,
        runtime_session_id="autonomous:alarm:run_1",
        summary="Collecting system information",
    )
    progressed = service.report_progress(
        running.id,
        summary="CPU and memory collected",
        current_step="report",
        completed_steps=1,
        total_steps=2,
        steps=(
            ActivityStep(
                "collect",
                "Collect system load",
                status="completed",
                summary="CPU and memory collected",
            ),
            ActivityStep("report", "Write report", status="running"),
        ),
    )
    paused = service.pause(
        progressed.id,
        reason=PauseReason.REALTIME_MESSAGE,
        summary="Replying to a realtime message",
    )
    resumed = service.resume(paused.id, summary="Continuing system inspection")
    completed = service.complete(resumed.id, summary="System report completed")

    assert created.status is ActivityStatus.QUEUED
    assert running.started_at is not None
    assert progressed.current_step == "report"
    assert progressed.steps[0].status == "completed"
    assert paused.pause_reason == PauseReason.REALTIME_MESSAGE.value
    assert resumed.pause_reason == ""
    assert completed.status is ActivityStatus.COMPLETED
    assert completed.result_summary == "System report completed"
    assert completed.completed_at is not None
    assert completed.revision == 6
    assert store.get(completed.id) == completed

    events = stream.get_recent(limit=20)
    event_types = [item["type"] for item in reversed(events)]
    assert event_types == [
        "activity_queued",
        "activity_started",
        "activity_progress",
        "activity_paused",
        "activity_resumed",
        "activity_completed",
    ]
    assert all(item["related_id"] == created.id for item in events)
    assert [name for name, _payload in published] == [
        "activity.queued",
        "activity.started",
        "activity.progress",
        "activity.paused",
        "activity.resumed",
        "activity.completed",
    ]


def test_invalid_transition_does_not_mutate_activity(tmp_path) -> None:
    service, store, _stream = _service(tmp_path)
    created = service.create(
        category="cognition",
        kind="memory_extraction",
        title="Extract memories",
    )

    with pytest.raises(InvalidActivityTransition):
        service.complete(created.id, summary="Cannot complete before start")

    assert store.get(created.id) == created


def test_failure_and_cancel_are_terminal(tmp_path) -> None:
    service, _store, _stream = _service(tmp_path)
    first = service.create(
        category="work",
        kind="learning",
        title="Learn a topic",
    )
    failed = service.fail(first.id, message="Model unavailable", code="LLM_DOWN")
    assert failed.status is ActivityStatus.FAILED
    assert failed.error_code == "LLM_DOWN"

    with pytest.raises(InvalidActivityTransition):
        service.start(failed.id)

    second = service.create(
        category="communication",
        kind="proactive_expression",
        title="Send a greeting",
    )
    cancelled = service.cancel(second.id, summary="No longer appropriate")
    assert cancelled.status is ActivityStatus.CANCELLED


def test_activity_delivery_receipt_is_persisted_separately(tmp_path) -> None:
    service, store, _stream = _service(tmp_path)
    activity = service.create(
        category="communication",
        kind="proactive_expression",
        title="Send a result",
        scope_type="session",
        scope_id="session-1",
        person_id="person-1",
        origin_session_id="session-1",
        delivery_status="pending",
        delivery_target="session-1",
    )

    delivered = service.report_delivery(
        activity.id,
        delivered=True,
        target="session-1",
    )

    assert delivered.delivery_status == "delivered"
    assert delivered.delivery_target == "session-1"
    assert delivered.delivered_at is not None
    assert store.get(activity.id) == delivered


def test_shared_experience_is_a_scoped_activity_projection(tmp_path) -> None:
    from xiaomei_brain.consciousness.shared_experience import render_shared_experience

    service, _store, _stream = _service(tmp_path)
    own = service.create(
        category="work",
        kind="autonomous_work",
        title="Write the report",
        scope_type="session",
        scope_id="session-1",
        person_id="person-1",
        origin_session_id="session-1",
        progress_summary="Report is ready",
        delivery_status="pending",
    )
    service.start(own.id, runtime_session_id="autonomous:work:run-1")
    service.create(
        category="work",
        kind="autonomous_work",
        title="Another person's private task",
        scope_type="person",
        scope_id="person-2",
        person_id="person-2",
        progress_summary="Private result",
    )

    rendered = render_shared_experience(
        activity_service=service,
        person_id="person-1",
        session_id="session-1",
    )

    assert own.title in rendered
    assert "delivery=pending" in rendered
    assert "Another person's private task" not in rendered


def test_recover_interrupted_only_pauses_running_rows(tmp_path) -> None:
    service, store, stream = _service(tmp_path)
    running = service.create(
        category="sleep",
        kind="dream",
        title="Dream and consolidate memories",
    )
    running = service.start(running.id, summary="Dreaming")
    queued = service.create(
        category="work",
        kind="goal_pace",
        title="Continue a Goal",
    )

    recovered = service.recover_interrupted()

    assert [item.id for item in recovered] == [running.id]
    paused = store.get(running.id)
    assert paused is not None
    assert paused.status is ActivityStatus.PAUSED
    assert paused.pause_reason == PauseReason.INTERRUPTED.value
    assert paused.revision == running.revision + 1
    assert store.get(queued.id) == queued
    assert stream.get_recent(limit=1)[0]["type"] == "activity_paused"


def test_list_filters_and_revision_conflict(tmp_path) -> None:
    service, store, _stream = _service(tmp_path)
    work = service.create(
        category="work",
        kind="assignment_run",
        title="Write a report",
        source_type="assignment",
        source_id="assignment_1",
        scope_type="person",
        scope_id="person_1",
    )
    service.create(
        category="cognition",
        kind="inner_voice_reflection",
        title="Reflect after conversation",
        scope_type="agent",
        scope_id="global",
    )

    assert [item.id for item in store.list(categories=["work"])] == [work.id]
    assert [
        item.id
        for item in store.list(
            source_type="assignment",
            source_id="assignment_1",
        )
    ] == [work.id]
    assert [
        item.id
        for item in store.list(scope_type="person", scope_id="person_1")
    ] == [work.id]

    updated = service.start(work.id)
    with pytest.raises(ActivityConflictError):
        store.mutate(
            work.id,
            expected_revision=work.revision,
            updates={"progress_summary": "Stale write"},
        )
    assert store.get(work.id) == updated


def test_activity_schema_does_not_change_existing_user_id_tables(tmp_path) -> None:
    db_path = tmp_path / "brain.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE messages (id INTEGER PRIMARY KEY, user_id TEXT, content TEXT)",
    )
    conn.execute(
        "INSERT INTO messages (user_id, content) VALUES ('legacy-user', 'hello')",
    )
    conn.commit()
    conn.close()

    store = ActivityStore(db_path)
    assert store.list() == []

    check = sqlite3.connect(db_path)
    columns = [
        row[1]
        for row in check.execute("PRAGMA table_info(messages)").fetchall()
    ]
    row = check.execute("SELECT user_id, content FROM messages").fetchone()
    version = check.execute(
        "SELECT version FROM schema_versions WHERE component = ?",
        ("agent_activity_storage",),
    ).fetchone()
    check.close()

    assert columns == ["id", "user_id", "content"]
    assert row == ("legacy-user", "hello")
    assert version == (2,)


def test_run_context_cooperatively_pauses_for_realtime_chat(tmp_path) -> None:
    service, _store, _stream = _service(tmp_path)
    activity = service.create(
        category="work",
        kind="autonomous_learning",
        title="Learn in the background",
    )
    busy_values = iter((True, False))
    context = ActivityRunContext(
        service,
        activity.id,
        realtime_busy=lambda: next(busy_values),
    )
    context.start(summary="Learning")

    assert context.wait_if_realtime_busy(poll_interval=0.01)
    current = context.current
    assert current.status is ActivityStatus.RUNNING
    assert current.pause_reason == ""
    assert current.progress_summary == "Resumed after realtime conversation"


def test_activity_steps_must_have_unique_ids(tmp_path) -> None:
    service, _store, _stream = _service(tmp_path)
    with pytest.raises(ValueError, match="unique"):
        service.create(
            category="work",
            kind="learning",
            title="Learn",
            steps=(
                ActivityStep("same", "First"),
                ActivityStep("same", "Second"),
            ),
        )


def test_internal_processing_is_one_agent_global_activity(tmp_path) -> None:
    service, store, _stream = _service(tmp_path)
    living = SimpleNamespace(_activity_service=service)

    record_internal_processing_activity(living, {
        "type": "internal_display",
        "data": {
            "dag": {"msg_count": 12, "summary_tokens": 800},
            "memory_review": {"added": 2, "turn_count": 3},
            "emergence_stored": 1,
            "narr_extracted": 1,
            "doubt_count": 2,
            "processing_results": [{
                "key": "l3_reflection",
                "label": "深度反思",
                "count": 1,
                "unit": "次",
                "detail": "重新理解最近的经验",
            }],
        },
    })

    activities = store.list()
    assert len(activities) == 1
    activity = activities[0]
    assert activity.kind == "internal_processing"
    assert activity.title == "本轮内部处理"
    assert activity.status is ActivityStatus.COMPLETED
    assert activity.scope_type == "agent"
    assert activity.scope_id == "global"
    assert activity.person_id is None
    assert activity.completed_steps == 6
    assert {step.id for step in activity.steps} == {
        "dag",
        "memory_review_added",
        "emergence_stored",
        "narr_extracted",
        "doubt_count",
        "l3_reflection",
    }


def test_generic_internal_result_has_same_cli_and_activity_shape() -> None:
    display = InternalDisplay()
    display.record_processing_result(
        "l4_association",
        "深度联想",
        detail="发现一条反复出现的模式",
    )

    payload = display.to_dict()
    report = InternalProcessingReport.from_display(payload)

    assert "深度联想: 1次" in display.render_lines()[0]
    assert report.summary == "深度联想 1次"
    assert report.items[0].detail == "发现一条反复出现的模式"


def test_internal_processing_keeps_memory_change_previews_and_turn_origin(
    tmp_path,
) -> None:
    service, store, _stream = _service(tmp_path)
    living = SimpleNamespace(_activity_service=service)

    record_internal_processing_activity(
        living,
        {
            "type": "internal_display",
            "data": {
                "memory": [
                    {
                        "action": "ADD",
                        "preview": "李白希望先完善独立 Agent",
                    },
                    {
                        "action": "UPDATE",
                        "preview": "提交后再由用户决定是否 push",
                    },
                    {"action": "NOOP", "preview": "没有形成新记忆"},
                ],
            },
        },
        session_id="desktop-session",
        turn_id="turn-memory",
        person_id="person-li",
    )

    activity = store.list()[0]
    assert activity.scope_type == "person"
    assert activity.scope_id == "person-li"
    assert activity.person_id == "person-li"
    assert activity.origin_session_id == "desktop-session"
    assert activity.origin_turn_id == "turn-memory"
    assert [step.title for step in activity.steps] == [
        "记住新内容",
        "更新已有记忆",
    ]
    assert [step.summary for step in activity.steps] == [
        "1 条 · 李白希望先完善独立 Agent",
        "1 条 · 提交后再由用户决定是否 push",
    ]


def test_dream_lifecycle_is_agent_global(tmp_path) -> None:
    service, store, _stream = _service(tmp_path)
    living = object.__new__(ConsciousLiving)
    living._load_consciousness = True
    living._model_service_health = SimpleNamespace(available=True)
    living._activity_service = service
    living._dream_engine = SimpleNamespace(run=lambda: SimpleNamespace(
        memories_reinforced=3,
        memories_consolidated=2,
        memories_extracted=2,
        memories_retained=1,
        memories_expired=0,
        summary="Integrated recent experiences",
        stages=(
            SimpleNamespace(name="memory", title="短期记忆巩固", status="completed", summary="巩固 2 条"),
            SimpleNamespace(name="dream1", title="自由梦境", status="completed", summary="形成梦境"),
        ),
    ))
    living._print_section = lambda *_args, **_kwargs: None
    living._print_dream_results = lambda _report: None
    states = []
    living._transition = states.append

    living._loop_dreaming()

    activities = store.list(categories=["sleep"])
    assert len(activities) == 1
    activity = activities[0]
    assert activity.kind == "dream"
    assert activity.scope_type == "agent"
    assert activity.scope_id == "global"
    assert activity.status is ActivityStatus.COMPLETED
    assert activity.completed_steps == 2
    assert all(step.status == "completed" for step in activity.steps)
    assert states == [LivingState.SLEEPING]
