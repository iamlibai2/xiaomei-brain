"""Validation boundary for user-selected Project delivery standards."""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from typing import Any

from xiaomei_brain.projects import (
    ProjectActor,
    ProjectAssetRole,
    ProjectAssetStatus,
    ProjectService,
)

from .models import (
    ProcessInstance,
    ProcessStage,
    ProcessStatus,
    ProcessSubmission,
)
from .store import ProcessStore, new_process_id

PublishCallback = Callable[[str, dict[str, Any]], None]
_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


class ProcessDefinitionError(ValueError):
    pass


def normalize_process_definition(definition: dict[str, Any]) -> dict[str, Any]:
    """Validate a Process definition and return its canonical representation."""
    if not isinstance(definition, dict):
        raise ProcessDefinitionError("Process definition must be an object")
    definition_id = str(definition.get("id") or "custom").strip()
    name = str(definition.get("name") or "").strip()
    if not _ID_PATTERN.fullmatch(definition_id) or not name:
        raise ProcessDefinitionError("Process id or name is invalid")
    raw_stages = definition.get("stages")
    if not isinstance(raw_stages, list) or not 1 <= len(raw_stages) <= 30:
        raise ProcessDefinitionError("Process must define 1 to 30 stages")
    stages = []
    seen = set()
    for position, raw in enumerate(raw_stages, start=1):
        if not isinstance(raw, dict):
            raise ProcessDefinitionError(f"Stage {position} must be an object")
        stage_id = str(raw.get("id") or "").strip()
        title = str(raw.get("title") or "").strip()
        if not _ID_PATTERN.fullmatch(stage_id) or not title or stage_id in seen:
            raise ProcessDefinitionError(f"Stage {position} has an invalid or duplicate id/title")
        seen.add(stage_id)
        raw_requirements = raw.get("requirements") or []
        if not isinstance(raw_requirements, list) or len(raw_requirements) > 20:
            raise ProcessDefinitionError(f"Stage {stage_id} requirements are invalid")
        requirements = []
        for index, requirement in enumerate(raw_requirements, start=1):
            if not isinstance(requirement, dict):
                raise ProcessDefinitionError(f"Stage {stage_id} requirement {index} is invalid")
            requirement_type = str(requirement.get("type") or "").strip()
            normalized = {
                "id": str(requirement.get("id") or f"requirement-{index}"),
                "label": str(requirement.get("label") or "").strip(),
                "type": requirement_type,
            }
            if requirement_type == "asset":
                kind = str(requirement.get("kind") or "").strip()
                if not kind:
                    raise ProcessDefinitionError(f"Stage {stage_id} asset requirement needs kind")
                normalized["kind"] = kind
                role = str(requirement.get("role") or "").strip()
                if role:
                    if role not in {item.value for item in ProjectAssetRole}:
                        raise ProcessDefinitionError(
                            f"Stage {stage_id} asset requirement has invalid role"
                        )
                    normalized["role"] = role
            elif requirement_type == "evidence":
                key = str(requirement.get("key") or "").strip()
                if not key:
                    raise ProcessDefinitionError(f"Stage {stage_id} evidence requirement needs key")
                normalized["key"] = key
                if requirement.get("from_asset") is True:
                    normalized["from_asset"] = True
                if "equals" in requirement:
                    normalized["equals"] = requirement["equals"]
            else:
                raise ProcessDefinitionError(
                    f"Stage {stage_id} requirement type must be asset or evidence"
                )
            requirements.append(normalized)
        stages.append(ProcessStage(
            stage_id=stage_id,
            title=title,
            position=int(raw.get("position") or position),
            required=raw.get("required") is not False,
            requirements=tuple(requirements),
        ))
    return {
        "id": definition_id,
        "name": name,
        "ordered": definition.get("ordered") is True,
        "stages": tuple(sorted(stages, key=lambda item: (item.position, item.stage_id))),
    }


