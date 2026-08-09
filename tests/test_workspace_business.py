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


def test_observation_source_columns_upgrade_without_losing_existing_rows(tmp_path):
    db_path = tmp_path / "workspaces.db"
    workspace_store = WorkspaceStore(db_path)
    workspace = workspace_store.create(
        name="既有经营数据",
        purpose="验证来源迁移",
        description="",
        created_reason="test",
        created_by_person_id="person-1",
    )
    conn = workspace_store._get_conn()
    conn.execute("""CREATE TABLE observations (
        id TEXT PRIMARY KEY,
        workspace_id TEXT NOT NULL,
        data_source_id TEXT NOT NULL DEFAULT '',
        source_person_id TEXT NOT NULL DEFAULT '',
        external_ref TEXT NOT NULL DEFAULT '',
        content TEXT NOT NULL DEFAULT '',
        attributes_json TEXT NOT NULL DEFAULT '{}',
        asset_id TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'unprocessed',
        occurred_at REAL,
        received_at REAL NOT NULL,
        resolved_collection_id TEXT NOT NULL DEFAULT '',
        resolved_record_id TEXT NOT NULL DEFAULT ''
    )""")
    conn.execute(
        """INSERT INTO observations (
            id, workspace_id, content, received_at
        ) VALUES ('observation-old', ?, '旧消息', 10)""",
        (workspace.id,),
    )
    conn.commit()
    workspace_store._set_schema_version("workspace_business", 3)
    calls = []

    store = BusinessStore(
        db_path,
        before_schema_migration=lambda: calls.append("backup"),
    )

    migrated = store.get_observation("observation-old")
    assert calls == ["backup"]
    assert migrated.content == "旧消息"
    assert migrated.session_id == ""
    assert migrated.turn_id == ""


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
        session_id="session-1",
        turn_id="turn-1",
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
    assert service.business.store.get_observation(observation.id).session_id == "session-1"
    assert service.business.store.get_observation(observation.id).turn_id == "turn-1"
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
        values={"客户": "A", "阶段": "线索", "预计金额": "20"},
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


def test_collection_coerces_only_unambiguous_numeric_text(tmp_path):
    service = _service(tmp_path)
    workspace = service.create(name="采购", purpose="管理原料采购")
    collection, _fields = service.business.create_collection(
        workspace.id,
        name="materials",
        label="原料",
        purpose="记录原料价格",
        fields=[
            {"name": "name", "label": "名称", "data_type": "text", "required": True},
            {"name": "quantity", "label": "数量", "data_type": "integer"},
            {"name": "price", "label": "参考单价", "data_type": "money"},
        ],
    )

    record, _changes, _event = service.business.upsert_record(
        collection.id,
        stable_key="soybean",
        values={"名称": "大豆", "数量": "20.0", "参考单价": "4,800.50"},
        business_intent="登记原料",
    )
    snapshot = service.business.record_snapshot(
        record,
        service.business.store.list_fields(collection.id),
    )
    assert snapshot["values"]["quantity"] == 20
    assert snapshot["values"]["price"] == 4800.5

    for invalid in ("4800元", "1,2,3", "", "NaN", "Infinity"):
        with pytest.raises(ValueError, match="requires a number"):
            service.business.upsert_record(
                collection.id,
                stable_key=f"invalid:{invalid}",
                values={"名称": "无效原料", "参考单价": invalid},
                business_intent="验证非法价格",
            )

    with pytest.raises(ValueError, match="requires a number"):
        service.business.upsert_record(
            collection.id,
            stable_key="boolean-price",
            values={"名称": "无效原料", "参考单价": True},
            business_intent="验证布尔值不能作为价格",
        )


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


