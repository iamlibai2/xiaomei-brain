from __future__ import annotations

from types import SimpleNamespace

import pytest

from xiaomei_brain.workspaces import WorkspaceService, WorkspaceStore, create_workspace_tools


def _world(tmp_path):
    events = []
    service = WorkspaceService(
        WorkspaceStore(tmp_path / "workspaces.db"),
        publish=lambda name, payload, **metadata: events.append((name, payload, metadata)),
    )
    workspace = service.create(
        name="客户经营",
        purpose="持续推进客户",
        created_by_person_id="person-1",
    )
    collection, _fields = service.business.create_collection(
        workspace.id,
        name="customers",
        label="客户",
        purpose="客户经营状态",
        fields=[
            {"name": "name", "label": "客户名称", "data_type": "text", "required": True},
            {"name": "stage", "label": "阶段", "data_type": "enum", "required": True},
            {"name": "amount", "label": "金额", "data_type": "money"},
        ],
    )
    records = []
    for index, name in enumerate(("甲公司", "乙公司", "丙公司", "丁公司"), start=1):
        record, _changes, _event = service.business.upsert_record(
            collection.id,
            stable_key=f"customer-{index}",
            values={"name": name, "stage": "报价", "amount": index * 100},
            business_intent="登记客户",
            person_id="person-1",
            session_id="session-1",
            turn_id=f"create-{index}",
        )
        records.append(record)
    for index, record in enumerate(records[:3], start=1):
        service.business.upsert_record(
            collection.id,
            record_id=record.id,
            expected_revision=record.revision,
            values={"stage": "合同"},
            business_intent="推进客户到合同阶段",
            person_id="person-1",
            session_id="session-1",
            turn_id=f"advance-{index}",
        )
    stage_field_id = next(
        field.id
        for field in service.business.store.list_fields(collection.id)
        if field.name == "stage"
    )
    candidate = next(
        item
        for item in service.business.store.list_action_candidates(
            workspace.id,
            min_occurrences=3,
        )
        if item.operation == "update" and item.field_ids == (stage_field_id,)
    )
    return service, workspace, collection, records, candidate, events


def test_candidate_crystallizes_and_action_run_links_real_changes(tmp_path):
    service, workspace, _collection, records, candidate, events = _world(tmp_path)
    definition = service.actions.establish(
        workspace.id,
        candidate_id=candidate.id,
        name="推进客户阶段",
        description="将客户推进到已经确认的新阶段",
        completion_criteria="客户阶段字段已更新，并记录对应业务事实",
        person_id="person-1",
        session_id="session-1",
        turn_id="establish-1",
    )
    assert definition.status == "active"
    assert definition.evidence_count == 3
    validation = service.actions.store.get_validation(definition.id)
    assert validation is not None
    assert validation["status"] == "passed"
    assert validation["occurrence_count"] == 3
    assert validation["record_count"] == 3
    assert validation["checked_occurrence_count"] == 3
    assert validation["establishment_occurrence_count"] == 3
    assert validation["subsequent_occurrence_count"] == 0
    assert all(item["valid"] for item in validation["evidence"])

    target = records[3]
    run, record, changes, event = service.actions.execute(
        definition.id,
        record_id=target.id,
        expected_revision=target.revision,
        values={"阶段": "合同"},
        business_intent="推进丁公司到合同阶段",
        event_type="customer_stage_advanced",
        event_summary="丁公司已进入合同阶段",
        person_id="person-1",
        session_id="session-1",
        turn_id="advance-4",
    )

    assert run.status == "completed"
    assert run.record_id == record.id
    assert run.record_change_ids == tuple(change.id for change in changes)
    assert run.event_id == event.id
    assert record.values[next(iter(definition.field_ids))] == "合同"
    refreshed_validation = service.actions.validate_candidate(
        workspace.id,
        candidate.id,
    )
    assert refreshed_validation["occurrence_count"] == 4
    assert refreshed_validation["establishment_occurrence_count"] == 3
    assert refreshed_validation["subsequent_occurrence_count"] == 1
    assert {name for name, _payload, _metadata in events} >= {
        "business_action.established",
        "business_action.completed",
        "record.changed",
        "business_event.created",
    }

    snapshot = service.snapshot(
        workspace,
        include_business=True,
        include_records=True,
    )["business"]
    assert snapshot["actions"][0]["name"] == "推进客户阶段"
    assert snapshot["actions"][0]["validation"]["status"] == "passed"
    assert snapshot["action_runs"][0]["status"] == "completed"
    assert candidate.id not in {item["id"] for item in snapshot["action_candidates"]}


