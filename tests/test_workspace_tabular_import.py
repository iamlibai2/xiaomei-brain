from __future__ import annotations

import hashlib
from types import SimpleNamespace

from xiaomei_brain.tools.execution_context import bind_tool_execution
from xiaomei_brain.workspaces import WorkspaceService, WorkspaceStore, create_workspace_tools


def _service(tmp_path):
    return WorkspaceService(WorkspaceStore(tmp_path / "workspaces.db"))


def test_csv_import_creates_source_observation_collection_and_records(tmp_path):
    events = []
    service = WorkspaceService(
        WorkspaceStore(tmp_path / "workspaces.db"),
        publish=lambda name, payload, **metadata: events.append((name, payload, metadata)),
    )
    workspace = service.create(
        name="客户经营", purpose="持续经营客户",
        created_by_person_id="person-1",
    )
    source = tmp_path / "customers.csv"
    source.write_text(
        "客户名称,阶段,预计金额\n甲公司,报价,120000\n乙公司,合同,80000\n",
        encoding="utf-8-sig",
    )

    result = service.imports.import_path(
        workspace.id,
        source,
        source_name="customers.csv",
        source_person_id="person-1",
        session_id="session-1",
        turn_id="turn-1",
    )

    assert result["created"] == 2
    assert result["updated"] == 0
    assert result["key_column"] == "客户名称"
    assert result["observation"]["status"] == "resolved"
    assert len(result["observation"]["resolved_record_ids"]) == 2
    collection = result["collection"]
    records = service.business.query_records(collection["id"], limit=10)
    assert {record["values"]["column_1"] for record in records} == {"甲公司", "乙公司"}
    amount_field = next(field for field in collection["fields"] if field["label"] == "预计金额")
    assert amount_field["data_type"] == "money"
    assert [name for name, _payload, _metadata in events].count("data_import.completed") == 1
    assert "record.changed" not in [name for name, _payload, _metadata in events]
    assert service.business.store.list_action_candidates(workspace.id) == []


def test_reimport_is_idempotent_and_new_snapshot_updates_existing_records(tmp_path):
    service = _service(tmp_path)
    workspace = service.create(name="客户经营", purpose="持续经营客户")
    source = tmp_path / "customers.csv"
    source.write_text("customer_id,amount\nA,100\nB,200\n", encoding="utf-8")
    first = service.imports.import_path(workspace.id, source, source_name="customers.csv")
    duplicate = service.imports.import_path(workspace.id, source, source_name="customers.csv")
    assert duplicate["duplicate"] is True
    assert duplicate["unchanged"] == 2

    source.write_text("customer_id,amount\nA,150\nB,200\nC,50\n", encoding="utf-8")
    changed = service.imports.import_path(workspace.id, source, source_name="customers.csv")
    assert changed["collection"]["id"] == first["collection"]["id"]
    assert changed["created"] == 1
    assert changed["updated"] == 1
    assert changed["unchanged"] == 1
    records = service.business.query_records(first["collection"]["id"], limit=10)
    values = {record["values"]["customer_id"]: record["values"]["amount"] for record in records}
    assert values == {"A": 150.0, "B": 200.0, "C": 50.0}


def test_import_tool_reads_only_current_execution_attachment(tmp_path):
    service = _service(tmp_path)
    workspace = service.create(
        name="销售",
        purpose="经营销售数据",
        created_by_person_id="person-1",
    )
    source = tmp_path / "sales.csv"
    source.write_text("order_id,amount\nSO-1,99\n", encoding="utf-8")
    core = SimpleNamespace(user_id="person-1", session_id="session-1", turn_id="turn-1")
    agent = SimpleNamespace(workspace_service=service, _get_agent=lambda: core)
    tool = {item.name: item for item in create_workspace_tools(agent)}["import_tabular_data"]

    with bind_tool_execution(
        tool_call_id="call-1",
        tool_name="import_tabular_data",
        arguments={},
        artifact_callback=None,
        session_id="session-1",
        turn_id="turn-1",
        person_id="person-1",
        attachments=({
            "id": "attachment-1",
            "name": "sales.csv",
            "local_path": str(source),
        },),
    ):
        result = tool.execute(
            workspace_id=workspace.id,
            attachment_id="attachment-1",
        )

    assert result["success"] is True
    assert result["created"] == 1
    assert result["data_source"]["locator"] == "attachment:sales.csv"
    assert service.current_for_session(
        "session-1",
        person_id="person-1",
    ).id == workspace.id


