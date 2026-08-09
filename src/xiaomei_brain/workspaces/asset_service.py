"""Stable Asset identities above conversation, Project and external sources."""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from hashlib import sha256 as sha256_digest
from pathlib import PurePosixPath
from typing import Any

from .asset_store import AssetStore
from .models import Asset
from .store import WorkspaceStore

PublishCallback = Callable[..., Any]


class AssetService:
    def __init__(
        self,
        store: AssetStore,
        workspace_store: WorkspaceStore,
        *,
        publish: PublishCallback | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.store = store
        self.workspace_store = workspace_store
        self._publish = publish
        self._clock = clock

    def require_for_person(
        self,
        asset_id: str,
        workspace_id: str,
        *,
        person_id: str,
    ) -> Asset:
        """Return one Asset only when both Person and Workspace may use it."""
        if not self.workspace_store.person_is_linked(workspace_id, person_id.strip()):
            raise PermissionError("Asset Workspace does not belong to the current Person")
        item = self.store.get(asset_id.strip())
        if item is None or not self.store.is_linked(item.id, workspace_id):
            raise KeyError(asset_id)
        return item

    def register_artifact(
        self,
        workspace_id: str,
        *,
        person_id: str,
        session_id: str,
        artifact: dict[str, Any],
        sha256: str,
    ) -> Asset:
        if not self.workspace_store.person_is_linked(workspace_id, person_id.strip()):
            raise PermissionError("Asset Workspace does not belong to the current Person")
        artifact_id = str(artifact.get("id", "")).strip()
        source_session_id = str(artifact.get("session_id") or session_id).strip()
        name = str(artifact.get("name", "")).strip()
        if not artifact_id or not source_session_id or not name:
            raise ValueError("Artifact identity, session and name are required")
        digest = sha256.strip().lower()
        if not re.fullmatch(r"[a-f0-9]{64}", digest):
            raise ValueError("Asset SHA-256 is invalid")
        metadata = {
            key: artifact[key]
            for key in (
                "description", "tool_call_id", "turn_id", "presented",
                "presented_at", "updated",
            )
            if key in artifact
        }
        metadata["latest_artifact_id"] = artifact_id
        metadata["latest_artifact_session_id"] = source_session_id

        # Conversation Artifacts describe a delivery in one turn, so editing
        # the same file in a later turn legitimately creates another Artifact
        # ID. A working Asset instead represents the durable file itself.
        # Use its Agent-relative path as an opaque stable identity so revisions
        # across turns and sessions continue to update one Asset without
        # exposing the path in public Asset snapshots.
        relative_path = self._normalized_relative_path(artifact)
        if relative_path:
            source_type = "agent_working_file"
            source_id = sha256_digest(relative_path.encode("utf-8")).hexdigest()
            asset_source_session_id = ""
            locator = f"agent-file:{source_id}"
        else:
            # Non-file and legacy Artifact producers may not have a managed
            # relative path. Keep their delivery identity as a safe fallback.
            source_type = "conversation_artifact"
            source_id = artifact_id
            asset_source_session_id = source_session_id
            locator = f"artifact:{source_session_id}:{artifact_id}"
        item, created, changed = self.store.upsert(
            nature="working",
            name=name,
            kind=str(artifact.get("kind") or "file"),
            mime_type=str(
                artifact.get("mime_type") or "application/octet-stream"
            ),
            size=max(0, int(artifact.get("size", 0))),
            sha256=digest,
            source_type=source_type,
            source_id=source_id,
            source_session_id=asset_source_session_id,
            locator=locator,
            metadata=metadata,
            now=self._clock(),
        )
        self.store.link(
            item.id, workspace_id,
            entity_type="workspace", entity_id=workspace_id,
            relation="member", now=self._clock(),
        )
        self.store.link(
            item.id, workspace_id,
            entity_type="session", entity_id=session_id,
            relation="created_in", now=self._clock(),
        )
        if changed:
            self._publish_asset(
                "workspace_asset.created" if created else "workspace_asset.updated",
                workspace_id,
                item,
                session_id=session_id,
                turn_id=str(artifact.get("turn_id", "")),
            )
        return item

    def register_attachment(
        self,
        workspace_id: str,
        *,
        person_id: str,
        session_id: str,
        attachment: dict[str, Any],
        sha256: str,
    ) -> Asset:
        """Register one conversation attachment as a durable Asset."""
        if not self.workspace_store.person_is_linked(workspace_id, person_id.strip()):
            raise PermissionError("Asset Workspace does not belong to the current Person")
        attachment_id = str(attachment.get("id") or "").strip()
        source_session_id = session_id.strip()
        name = str(attachment.get("name") or "").strip()
        if not attachment_id or not source_session_id or not name:
            raise ValueError("Attachment identity, session and name are required")
        digest = sha256.strip().lower()
        if not re.fullmatch(r"[a-f0-9]{64}", digest):
            raise ValueError("Asset SHA-256 is invalid")
        metadata = {
            key: attachment[key]
            for key in ("kind", "mime_type", "size")
            if key in attachment
        }
        item, created, changed = self.store.upsert(
            nature="working",
            name=name,
            kind=str(attachment.get("kind") or "file"),
            mime_type=str(
                attachment.get("mime_type") or "application/octet-stream"
            ),
            size=max(0, int(attachment.get("size", 0))),
            sha256=digest,
            source_type="conversation_attachment",
            source_id=attachment_id,
            source_session_id=source_session_id,
            locator=f"attachment:{source_session_id}:{attachment_id}",
            metadata=metadata,
            now=self._clock(),
        )
        self.store.link(
            item.id, workspace_id,
            entity_type="workspace", entity_id=workspace_id,
            relation="member", now=self._clock(),
        )
        self.store.link(
            item.id, workspace_id,
            entity_type="session", entity_id=source_session_id,
            relation="received_in", now=self._clock(),
        )
        if changed:
            self._publish_asset(
                "workspace_asset.created" if created else "workspace_asset.updated",
                workspace_id,
                item,
                session_id=source_session_id,
                turn_id="",
            )
        return item

    def register_external(
        self,
        workspace_id: str,
        *,
        person_id: str,
        source_type: str,
        source_id: str,
        name: str,
        locator: str,
        kind: str = "external",
        mime_type: str = "application/octet-stream",
        size: int = 0,
        metadata: dict[str, Any] | None = None,
        session_id: str = "",
        turn_id: str = "",
    ) -> Asset:
        """Register a stable object whose authoritative content remains external."""
        if not self.workspace_store.person_is_linked(workspace_id, person_id.strip()):
            raise PermissionError("Asset Workspace does not belong to the current Person")
        normalized_source_type = source_type.strip()
        normalized_source_id = source_id.strip()
        normalized_name = name.strip()
        normalized_locator = locator.strip()
        if not all((
            normalized_source_type,
            normalized_source_id,
            normalized_name,
            normalized_locator,
        )):
            raise ValueError("External Asset source, name and locator are required")
        item, created, changed = self.store.upsert(
            nature="external",
            name=normalized_name,
            kind=kind.strip() or "external",
            mime_type=mime_type.strip() or "application/octet-stream",
            size=max(0, int(size)),
            sha256="",
            source_type=normalized_source_type,
            source_id=normalized_source_id,
            source_session_id="",
            locator=normalized_locator,
            metadata=dict(metadata or {}),
            now=self._clock(),
        )
        self.store.link(
            item.id, workspace_id,
            entity_type="workspace", entity_id=workspace_id,
            relation="member", now=self._clock(),
        )
        if session_id.strip():
            self.store.link(
                item.id, workspace_id,
                entity_type="session", entity_id=session_id.strip(),
                relation="referenced_in", now=self._clock(),
            )
        if changed:
            self._publish_asset(
                "workspace_asset.created" if created else "workspace_asset.updated",
                workspace_id,
                item,
                session_id=session_id,
                turn_id=turn_id,
            )
        return item

    def link_existing(
        self,
        workspace_id: str,
        asset_id: str,
        *,
        person_id: str,
        session_id: str,
        relation: str = "referenced_in",
    ) -> Asset:
        """Link a trusted existing Asset into another authorized work context."""
        if not self.workspace_store.person_is_linked(workspace_id, person_id.strip()):
            raise PermissionError("Asset Workspace does not belong to the current Person")
        item = self.store.get(asset_id.strip())
        if item is None:
            raise KeyError(asset_id)
        self.store.link(
            item.id, workspace_id,
            entity_type="workspace", entity_id=workspace_id,
            relation="member", now=self._clock(),
        )
        self.store.link(
            item.id, workspace_id,
            entity_type="session", entity_id=session_id.strip(),
            relation=relation.strip() or "referenced_in", now=self._clock(),
        )
        return item

    def link_project_asset(
        self,
        workspace_id: str,
        asset_id: str,
        *,
        person_id: str,
        project_id: str,
        project_asset_id: str,
    ) -> Asset:
        """Relate the unified Asset to its existing Project projection."""
        if not self.workspace_store.person_is_linked(workspace_id, person_id.strip()):
            raise PermissionError("Asset Workspace does not belong to the current Person")
        item = self.store.get(asset_id.strip())
        if item is None or not self.store.is_linked(item.id, workspace_id):
            raise KeyError(asset_id)
        self.store.link(
            item.id, workspace_id,
            entity_type="project", entity_id=project_id.strip(),
            relation="used_by", now=self._clock(),
        )
        self.store.link(
            item.id, workspace_id,
            entity_type="project_asset", entity_id=project_asset_id.strip(),
            relation="projected_as", now=self._clock(),
        )
        return item

    def link_observation(
        self,
        workspace_id: str,
        asset_id: str,
        *,
        person_id: str,
        observation_id: str,
    ) -> Asset:
        """Relate an Asset to the message or source fact that introduced it."""
        item = self.require_for_person(
            asset_id, workspace_id, person_id=person_id,
        )
        self.store.link(
            item.id, workspace_id,
            entity_type="observation", entity_id=observation_id.strip(),
            relation="observed_with", now=self._clock(),
        )
        return item

    def link_materialization(
        self,
        workspace_id: str,
        working_asset_id: str,
        *,
        person_id: str,
        source_asset_id: str,
    ) -> Asset:
        """Record that a working file materializes one external Asset."""
        working = self.require_for_person(
            working_asset_id, workspace_id, person_id=person_id,
        )
        source = self.require_for_person(
            source_asset_id, workspace_id, person_id=person_id,
        )
        if working.nature != "working":
            raise ValueError("Materialized Asset must be a working Asset")
        if source.nature != "external":
            raise ValueError("Materialization source must be an external Asset")
        self.store.link(
            working.id, workspace_id,
            entity_type="asset", entity_id=source.id,
            relation="materialized_from", now=self._clock(),
        )
        self.store.link(
            source.id, workspace_id,
            entity_type="asset", entity_id=working.id,
            relation="materialized_as", now=self._clock(),
        )
        return working

    def preserve_as_evidence(
        self,
        workspace_id: str,
        asset_id: str,
        *,
        person_id: str,
        reason: str,
        session_id: str,
        turn_id: str,
    ) -> Asset:
        """Freeze the current working revision as one immutable evidence Asset."""
        source, content_kind, content_session_id, content_id = self.content_reference(
            asset_id,
            workspace_id,
            person_id=person_id,
        )
        if source.nature != "working":
            raise ValueError("Only a working Asset can be preserved as evidence")
        normalized_reason = reason.strip()
        if not normalized_reason:
            raise ValueError("Evidence reason is required")
        evidence_source_id = f"{source.id}:{source.revision}"
        existing = self.store.get_by_source(
            "asset_evidence_snapshot",
            "",
            evidence_source_id,
        )
        if existing is not None:
            return existing
        metadata = {
            "source_asset_id": source.id,
            "source_revision": source.revision,
            "reason": normalized_reason,
            "captured_by_person_id": person_id.strip(),
            "content_source_kind": (
                "artifact_snapshot" if content_kind == "artifact" else content_kind
            ),
            "content_source_session_id": content_session_id,
            "content_source_id": content_id,
        }
        item, _created, _changed = self.store.upsert(
            nature="evidence",
            name=source.name,
            kind=source.kind,
            mime_type=source.mime_type,
            size=source.size,
            sha256=source.sha256,
            source_type="asset_evidence_snapshot",
            source_id=evidence_source_id,
            source_session_id="",
            locator=f"evidence:{evidence_source_id}",
            metadata=metadata,
            now=self._clock(),
        )
        self.store.link(
            item.id, workspace_id,
            entity_type="workspace", entity_id=workspace_id,
            relation="evidence", now=self._clock(),
        )
        self.store.link(
            item.id, workspace_id,
            entity_type="asset", entity_id=source.id,
            relation="evidence_of", now=self._clock(),
        )
        self._publish_asset(
            "workspace_asset.created",
            workspace_id,
            item,
            session_id=session_id,
            turn_id=turn_id,
        )
        return item

    @staticmethod
    def _normalized_relative_path(artifact: dict[str, Any]) -> str:
        raw = str(artifact.get("relative_path") or "").strip().replace("\\", "/")
        if not raw:
            return ""
        path = PurePosixPath(raw)
        if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
            return ""
        return path.as_posix()

    def list_snapshots(self, workspace_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        return [
            self.snapshot(item)
            for item in self.store.list_for_workspace(workspace_id, limit=limit)
        ]

    def find_by_artifact_reference(
        self,
        source_session_id: str,
        artifact_id: str,
    ) -> Asset | None:
        return self.store.get_by_artifact_reference(
            source_session_id.strip(),
            artifact_id.strip(),
        )

    def content_reference(
        self,
        asset_id: str,
        workspace_id: str,
        *,
        person_id: str,
    ) -> tuple[Asset, str, str, str]:
        """Resolve a Person-visible Asset to its managed content source."""
        item = self.require_for_person(
            asset_id, workspace_id, person_id=person_id,
        )
        if item.nature == "external":
            raise ValueError(
                "External Asset content must be fetched through its source capability"
            )
        if item.source_type == "conversation_attachment":
            return item, "attachment", item.source_session_id, item.source_id
        if item.source_type == "asset_evidence_snapshot":
            content_kind = str(item.metadata.get("content_source_kind") or "")
            content_session_id = str(
                item.metadata.get("content_source_session_id") or "",
            )
            content_id = str(item.metadata.get("content_source_id") or "")
            if not content_kind or not content_session_id or not content_id:
                raise ValueError("Evidence Asset has no immutable content snapshot")
            return item, content_kind, content_session_id, content_id
        artifact_id = str(item.metadata.get("latest_artifact_id") or "").strip()
        source_session_id = str(
            item.metadata.get("latest_artifact_session_id") or "",
        ).strip()
        if not artifact_id and item.source_type == "conversation_artifact":
            artifact_id = item.source_id
            source_session_id = item.source_session_id
        if not artifact_id or not source_session_id:
            raise ValueError("Asset has no readable conversation Artifact snapshot")
        return item, "artifact", source_session_id, artifact_id

    @staticmethod
    def snapshot(item: Asset) -> dict[str, Any]:
        return {
            "id": item.id,
            "nature": item.nature,
            "name": item.name,
            "kind": item.kind,
            "mime_type": item.mime_type,
            "size": item.size,
            "sha256": item.sha256,
            "status": item.status,
            "source_type": item.source_type,
            "source_id": item.source_id,
            "source_session_id": item.source_session_id,
            "locator": item.locator,
            "metadata": item.metadata,
            "revision": item.revision,
            "created_at": item.created_at,
            "updated_at": item.updated_at,
        }

    def _publish_asset(
        self,
        event: str,
        workspace_id: str,
        item: Asset,
        *,
        session_id: str,
        turn_id: str,
    ) -> None:
        if self._publish is None:
            return
        for linked_person_id in self.workspace_store.linked_person_ids(workspace_id):
            payload = self.snapshot(item)
            payload["workspace_id"] = workspace_id
            payload["_target_person_id"] = linked_person_id
            self._publish(event, payload, session_id=session_id, turn_id=turn_id)