def test_failed_action_run_does_not_manufacture_event(tmp_path):
    service, workspace, _collection, records, candidate, _events = _world(tmp_path)
    definition = service.actions.establish(
        workspace.id,
        candidate_id=candidate.id,
        name="推进客户阶段",
        description="更新阶段",
        completion_criteria="阶段已更新",
        person_id="person-1",
    )
    event_count = service.business.store.summary(workspace.id)["events"]

    with pytest.raises(ValueError, match="outside its definition"):
        service.actions.execute(
            definition.id,
            record_id=records[3].id,
            expected_revision=records[3].revision,
            values={"金额": 999},
            business_intent="错误地修改金额",
            event_type="amount_changed",
            event_summary="金额已修改",
            person_id="person-1",
        )

    assert service.actions.store.list_runs(workspace.id) == []
    assert service.business.store.summary(workspace.id)["events"] == event_count

    with pytest.raises(Exception):
        service.actions.execute(
            definition.id,
            record_id=records[3].id,
            expected_revision=999,
            values={"阶段": "合同"},
            business_intent="使用过期记录推进",
            event_type="customer_stage_advanced",
            event_summary="丁公司已进入合同阶段",
            person_id="person-1",
        )

    failed = service.actions.store.list_runs(workspace.id)[0]
    assert failed.status == "failed"
    assert failed.error
    assert service.business.store.summary(workspace.id)["events"] == event_count


def test_action_tools_enforce_person_boundary(tmp_path):
    service, workspace, _collection, _records, candidate, _events = _world(tmp_path)
    definition = service.actions.establish(
        workspace.id,
        candidate_id=candidate.id,
        name="推进客户阶段",
        description="更新阶段",
        completion_criteria="阶段已更新",
        person_id="person-1",
    )
    core = SimpleNamespace(user_id="person-2", session_id="session-2", turn_id="turn-2")
    agent = SimpleNamespace(workspace_service=service, _get_agent=lambda: core)
    tools = {item.name: item for item in create_workspace_tools(agent)}

    with pytest.raises(PermissionError, match="current Person"):
        tools["execute_business_action"].execute(
            action_id=definition.id,
            values={"阶段": "合同"},
            business_intent="越权执行",
        )


def test_candidate_validation_tool_is_read_only(tmp_path):
    service, workspace, _collection, _records, candidate, _events = _world(tmp_path)
    core = SimpleNamespace(user_id="person-1", session_id="session-1", turn_id="turn")
    agent = SimpleNamespace(workspace_service=service, _get_agent=lambda: core)
    tools = {item.name: item for item in create_workspace_tools(agent)}
    before = service.business.store.summary(workspace.id)

    report = tools["validate_business_action_candidate"].execute(
        workspace_id=workspace.id,
        candidate_id=candidate.id,
    )

    assert report["status"] == "passed"
    assert report["checked_occurrence_count"] == 3
    assert report["establishment_occurrence_count"] == 3
    assert report["subsequent_occurrence_count"] == 0
    assert service.business.store.summary(workspace.id) == before
    assert service.actions.store.list_definitions(workspace.id) == []