def test_import_tool_links_stable_workspace_asset_to_import_observation(tmp_path):
    service = _service(tmp_path)
    workspace = service.create(
        name="销售",
        purpose="经营销售数据",
        created_by_person_id="person-1",
    )
    source = tmp_path / "sales.csv"
    source.write_text("order_id,amount\nSO-1,99\n", encoding="utf-8")
    asset = service.assets.register_attachment(
        workspace.id,
        person_id="person-1",
        session_id="session-1",
        attachment={
            "id": "attachment-1",
            "name": "sales.csv",
            "kind": "file",
            "mime_type": "text/csv",
            "size": source.stat().st_size,
        },
        sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
    )
    core = SimpleNamespace(user_id="person-1", session_id="session-1", turn_id="turn-1")
    agent = SimpleNamespace(workspace_service=service, _get_agent=lambda: core)
    tool = {item.name: item for item in create_workspace_tools(agent)}["import_tabular_data"]

    with bind_tool_execution(
        tool_call_id="call-1",
        tool_name="import_tabular_data",
        arguments={},
        artifact_callback=None,
        session_id="session-1",
        turn_id="turn-1",
        person_id="person-1",
        attachments=({
            "id": "attachment-1",
            "name": "sales.csv",
            "local_path": str(source),
            "workspace_asset_id": asset.id,
        },),
    ):
        result = tool.execute(
            workspace_id=workspace.id,
            attachment_id="attachment-1",
        )

    assert result["success"] is True
    assert result["observation"]["asset_id"] == asset.id
    assert service.assets.store.has_link(
        asset.id,
        workspace.id,
        entity_type="observation",
        entity_id=result["observation"]["id"],
        relation="observed_with",
    )


def test_import_tool_rejects_unlinked_workspace_asset_before_import(tmp_path):
    service = _service(tmp_path)
    workspace = service.create(
        name="销售",
        purpose="经营销售数据",
        created_by_person_id="person-1",
    )
    other = service.create(
        name="采购",
        purpose="经营采购数据",
        created_by_person_id="person-1",
    )
    source = tmp_path / "sales.csv"
    source.write_text("order_id,amount\nSO-1,99\n", encoding="utf-8")
    foreign_asset = service.assets.register_attachment(
        other.id,
        person_id="person-1",
        session_id="session-1",
        attachment={"id": "attachment-1", "name": "sales.csv"},
        sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
    )
    core = SimpleNamespace(user_id="person-1", session_id="session-1", turn_id="turn-1")
    agent = SimpleNamespace(workspace_service=service, _get_agent=lambda: core)
    tool = {item.name: item for item in create_workspace_tools(agent)}["import_tabular_data"]

    with bind_tool_execution(
        tool_call_id="call-1",
        tool_name="import_tabular_data",
        arguments={},
        artifact_callback=None,
        session_id="session-1",
        turn_id="turn-1",
        person_id="person-1",
        attachments=({
            "id": "attachment-1",
            "name": "sales.csv",
            "local_path": str(source),
            "workspace_asset_id": foreign_asset.id,
        },),
    ):
        result = tool.execute(workspace_id=workspace.id)

    assert result["error"] == f"'{foreign_asset.id}'"
    assert service.business.store.list_data_sources(workspace.id) == []


def test_import_tool_resolves_the_only_compatible_attachment_without_opaque_id(tmp_path):
    service = _service(tmp_path)
    workspace = service.create(
        name="销售",
        purpose="经营销售数据",
        created_by_person_id="person-1",
    )
    source = tmp_path / "sales.csv"
    source.write_text("order_id,amount\nSO-1,99\n", encoding="utf-8")
    core = SimpleNamespace(user_id="person-1", session_id="session-1", turn_id="turn-1")
    agent = SimpleNamespace(workspace_service=service, _get_agent=lambda: core)
    tool = {item.name: item for item in create_workspace_tools(agent)}["import_tabular_data"]

    with bind_tool_execution(
        tool_call_id="call-1",
        tool_name="import_tabular_data",
        arguments={},
        artifact_callback=None,
        session_id="session-1",
        turn_id="turn-1",
        person_id="person-1",
        attachments=({
            "id": "opaque-attachment-id",
            "name": "sales.csv",
            "local_path": str(source),
        },),
    ):
        result = tool.execute(workspace_id=workspace.id)

    assert result["success"] is True
    assert result["created"] == 1


