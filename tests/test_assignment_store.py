from __future__ import annotations

import sqlite3

import pytest

from xiaomei_brain.assignments.models import (
    ActorType,
    Assignment,
    AssignmentActor,
    AssignmentChannelMessage,
    AssignmentResource,
    AssignmentRun,
    AssignmentStatus,
)
from xiaomei_brain.assignments.store import (
    AssignmentConflictError,
    AssignmentStore,
)


def _assignment(*, assignment_id: str = "assignment_1") -> Assignment:
    return Assignment(
        id=assignment_id,
        title="竞品分析",
        objective="比较三份竞品资料并形成报告",
        status=AssignmentStatus.OFFERED,
        requester_person_id="person_1",
        scope_type="person",
        scope_id="person_1",
        origin_channel="desktop",
        origin_session_id="session_1",
        origin_turn_id="turn_1",
        root_goal_id=None,
        acceptance_criteria=("管理层报告", "产品对比表"),
        constraints={"language": "zh-CN"},
        requested_due_at=None,
        progress_summary="",
        completed_steps=None,
        total_steps=None,
        waiting_reason="",
        terminal_reason="",
        revision=1,
        created_at=100.0,
        accepted_at=None,
        started_at=None,
        updated_at=100.0,
        completed_at=None,
    )


def test_assignment_store_upgrades_existing_brain_without_touching_data(tmp_path):
    path = tmp_path / "brain.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, content TEXT)")
    conn.execute("INSERT INTO messages (content) VALUES ('旧消息')")
    conn.commit()
    conn.close()

    store = AssignmentStore(path)
    assert store._get_schema_version("assignment_storage") == 2
    assert store._get_conn().execute(
        "SELECT content FROM messages",
    ).fetchone()["content"] == "旧消息"
    tables = {
        row["name"]
        for row in store._get_conn().execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'",
        ).fetchall()
    }
    assert {
        "assignments",
        "assignment_events",
        "assignment_resources",
        "assignment_runs",
        "assignment_channel_messages",
    }.issubset(tables)
    store.close()


def test_assignment_channel_message_binding_survives_restart_and_rejects_stale_update(
    tmp_path,
):
    path = tmp_path / "brain.db"
    store = AssignmentStore(path)
    agent = AssignmentActor(ActorType.AGENT, "xiaomei")
    store.create_assignment(_assignment(), actor=agent)
    current = AssignmentChannelMessage(
        assignment_id="assignment_1",
        channel="feishu",
        account_id="default",
        conversation_id="oc_private",
        external_message_id="om_card_1",
        last_revision=3,
        updated_at=110.0,
    )
    assert store.upsert_channel_message(current) == current
    store.close()

    reopened = AssignmentStore(path)
    assert reopened.get_channel_message(
        "assignment_1", "feishu", "default", "oc_private",
    ) == current
    assert reopened.get_channel_message_by_external_id(
        "feishu", "default", "om_card_1",
    ) == current
    stale = AssignmentChannelMessage(
        assignment_id="assignment_1",
        channel="feishu",
        account_id="default",
        conversation_id="oc_private",
        external_message_id="om_stale",
        last_revision=2,
        updated_at=120.0,
    )
    assert reopened.upsert_channel_message(stale) == current
    reopened.close()


def test_assignment_store_migrates_v1_database_without_losing_assignments(tmp_path):
    path = tmp_path / "brain.db"
    old = AssignmentStore(path)
    old.create_assignment(
        _assignment(),
        actor=AssignmentActor(ActorType.AGENT, "xiaomei"),
    )
    old._get_conn().execute("DROP TABLE assignment_channel_messages")
    old._set_schema_version("assignment_storage", 1)
    old.close()

    upgraded = AssignmentStore(path)
    assert upgraded._get_schema_version("assignment_storage") == 2
    assert upgraded.get_assignment("assignment_1") is not None
    assert upgraded.get_channel_message(
        "assignment_1", "feishu", "default", "oc_private",
    ) is None
    upgraded.close()