class ProcessService:
    def __init__(
        self,
        store: ProcessStore,
        project_service: ProjectService,
        *,
        publish: PublishCallback | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.store = store
        self.project_service = project_service
        self._publish = publish
        self._clock = clock

    def define(
        self,
        project_id: str,
        definition: dict[str, Any],
        *,
        actor: ProjectActor,
    ) -> ProcessInstance:
        self.project_service.require_project(project_id, actor=actor)
        normalized = normalize_process_definition(definition)
        existing = self.store.get_for_project(project_id)
        now = self._clock()
        process = ProcessInstance(
            id=existing.id if existing else new_process_id(),
            project_id=project_id,
            definition_id=normalized["id"],
            name=normalized["name"],
            ordered=normalized["ordered"],
            status=ProcessStatus.ACTIVE,
            stages=normalized["stages"],
            revision=(existing.revision + 1 if existing else 1),
            created_at=(existing.created_at if existing else now),
            updated_at=now,
            satisfied_at=None,
        )
        saved = self.store.put_process(process)
        saved = self._revalidate_submissions(saved, actor=actor)
        self._publish_snapshot(saved)
        return saved

    def require_for_project(
        self,
        project_id: str,
        *,
        actor: ProjectActor,
    ) -> ProcessInstance:
        self.project_service.require_project(project_id, actor=actor)
        process = self.store.get_for_project(project_id)
        if process is None:
            raise KeyError(f"Project has no Process: {project_id}")
        return process

    def completion_blocker(self, project_id: str) -> str | None:
        """Explain why a Project with a live Process cannot be completed."""
        process = self.store.get_for_project(project_id)
        project = self.project_service.store.get_project(project_id)
        requirement = project.metadata.get("delivery_process") if project else None
        if (
            process is None
            and isinstance(requirement, dict)
            and requirement.get("required") is True
        ):
            count = requirement.get("requested_stage_count")
            count_text = f"{count} 阶段" if count else ""
            return (
                f"Project 要求{count_text}正式交付标准，但尚未建立 Process，"
                "不能标记为 completed"
            )
        if process is None or process.status in {
            ProcessStatus.SATISFIED,
            ProcessStatus.ABANDONED,
        }:
            return None
        missing = [
            stage["title"]
            for stage in self.snapshot(process)["stages"]
            if stage["required"] and stage["status"] != "satisfied"
        ]
        detail = "、".join(missing) if missing else "正式提交"
        return (
            f"Project 的 Process 尚未满足，不能标记为 completed；"
            f"仍需提交：{detail}"
        )

    def submit(
        self,
        project_id: str,
        stage_id: str,
        *,
        actor: ProjectActor,
        summary: str = "",
        asset_ids: list[str] | None = None,
        evidence: dict[str, Any] | None = None,
    ) -> ProcessSubmission:
        process = self.require_for_project(project_id, actor=actor)
        if process.status is ProcessStatus.ABANDONED:
            raise ValueError("Process has been abandoned")
        stage = next(
            (item for item in process.stages if item.stage_id == stage_id.strip()),
            None,
        )
        if stage is None:
            raise KeyError(f"Unknown Process stage: {stage_id}")
        existing_submissions = {
            item.stage_id: item for item in self.store.list_submissions(process.id)
        }
        if process.ordered:
            blockers = [
                item.title for item in process.stages
                if item.position < stage.position
                and item.required
                and not existing_submissions.get(item.stage_id, None)
            ]
            blockers.extend(
                item.title for item in process.stages
                if item.position < stage.position
                and item.required
                and existing_submissions.get(item.stage_id) is not None
                and not existing_submissions[item.stage_id].complete
            )
            if blockers:
                raise ValueError("Ordered Process has unfinished earlier stages: " + ", ".join(blockers))

        selected_ids = tuple(dict.fromkeys(
            str(item).strip() for item in (asset_ids or []) if str(item).strip()
        ))
        available_assets = {
            item.id: item
            for item in self.project_service.store.list_assets(project_id)
            if item.status is ProjectAssetStatus.AVAILABLE
        }
        unknown = [item for item in selected_ids if item not in available_assets]
        if unknown:
            raise ValueError("Submission references unavailable Project assets: " + ", ".join(unknown))
        facts = dict(evidence or {})
        missing = self._missing_requirements(
            stage,
            selected_assets=[available_assets[item] for item in selected_ids],
            evidence=facts,
            summary=summary,
        )
        now = self._clock()
        previous = existing_submissions.get(stage.stage_id)
        submission = ProcessSubmission(
            process_id=process.id,
            stage_id=stage.stage_id,
            summary=summary.strip(),
            asset_ids=selected_ids,
            evidence=facts,
            complete=not missing,
            missing=tuple(missing),
            submitted_by_type=actor.actor_type.value,
            submitted_by_id=actor.actor_id,
            created_at=previous.created_at if previous else now,
            updated_at=now,
        )
        saved = self.store.put_submission(submission)
        refreshed = self._refresh_status(process)
        self._publish_snapshot(refreshed)
        return saved

    def snapshot(self, process: ProcessInstance) -> dict[str, Any]:
        submissions = {
            item.stage_id: item for item in self.store.list_submissions(process.id)
        }
        stages = []
        for stage in process.stages:
            submission = submissions.get(stage.stage_id)
            stages.append({
                "id": stage.stage_id,
                "title": stage.title,
                "position": stage.position,
                "required": stage.required,
                "requirements": [dict(item) for item in stage.requirements],
                "status": (
                    "satisfied" if submission and submission.complete
                    else "incomplete" if submission
                    else "pending"
                ),
                "submission": self.submission_snapshot(submission) if submission else None,
            })
        return {
            "id": process.id,
            "project_id": process.project_id,
            "definition_id": process.definition_id,
            "name": process.name,
            "ordered": process.ordered,
            "status": process.status.value,
            "revision": process.revision,
            "stages": stages,
            "created_at": process.created_at,
            "updated_at": process.updated_at,
            "satisfied_at": process.satisfied_at,
        }

    @staticmethod
    def submission_snapshot(submission: ProcessSubmission) -> dict[str, Any]:
        return {
            "summary": submission.summary,
            "asset_ids": list(submission.asset_ids),
            "evidence": dict(submission.evidence),
            "complete": submission.complete,
            "missing": list(submission.missing),
            "updated_at": submission.updated_at,
        }

    def _refresh_status(self, process: ProcessInstance) -> ProcessInstance:
        submissions = {
            item.stage_id: item for item in self.store.list_submissions(process.id)
        }
        satisfied = all(
            not stage.required
            or (
                stage.stage_id in submissions
                and submissions[stage.stage_id].complete
            )
            for stage in process.stages
        )
        target = ProcessStatus.SATISFIED if satisfied else ProcessStatus.ACTIVE
        if process.status is target:
            return process
        now = self._clock()
        changed = ProcessInstance(
            **{
                **process.__dict__,
                "status": target,
                "revision": process.revision + 1,
                "updated_at": now,
                "satisfied_at": now if satisfied else None,
            }
        )
        return self.store.put_process(changed)

    def _revalidate_submissions(
        self,
        process: ProcessInstance,
        *,
        actor: ProjectActor,
    ) -> ProcessInstance:
        """Recheck durable submissions when the user revises a Process."""
        self.project_service.require_project(process.project_id, actor=actor)
        available_assets = {
            item.id: item
            for item in self.project_service.store.list_assets(process.project_id)
            if item.status is ProjectAssetStatus.AVAILABLE
        }
        stages = {item.stage_id: item for item in process.stages}
        for submission in self.store.list_submissions(process.id):
            stage = stages.get(submission.stage_id)
            if stage is None:
                continue
            selected = [
                available_assets[item]
                for item in submission.asset_ids
                if item in available_assets
            ]
            missing = self._missing_requirements(
                stage,
                selected_assets=selected,
                evidence=submission.evidence,
                summary=submission.summary,
            )
            if submission.complete == (not missing) and submission.missing == tuple(missing):
                continue
            self.store.put_submission(ProcessSubmission(
                **{
                    **submission.__dict__,
                    "complete": not missing,
                    "missing": tuple(missing),
                    "updated_at": self._clock(),
                }
            ))
        return self._refresh_status(process)

    @staticmethod
    def _missing_requirements(
        stage: ProcessStage,
        *,
        selected_assets: list[Any],
        evidence: dict[str, Any],
        summary: str,
    ) -> list[str]:
        if not stage.requirements:
            return [] if summary.strip() or selected_assets or evidence else ["提交说明或结果"]
        missing = []
        for requirement in stage.requirements:
            label = str(requirement.get("label") or requirement.get("id") or "未命名要求")
            requirement_type = requirement["type"]
            if requirement_type == "asset":
                kind = requirement["kind"]
                role = str(requirement.get("role") or "")
                if not any(
                    asset.kind == kind
                    and (not role or asset.role.value == role)
                    for asset in selected_assets
                ):
                    missing.append(label)
                continue
            key = requirement["key"]
            if requirement.get("from_asset") is True:
                asset_values = [
                    asset.metadata[key]
                    for asset in selected_assets
                    if key in asset.metadata
                ]
                if not asset_values:
                    missing.append(label)
                elif (
                    "equals" in requirement
                    and not any(value == requirement["equals"] for value in asset_values)
                ):
                    missing.append(f"{label}（期望 {requirement['equals']!r}）")
                continue
            if key not in evidence:
                missing.append(label)
            elif "equals" in requirement and evidence[key] != requirement["equals"]:
                missing.append(f"{label}（期望 {requirement['equals']!r}）")
        return missing

    def _publish_snapshot(self, process: ProcessInstance) -> None:
        if self._publish is not None:
            payload = {"process": self.snapshot(process)}
            project = self.project_service.store.get_project(process.project_id)
            if project is not None and project.scope_type == "person":
                payload["_target_person_id"] = project.scope_id
            self._publish("process.updated", payload)