def test_validation_backfills_an_existing_action_without_replaying_it(tmp_path):
    service, workspace, _collection, _records, candidate, _events = _world(tmp_path)
    definition = service.actions.establish(
        workspace.id,
        candidate_id=candidate.id,
        name="推进客户阶段",
        description="更新客户阶段",
        completion_criteria="阶段字段已经更新",
        person_id="person-1",
    )
    conn = service.actions.store._get_conn()
    conn.execute(
        "DELETE FROM business_action_validations WHERE action_id = ?",
        (definition.id,),
    )
    conn.commit()
    before = service.business.store.summary(workspace.id)

    report = service.actions.validate_candidate(workspace.id, candidate.id)

    assert report["status"] == "passed"
    assert service.actions.store.get_validation(definition.id)["status"] == "passed"
    assert service.business.store.summary(workspace.id) == before


def test_candidate_from_one_record_cannot_be_established_as_stable_action(tmp_path):
    service = WorkspaceService(WorkspaceStore(tmp_path / "workspaces.db"))
    workspace = service.create(
        name="单一客户测试",
        purpose="验证历史证据必须跨业务对象",
        created_by_person_id="person-1",
    )
    collection, fields = service.business.create_collection(
        workspace.id,
        name="customers",
        label="客户",
        purpose="客户阶段",
        fields=[
            {"name": "name", "label": "名称", "data_type": "text"},
            {"name": "stage", "label": "阶段", "data_type": "enum"},
        ],
    )
    record, _changes, _event = service.business.upsert_record(
        collection.id,
        stable_key="customer:only",
        values={"name": "唯一客户", "stage": "接洽"},
        business_intent="登记客户",
        person_id="person-1",
        turn_id="create",
    )
    for index, stage in enumerate(("报价", "合同", "合作"), start=1):
        record, _changes, _event = service.business.upsert_record(
            collection.id,
            record_id=record.id,
            expected_revision=record.revision,
            values={"stage": stage},
            business_intent="推进客户阶段",
            person_id="person-1",
            turn_id=f"advance-{index}",
        )
    stage_field = next(item for item in fields if item.name == "stage")
    candidate = next(
        item for item in service.business.store.list_action_candidates(
            workspace.id,
            min_occurrences=3,
        )
        if item.field_ids == (stage_field.id,)
    )

    report = service.actions.validate_candidate(workspace.id, candidate.id)
    assert report["status"] == "failed"
    assert report["record_count"] == 1
    assert "at least two business records" in " ".join(report["reasons"])
    with pytest.raises(ValueError, match="historical validation"):
        service.actions.establish(
            workspace.id,
            candidate_id=candidate.id,
            name="推进客户阶段",
            description="推进阶段",
            completion_criteria="阶段已更新",
            person_id="person-1",
        )


def test_action_definitions_and_runs_survive_restart(tmp_path):
    service, workspace, _collection, records, candidate, _events = _world(tmp_path)
    definition = service.actions.establish(
        workspace.id,
        candidate_id=candidate.id,
        name="推进客户阶段",
        description="更新阶段",
        completion_criteria="阶段已更新",
        person_id="person-1",
    )
    run, _record, _changes, _event = service.actions.execute(
        definition.id,
        record_id=records[3].id,
        expected_revision=records[3].revision,
        values={"阶段": "合同"},
        business_intent="推进丁公司",
        person_id="person-1",
    )

    reopened = WorkspaceService(WorkspaceStore(tmp_path / "workspaces.db"))
    assert reopened.actions.require(definition.id).name == "推进客户阶段"
    assert reopened.actions.store.get_run(run.id).status == "completed"


