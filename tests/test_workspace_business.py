from __future__ import annotations

import sqlite3
from types import SimpleNamespace

import pytest

from xiaomei_brain.workspaces import (
    BusinessStore,
    WorkspaceService,
    WorkspaceStore,
    create_workspace_tools,
)


def _service(tmp_path):
    return WorkspaceService(WorkspaceStore(tmp_path / "workspaces.db"), clock=lambda: 100.0)


def _customer_collection(service, workspace_id):
    return service.business.create_collection(
        workspace_id,
        name="customers",
        label="客户",
        purpose="持续记录客户经营状态",
        fields=[
            {"name": "name", "label": "客户名称", "data_type": "text", "required": True, "aliases": ["客户"]},
            {"name": "stage", "label": "阶段", "data_type": "enum", "required": True},
            {"name": "amount", "label": "预计金额", "data_type": "money"},
        ],
    )


def test_existing_workspace_is_backed_up_before_business_schema_migration(tmp_path):
    db_path = tmp_path / "workspaces.db"
    workspace_store = WorkspaceStore(db_path)
    workspace_store.create(
        name="既有经营数据",
        purpose="验证迁移备份",
        description="",
        created_reason="test",
        created_by_person_id="person-1",
    )
    calls = []
    BusinessStore(db_path, before_schema_migration=lambda: calls.append("backup"))
    BusinessStore(db_path, before_schema_migration=lambda: calls.append("again"))
    assert calls == ["backup"]


def test_observation_becomes_record_with_atomic_change_and_event(tmp_path):
    events = []
    store = WorkspaceStore(tmp_path / "workspaces.db")
    service = WorkspaceService(
        store,
        publish=lambda name, payload, **metadata: events.append((name, payload, metadata)),
        clock=lambda: 100.0,
    )
    workspace = service.create(
        name="销售经营",
        purpose="持续管理客户与成交",
        created_by_person_id="person-1",
    )
    source = service.business.create_data_source(
        workspace.id, kind="conversation", name="客户沟通",
    )
    observation = service.business.observe(
        workspace.id,
        data_source_id=source.id,
        source_person_id="person-1",
        content="甲公司确认进入报价阶段",
    )
    collection, fields = _customer_collection(service, workspace.id)
    record, changes, event = service.business.upsert_record(
        collection.id,
        stable_key="customer:甲公司",
        values={"客户名称": "甲公司", "阶段": "报价", "预计金额": 120000},
        business_intent="将甲公司推进到报价阶段",
        person_id="person-1",
        session_id="session-1",
        turn_id="turn-1",
        observation_id=observation.id,
        event_type="customer_entered_quotation",
        event_summary="甲公司已进入报价阶段",
        event_idempotency_key="quote:甲公司:1",
    )

    assert len(changes) == 3
    assert event is not None
    assert set(event.record_change_ids) == {item.id for item in changes}
    assert service.business.store.get_observation(observation.id).status == "resolved"
    visible = service.business.record_snapshot(record, fields)
    assert visible["values"] == {
        "name": "甲公司", "stage": "报价", "amount": 120000,
    }
    assert service.business.store.summary(workspace.id) == {
        "data_sources": 1,
        "unprocessed_observations": 0,
        "collections": 1,
        "records": 1,
        "events": 1,
    }
    assert "record.changed" in [item[0] for item in events]
    assert "business_event.created" in [item[0] for item in events]


def test_record_revision_history_and_event_idempotency_are_transactional(tmp_path):
    service = _service(tmp_path)
    workspace = service.create(name="经营", purpose="管理业务")
    collection, _fields = _customer_collection(service, workspace.id)
    record, _, _ = service.business.upsert_record(
        collection.id,
        stable_key="customer:a",
        values={"name": "A", "stage": "线索"},
        business_intent="登记客户",
        event_type="customer_created",
        event_summary="客户 A 已登记",
        event_idempotency_key="customer:a",
    )
    updated, changes, event = service.business.upsert_record(
        collection.id,
        record_id=record.id,
        expected_revision=1,
        values={"stage": "报价"},
        business_intent="推进到报价阶段",
    )
    assert updated.revision == 2
    assert len(changes) == 1
    assert changes[0].before_value == "线索"
    assert changes[0].after_value == "报价"
    assert event is None

    with pytest.raises(sqlite3.IntegrityError):
        service.business.upsert_record(
            collection.id,
            record_id=record.id,
            expected_revision=2,
            values={"stage": "合同"},
            business_intent="推进到合同阶段",
            event_type="customer_created",
            event_summary="重复事件",
            event_idempotency_key="customer:a",
        )
    persisted = service.business.store.get_record(record.id)
    assert persisted.revision == 2
    assert service.business.record_snapshot(
        persisted, service.business.store.list_fields(collection.id),
    )["values"]["stage"] == "报价"


def test_collection_validates_schema_values_and_query_aliases(tmp_path):
    service = _service(tmp_path)
    workspace = service.create(name="经营", purpose="管理业务")
    collection, _fields = _customer_collection(service, workspace.id)
    with pytest.raises(ValueError, match="requires a number"):
        service.business.upsert_record(
            collection.id,
            values={"客户": "A", "阶段": "线索", "预计金额": "很多"},
            business_intent="登记客户",
        )
    service.business.upsert_record(
        collection.id,
        values={"客户": "A", "阶段": "线索", "预计金额": 20},
        business_intent="登记客户",
    )
    assert service.business.query_records(
        collection.id, filters={"客户": "A"},
    )[0]["values"]["amount"] == 20
    with pytest.raises(ValueError, match="required field"):
        service.business.add_collection_fields(
            collection.id,
            expected_revision=1,
            fields=[
                {"name": "owner", "label": "负责人", "data_type": "text", "required": True},
            ],
        )
    changed, fields = service.business.add_collection_fields(
        collection.id,
        expected_revision=1,
        fields=[
            {"name": "owner", "label": "负责人", "data_type": "text"},
        ],
    )
    assert changed.revision == 2
    assert "owner" in {field.name for field in fields}


def test_agent_tools_expose_business_fact_vertical_slice(tmp_path):
    service = _service(tmp_path)
    core = SimpleNamespace(user_id="person-1", session_id="session-1", turn_id="turn-1")
    agent = SimpleNamespace(workspace_service=service, _get_agent=lambda: core)
    tools = {item.name: item for item in create_workspace_tools(agent)}
    assert {
        "create_data_source",
        "record_observation",
        "define_collection",
        "upsert_business_record",
        "add_collection_fields",
        "query_business_records",
    }.issubset(tools)
    workspace = tools["create_workspace"].execute(name="销售", purpose="持续经营")
    collection = tools["define_collection"].execute(
        workspace_id=workspace["id"],
        name="customers",
        label="客户",
        purpose="客户状态",
        fields=[
            {"name": "name", "label": "名称", "data_type": "text", "required": True},
        ],
    )
    result = tools["upsert_business_record"].execute(
        collection_id=collection["id"],
        stable_key="a",
        values={"名称": "A 公司"},
        business_intent="登记客户",
    )
    assert result["record"]["values"]["name"] == "A 公司"
    assert result["changes"][0]["person_id"] == "person-1"
