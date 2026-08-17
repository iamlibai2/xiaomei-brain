from __future__ import annotations

import sqlite3
import time
from types import SimpleNamespace

import pytest

from xiaomei_brain.consciousness.missions import (
    InvalidMissionTransition,
    MissionRunStatus,
    MissionService,
    MissionStatus,
    MissionStore,
)
from xiaomei_brain.consciousness.missions.runner import MissionRunner


def _service(tmp_path):
    return MissionService(
        MissionStore(tmp_path / "brain.db"),
        skill_exists=lambda name: name == "promotion-guide",
    )


def test_existing_v1_database_adds_waiting_columns(tmp_path) -> None:
    db_path = tmp_path / "brain.db"
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE schema_versions (
            component TEXT PRIMARY KEY,
            version INTEGER NOT NULL DEFAULT 0
        );
        INSERT INTO schema_versions(component, version) VALUES ('missions', 1);
        CREATE TABLE missions (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            objective TEXT NOT NULL,
            status TEXT NOT NULL,
            priority REAL NOT NULL DEFAULT 0.5,
            accountable_person_id TEXT NOT NULL DEFAULT '',
            origin_session_id TEXT NOT NULL DEFAULT '',
            origin_turn_id TEXT NOT NULL DEFAULT '',
            skill_name TEXT NOT NULL DEFAULT '',
            success_criteria_json TEXT NOT NULL DEFAULT '[]',
            constraints_json TEXT NOT NULL DEFAULT '[]',
            permissions_json TEXT NOT NULL DEFAULT '[]',
            checkpoint_json TEXT NOT NULL DEFAULT '{}',
            progress_summary TEXT NOT NULL DEFAULT '',
            next_run_at REAL,
            last_run_at REAL,
            created_by TEXT NOT NULL DEFAULT 'user',
            revision INTEGER NOT NULL DEFAULT 1,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            completed_at REAL
        );
    """)
    conn.commit()
    conn.close()

    store = MissionStore(db_path)
    columns = {
        row["name"]
        for row in store._get_conn().execute("PRAGMA table_info(missions)").fetchall()
    }

    assert "waiting_reason" in columns
    assert "waiting_for_json" in columns
    assert store._get_schema_version("missions") == 2


def test_mission_requires_a_real_skill_before_activation(tmp_path) -> None:
    service = _service(tmp_path)
    mission = service.create(
        title="推广小美",
        objective="持续获得第一批真实用户",
        accountable_person_id="person-1",
    )

    assert mission.status is MissionStatus.PREPARING
    with pytest.raises(ValueError, match="requires a global Skill"):
        service.transition(mission.id, MissionStatus.ACTIVE)

    service.update_definition(
        mission.id,
        skill_name="promotion-guide",
        success_criteria=["获得 10 名有效试用用户"],
        permissions=["允许公开发布已确认的产品介绍"],
    )
    active = service.transition(mission.id, MissionStatus.ACTIVE)

    assert active.status is MissionStatus.ACTIVE
    assert active.next_run_at is not None
    assert service.due_signals()[0]["mission_id"] == mission.id


def test_checkpoint_schedules_next_signal_without_direct_execution(tmp_path) -> None:
    service = _service(tmp_path)
    mission = service.create(
        title="推广小美",
        objective="持续获得第一批真实用户",
        skill_name="promotion-guide",
        activate=True,
    )
    run = service.start_run(mission.id, "intent-1", "autonomous:mission:1")
    future = time.time() + 3600
    updated = service.checkpoint(
        mission.id,
        summary="完成第一篇内容草稿",
        checkpoint={"next": "等待复核后发布"},
        next_run_at=future,
        run_id=run.id,
    )
    service.finish_run(
        run.id,
        MissionRunStatus.COMPLETED,
        result_summary="完成第一篇内容草稿",
        checkpoint=updated.checkpoint,
    )

    assert service.due_signals(now=future - 1) == []
    assert service.due_signals(now=future + 1)[0]["mission_id"] == mission.id
    assert service.store.require_run(run.id).status is MissionRunStatus.COMPLETED
    assert any(event.event_type == "checkpoint" for event in service.store.list_events(mission.id))


def test_waiting_requires_structured_conditions_and_stops_scheduling(tmp_path) -> None:
    service = _service(tmp_path)
    mission = service.create(
        title="推广小美",
        objective="获得第一批真实用户",
        skill_name="promotion-guide",
        activate=True,
    )

    with pytest.raises(ValueError, match="waiting_reason"):
        service.checkpoint(
            mission.id,
            summary="发布材料已准备完成",
            status=MissionStatus.WAITING,
        )

    waiting = service.checkpoint(
        mission.id,
        summary="发布材料已准备完成",
        status=MissionStatus.WAITING,
        waiting_reason="等待博士提供可用的 X 账号并授权发布",
        waiting_for=[{
            "type": "external_connection",
            "key": "x_account",
            "description": "可用的 X 账号",
        }, {
            "type": "authorization",
            "key": "external_publish",
            "description": "允许使用该账号对外发布",
        }],
    )

    assert waiting.status is MissionStatus.WAITING
    assert waiting.next_run_at is None
    assert waiting.waiting_reason == "等待博士提供可用的 X 账号并授权发布"
    assert waiting.waiting_for[0]["key"] == "x_account"
    assert service.due_signals() == []

    resumed = service.transition(mission.id, MissionStatus.ACTIVE)
    assert resumed.status is MissionStatus.ACTIVE
    assert resumed.waiting_reason == ""
    assert resumed.waiting_for == ()
    assert resumed.next_run_at is not None


def test_wait_transition_clears_an_existing_schedule(tmp_path) -> None:
    service = _service(tmp_path)
    mission = service.create(
        title="推广小美",
        objective="获得第一批真实用户",
        skill_name="promotion-guide",
        activate=True,
    )

    waiting = service.transition(
        mission.id,
        MissionStatus.WAITING,
        reason="等待发布账号",
        waiting_for=["博士提供可用的 X 账号"],
    )

    assert waiting.next_run_at is None
    assert waiting.waiting_for == ({
        "type": "external_condition",
        "key": "condition_1",
        "description": "博士提供可用的 X 账号",
    },)


def test_terminal_mission_cannot_be_reactivated(tmp_path) -> None:
    service = _service(tmp_path)
    mission = service.create(
        title="一次长期责任",
        objective="达到可验证结果",
        skill_name="promotion-guide",
        activate=True,
    )
    completed = service.transition(mission.id, MissionStatus.COMPLETED, reason="成功标准已满足")

    assert completed.is_terminal
    assert service.due_signals() == []
    with pytest.raises(InvalidMissionTransition):
        service.transition(mission.id, MissionStatus.ACTIVE)


def test_learning_gap_is_a_signal_and_reactivates_only_after_learning(tmp_path) -> None:
    service = _service(tmp_path)
    mission = service.create(
        title="长期推广",
        objective="持续验证推广方法",
        skill_name="promotion-guide",
        activate=True,
    )
    waiting = service.request_learning(
        mission.id,
        topic="企业软件冷启动渠道",
        reason="现有指南缺少可验证的渠道选择依据",
    )

    assert waiting.status is MissionStatus.WAITING
    assert service.due_signals() == []
    assert service.learning_signals()[0]["topic"] == "企业软件冷启动渠道"

    active = service.learning_completed(
        mission.id,
        topic="企业软件冷启动渠道",
        summary="已形成渠道对比结论",
    )

    assert active.status is MissionStatus.ACTIVE
    assert service.learning_signals() == []
    assert service.due_signals()[0]["mission_id"] == mission.id


def test_runner_loads_global_skill_and_persists_one_bounded_run(tmp_path, monkeypatch) -> None:
    service = _service(tmp_path)
    mission = service.create(
        title="长期推广",
        objective="持续验证推广方法",
        skill_name="promotion-guide",
        accountable_person_id="person-1",
        origin_session_id="session-1",
        activate=True,
    )
    monkeypatch.setattr(
        "xiaomei_brain.consciousness.missions.runner.build_simple_context",
        lambda *_args, **_kwargs: "identity context",
    )
    skill_loader = SimpleNamespace(
        view_skill=lambda name: {"name": name, "runtime_content": "先验证，再行动。"},
        record_usage=lambda _name: None,
    )
    observed = {}

    class Runtime:
        session_id = "autonomous:mission:test"
        exp_stream = None

        def react_nodb(self, **kwargs):
            observed["messages"] = kwargs["messages"]
            service.checkpoint(
                mission.id,
                summary="已完成一次渠道假设验证",
                checkpoint={"next": "验证第二个渠道"},
                next_run_at=time.time() + 3600,
            )
            return "已完成一次渠道假设验证"

    runner = MissionRunner(
        service,
        SimpleNamespace(),
        skill_loader=skill_loader,
    )

    assert runner.execute(mission.id, Runtime(), intent_id="intent-1") is True
    assert "先验证，再行动" in observed["messages"][0]["content"]
    assert service.require(mission.id).checkpoint["next"] == "验证第二个渠道"


def test_waiting_mission_can_enter_a_model_selected_run_without_forced_resume(tmp_path, monkeypatch) -> None:
    service = _service(tmp_path)
    mission = service.create(
        title="持续推广",
        objective="持续验证推广方法",
        skill_name="promotion-guide",
        accountable_person_id="person-1",
        origin_session_id="session-1",
        activate=True,
    )
    waiting = service.checkpoint(
        mission.id,
        summary="等待选择发布方式",
        status=MissionStatus.WAITING,
        waiting_reason="等待选择发布方式",
        waiting_for=[{"type": "choice", "key": "publish_mode", "description": "选择 A 或 B"}],
    )
    monkeypatch.setattr(
        "xiaomei_brain.consciousness.missions.runner.build_simple_context",
        lambda *_args, **_kwargs: "identity context",
    )
    skill_loader = SimpleNamespace(
        view_skill=lambda name: {"name": name, "runtime_content": "根据最新事实自主判断。"},
        record_usage=lambda _name: None,
    )

    class Runtime:
        session_id = "autonomous:mission:waiting"
        exp_stream = None

        def react_nodb(self, **_kwargs):
            # The model may decide the new input is still insufficient. The
            # runtime records a real Run but does not force the Mission active.
            return "新信息仍不足，继续等待。"

    runner = MissionRunner(service, SimpleNamespace(), skill_loader=skill_loader)

    assert runner.execute(waiting.id, Runtime(), intent_id="intent-waiting") is True
    refreshed = service.require(waiting.id)
    assert refreshed.status is MissionStatus.WAITING
    assert refreshed.waiting_reason == "等待选择发布方式"
    runs = service.store._get_conn().execute(
        "SELECT status FROM mission_runs WHERE mission_id = ? ORDER BY started_at DESC",
        (waiting.id,),
    ).fetchall()
    assert runs[0]["status"] == MissionRunStatus.COMPLETED.value