def test_conversation_observation_tool_persists_and_reuses_source_context(tmp_path):
    service = _service(tmp_path)
    core = SimpleNamespace(user_id="person-1", session_id="session-1", turn_id="turn-1")
    agent = SimpleNamespace(workspace_service=service, _get_agent=lambda: core)
    tools = {item.name: item for item in create_workspace_tools(agent)}
    workspace = tools["create_workspace"].execute(name="销售", purpose="持续经营")

    first = tools["record_observation"].execute(
        workspace_id=workspace["id"],
        content="甲公司确认报价",
    )
    core.turn_id = "turn-2"
    second = tools["record_observation"].execute(
        workspace_id=workspace["id"],
        content="甲公司确认合同",
    )

    assert first["session_id"] == "session-1"
    assert first["turn_id"] == "turn-1"
    assert second["turn_id"] == "turn-2"
    assert first["data_source_id"] == second["data_source_id"]
    assert first["data_source"]["kind"] == "conversation"
    assert first["data_source"]["locator"] == "session:session-1"
    assert len(service.business.store.list_data_sources(workspace["id"])) == 1


def test_inbound_channel_observation_is_reused_and_auto_linked(tmp_path):
    service = _service(tmp_path)
    core = SimpleNamespace(
        user_id="person-1",
        session_id="group-session-1",
        turn_id="turn-1",
        current_observation_id="",
    )
    agent = SimpleNamespace(workspace_service=service, _get_agent=lambda: core)
    tools = {item.name: item for item in create_workspace_tools(agent)}
    workspace = tools["create_workspace"].execute(
        name="Customer operations",
        purpose="Track customer progress",
    )
    source = service.business.create_data_source(
        workspace["id"],
        kind="channel",
        name="Customer group",
        locator="channel:feishu:group:demo",
    )
    observation = service.business.observe(
        workspace["id"],
        content="Acme confirmed the quote",
        data_source_id=source.id,
        external_ref="external:om-1",
        session_id=core.session_id,
    )
    core.current_observation_id = observation.id

    reused = tools["record_observation"].execute(
        workspace_id=workspace["id"],
        content="A paraphrase that must not create another Observation",
    )
    assert reused["id"] == observation.id
    assert len(service.business.store.list_observations(workspace["id"])) == 1

    collection = tools["define_collection"].execute(
        workspace_id=workspace["id"],
        name="customers",
        label="Customers",
        purpose="Current customer state",
        fields=[{
            "name": "name",
            "label": "Name",
            "data_type": "text",
            "required": True,
        }],
    )
    result = tools["upsert_business_record"].execute(
        collection_id=collection["id"],
        stable_key="acme",
        values={"name": "Acme"},
        business_intent="Record customer confirmation",
    )
    assert result["changes"][0]["observation_id"] == observation.id
    linked = service.business.observation_snapshot_with_links(observation)
    assert linked["resolved_record_ids"] == [result["record"]["id"]]


def test_repeated_cross_turn_changes_form_candidate_business_practice(tmp_path):
    events = []
    service = WorkspaceService(
        WorkspaceStore(tmp_path / "workspaces.db"),
        publish=lambda name, payload, **metadata: events.append((name, payload)),
        clock=lambda: 100.0,
    )
    workspace = service.create(
        name="客户经营",
        purpose="持续推进客户",
        created_by_person_id="person-1",
    )
    collection, _fields = _customer_collection(service, workspace.id)
    records = []
    for index in range(4):
        record, _changes, _event = service.business.upsert_record(
            collection.id,
            stable_key=f"customer:{index}",
            values={"name": f"客户 {index}", "stage": "线索"},
            business_intent="初始导入",
            notify=False,
        )
        records.append(record)

    for index, record in enumerate(records):
        service.business.upsert_record(
            collection.id,
            record_id=record.id,
            expected_revision=1,
            values={"stage": "报价"},
            business_intent="把客户推进到报价阶段",
            person_id="person-1",
            session_id="session-1",
            turn_id="turn-1" if index < 2 else f"turn-{index}",
        )

    candidates = service.business.workspace_snapshot(
        workspace.id,
    )["action_candidates"]
    assert len(candidates) == 1
    assert candidates[0]["status"] == "candidate"
    assert candidates[0]["occurrence_count"] == 3
    assert candidates[0]["record_count"] == 4
    assert [field["label"] for field in candidates[0]["fields"]] == ["阶段"]
    assert [name for name, _payload in events].count(
        "business_action.candidate",
    ) == 1
