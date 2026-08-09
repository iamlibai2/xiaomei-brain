from __future__ import annotations

import pytest

from xiaomei_brain.workspaces import (
    SchemaAmbiguityError,
    WorkspaceService,
    WorkspaceStore,
)


def _service(tmp_path):
    return WorkspaceService(WorkspaceStore(tmp_path / "workspaces.db"))


def _workspace(service):
    return service.create(name="Operations", purpose="Run the business")


def _customers(service, workspace_id):
    return service.business.create_collection(
        workspace_id,
        name="customers",
        label="Customers",
        purpose="Customer operations",
        fields=[
            {
                "name": "customer_name",
                "label": "Customer Name",
                "data_type": "text",
                "required": True,
                "aliases": ["client"],
            },
            {
                "name": "stage",
                "label": "Stage",
                "data_type": "enum",
                "required": False,
            },
        ],
    )


def test_collection_definition_reuses_and_evolves_one_canonical_schema(tmp_path):
    service = _service(tmp_path)
    workspace = _workspace(service)
    original, original_fields = _customers(service, workspace.id)

    resolved, fields = service.business.create_collection(
        workspace.id,
        name="customer-s",
        label="Customer s",
        purpose="A differently formatted proposal",
        fields=[
            {
                "name": "customer name",
                "label": "Customer_Name",
                "data_type": "text",
                "required": True,
                "aliases": ["account name"],
            },
            {
                "name": "annual_revenue",
                "label": "Annual Revenue",
                "data_type": "money",
                "required": False,
            },
        ],
    )

    assert resolved.id == original.id
    assert len(service.business.store.list_collections(workspace.id)) == 1
    assert fields[0].id == original_fields[0].id
    assert "account name" in fields[0].aliases
    assert {field.name for field in fields} == {
        "customer_name",
        "stage",
        "annual_revenue",
    }
    assert resolved.revision == original.revision + 1


def test_record_values_use_same_identity_rules_and_reject_conflicting_keys(tmp_path):
    service = _service(tmp_path)
    workspace = _workspace(service)
    collection, fields = _customers(service, workspace.id)

    record, _changes, _event = service.business.upsert_record(
        collection.id,
        stable_key="customer:a",
        values={"Customer-Name": "A", "STAGE": "lead"},
        business_intent="Create customer",
    )
    by_name = {field.name: field.id for field in fields}
    assert record.values[by_name["customer_name"]] == "A"

    with pytest.raises(SchemaAmbiguityError, match="same field"):
        service.business.upsert_record(
            collection.id,
            stable_key="customer:b",
            values={"customer_name": "B", "Customer Name": "C"},
            business_intent="Create conflicting customer",
        )


def test_field_evolution_reuses_compatible_field_and_rejects_type_change(tmp_path):
    service = _service(tmp_path)
    workspace = _workspace(service)
    collection, fields = _customers(service, workspace.id)

    unchanged, reused = service.business.add_collection_fields(
        collection.id,
        fields=[{
            "name": "customer-name",
            "label": "Customer Name",
            "data_type": "text",
            "aliases": ["buyer"],
        }],
        expected_revision=collection.revision,
    )
    assert unchanged.revision == collection.revision + 1
    assert len(reused) == len(fields)
    assert "buyer" in reused[0].aliases

    with pytest.raises(ValueError, match="incompatible"):
        service.business.add_collection_fields(
            collection.id,
            fields=[{
                "name": "stage",
                "label": "Stage",
                "data_type": "number",
            }],
            expected_revision=unchanged.revision,
        )


def test_one_proposal_cannot_describe_the_same_stable_field_twice(tmp_path):
    service = _service(tmp_path)
    workspace = _workspace(service)
    collection, _fields = _customers(service, workspace.id)

    with pytest.raises(SchemaAmbiguityError, match="same stable field"):
        service.business.add_collection_fields(
            collection.id,
            fields=[
                {
                    "name": "customer_name",
                    "label": "Customer Name",
                    "data_type": "text",
                },
                {
                    "name": "client",
                    "label": "Client",
                    "data_type": "text",
                },
            ],
            expected_revision=collection.revision,
        )


def test_ambiguous_legacy_field_identity_is_never_silently_selected(tmp_path):
    service = _service(tmp_path)
    workspace = _workspace(service)
    collection, fields = service.business.create_collection(
        workspace.id,
        name="orders",
        label="Orders",
        purpose="Legacy schema",
        fields=[
            {"name": "order_id", "label": "Primary Order", "data_type": "text"},
            {"name": "reference", "label": "External Reference", "data_type": "text"},
        ],
    )
    second = fields[1]
    conn = service.business.store._get_conn()
    conn.execute(
        "UPDATE collection_fields SET aliases_json = ? WHERE id = ?",
        ('["order-id"]', second.id),
    )
    conn.commit()

    with pytest.raises(SchemaAmbiguityError, match="ambiguous"):
        service.business.upsert_record(
            collection.id,
            stable_key="order:1",
            values={"order id": "SO-1"},
            business_intent="Import legacy order",
        )


def test_tabular_import_reuses_explicit_collection_and_reports_field_bindings(tmp_path):
    service = _service(tmp_path)
    workspace = _workspace(service)
    collection, original_fields = _customers(service, workspace.id)
    source = tmp_path / "customers.csv"
    source.write_text(
        "Customer Name,Stage,Annual Revenue\nA,lead,100\n",
        encoding="utf-8",
    )

    result = service.imports.import_path(
        workspace.id,
        source,
        collection_name="Customers",
        key_column="customer_name",
    )

    assert result["collection"]["id"] == collection.id
    assert len(service.business.store.list_collections(workspace.id)) == 1
    assert result["schema_resolution"]["canonical_collection_id"] == collection.id
    assert result["schema_resolution"]["fields_by_column"]["Customer Name"] == (
        original_fields[0].id
    )
    assert result["key_column"] == "Customer Name"


def test_tabular_import_rejects_equal_structural_matches(tmp_path):
    service = _service(tmp_path)
    workspace = _workspace(service)
    for name in ("customers", "prospects"):
        service.business.create_collection(
            workspace.id,
            name=name,
            label=name.title(),
            purpose="Ambiguity test",
            fields=[
                {"name": "name", "label": "Name", "data_type": "text"},
                {"name": "stage", "label": "Stage", "data_type": "text"},
            ],
        )
    source = tmp_path / "ambiguous.csv"
    source.write_text("Name,Stage\nA,lead\n", encoding="utf-8")

    with pytest.raises(SchemaAmbiguityError, match="multiple Collections"):
        service.imports.import_path(workspace.id, source)

    assert len(service.business.store.list_collections(workspace.id)) == 2
