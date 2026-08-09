"""Resolve durable Workspace Assets into sealed tool-call content handles."""

from __future__ import annotations

from pathlib import Path
from typing import Any


class WorkspaceAssetContentResolver:
    """Bridge stable Asset identities to existing managed conversation files.

    The resolver is injected into a tool execution context. Plugins receive a
    trusted local handle only after Workspace membership and Person visibility
    have been checked; public Asset snapshots continue to hide host paths.
    """

    def __init__(self, service: Any, conversation_db: Any, agent_id: str) -> None:
        self._service = service
        self._conversation_db = conversation_db
        self._agent_id = str(agent_id or "default")

    def resolve(
        self,
        asset_id: str,
        *,
        person_id: str,
        session_id: str,
        workspace_id: str = "",
        writable: bool = False,
    ) -> dict[str, Any]:
        resolved_workspace_id = str(workspace_id or "").strip()
        if not resolved_workspace_id:
            resolved_workspace_id = self._service.store.focused_workspace_id(
                str(session_id or "").strip(),
                person_id=str(person_id or "").strip(),
            )
        if not resolved_workspace_id:
            raise ValueError("The current session is not focused on a Workspace")

        item, source_kind, source_session_id, source_id = (
            self._service.assets.content_reference(
                str(asset_id or "").strip(),
                resolved_workspace_id,
                person_id=str(person_id or "").strip(),
            )
        )
        if writable and item.nature != "working":
            raise ValueError("Only a working Asset can be revised")

        if source_kind == "attachment":
            attachment = self._conversation_db.get_attachment_metadata(
                source_session_id,
                source_id,
            )
            if attachment is None:
                raise ValueError("Asset source Attachment no longer exists")
            from xiaomei_brain.gateway.attachments import restore_attachment_refs

            restored, _images = restore_attachment_refs(
                self._agent_id,
                source_session_id,
                [attachment],
            )
            if not restored:
                raise ValueError("Asset source Attachment cannot be restored")
            resolved = dict(restored[0])
            resolved["workspace_asset_id"] = item.id
            resolved["workspace_id"] = resolved_workspace_id
            return resolved

        artifact = self._conversation_db.get_artifact_metadata(
            source_session_id,
            source_id,
        )
        if artifact is None:
            raise ValueError("Asset source Artifact no longer exists")

        from xiaomei_brain.gateway.artifacts import (
            managed_artifact_path,
            stored_artifact_path,
        )

        if source_kind == "artifact_snapshot":
            if writable:
                raise ValueError("An evidence Asset cannot be revised")
            path = stored_artifact_path(self._agent_id, source_session_id, artifact)
        else:
            path = managed_artifact_path(self._agent_id, artifact)
        path = Path(path).resolve(strict=True)
        return {
            "id": item.id,
            "name": item.name or str(artifact.get("name") or path.name),
            "kind": item.kind or str(artifact.get("kind") or "file"),
            "mime_type": item.mime_type or str(artifact.get("mime_type") or ""),
            "size": item.size or path.stat().st_size,
            "local_path": str(path),
            "managed_artifact_path": str(path) if source_kind == "artifact" else "",
            "source_artifact": {
                "artifact_id": source_id,
                "session_id": source_session_id,
                "workspace_asset_id": item.id,
            },
            "workspace_asset_id": item.id,
            "workspace_id": resolved_workspace_id,
        }
