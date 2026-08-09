from __future__ import annotations

from types import SimpleNamespace

import pytest

from xiaomei_brain.tools.dynamic import _contextual_required_tool_names
from xiaomei_brain.workspaces import (
    WorkspaceService,
    WorkspaceStore,
    create_workspace_tools,
)


def _world(tmp_path):
    service = WorkspaceService(WorkspaceStore(tmp_path / "workspaces.db"))
    workspace = service.create(
        name="Materials",
        purpose="Track material quality and purchasing",
        created_by_person_id="person-1",
    )
    collection, fields = service.business.create_collection(
        workspace.id,
        name="materials",
        label="Materials",
        purpose="Material receipts",
        fields=[
            {"name": "name", "label": "Name", "data_type": "text", "required": True},
            {"name": "moisture", "label": "Moisture", "data_type": "number"},
            {"name": "quality", "label": "Quality", "data_type": "enum"},
            {"name": "weight", "label": "Weight", "data_type": "number"},
            {"name": "warehouse", "label": "Warehouse", "data_type": "enum"},
            {"name": "net", "label": "Net", "data_type": "money"},
            {"name": "tax_rate", "label": "Tax rate", "data_type": "number"},
            {"name": "gross", "label": "Gross", "data_type": "money"},
        ],
    )
    return service, workspace, collection, {field.name: field for field in fields}


def _establish_rules(service, workspace, collection):
    quality = service.context.establish(
        workspace.id,
        statement="Moisture below 10 is defective",
        context_type="decision",
        executable={
            "target_collection_id": collection.id,
            "condition": {"field": "moisture", "operator": "lt", "value": 10},
            "effects": [{"type": "set", "field": "quality", "value": "defective"}],
        },
        person_id="person-1",
    )
    service.context.establish(
        workspace.id,
        statement="Use a default tax rate of 13 percent",
        context_type="default",
        executable={
            "target_collection_id": collection.id,
            "effects": [{"type": "set_default", "field": "tax_rate", "value": 13}],
        },
        person_id="person-1",
    )
    service.context.establish(
        workspace.id,
        statement="Gross equals net multiplied by one plus tax rate",
        context_type="calculation",
        executable={
            "target_collection_id": collection.id,
            "effects": [{
                "type": "set",
                "field": "gross",
                "value": {
                    "operator": "round",
                    "args": [{
                        "operator": "multiply",
                        "args": [
                            {"field": "net"},
                            {
                                "operator": "add",
                                "args": [
                                    1,
                                    {
                                        "operator": "divide",
                                        "args": [{"field": "tax_rate"}, 100],
                                    },
                                ],
                            },
                        ],
                    }, 2],
                },
            }],
        },
        person_id="person-1",
    )
    return quality


def test_context_rules_apply_in_dependency_order_and_record_provenance(tmp_path):
    service, workspace, collection, fields = _world(tmp_path)
    quality_context = _establish_rules(service, workspace, collection)

    record, changes, _event = service.business.upsert_record(
        collection.id,
        stable_key="material-1",
        values={"name": "Steel", "moisture": 8, "net": 100},
        business_intent="Receive material",
        person_id="person-1",
    )

    assert record.values[fields["quality"].id] == "defective"
    assert record.values[fields["tax_rate"].id] == 13
    assert record.values[fields["gross"].id] == 113
    quality_change = next(item for item in changes if item.field_id == fields["quality"].id)
    assert quality_change.origin == "workspace_context"
    assert quality_change.context_id == quality_context.id
    assert quality_change.context_revision == quality_context.revision
    assert quality_change.reason == quality_context.statement
    snapshot = service.context.entry_snapshot(quality_context)
    assert snapshot["execution"]["target_collection_id"] == collection.id
    assert snapshot["execution"]["write_field_ids"] == [fields["quality"].id]

    restarted = WorkspaceService(WorkspaceStore(tmp_path / "workspaces.db"))
    persisted = restarted.context.entry_snapshot(
        restarted.context.store.get(quality_context.id)
    )
    assert persisted["execution"]["specification"]["condition"]["field_id"] == fields["moisture"].id


def test_context_rule_applies_to_import_and_business_action(tmp_path):
    service, workspace, collection, fields = _world(tmp_path)
    _establish_rules(service, workspace, collection)
    source = tmp_path / "materials.csv"
    source.write_text("Name,Moisture,Net\nCopper,7,200\n", encoding="utf-8")

    imported = service.imports.import_path(
        workspace.id,
        source,
        collection_id=collection.id,
        key_column="Name",
        source_person_id="person-1",
    )
    assert imported["created"] == 1
    copper = service.business.query_records(
        collection.id,
        filters={"Name": "Copper"},
    )[0]
    assert copper["values"]["quality"] == "defective"
    assert copper["values"]["gross"] == 226

    action = service.actions.store.create_definition(
        workspace_id=workspace.id,
        collection_id=collection.id,
        source_candidate_id="candidate-test",
        name="Register material",
        description="Register a material receipt",
        operation="create",
        field_ids=(fields["name"].id, fields["moisture"].id, fields["net"].id),
        completion_criteria="A material exists",
        evidence_count=3,
        validation={"status": "passed"},
        created_by_person_id="person-1",
    )
    run, record, changes, _event = service.actions.execute(
        action.id,
        stable_key="material-action",
        values={"Name": "Aluminium", "Moisture": 9, "Net": 300},
        business_intent="Register through Business Action",
        person_id="person-1",
    )
    assert run.status == "completed"
    assert record.values[fields["quality"].id] == "defective"
    assert record.values[fields["gross"].id] == 339
    assert any(item.origin == "workspace_context" for item in changes)