def test_store_persists_snapshot_event_and_filters(tmp_path):
    store = AssignmentStore(tmp_path / "brain.db")
    agent = AssignmentActor(ActorType.AGENT, "xiaomei")

    created = store.create_assignment(_assignment(), actor=agent)

    assert created.acceptance_criteria == ("管理层报告", "产品对比表")
    assert created.constraints == {"language": "zh-CN"}
    assert store.list_assignments(
        statuses=[AssignmentStatus.OFFERED],
        requester_person_id="person_1",
    ) == [created]
    events = store.list_events(created.id)
    assert [(event.event_type, event.actor_id) for event in events] == [
        ("offered", "xiaomei"),
    ]
    store.close()


def test_store_uses_revision_and_idempotency_to_prevent_duplicate_updates(tmp_path):
    store = AssignmentStore(tmp_path / "brain.db")
    agent = AssignmentActor(ActorType.AGENT, "xiaomei")
    created = store.create_assignment(_assignment(), actor=agent)

    accepted = store.mutate_assignment(
        created.id,
        expected_revision=1,
        updates={"status": AssignmentStatus.ACCEPTED, "accepted_at": 110.0},
        event_type="accepted",
        actor=agent,
        idempotency_key="accept-1",
        now=110.0,
    )
    duplicate = store.mutate_assignment(
        created.id,
        expected_revision=1,
        updates={"status": AssignmentStatus.ACCEPTED},
        event_type="accepted",
        actor=agent,
        idempotency_key="accept-1",
        now=111.0,
    )

    assert accepted.revision == 2
    assert duplicate == accepted
    assert len(store.list_events(created.id)) == 2
    with pytest.raises(AssignmentConflictError):
        store.mutate_assignment(
            created.id,
            expected_revision=1,
            updates={"progress_summary": "过期写入"},
            event_type="progressed",
            actor=agent,
            now=112.0,
        )
    store.close()


def test_resource_link_is_idempotent_and_does_not_copy_asset(tmp_path):
    store = AssignmentStore(tmp_path / "brain.db")
    agent = AssignmentActor(ActorType.AGENT, "xiaomei")
    store.create_assignment(_assignment(), actor=agent)
    resource = AssignmentResource(
        assignment_id="assignment_1",
        resource_type="artifact",
        resource_key="session_1:artifact_1",
        relation="final",
        metadata={"name": "report.docx"},
        created_at=120.0,
    )

    linked, inserted = store.link_resource(resource, actor=agent)
    duplicate, inserted_again = store.link_resource(resource, actor=agent)

    assert linked == duplicate
    assert inserted is True
    assert inserted_again is False
    assert store.get_assignment("assignment_1").revision == 2
    assert store.list_resources("assignment_1") == [linked]
    assert [event.event_type for event in store.list_events("assignment_1")] == [
        "offered",
        "resource_linked",
    ]
    store.close()


def test_store_persists_assignment_run_checkpoint(tmp_path):
    store = AssignmentStore(tmp_path / "brain.db")
    agent = AssignmentActor(ActorType.AGENT, "xiaomei")
    store.create_assignment(_assignment(), actor=agent)
    run = AssignmentRun(
        run_id="assignment_run_1",
        assignment_id="assignment_1",
        status="interrupted",
        trigger_type="accepted",
        trigger_actor_id="xiaomei",
        checkpoint={"step": 2},
        safe_to_resume=True,
        started_at=130.0,
        updated_at=140.0,
        ended_at=140.0,
        error="agent restarted",
    )

    stored = store.create_run(run)

    assert stored == run
    assert store.list_runs("assignment_1") == [run]
    store.close()


def test_store_updates_and_finds_recoverable_runs(tmp_path):
    store = AssignmentStore(tmp_path / "brain.db")
    agent = AssignmentActor(ActorType.AGENT, "xiaomei")
    store.create_assignment(_assignment(), actor=agent)
    run = store.create_run(AssignmentRun(
        run_id="assignment_run_1",
        assignment_id="assignment_1",
        status="running",
        trigger_type="accepted",
        trigger_actor_id="xiaomei",
        started_at=100.0,
        updated_at=100.0,
    ))

    updated = store.update_run(
        run.run_id,
        status="checkpointed",
        checkpoint={"step": 4},
        safe_to_resume=True,
        now=110.0,
    )

    assert updated.checkpoint == {"step": 4}
    assert updated.safe_to_resume is True
    assert updated.updated_at == 110.0
    assert store.list_runs_by_status(
        ["running", "checkpointed"],
        safe_to_resume=True,
    ) == [updated]
    store.close()
