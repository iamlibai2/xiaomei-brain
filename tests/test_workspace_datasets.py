from __future__ import annotations

import hashlib
from types import SimpleNamespace

from xiaomei_brain.workspaces import WorkspaceService, WorkspaceStore, create_workspace_tools


def _world(tmp_path):
    tick = iter(float(value) for value in range(100, 1000))
    service = WorkspaceService(
        WorkspaceStore(tmp_path / "workspaces.db"),
        clock=lambda: next(tick),
    )
    workspace = service.create(
        name="客户经营",
        purpose="持续经营客户",
        created_by_person_id="person-1",
    )
    collection, _ = service.business.create_collection(
        workspace.id,
        name="customers",
        label="客户",
        purpose="客户经营状态",
        fields=[
            {"name": "name", "label": "客户名称", "data_type": "text", "required": True},
            {"name": "stage", "label": "阶段", "data_type": "enum", "required": True},
            {"name": "amount", "label": "金额", "data_type": "money"},
            {"name": "created_on", "label": "登记日期", "data_type": "date"},
        ],
    )
    first, _, _ = service.business.upsert_record(
        collection.id,
        stable_key="a",
        values={"name": "甲公司", "stage": "报价", "amount": 100, "created_on": "2026-08-01"},
        business_intent="登记客户",
    )
    second, _, _ = service.business.upsert_record(
        collection.id,
        stable_key="b",
        values={"name": "乙公司", "stage": "合同", "amount": 300, "created_on": "2026-08-02"},
        business_intent="登记客户",
    )
    return service, workspace, collection, first, second


def test_table_metric_and_time_series_datasets_use_collection_data(tmp_path):
    service, workspace, collection, _first, _second = _world(tmp_path)
    grouped = service.datasets.create(
        workspace.id,
        name="阶段汇总",
        kind="table",
        description="按阶段统计客户",
        source_collection_id=collection.id,
        source_spec={
            "dimensions": ["阶段"],
            "metrics": [
                {"key": "customer_count", "label": "客户数", "operation": "count"},
                {"key": "total_amount", "label": "总金额", "operation": "sum", "field": "金额"},
            ],
        },
    )
    assert grouped.data["rows"] == [
        {"stage": "合同", "customer_count": 1, "total_amount": 300.0},
        {"stage": "报价", "customer_count": 1, "total_amount": 100.0},
    ]
    metrics = service.datasets.create(
        workspace.id,
        name="经营指标",
        kind="metric_set",
        description="客户经营总览",
        source_collection_id=collection.id,
        source_spec={"metrics": [
            {"key": "customers", "label": "客户数", "operation": "count"},
            {"key": "amount", "label": "预计金额", "operation": "sum", "field": "金额", "unit": "元"},
        ]},
    )
    assert metrics.data["metrics"][1]["value"] == 400.0
    timeline = service.datasets.create(
        workspace.id,
        name="客户增长",
        kind="time_series",
        description="每日新增",
        source_collection_id=collection.id,
        source_spec={
            "date_field": "登记日期", "operation": "count",
            "interval": "day", "label": "新增客户",
        },
    )
    assert timeline.data["points"] == [
        {"period": "2026-08-01", "value": 1},
        {"period": "2026-08-02", "value": 1},
    ]


def test_record_change_invalidates_dataset_and_surface_lazily_recomputes(tmp_path):
    service, workspace, collection, first, _second = _world(tmp_path)
    metrics = service.datasets.create(
        workspace.id,
        name="经营指标",
        kind="metric_set",
        description="客户经营总览",
        source_collection_id=collection.id,
        source_spec={"metrics": [
            {"key": "amount", "label": "预计金额", "operation": "sum", "field": "金额", "unit": "元"},
        ]},
    )
    surface = service.surfaces.create(
        workspace.id,
        name="经营看板",
        purpose="查看客户金额",
        definition={"components": [{
            "id": "amount", "type": "metric", "title": "预计金额",
            "binding": {"dataset_id": metrics.id, "metric_key": "amount"},
        }]},
    )
    service.business.upsert_record(
        collection.id,
        record_id=first.id,
        expected_revision=first.revision,
        values={"amount": 200},
        business_intent="更新预计金额",
    )
    assert service.datasets.store.get(metrics.id).status == "stale"
    resolved = service.surfaces.snapshot(surface)
    component = resolved["resolved_definition"]["components"][0]
    assert component["value"] == 500.0
    assert component["unit"] == "元"
    assert component["dataset_revision"] == 2
    assert service.datasets.store.get(metrics.id).status == "valid"


