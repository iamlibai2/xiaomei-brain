"""Policy and mutation boundary for Agent-local Projects."""

from __future__ import annotations

import hashlib
import mimetypes
import shutil
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .models import (
    InvalidProjectTransition,
    Project,
    ProjectActor,
    ProjectActorType,
    ProjectAsset,
    ProjectAssetRole,
    ProjectAssetStatus,
    ProjectResource,
    ProjectRuntimeContext,
    ProjectSession,
    ProjectStatus,
    ProjectStep,
    ProjectStepStatus,
    WorkspaceKind,
    validate_project_transition,
)
from xiaomei_brain.media import probe_media_facts
from .store import ProjectStore, new_project_asset_id, new_project_id
from .workspace import ProjectWorkspaceManager

PublishCallback = Callable[[str, dict[str, Any]], None]
ScopeAccess = Callable[[ProjectActor, str, str], bool]
CompletionGuard = Callable[[str], str | None]


def _deep_merge_dict(
    current: dict[str, Any],
    updates: dict[str, Any],
) -> dict[str, Any]:
    """Merge nested Project metadata without dropping sibling facts."""
    merged = dict(current)
    for key, value in updates.items():
        existing = merged.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            merged[key] = _deep_merge_dict(existing, value)
        else:
            merged[key] = value
    return merged


class ProjectPermissionError(PermissionError):
    """The verified actor cannot inspect or mutate this Project."""