def test_context_rejects_write_and_correction_replaces_executable_rule(tmp_path):
    service, workspace, collection, fields = _world(tmp_path)
    constraint = service.context.establish(
        workspace.id,
        statement="Weight cannot exceed 500",
        context_type="constraint",
        executable={
            "target_collection_id": collection.id,
            "condition": {"field": "weight", "operator": "gt", "value": 500},
            "effects": [{"type": "reject", "message": "Weight exceeds the limit"}],
        },
        person_id="person-1",
    )
    with pytest.raises(ValueError, match="Weight exceeds the limit"):
        service.business.upsert_record(
            collection.id,
            stable_key="too-heavy",
            values={"name": "Machine", "weight": 501},
            business_intent="Receive machine",
            person_id="person-1",
        )

    replacement = service.context.correct(
        constraint.id,
        statement="Weight cannot exceed 1000",
        executable={
            "target_collection_id": collection.id,
            "condition": {"field": "weight", "operator": "gt", "value": 1000},
            "effects": [{"type": "reject", "message": "Weight exceeds the new limit"}],
        },
        person_id="person-1",
    )
    record, _changes, _event = service.business.upsert_record(
        collection.id,
        stable_key="accepted",
        values={"name": "Machine", "weight": 501},
        business_intent="Receive machine after correction",
        person_id="person-1",
    )
    assert record.values[fields["weight"].id] == 501
    assert service.context.store.get(constraint.id).status == "superseded"
    assert service.context.entry_snapshot(
        service.context.store.get(constraint.id)
    )["execution"]["status"] == "inactive"
    assert service.context.entry_snapshot(replacement)["execution"]["context_id"] == replacement.id


def test_context_execution_rejects_dependency_cycles_before_saving_second_rule(tmp_path):
    service, workspace, collection, _fields = _world(tmp_path)
    service.context.establish(
        workspace.id,
        statement="Gross feeds net",
        context_type="calculation",
        executable={
            "target_collection_id": collection.id,
            "effects": [{"type": "set", "field": "net", "value": {"field": "gross"}}],
        },
        person_id="person-1",
    )
    with pytest.raises(ValueError, match="dependencies contain a cycle"):
        service.context.establish(
            workspace.id,
            statement="Net feeds gross",
            context_type="calculation",
            executable={
                "target_collection_id": collection.id,
                "effects": [{"type": "set", "field": "gross", "value": {"field": "net"}}],
            },
            person_id="person-1",
        )
    contexts = service.context.store.list_for_workspace(workspace.id)
    assert [item.statement for item in contexts] == ["Gross feeds net"]


def test_agent_can_configure_existing_context_without_semantic_tool_retrieval(tmp_path):
    service, workspace, collection, fields = _world(tmp_path)
    service.focus_session(
        workspace.id,
        session_id="session-1",
        person_id="person-1",
        turn_id="turn-focus",
    )
    context = service.context.establish(
        workspace.id,
        statement="Heavy materials go to the large warehouse",
        context_type="decision",
        person_id="person-1",
    )
    core = SimpleNamespace(
        user_id="person-1",
        session_id="session-1",
        turn_id="turn-1",
    )
    agent = SimpleNamespace(workspace_service=service, _get_agent=lambda: core)
    tools = {item.name: item for item in create_workspace_tools(agent)}

    configured = tools["configure_context_execution"].execute(
        context_id=context.id,
        executable={
            "target_collection_id": collection.id,
            "condition": {"field": "weight", "operator": "gt", "value": 500},
            "effects": [{
                "type": "set",
                "field": "warehouse",
                "value": "large_goods",
            }],
        },
    )

    assert configured["execution"]["write_field_ids"] == [fields["warehouse"].id]
    same = tools["configure_context_execution"].execute(
        context_id=context.id,
        executable={
            "target_collection_id": collection.id,
            "condition": {"field": "weight", "operator": "gt", "value": 500},
            "effects": [{
                "type": "set", "field": "warehouse", "value": "large_goods",
            }],
        },
    )
    assert same["execution"]["updated_at"] == configured["execution"]["updated_at"]
    with pytest.raises(ValueError, match="cannot be changed in place"):
        tools["configure_context_execution"].execute(
            context_id=context.id,
            executable={
                "target_collection_id": collection.id,
                "condition": {"field": "weight", "operator": "gt", "value": 800},
                "effects": [{
                    "type": "set", "field": "warehouse", "value": "large_goods",
                }],
            },
        )
    required = _contextual_required_tool_names(
        '<focused_workspace>{"id":"workspace-1"}</focused_workspace> '
        "Please add a business rule",
    )
    assert {
        "record_business_context",
        "configure_context_execution",
        "correct_business_context",
        "list_business_context",
    }.issubset(required)