def test_surface_resolves_record_timeline_asset_and_nested_group(tmp_path):
    service, workspace, collection, _first, _second = _world(tmp_path)
    records = service.datasets.create(
        workspace.id,
        name="客户明细",
        kind="table",
        description="客户经营记录",
        source_collection_id=collection.id,
        source_spec={"fields": ["客户名称", "阶段", "金额"]},
    )
    timeline = service.datasets.create(
        workspace.id,
        name="客户增长",
        kind="time_series",
        description="按日统计新增客户",
        source_collection_id=collection.id,
        source_spec={
            "date_field": "登记日期",
            "operation": "count",
            "interval": "day",
            "label": "新增客户",
        },
    )
    artifact = {
        "id": "a" * 32,
        "session_id": "session-1",
        "name": "客户报价.xlsx",
        "mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "size": 12,
        "kind": "document",
        "relative_path": "workspace/outputs/customer-quote.xlsx",
    }
    asset = service.assets.register_artifact(
        workspace.id,
        person_id="person-1",
        session_id="session-1",
        artifact=artifact,
        sha256=hashlib.sha256(b"spreadsheet").hexdigest(),
    )
    surface = service.surfaces.create(
        workspace.id,
        name="完整经营界面",
        purpose="验证标准组件",
        definition={"components": [
            {
                "id": "business-group",
                "type": "group",
                "title": "客户现场",
                "components": [
                    {
                        "id": "customer-records",
                        "type": "record",
                        "binding": {"dataset_id": records.id},
                    },
                    {
                        "id": "customer-timeline",
                        "type": "timeline",
                        "binding": {"dataset_id": timeline.id},
                    },
                ],
            },
            {
                "id": "quote-asset",
                "type": "asset",
                "title": "当前报价",
                "binding": {"asset_id": asset.id},
            },
        ]},
    )

    resolved = service.surfaces.snapshot(surface)["resolved_definition"]["components"]
    group = resolved[0]
    assert {
        row["name"] for row in group["components"][0]["rows"]
    } == {"甲公司", "乙公司"}
    assert group["components"][1]["items"] == [
        {"time": "2026-08-01", "title": "2026-08-01", "detail": 1},
        {"time": "2026-08-02", "title": "2026-08-02", "detail": 1},
    ]
    assert resolved[1]["asset"]["id"] == asset.id


def test_surface_rejects_empty_group_and_unbound_asset(tmp_path):
    service, workspace, _collection, _first, _second = _world(tmp_path)

    for component in (
        {"type": "group", "components": []},
        {"type": "asset"},
    ):
        try:
            service.surfaces.create(
                workspace.id,
                name="无效界面",
                purpose="验证约束",
                definition={"components": [component]},
            )
        except ValueError:
            pass
        else:
            raise AssertionError("Invalid standard component was accepted")


def test_dataset_tools_are_registered_without_new_agent_manager_wiring(tmp_path):
    service, workspace, collection, _first, _second = _world(tmp_path)
    core = SimpleNamespace(user_id="person-1", session_id="session-1", turn_id="turn-1")
    agent = SimpleNamespace(workspace_service=service, _get_agent=lambda: core)
    tools = {tool.name: tool for tool in create_workspace_tools(agent)}
    result = tools["create_dataset"].execute(
        workspace_id=workspace.id,
        name="客户数",
        kind="metric_set",
        source_collection_id=collection.id,
        source_spec={"metrics": [
            {"key": "count", "label": "客户数", "operation": "count"},
        ]},
    )
    assert result["data"]["metrics"][0]["value"] == 2
    assert tools["list_datasets"].execute(workspace_id=workspace.id)["datasets"][0]["id"] == result["id"]