class ProjectService:
    """Only public write boundary for Project state."""

    def __init__(
        self,
        store: ProjectStore,
        workspace: ProjectWorkspaceManager,
        *,
        scope_access: ScopeAccess | None = None,
        publish: PublishCallback | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.store = store
        self.workspace = workspace
        self._scope_access = scope_access
        self._publish = publish
        self._clock = clock
        self._completion_guard: CompletionGuard | None = None

    def set_completion_guard(self, guard: CompletionGuard | None) -> None:
        """Attach an external delivery constraint without coupling domains."""
        self._completion_guard = guard

    def create(
        self,
        *,
        name: str,
        project_type: str,
        actor: ProjectActor,
        scope_type: str,
        scope_id: str,
        summary: str = "",
        workspace_kind: WorkspaceKind = WorkspaceKind.MANAGED,
        workspace_uri: str = "",
        metadata: dict[str, Any] | None = None,
        project_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> Project:
        name = name.strip()
        project_type = project_type.strip()
        scope_type = scope_type.strip()
        scope_id = scope_id.strip()
        if not name or not project_type:
            raise ValueError("Project name and type cannot be empty")
        if not scope_type or not scope_id:
            raise ValueError("Project scope cannot be empty")
        self._require_scope_access(actor, scope_type, scope_id)
        if idempotency_key:
            existing = self.store.get_project_by_idempotency(idempotency_key)
            if existing is not None:
                self._require_scope_access(
                    actor, existing.scope_type, existing.scope_id,
                )
                return existing
        identifier = (project_id or new_project_id()).strip()
        prepared = self.workspace.prepare(
            identifier, kind=workspace_kind, workspace_uri=workspace_uri,
        )
        now = self._clock()
        project = Project(
            id=identifier, name=name, summary=summary.strip(),
            project_type=project_type, status=ProjectStatus.ACTIVE,
            scope_type=scope_type, scope_id=scope_id,
            created_by_type=actor.actor_type, created_by_id=actor.actor_id,
            workspace_kind=workspace_kind,
            workspace_uri=(str(prepared.work_root) if prepared.work_root else ""),
            state_root=str(prepared.state_root), progress_summary="",
            current_step_id="", waiting_reason="", metadata=dict(metadata or {}),
            revision=1, created_at=now, updated_at=now, completed_at=None,
        )
        created = self.store.create_project(
            project, actor=actor, idempotency_key=idempotency_key,
        )
        self._publish_snapshot(created, event="project.created")
        return created

    def require_project(self, project_id: str, *, actor: ProjectActor) -> Project:
        project = self.store.get_project(project_id)
        if project is None:
            raise KeyError(project_id)
        self._require_scope_access(actor, project.scope_type, project.scope_id)
        return project

    def list_for_actor(
        self,
        *,
        actor: ProjectActor,
        status: ProjectStatus | None = None,
        limit: int = 100,
    ) -> list[Project]:
        if actor.actor_type in {ProjectActorType.AGENT, ProjectActorType.SYSTEM}:
            return self.store.list_projects(status=status, limit=limit)
        projects = self.store.list_projects(status=status, limit=min(limit * 3, 500))
        visible: list[Project] = []
        for project in projects:
            try:
                self._require_scope_access(
                    actor, project.scope_type, project.scope_id,
                )
            except ProjectPermissionError:
                continue
            visible.append(project)
            if len(visible) >= limit:
                break
        return visible

    def update(
        self,
        project_id: str,
        *,
        actor: ProjectActor,
        expected_revision: int | None = None,
        name: str | None = None,
        summary: str | None = None,
        progress_summary: str | None = None,
        current_step_id: str | None = None,
        waiting_reason: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Project:
        current = self.require_project(project_id, actor=actor)
        updates: dict[str, Any] = {}
        for key, value in {
            "name": name,
            "summary": summary,
            "progress_summary": progress_summary,
            "current_step_id": current_step_id,
            "waiting_reason": waiting_reason,
        }.items():
            if value is not None:
                normalized = value.strip()
                if key == "name" and not normalized:
                    raise ValueError("Project name cannot be empty")
                updates[key] = normalized
        if metadata is not None:
            updates["metadata_json"] = _deep_merge_dict(
                dict(current.metadata),
                metadata,
            )
        if not updates:
            return current
        changed = self.store.mutate_project(
            project_id, actor=actor, event_type="updated", updates=updates,
            expected_revision=expected_revision, now=self._clock(),
        )
        self._publish_snapshot(changed)
        return changed

    def transition(
        self,
        project_id: str,
        target: ProjectStatus,
        *,
        actor: ProjectActor,
        expected_revision: int | None = None,
        reason: str = "",
    ) -> Project:
        current = self.require_project(project_id, actor=actor)
        validate_project_transition(current.status, target)
        if target is ProjectStatus.COMPLETED and self._completion_guard is not None:
            blocker = self._completion_guard(project_id)
            if blocker:
                raise InvalidProjectTransition(blocker)
        now = self._clock()
        changed = self.store.mutate_project(
            project_id, actor=actor, event_type=f"status.{target.value}",
            updates={
                "status": target,
                "waiting_reason": "",
                "current_step_id": (
                    "" if target is ProjectStatus.COMPLETED
                    else current.current_step_id
                ),
                "completed_at": now if target is ProjectStatus.COMPLETED else None,
            },
            expected_revision=expected_revision,
            payload={"from": current.status.value, "to": target.value,
                     "reason": reason.strip()},
            now=now,
        )
        self._publish_snapshot(changed)
        return changed

    def record_review(
        self,
        project_id: str,
        *,
        actor: ProjectActor,
        assessment: str,
        step_updates: list[dict[str, Any]],
        plan_changes: list[str] | None = None,
        deviations: list[str] | None = None,
        metadata_updates: dict[str, Any] | None = None,
        next_action: str = "",
        progress_summary: str | None = None,
        current_step_id: str | None = None,
        waiting_reason: str | None = None,
    ) -> Project:
        """Persist one Agent-led reflection without prescribing execution order."""
        current = self.require_project(project_id, actor=actor)
        normalized_assessment = assessment.strip()
        if not normalized_assessment:
            raise ValueError("Project review assessment cannot be empty")
        now = self._clock()
        metadata = dict(current.metadata)
        previous_review = metadata.get("last_review")
        if not isinstance(previous_review, dict):
            previous_review = {}

        def _review_list(value: list[str] | None, key: str) -> list[str]:
            source = previous_review.get(key, []) if value is None else value
            if not isinstance(source, list):
                return []
            return [str(item).strip() for item in source if str(item).strip()]

        effective_plan_changes = _review_list(plan_changes, "plan_changes")
        effective_deviations = _review_list(deviations, "deviations")
        review = {
            "assessment": normalized_assessment,
            "step_updates": [dict(item) for item in step_updates],
            "plan_changes": effective_plan_changes,
            "deviations": effective_deviations,
            "next_action": next_action.strip(),
            "reviewed_at": now,
        }
        if metadata_updates:
            metadata = _deep_merge_dict(metadata, metadata_updates)
            review["metadata_updates"] = dict(metadata_updates)
        metadata["last_review"] = review
        updates: dict[str, Any] = {"metadata_json": metadata}
        if progress_summary is not None:
            updates["progress_summary"] = progress_summary.strip()
        if current_step_id is not None:
            updates["current_step_id"] = current_step_id.strip()
        if waiting_reason is not None:
            updates["waiting_reason"] = waiting_reason.strip()
        changed = self.store.mutate_project(
            project_id,
            actor=actor,
            event_type="reviewed",
            updates=updates,
            payload=review,
            now=now,
        )
        self._publish_snapshot(changed)
        return changed

    def put_step(
        self,
        project_id: str,
        *,
        actor: ProjectActor,
        step_id: str,
        title: str,
        status: ProjectStepStatus = ProjectStepStatus.PENDING,
        parent_step_id: str | None = None,
        position: int = 0,
        summary: str = "",
        completed_units: int | None = None,
        total_units: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ProjectStep:
        self.require_project(project_id, actor=actor)
        existing = {step.step_id: step for step in self.store.list_steps(project_id)}
        previous = existing.get(step_id)
        if not step_id.strip() or not title.strip():
            raise ValueError("Project step id and title cannot be empty")
        if total_units is not None and total_units < 0:
            raise ValueError("total_units cannot be negative")
        if completed_units is not None and completed_units < 0:
            raise ValueError("completed_units cannot be negative")
        step = ProjectStep(
            project_id=project_id, step_id=step_id.strip(),
            parent_step_id=parent_step_id, title=title.strip(), position=position,
            status=status, summary=summary.strip(), completed_units=completed_units,
            total_units=total_units, metadata=dict(metadata or {}),
            updated_at=self._clock(),
        )
        saved = self.store.upsert_step(step)
        changed = self.store.record_event(
            project_id,
            actor=actor,
            event_type="step.updated" if previous else "step.created",
            payload={
                "step_id": step.step_id,
                "title": step.title,
                "status": step.status.value,
            },
            now=step.updated_at,
        )
        self._publish_snapshot(changed)
        return saved

    def remove_step(
        self,
        project_id: str,
        step_id: str,
        *,
        actor: ProjectActor,
        reason: str = "",
    ) -> bool:
        """Remove one item from the Agent's adjustable Project map."""
        project = self.require_project(project_id, actor=actor)
        normalized = step_id.strip()
        if not normalized:
            raise ValueError("Project step id cannot be empty")
        existing = self.get_step(project_id, normalized, actor=actor)
        if existing is None:
            return False
        self.store.delete_step(project_id, normalized)
        updates = {
            "current_step_id": "",
        } if project.current_step_id == normalized else {}
        changed = self.store.mutate_project(
            project_id,
            actor=actor,
            event_type="step.removed",
            updates=updates,
            payload={
                "step_id": normalized,
                "title": existing.title,
                "reason": reason.strip(),
            },
            now=self._clock(),
        )
        self._publish_snapshot(changed)
        return True

    def get_step(
        self,
        project_id: str,
        step_id: str,
        *,
        actor: ProjectActor,
    ) -> ProjectStep | None:
        """Return one visible durable step without exposing the persistence store."""
        self.require_project(project_id, actor=actor)
        normalized = step_id.strip()
        return next(
            (
                step for step in self.store.list_steps(project_id)
                if step.step_id == normalized
            ),
            None,
        )

    def register_asset(
        self,
        project_id: str,
        *,
        actor: ProjectActor,
        relative_uri: str,
        role: ProjectAssetRole,
        kind: str,
        name: str = "",
        source_type: str = "",
        source_id: str = "",
        producer: str = "",
        provider: str = "",
        model: str = "",
        parent_asset_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ProjectAsset:
        project = self.require_project(project_id, actor=actor)
        path = self.workspace.resolve_asset_path(project.state_root, relative_uri)
        if not path.is_file():
            raise FileNotFoundError(path)
        mime_type = mimetypes.guess_type(path.name)[0] or ""
        asset_metadata = dict(metadata or {})
        # Objective probe results take precedence over caller-provided media
        # claims. This makes Process evidence independent from the code path
        # that produced or delivered the file.
        asset_metadata.update(probe_media_facts(path, mime_type))
        now = self._clock()
        asset = ProjectAsset(
            id=new_project_asset_id(), project_id=project_id, role=role,
            kind=kind.strip() or "file", name=name.strip() or path.name,
            relative_uri=path.relative_to(Path(project.state_root)).as_posix(),
            mime_type=mime_type,
            size=path.stat().st_size, sha256=self._sha256(path),
            status=ProjectAssetStatus.AVAILABLE,
            source_type=source_type.strip(), source_id=source_id.strip(),
            producer=producer.strip(), provider=provider.strip(), model=model.strip(),
            parent_asset_id=parent_asset_id, metadata=asset_metadata,
            created_at=now, updated_at=now,
        )
        saved = self.store.register_asset(asset)
        changed = self.store.record_event(
            project_id,
            actor=actor,
            event_type="asset.registered",
            payload={
                "asset_id": asset.id,
                "role": asset.role.value,
                "kind": asset.kind,
                "name": asset.name,
            },
            now=now,
        )
        self._publish_snapshot(changed)
        return saved

    def import_delivered_asset(
        self,
        project_id: str,
        *,
        actor: ProjectActor,
        source_path: str | Path,
        kind: str = "file",
        name: str = "",
        source_id: str = "",
        producer: str = "present_artifacts",
    ) -> ProjectAsset:
        """Adopt one explicitly delivered Agent file into a Project.

        Conversation artifacts may originate in the Agent workspace rather
        than the Project workspace.  The Project keeps its own durable copy so
        its asset list still identifies the actual final deliverable.
        """
        project = self.require_project(project_id, actor=actor)
        source = Path(source_path).expanduser().resolve(strict=True)
        if not source.is_file():
            raise FileNotFoundError(source)
        digest = self._sha256(source)
        existing_assets = self.store.list_assets(project_id)
        for existing in existing_assets:
            if (
                existing.status is ProjectAssetStatus.AVAILABLE
                and existing.role is ProjectAssetRole.DELIVERABLE
                and existing.sha256 == digest
            ):
                return existing

        safe_name = Path(name.strip() or source.name).name
        deliverables = Path(project.state_root) / "deliverables"
        deliverables.mkdir(parents=True, exist_ok=True)
        target = deliverables / safe_name
        logical_asset = next((
            existing for existing in existing_assets
            if existing.status is ProjectAssetStatus.AVAILABLE
            and existing.role is ProjectAssetRole.DELIVERABLE
            and existing.source_type == "conversation_artifact"
            and existing.producer == producer
            and (
                existing.metadata.get("logical_name") == safe_name
                or existing.name == safe_name
            )
        ), None)
        try:
            source.relative_to(Path(project.state_root).resolve())
            target = source
        except ValueError:
            if source != target:
                shutil.copy2(source, target)

        if logical_asset is not None:
            mime_type = mimetypes.guess_type(target.name)[0] or ""
            metadata = {
                **logical_asset.metadata,
                "presented": True,
                "logical_name": safe_name,
            }
            metadata.update(probe_media_facts(target, mime_type))
            now = self._clock()
            updated = ProjectAsset(
                id=logical_asset.id,
                project_id=project_id,
                role=ProjectAssetRole.DELIVERABLE,
                kind=kind.strip() or "file",
                name=target.name,
                relative_uri=target.relative_to(Path(project.state_root)).as_posix(),
                mime_type=mime_type,
                size=target.stat().st_size,
                sha256=digest,
                status=ProjectAssetStatus.AVAILABLE,
                source_type="conversation_artifact",
                source_id=source_id.strip(),
                producer=producer.strip(),
                provider=logical_asset.provider,
                model=logical_asset.model,
                parent_asset_id=logical_asset.parent_asset_id,
                metadata=metadata,
                created_at=logical_asset.created_at,
                updated_at=now,
            )
            saved = self.store.update_asset(updated)
            changed = self.store.record_event(
                project_id,
                actor=actor,
                event_type="asset.updated",
                payload={
                    "asset_id": saved.id,
                    "role": saved.role.value,
                    "kind": saved.kind,
                    "name": saved.name,
                },
                now=now,
            )
            self._publish_snapshot(changed)
            return saved

        return self.register_asset(
            project_id,
            actor=actor,
            relative_uri=target.relative_to(Path(project.state_root)).as_posix(),
            role=ProjectAssetRole.DELIVERABLE,
            kind=kind,
            name=target.name,
            source_type="conversation_artifact",
            source_id=source_id,
            producer=producer,
            metadata={"presented": True, "logical_name": safe_name},
        )

    def link_resource(
        self,
        project_id: str,
        *,
        actor: ProjectActor,
        resource_type: str,
        resource_key: str,
        relation: str,
        metadata: dict[str, Any] | None = None,
    ) -> ProjectResource:
        self.require_project(project_id, actor=actor)
        if not all(value.strip() for value in (resource_type, resource_key, relation)):
            raise ValueError("Project resource fields cannot be empty")
        resource = ProjectResource(
            project_id=project_id, resource_type=resource_type.strip(),
            resource_key=resource_key.strip(), relation=relation.strip(),
            metadata=dict(metadata or {}), created_at=self._clock(),
        )
        saved = self.store.link_resource(resource)
        changed = self.store.record_event(
            project_id,
            actor=actor,
            event_type="resource.linked",
            payload={
                "resource_type": resource.resource_type,
                "resource_key": resource.resource_key,
                "relation": resource.relation,
            },
            now=resource.created_at,
        )
        self._publish_snapshot(changed)
        return saved

    def bind_session(
        self,
        session_id: str,
        project_id: str,
        *,
        actor: ProjectActor,
    ) -> ProjectSession:
        self.require_project(project_id, actor=actor)
        if not session_id.strip():
            raise ValueError("session_id cannot be empty")
        now = self._clock()
        previous = self.store.get_session_binding(session_id)
        binding = ProjectSession(
            session_id=session_id.strip(), project_id=project_id,
            bound_by_type=actor.actor_type, bound_by_id=actor.actor_id,
            created_at=previous.created_at if previous else now, updated_at=now,
        )
        saved = self.store.bind_session(binding)
        changed = self.store.record_event(
            project_id,
            actor=actor,
            event_type="session.bound",
            payload={"session_id": binding.session_id},
            now=now,
        )
        self._publish_snapshot(changed)
        return saved

    def runtime_context(
        self,
        project_id: str,
        *,
        actor: ProjectActor,
        active_assignment_id: str = "",
    ) -> ProjectRuntimeContext:
        project = self.require_project(project_id, actor=actor)
        return ProjectRuntimeContext(
            project_id=project.id, project_type=project.project_type,
            scope_type=project.scope_type, scope_id=project.scope_id,
            workspace_kind=project.workspace_kind, state_root=project.state_root,
            work_root=project.workspace_uri,
            active_assignment_id=active_assignment_id,
            allowed_asset_ids=tuple(
                asset.id for asset in self.store.list_assets(project_id)
                if asset.status is ProjectAssetStatus.AVAILABLE
            ),
        )

    def _require_scope_access(
        self,
        actor: ProjectActor,
        scope_type: str,
        scope_id: str,
    ) -> None:
        if actor.actor_type in {ProjectActorType.AGENT, ProjectActorType.SYSTEM}:
            return
        if scope_type == "person" and scope_id == actor.actor_id:
            return
        if self._scope_access and self._scope_access(actor, scope_type, scope_id):
            return
        raise ProjectPermissionError(
            f"Actor {actor.actor_id} cannot access {scope_type}:{scope_id}",
        )

    def _publish_snapshot(
        self,
        project: Project,
        *,
        event: str = "project.updated",
    ) -> None:
        if self._publish:
            payload = self.public_snapshot(project)
            if project.scope_type == "person":
                payload["_target_person_id"] = project.scope_id
            self._publish(event, payload)

    @staticmethod
    def public_snapshot(project: Project) -> dict[str, Any]:
        return {
            "id": project.id, "name": project.name,
            "summary": project.summary, "project_type": project.project_type,
            "status": project.status.value, "scope_type": project.scope_type,
            "scope_id": project.scope_id,
            "workspace_kind": project.workspace_kind.value,
            "progress_summary": project.progress_summary,
            "current_step_id": project.current_step_id,
            "waiting_reason": project.waiting_reason,
            "revision": project.revision, "created_at": project.created_at,
            "updated_at": project.updated_at,
            "completed_at": project.completed_at,
        }

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as file:
            for chunk in iter(lambda: file.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