def test_import_tool_rejects_workspace_from_another_person(tmp_path):
    service = _service(tmp_path)
    workspace = service.create(
        name="销售",
        purpose="经营销售数据",
        created_by_person_id="person-2",
    )
    source = tmp_path / "sales.csv"
    source.write_text("order_id,amount\nSO-1,99\n", encoding="utf-8")
    core = SimpleNamespace(user_id="person-1", session_id="session-1", turn_id="turn-1")
    agent = SimpleNamespace(workspace_service=service, _get_agent=lambda: core)
    tool = {item.name: item for item in create_workspace_tools(agent)}["import_tabular_data"]

    with bind_tool_execution(
        tool_call_id="call-1",
        tool_name="import_tabular_data",
        arguments={},
        artifact_callback=None,
        session_id="session-1",
        turn_id="turn-1",
        person_id="person-1",
        attachments=({
            "id": "attachment-1",
            "name": "sales.csv",
            "local_path": str(source),
        },),
    ):
        result = tool.execute(
            workspace_id=workspace.id,
            attachment_id="attachment-1",
        )

    assert result["error"] == "Workspace is not available to the current Person"
    assert service.current_for_session("session-1", person_id="person-1") is None


def test_xlsx_and_another_source_can_update_same_collection_by_business_key(tmp_path):
    from openpyxl import Workbook

    service = _service(tmp_path)
    workspace = service.create(name="订单", purpose="持续管理订单")
    first_path = tmp_path / "orders.csv"
    first_path.write_text("order_id,amount\nSO-1,100\n", encoding="utf-8")
    first = service.imports.import_path(workspace.id, first_path, source_name="orders.csv")

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "本月订单"
    sheet.append(["order_id", "amount", "owner"])
    sheet.append(["SO-1", 180, "李白"])
    second_path = tmp_path / "orders-revised.xlsx"
    workbook.save(second_path)
    workbook.close()

    second = service.imports.import_path(
        workspace.id,
        second_path,
        source_name="orders-revised.xlsx",
        sheet="本月订单",
        collection_id=first["collection"]["id"],
    )
    assert second["created"] == 0
    assert second["updated"] == 1
    assert second["collection"]["revision"] == 2
    records = service.business.query_records(first["collection"]["id"], limit=10)
    assert len(records) == 1
    assert records[0]["values"] == {
        "order_id": "SO-1",
        "amount": 180.0,
        "owner": "李白",
    }


def test_new_source_reuses_one_unambiguous_compatible_collection(tmp_path):
    service = _service(tmp_path)
    workspace = service.create(name="客户经营", purpose="持续经营客户")
    collection, _fields = service.business.create_collection(
        workspace.id,
        name="customer",
        label="客户",
        purpose="持续维护客户经营数据",
        fields=[
            {"name": "customer_name", "label": "客户名称", "data_type": "text"},
            {"name": "stage", "label": "阶段", "data_type": "enum"},
            {"name": "estimated_amount", "label": "预计金额", "data_type": "money"},
        ],
    )
    source = tmp_path / "customer-snapshot.csv"
    source.write_text(
        "客户名称,阶段,预计金额\n甲公司,报价,120000\n",
        encoding="utf-8-sig",
    )

    result = service.imports.import_path(
        workspace.id,
        source,
        source_name="customer-snapshot.csv",
    )

    assert result["collection"]["id"] == collection.id
    assert result["created"] == 1
    records = service.business.query_records(collection.id, limit=10)
    assert records[0]["values"] == {
        "customer_name": "甲公司",
        "stage": "报价",
        "estimated_amount": 120000.0,
    }


def test_import_matches_an_existing_record_by_business_key_not_internal_stable_key(tmp_path):
    service = _service(tmp_path)
    workspace = service.create(name="客户经营", purpose="持续经营客户")
    collection, _fields = service.business.create_collection(
        workspace.id,
        name="customer",
        label="客户",
        purpose="持续维护客户经营数据",
        fields=[
            {"name": "customer_code", "label": "客户编号", "data_type": "text"},
            {"name": "customer_name", "label": "客户名称", "data_type": "text"},
            {"name": "estimated_amount", "label": "预计金额", "data_type": "money"},
        ],
    )
    existing, _changes, _event = service.business.upsert_record(
        collection.id,
        stable_key="customer:CUST-001",
        values={
            "customer_code": "CUST-001",
            "customer_name": "甲公司",
            "estimated_amount": 100000,
        },
        business_intent="对话中登记客户",
    )
    source = tmp_path / "customer-update.csv"
    source.write_text(
        "客户编号,客户名称,预计金额\nCUST-001,甲公司,180000\n",
        encoding="utf-8-sig",
    )

    result = service.imports.import_path(
        workspace.id,
        source,
        source_name="customer-update.csv",
        collection_id=collection.id,
        key_column="客户编号",
    )

    assert result["created"] == 0
    assert result["updated"] == 1
    records = service.business.query_records(collection.id, limit=10)
    assert len(records) == 1
    assert records[0]["id"] == existing.id
    assert records[0]["values"]["estimated_amount"] == 180000.0
    assert records[0]["stable_key"].startswith("key:")