def test_action_run_preserves_effective_context_after_rules_are_corrected(tmp_path):
    service, workspace, _collection, records, candidate, _events = _world(tmp_path)
    definition = service.actions.establish(
        workspace.id,
        candidate_id=candidate.id,
        name="推进客户阶段",
        description="更新阶段",
        completion_criteria="阶段已更新",
        person_id="person-1",
    )
    default = service.context.establish(
        workspace.id,
        statement="客户默认先进入报价阶段",
        context_type="default",
        person_id="person-1",
    )
    constraint = service.context.establish(
        workspace.id,
        statement="阶段变化必须保留业务记录",
        context_type="constraint",
        person_id="person-1",
    )
    exception = service.context.establish(
        workspace.id,
        statement="丁公司可以直接进入合同阶段",
        context_type="default",
        scope_type="transaction",
        scope_id=records[3].id,
        overrides_context_id=default.id,
        person_id="person-1",
    )

    first_run, record, _changes, _event = service.actions.execute(
        definition.id,
        record_id=records[3].id,
        expected_revision=records[3].revision,
        values={"阶段": "合同"},
        business_intent="推进丁公司到合同阶段",
        person_id="person-1",
    )
    first_context_ids = {
        item["id"] for item in first_run.context_snapshot["contexts"]
    }
    assert first_context_ids == {constraint.id, exception.id}
    assert first_run.context_snapshot["context_overrides"] == [{
        "overriding_context_id": exception.id,
        "overridden_context_id": default.id,
    }]

    replacement = service.context.correct(
        exception.id,
        statement="丁公司后续可以直接进入合作阶段",
        person_id="person-1",
    )
    second_run, _record, _changes, _event = service.actions.execute(
        definition.id,
        record_id=record.id,
        expected_revision=record.revision,
        values={"阶段": "合作"},
        business_intent="推进丁公司到合作阶段",
        person_id="person-1",
    )
    second_context_ids = {
        item["id"] for item in second_run.context_snapshot["contexts"]
    }
    assert second_context_ids == {constraint.id, replacement.id}
    assert exception.id in first_context_ids
    assert replacement.id not in first_context_ids

    reopened = WorkspaceService(WorkspaceStore(tmp_path / "workspaces.db"))
    historical = reopened.actions.store.get_run(first_run.id)
    assert historical is not None
    assert {item["id"] for item in historical.context_snapshot["contexts"]} == {
        constraint.id,
        exception.id,
    }


def test_action_schema_upgrade_adds_context_snapshot_without_losing_runs(tmp_path):
    service, _workspace, _collection, records, candidate, _events = _world(tmp_path)
    definition = service.actions.establish(
        service.store.list_all()[0].id,
        candidate_id=candidate.id,
        name="推进客户阶段",
        description="更新阶段",
        completion_criteria="阶段已更新",
        person_id="person-1",
    )
    run, _record, _changes, _event = service.actions.execute(
        definition.id,
        record_id=records[3].id,
        expected_revision=records[3].revision,
        values={"阶段": "合同"},
        business_intent="推进丁公司",
        person_id="person-1",
    )
    conn = service.actions.store._get_conn()
    conn.execute("ALTER TABLE business_action_runs DROP COLUMN context_snapshot_json")
    conn.execute(
        "UPDATE schema_versions SET version = 2 WHERE component = 'workspace_actions'"
    )
    conn.commit()
    service.actions.store.close()

    backups = []
    reopened = WorkspaceService(
        WorkspaceStore(tmp_path / "workspaces.db"),
        before_business_migration=lambda: backups.append("backup"),
    )
    migrated = reopened.actions.store.get_run(run.id)
    assert backups == ["backup"]
    assert migrated is not None
    assert migrated.context_snapshot == {}
    columns = {
        str(row["name"])
        for row in reopened.actions.store._get_conn().execute(
            "PRAGMA table_info(business_action_runs)"
        )
    }
    assert "context_snapshot_json" in columns


def test_action_schema_upgrade_requests_backup(tmp_path):
    service, _workspace, _collection, _records, _candidate, _events = _world(tmp_path)
    conn = service.actions.store._get_conn()
    conn.executescript("""
        DROP TABLE business_action_runs;
        DROP TABLE business_action_definitions;
        DELETE FROM schema_versions WHERE component = 'workspace_actions';
    """)
    conn.commit()
    service.actions.store.close()

    backups = []
    reopened = WorkspaceService(
        WorkspaceStore(tmp_path / "workspaces.db"),
        before_business_migration=lambda: backups.append("backup"),
    )
    assert backups == ["backup"]
    assert reopened.actions.store.list_definitions(
        service.store.list_all()[0].id,
    ) == []
