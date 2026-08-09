"""Agent tools for creating business workspaces and interactive surfaces."""

from __future__ import annotations

from typing import Any

from xiaomei_brain.tools.base import Tool

from .dataset_tools import create_dataset_tools
from .import_tools import create_import_tools


def create_workspace_tools(agent: Any) -> list[Tool]:
    def core() -> Any:
        return agent._get_agent()

    def service():
        value = getattr(agent, "workspace_service", None)
        if value is None:
            value = getattr(core(), "workspace_service", None)
        if value is None:
            raise RuntimeError("Workspace service is not initialized")
        return value

    def person_id() -> str:
        value = str(getattr(core(), "user_id", "")).strip()
        if not value or value in {"global", "system"}:
            raise ValueError("The current conversation has no verified Person")
        return value

    def context() -> tuple[str, str]:
        current = core()
        return (
            str(getattr(current, "session_id", "") or ""),
            str(getattr(current, "turn_id", "") or ""),
        )

    def require_workspace(workspace_id: str):
        return service().require_for_person(
            workspace_id,
            person_id=person_id(),
        )

    def require_collection(collection_id: str):
        collection = service().business.require_collection(collection_id)
        require_workspace(collection.workspace_id)
        return collection

    def require_surface(surface_id: str):
        surface = service().store.get_surface(surface_id)
        if surface is None:
            raise KeyError(surface_id)
        require_workspace(surface.workspace_id)
        return surface

    def require_action(action_id: str):
        definition = service().actions.require(action_id)
        require_workspace(definition.workspace_id)
        return definition

    def focus(workspace_id: str) -> None:
        session_id, turn_id = context()
        if session_id:
            service().focus_session(
                workspace_id,
                session_id=session_id,
                person_id=person_id(),
                turn_id=turn_id,
            )

    def resolve_workspace_id(workspace_id: str = "") -> str:
        resolved = workspace_id.strip()
        if resolved:
            require_workspace(resolved)
            return resolved
        session_id, _turn_id = context()
        current = service().current_for_session(
            session_id,
            person_id=person_id(),
        )
        if current is None:
            raise ValueError("The current conversation is not focused on a Workspace")
        return current.id

    def create_workspace(
        name: str,
        purpose: str,
        description: str = "",
        initial_surface: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a persistent business world, optionally with its first Surface."""
        session_id, turn_id = context()
        workspace = service().create(
            name=name,
            purpose=purpose,
            description=description,
            created_reason="Created by the Agent from the current conversation",
            created_by_person_id=person_id(),
            default_surface_definition=initial_surface,
            session_id=session_id,
            turn_id=turn_id,
        )
        focus(workspace.id)
        return service().snapshot(workspace, include_surfaces=True)

    def update_workspace(
        workspace_id: str,
        expected_revision: int,
        name: str = "",
        purpose: str = "",
        description: str = "",
        status: str = "",
    ) -> dict[str, Any]:
        """Update a Workspace's identity, purpose, lifecycle or description."""
        require_workspace(workspace_id)
        session_id, turn_id = context()
        workspace = service().update(
            workspace_id,
            name=name or None,
            purpose=purpose or None,
            description=description or None,
            status=status or None,
            expected_revision=expected_revision,
            session_id=session_id,
            turn_id=turn_id,
        )
        return service().snapshot(workspace, include_surfaces=True)

    def create_surface(
        workspace_id: str,
        name: str,
        purpose: str,
        definition: dict[str, Any],
        is_default: bool = False,
    ) -> dict[str, Any]:
        """Create a durable interactive Surface inside a Workspace."""
        require_workspace(workspace_id)
        session_id, turn_id = context()
        surface = service().surfaces.create(
            workspace_id,
            name=name,
            purpose=purpose,
            definition=definition,
            is_default=is_default,
            session_id=session_id,
            turn_id=turn_id,
        )
        return service().surfaces.snapshot(surface)

    def update_surface(
        surface_id: str,
        definition: dict[str, Any],
        expected_revision: int,
        name: str = "",
        purpose: str = "",
    ) -> dict[str, Any]:
        """Replace one Surface definition after inspecting its current revision."""
        require_surface(surface_id)
        session_id, turn_id = context()
        surface = service().surfaces.update(
            surface_id,
            name=name or None,
            purpose=purpose or None,
            definition=definition,
            expected_revision=expected_revision,
            session_id=session_id,
            turn_id=turn_id,
        )
        return service().surfaces.snapshot(surface)

    def get_workspace(workspace_id: str) -> dict[str, Any]:
        """Inspect a Workspace, its Surfaces and current business world."""
        workspace = require_workspace(workspace_id)
        focus(workspace.id)
        return service().snapshot(
            workspace, include_surfaces=True,
            include_business=True, include_records=True,
        )

    def list_workspaces() -> dict[str, Any]:
        """List Workspaces related to the current Person and current Session focus."""
        session_id, _turn_id = context()
        focused = service().current_for_session(
            session_id,
            person_id=person_id(),
        )
        return {
            "workspaces": [
                service().snapshot(item)
                for item in service().list_for_person(person_id(), limit=100)
            ],
            "focused_workspace_id": focused.id if focused is not None else "",
        }

    def focus_workspace(workspace_id: str) -> dict[str, Any]:
        """Make one Workspace the continuing business context of this Session."""
        focus(workspace_id)
        workspace = require_workspace(workspace_id)
        return service().snapshot(
            workspace,
            include_surfaces=True,
            include_business=True,
        )

    def get_current_workspace() -> dict[str, Any]:
        """Read the Workspace currently focused by this conversation Session."""
        session_id, _turn_id = context()
        workspace = service().current_for_session(
            session_id,
            person_id=person_id(),
        )
        if workspace is None:
            return {
                "focused": False,
                "message": "This conversation has no focused Workspace",
            }
        return {
            "focused": True,
            "workspace": service().snapshot(
                workspace,
                include_surfaces=True,
                include_business=True,
                include_records=True,
            ),
        }

    def create_data_source(
        workspace_id: str,
        kind: str,
        name: str,
        locator: str = "",
    ) -> dict[str, Any]:
        """Register a stable source from which business observations arrive."""
        require_workspace(workspace_id)
        session_id, turn_id = context()
        source = service().business.create_data_source(
            workspace_id,
            kind=kind,
            name=name,
            locator=locator,
            session_id=session_id,
            turn_id=turn_id,
        )
        return service().business.data_source_snapshot(source)

    def record_observation(
        workspace_id: str,
        content: str,
        data_source_id: str = "",
        external_ref: str = "",
        attributes: dict[str, Any] | None = None,
        asset_id: str = "",
        occurred_at: float | None = None,
    ) -> dict[str, Any]:
        """Record what was received before deciding whether it is a business fact."""
        require_workspace(workspace_id)
        session_id, turn_id = context()
        resolved_data_source_id = data_source_id.strip()
        if not resolved_data_source_id and session_id:
            locator = f"session:{session_id}"
            source = service().business.store.find_data_source(
                workspace_id,
                kind="conversation",
                locator=locator,
            )
            if source is None:
                source = service().business.create_data_source(
                    workspace_id,
                    kind="conversation",
                    name="Conversation",
                    locator=locator,
                    session_id=session_id,
                    turn_id=turn_id,
                )
            resolved_data_source_id = source.id
        observation = service().business.observe(
            workspace_id,
            content=content,
            data_source_id=resolved_data_source_id,
            source_person_id=person_id(),
            external_ref=external_ref,
            attributes=attributes,
            asset_id=asset_id,
            occurred_at=occurred_at,
            session_id=session_id,
            turn_id=turn_id,
        )
        return service().business.observation_snapshot_with_links(observation)

    def define_collection(
        workspace_id: str,
        name: str,
        label: str,
        purpose: str,
        fields: list[dict[str, Any]],
        maturity: str = "candidate",
    ) -> dict[str, Any]:
        """Define a stable business object and its typed fields."""
        require_workspace(workspace_id)
        session_id, turn_id = context()
        collection, definitions = service().business.create_collection(
            workspace_id,
            name=name,
            label=label,
            purpose=purpose,
            fields=fields,
            maturity=maturity,
            session_id=session_id,
            turn_id=turn_id,
        )
        return service().business.collection_snapshot(collection, definitions)

    def upsert_business_record(
        collection_id: str,
        values: dict[str, Any],
        business_intent: str,
        record_id: str = "",
        stable_key: str = "",
        expected_revision: int | None = None,
        observation_id: str = "",
        event_type: str = "",
        event_summary: str = "",
        event_occurred_at: float | None = None,
        event_idempotency_key: str = "",
        event_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create or update current business state and preserve every field change."""
        require_collection(collection_id)
        session_id, turn_id = context()
        record, changes, event = service().business.upsert_record(
            collection_id,
            values=values,
            record_id=record_id,
            stable_key=stable_key,
            expected_revision=expected_revision,
            business_intent=business_intent,
            person_id=person_id(),
            session_id=session_id,
            turn_id=turn_id,
            observation_id=observation_id,
            event_type=event_type,
            event_summary=event_summary,
            event_occurred_at=event_occurred_at,
            event_idempotency_key=event_idempotency_key,
            event_metadata=event_metadata,
        )
        fields = service().business.store.list_fields(collection_id)
        return {
            "record": service().business.record_snapshot(record, fields),
            "changes": [
                service().business.change_snapshot(change, fields)
                for change in changes
            ],
            "event": (
                service().business.event_snapshot(event)
                if event is not None else None
            ),
        }

    def add_collection_fields(
        collection_id: str,
        expected_revision: int,
        fields: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Extend a Collection as the Agent learns more about the business."""
        require_collection(collection_id)
        session_id, turn_id = context()
        collection, definitions = service().business.add_collection_fields(
            collection_id,
            expected_revision=expected_revision,
            fields=fields,
            session_id=session_id,
            turn_id=turn_id,
        )
        return service().business.collection_snapshot(collection, definitions)

    def query_business_records(
        collection_id: str,
        filters: dict[str, Any] | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Query current records using field names, labels, aliases or IDs."""
        require_collection(collection_id)
        return {
            "records": service().business.query_records(
                collection_id, filters=filters, limit=limit,
            ),
        }

    def establish_business_action(
        workspace_id: str,
        candidate_id: str,
        name: str,
        description: str,
        completion_criteria: str,
    ) -> dict[str, Any]:
        """Crystallize a repeated successful pattern as reusable business meaning."""
        require_workspace(workspace_id)
        session_id, turn_id = context()
        definition = service().actions.establish(
            workspace_id,
            candidate_id=candidate_id,
            name=name,
            description=description,
            completion_criteria=completion_criteria,
            person_id=person_id(),
            session_id=session_id,
            turn_id=turn_id,
        )
        return service().actions.definition_snapshot(definition)

    def list_business_actions(workspace_id: str = "") -> dict[str, Any]:
        """Inspect stable business actions and their recent attempts."""
        resolved_workspace_id = workspace_id.strip()
        if not resolved_workspace_id:
            session_id, _turn_id = context()
            current = service().current_for_session(
                session_id,
                person_id=person_id(),
            )
            if current is None:
                return {"actions": [], "action_runs": [], "focused": False}
            resolved_workspace_id = current.id
        require_workspace(resolved_workspace_id)
        return {
            **service().actions.workspace_snapshot(resolved_workspace_id),
            "focused": True,
        }

    def execute_business_action(
        action_id: str,
        values: dict[str, Any],
        business_intent: str,
        record_id: str = "",
        stable_key: str = "",
        expected_revision: int | None = None,
        observation_id: str = "",
        event_type: str = "",
        event_summary: str = "",
        event_occurred_at: float | None = None,
        event_idempotency_key: str = "",
        event_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute one stable business meaning while preserving Agent freedom."""
        definition = require_action(action_id)
        session_id, turn_id = context()
        run, record, changes, event = service().actions.execute(
            definition.id,
            values=values,
            business_intent=business_intent,
            person_id=person_id(),
            record_id=record_id,
            stable_key=stable_key,
            expected_revision=expected_revision,
            observation_id=observation_id,
            event_type=event_type,
            event_summary=event_summary,
            event_occurred_at=event_occurred_at,
            event_idempotency_key=event_idempotency_key,
            event_metadata=event_metadata,
            session_id=session_id,
            turn_id=turn_id,
        )
        fields = service().business.store.list_fields(definition.collection_id)
        return {
            "action": service().actions.definition_snapshot(definition),
            "run": service().actions.run_snapshot(run),
            "record": service().business.record_snapshot(record, fields),
            "changes": [
                service().business.change_snapshot(change, fields)
                for change in changes
            ],
            "event": (
                service().business.event_snapshot(event)
                if event is not None else None
            ),
        }

    def record_business_context(
        statement: str,
        context_type: str,
        scope_type: str = "workspace",
        scope_id: str = "",
        evidence_observation_ids: list[str] | None = None,
        workspace_id: str = "",
    ) -> dict[str, Any]:
        """Persist a stable business meaning, not an incidental conversation detail."""
        resolved_workspace_id = resolve_workspace_id(workspace_id)
        session_id, turn_id = context()
        item = service().context.establish(
            resolved_workspace_id,
            statement=statement,
            context_type=context_type,
            scope_type=scope_type,
            scope_id=scope_id,
            evidence_observation_ids=evidence_observation_ids or [],
            person_id=person_id(),
            session_id=session_id,
            turn_id=turn_id,
        )
        return service().context.entry_snapshot(item)

    def correct_business_context(
        context_id: str,
        statement: str,
        evidence_observation_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """Replace an active business meaning while preserving its correction chain."""
        current = service().context.store.get(context_id)
        if current is None:
            raise KeyError(context_id)
        require_workspace(current.workspace_id)
        session_id, turn_id = context()
        item = service().context.correct(
            context_id,
            statement=statement,
            evidence_observation_ids=evidence_observation_ids or [],
            person_id=person_id(),
            session_id=session_id,
            turn_id=turn_id,
        )
        return service().context.entry_snapshot(item)

    def list_business_context(
        workspace_id: str = "",
        include_inactive: bool = False,
    ) -> dict[str, Any]:
        """Inspect durable business meanings and their correction history."""
        resolved = resolve_workspace_id(workspace_id)
        return {
            "workspace_id": resolved,
            "contexts": service().context.list_snapshots(
                resolved,
                include_inactive=include_inactive,
            ),
        }

    component_schema = {
        "type": "object",
        "additionalProperties": True,
        "properties": {
            "id": {"type": "string"},
            "type": {
                "type": "string",
                "enum": [
                    "metric", "text", "table", "record", "bar_chart",
                    "line_chart", "pie_chart", "timeline", "asset", "group",
                ],
            },
            "title": {"type": "string"},
            "value": {},
            "unit": {"type": "string"},
            "detail": {"type": "string"},
            "content": {"type": "string"},
            "columns": {"type": "array", "items": {}},
            "rows": {
                "type": "array",
                "items": {"type": "object", "additionalProperties": True},
            },
            "data": {
                "type": "array",
                "items": {"type": "object", "additionalProperties": True},
            },
            "binding": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "dataset_id": {"type": "string"},
                    "metric_key": {"type": "string"},
                    "label_field": {"type": "string"},
                    "value_field": {"type": "string"},
                },
                "required": ["dataset_id"],
            },
        },
        "required": ["type"],
    }
    definition_schema = {
        "type": "object",
        "additionalProperties": True,
        "properties": {
            "components": {
                "type": "array",
                "items": component_schema,
                "minItems": 1,
                "maxItems": 48,
            },
        },
        "required": ["components"],
    }
    tools = [
        Tool(
            name="create_workspace",
            description=(
                "Create a Workspace only for a business that will continue to change, "
                "be queried or receive future action. Do not create one for a one-off task. "
                "An optional initial_surface may present the first useful business interface."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "purpose": {"type": "string"},
                    "description": {"type": "string"},
                    "initial_surface": definition_schema,
                },
                "required": ["name", "purpose"],
            },
            func=create_workspace,
            category="workspace",
        ),
        Tool(
            name="update_workspace",
            description=(
                "Update a Workspace's name, purpose, description or active/closed status. "
                "Surface contents are changed with update_surface instead."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "workspace_id": {"type": "string"},
                    "expected_revision": {"type": "integer", "minimum": 1},
                    "name": {"type": "string"},
                    "purpose": {"type": "string"},
                    "description": {"type": "string"},
                    "status": {"type": "string", "enum": ["active", "closed"]},
                },
                "required": ["workspace_id", "expected_revision"],
            },
            func=update_workspace,
            category="workspace",
        ),
        Tool(
            name="create_surface",
            description=(
                "Create a persistent interactive Surface in an existing Workspace. "
                "A Surface presents business data; it is not the Workspace itself. "
                "For durable business values, bind components to a Dataset instead "
                "of copying static values into the Surface."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "workspace_id": {"type": "string"},
                    "name": {"type": "string"},
                    "purpose": {"type": "string"},
                    "definition": definition_schema,
                    "is_default": {"type": "boolean"},
                },
                "required": ["workspace_id", "name", "purpose", "definition"],
            },
            func=create_surface,
            category="workspace",
        ),
        Tool(
            name="update_surface",
            description=(
                "Update an existing Surface after get_workspace. Send its complete "
                "definition and current revision so concurrent changes are preserved."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "surface_id": {"type": "string"},
                    "definition": definition_schema,
                    "expected_revision": {"type": "integer", "minimum": 1},
                    "name": {"type": "string"},
                    "purpose": {"type": "string"},
                },
                "required": ["surface_id", "definition", "expected_revision"],
            },
            func=update_surface,
            category="workspace",
        ),
        Tool(
            name="get_workspace",
            description=(
                "Read one Workspace, its Surfaces, business schema, current records "
                "and Events before changing them."
            ),
            parameters={
                "type": "object",
                "properties": {"workspace_id": {"type": "string"}},
                "required": ["workspace_id"],
            },
            func=get_workspace,
            category="workspace",
        ),
        Tool(
            name="list_workspaces",
            description=(
                "List persistent business Workspaces related to the current Person, "
                "including which one this conversation currently focuses."
            ),
            parameters={"type": "object", "properties": {}},
            func=list_workspaces,
            category="workspace",
        ),
        Tool(
            name="focus_workspace",
            description=(
                "Focus this conversation on one Workspace. Use when the Person says "
                "they are entering, switching to or continuing work in a Workspace."
            ),
            parameters={
                "type": "object",
                "properties": {"workspace_id": {"type": "string"}},
                "required": ["workspace_id"],
            },
            func=focus_workspace,
            category="workspace",
        ),
        Tool(
            name="get_current_workspace",
            description=(
                "Inspect the Workspace already focused by this conversation. Use it "
                "for follow-up customer, quote, contract, payment, metric or dashboard "
                "requests when the Person does not repeat the Workspace name."
            ),
            parameters={"type": "object", "properties": {}},
            func=get_current_workspace,
            category="workspace",
        ),
        Tool(
            name="create_data_source",
            description=(
                "Register a stable source such as a conversation, file, channel, "
                "manual entry, import or external API. Store only a locator here, "
                "never credentials or secret tokens."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "workspace_id": {"type": "string"},
                    "kind": {
                        "type": "string",
                        "enum": [
                            "conversation", "file", "channel", "manual",
                            "external_api", "import",
                        ],
                    },
                    "name": {"type": "string"},
                    "locator": {"type": "string"},
                },
                "required": ["workspace_id", "kind", "name"],
            },
            func=create_data_source,
            category="workspace",
        ),
        Tool(
            name="record_observation",
            description=(
                "Preserve information received in the current conversation before "
                "treating it as verified business state. When a Person reports or "
                "requests a customer, quote, contract, order or payment change, call "
                "this first with a faithful concise account of what they said, then "
                "pass its observation_id to upsert_business_record. Keep uncertain "
                "statements here without prematurely changing a Collection."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "workspace_id": {"type": "string"},
                    "content": {"type": "string"},
                    "data_source_id": {"type": "string"},
                    "external_ref": {"type": "string"},
                    "attributes": {"type": "object", "additionalProperties": True},
                    "asset_id": {"type": "string"},
                    "occurred_at": {"type": "number"},
                },
                "required": ["workspace_id", "content"],
            },
            func=record_observation,
            category="workspace",
        ),
        Tool(
            name="define_collection",
            description=(
                "Define a reusable typed business object such as customer, quote, "
                "contract or payment. Use a stable machine name and human-readable label."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "workspace_id": {"type": "string"},
                    "name": {"type": "string"},
                    "label": {"type": "string"},
                    "purpose": {"type": "string"},
                    "maturity": {
                        "type": "string",
                        "enum": ["provisional", "candidate", "established"],
                    },
                    "fields": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 128,
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "label": {"type": "string"},
                                "data_type": {
                                    "type": "string",
                                    "enum": [
                                        "text", "integer", "number", "boolean",
                                        "date", "datetime", "money", "enum",
                                        "reference", "json",
                                    ],
                                },
                                "required": {"type": "boolean"},
                                "aliases": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                            },
                            "required": ["name", "label", "data_type"],
                        },
                    },
                },
                "required": ["workspace_id", "name", "label", "purpose", "fields"],
            },
            func=define_collection,
            category="workspace",
        ),
        Tool(
            name="upsert_business_record",
            description=(
                "Create or revise current business state. Address fields by ID, name, "
                "label or alias. Every changed field is recorded. For facts or change "
                "requests received in conversation, first call record_observation and "
                "link its observation_id so the source remains traceable. Add event_type "
                "and event_summary only when a meaningful past-tense business fact is "
                "known to have occurred; ordinary data cleanup must not manufacture Events."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "collection_id": {"type": "string"},
                    "record_id": {"type": "string"},
                    "stable_key": {"type": "string"},
                    "expected_revision": {"type": "integer", "minimum": 1},
                    "values": {"type": "object", "additionalProperties": True},
                    "business_intent": {"type": "string"},
                    "observation_id": {"type": "string"},
                    "event_type": {"type": "string"},
                    "event_summary": {"type": "string"},
                    "event_occurred_at": {"type": "number"},
                    "event_idempotency_key": {"type": "string"},
                    "event_metadata": {"type": "object", "additionalProperties": True},
                },
                "required": ["collection_id", "values", "business_intent"],
            },
            func=upsert_business_record,
            category="workspace",
        ),
        Tool(
            name="add_collection_fields",
            description=(
                "Extend an existing Collection when repeated business use reveals "
                "new facts worth storing. Inspect the Collection first and provide "
                "its current revision. Existing field IDs and values remain unchanged."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "collection_id": {"type": "string"},
                    "expected_revision": {"type": "integer", "minimum": 1},
                    "fields": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 128,
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "label": {"type": "string"},
                                "data_type": {
                                    "type": "string",
                                    "enum": [
                                        "text", "integer", "number", "boolean",
                                        "date", "datetime", "money", "enum",
                                        "reference", "json",
                                    ],
                                },
                                "required": {"type": "boolean"},
                                "aliases": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                            },
                            "required": ["name", "label", "data_type"],
                        },
                    },
                },
                "required": ["collection_id", "expected_revision", "fields"],
            },
            func=add_collection_fields,
            category="workspace",
        ),
        Tool(
            name="query_business_records",
            description=(
                "Query a Collection's current records. Filters are exact matches and "
                "may use field IDs, names, labels or aliases."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "collection_id": {"type": "string"},
                    "filters": {"type": "object", "additionalProperties": True},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 500},
                },
                "required": ["collection_id"],
            },
            func=query_business_records,
            category="workspace",
        ),
        Tool(
            name="establish_business_action",
            description=(
                "Turn a repeated candidate shown by get_workspace into a stable named "
                "business action. This records the business outcome and completion "
                "meaning, not a fixed workflow or reasoning sequence. Only establish "
                "a candidate supported by at least three independent successful Turns."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "workspace_id": {"type": "string"},
                    "candidate_id": {"type": "string"},
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "completion_criteria": {"type": "string"},
                },
                "required": [
                    "workspace_id", "candidate_id", "name",
                    "description", "completion_criteria",
                ],
            },
            func=establish_business_action,
            category="workspace",
        ),
        Tool(
            name="list_business_actions",
            description=(
                "List stable business actions and recent ActionRuns in the current or "
                "specified Workspace. Use before a recurring business change so an "
                "established meaning can be reused instead of guessed from scratch."
            ),
            parameters={
                "type": "object",
                "properties": {"workspace_id": {"type": "string"}},
            },
            func=list_business_actions,
            category="workspace",
        ),
        Tool(
            name="execute_business_action",
            description=(
                "Execute an established business action against one record. The Agent "
                "remains free to reason and choose tools; this call only validates the "
                "declared business effect and records one ActionRun. Inspect the record "
                "first, pass expected_revision for updates, and link the current "
                "Observation when the request came from conversation."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action_id": {"type": "string"},
                    "record_id": {"type": "string"},
                    "stable_key": {"type": "string"},
                    "expected_revision": {"type": "integer", "minimum": 1},
                    "values": {"type": "object", "additionalProperties": True},
                    "business_intent": {"type": "string"},
                    "observation_id": {"type": "string"},
                    "event_type": {"type": "string"},
                    "event_summary": {"type": "string"},
                    "event_occurred_at": {"type": "number"},
                    "event_idempotency_key": {"type": "string"},
                    "event_metadata": {"type": "object", "additionalProperties": True},
                },
                "required": ["action_id", "values", "business_intent"],
            },
            func=execute_business_action,
            category="workspace",
        ),
        Tool(
            name="record_business_context",
            description=(
                "Record a durable business meaning in the focused Workspace: a term, "
                "default practice, constraint, effective decision, calculation rule or "
                "business boundary. Do not store one-off chat details as Context. Use "
                "workspace scope for shared business meaning, person scope only for the "
                "current Person's working preference, and transaction scope for one "
                "specific business record. Link source Observations when available."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "workspace_id": {"type": "string"},
                    "statement": {"type": "string"},
                    "context_type": {
                        "type": "string",
                        "enum": [
                            "term", "default", "constraint", "decision",
                            "calculation", "boundary",
                        ],
                    },
                    "scope_type": {
                        "type": "string",
                        "enum": ["workspace", "person", "transaction"],
                    },
                    "scope_id": {"type": "string"},
                    "evidence_observation_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["statement", "context_type"],
            },
            func=record_business_context,
            category="workspace",
        ),
        Tool(
            name="correct_business_context",
            description=(
                "Correct or replace an established business Context entry. The old "
                "entry remains in history as superseded and only the replacement stays "
                "active. Inspect Context first so the exact entry is corrected."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "context_id": {"type": "string"},
                    "statement": {"type": "string"},
                    "evidence_observation_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["context_id", "statement"],
            },
            func=correct_business_context,
            category="workspace",
        ),
        Tool(
            name="list_business_context",
            description=(
                "List durable terminology, defaults, constraints, decisions, calculation "
                "rules and boundaries in the focused Workspace. Include inactive entries "
                "only when explaining a correction history."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "workspace_id": {"type": "string"},
                    "include_inactive": {"type": "boolean"},
                },
            },
            func=list_business_context,
            category="workspace",
        ),
    ]
    return tools + create_dataset_tools(agent) + create_import_tools(agent)
