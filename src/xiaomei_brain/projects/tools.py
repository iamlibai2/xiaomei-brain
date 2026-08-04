"""Conversation tools for managing durable Projects through dialogue."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Literal

from xiaomei_brain.tools.base import Tool, tool

from .models import (
    ProjectActor,
    ProjectActorType,
    ProjectStatus,
    ProjectStepStatus,
    WorkspaceKind,
)


_PROCESS_TOOL_NAMES = [
    "list_project_process_templates",
    "apply_project_process_template",
    "define_project_process",
    "inspect_project_process",
    "submit_process_stage",
    "accept_assignment",
]
_DELIVERY_STANDARD_PATTERN = re.compile(
    r"(?:(?P<count>\d{1,2}|[一二三四五六七八九十两]{1,4})\s*个?\s*阶段(?:的)?\s*)?"
    r"(?:正式)?交付标准",
)
_DELIVERY_STANDARD_NEGATIONS = ("不需要", "不要", "无需", "取消", "不使用")


def _chinese_number(value: str) -> int | None:
    if value.isdigit():
        number = int(value)
        return number if number > 0 else None
    digits = {
        "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
        "六": 6, "七": 7, "八": 8, "九": 9,
    }
    if value == "十":
        return 10
    if "十" in value:
        left, right = value.split("十", 1)
        tens = digits.get(left, 1) if left else 1
        ones = digits.get(right, 0) if right else 0
        return tens * 10 + ones
    return digits.get(value)


def _message_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    return "\n".join(
        str(item.get("text") or "").strip()
        for item in content
        if isinstance(item, dict) and item.get("type") in {"text", "input_text"}
    ).strip()


def _delivery_process_requirement(core: Any, *fallbacks: str) -> dict[str, Any] | None:
    """Capture an explicit user-requested delivery standard as Project state."""
    texts: list[str] = []
    messages = getattr(core, "_last_all_messages", None)
    if isinstance(messages, list):
        for message in reversed(messages):
            if not isinstance(message, dict) or message.get("role") != "user":
                continue
            text = _message_text(message.get("content"))
            if text:
                texts.append(text)
            if len(texts) >= 8:
                break
    texts.extend(str(item).strip() for item in fallbacks if str(item).strip())

    for text in texts:
        for match in _DELIVERY_STANDARD_PATTERN.finditer(text):
            prefix = text[max(0, match.start() - 8):match.start()]
            if any(negation in prefix for negation in _DELIVERY_STANDARD_NEGATIONS):
                continue
            raw_count = str(match.group("count") or "")
            return {
                "required": True,
                "requested_stage_count": _chinese_number(raw_count) if raw_count else None,
                "request": match.group(0),
            }
    return None


def create_project_tools(agent: Any = None) -> list[Tool]:
    """Create tools that resolve verified identity and services at call time."""

    def _core() -> Any:
        if agent is None:
            raise RuntimeError("Agent is not initialized")
        return agent._get_agent()

    def _service() -> Any:
        service = getattr(agent, "project_service", None)
        if service is None:
            service = getattr(_core(), "project_service", None)
        if service is None:
            raise RuntimeError("Project service is not initialized")
        return service

    def _person_actor() -> ProjectActor:
        person_id = str(getattr(_core(), "user_id", "")).strip()
        if not person_id or person_id in {"global", "system"}:
            raise ValueError("当前对话尚未识别到人物，不能访问人物项目")
        return ProjectActor(ProjectActorType.PERSON, person_id)

    def _agent_actor() -> ProjectActor:
        agent_id = str(getattr(agent, "id", "")).strip()
        if not agent_id:
            raise RuntimeError("Agent identity is unavailable")
        return ProjectActor(ProjectActorType.AGENT, agent_id)

    def _session_id() -> str:
        return str(getattr(_core(), "session_id", "")).strip()

    def _set_active(project_id: str) -> None:
        core = _core()
        core.active_project_id = project_id
        core.project_context = _service().runtime_context(
            project_id, actor=_agent_actor(),
        )

    def _snapshot(project: Any, *, details: bool = False) -> dict[str, Any]:
        value = _service().public_snapshot(project)
        process_requirement = project.metadata.get("delivery_process")
        if isinstance(process_requirement, dict) and process_requirement.get("required") is True:
            value["process_requirement"] = {
                "required": True,
                "requested_stage_count": process_requirement.get("requested_stage_count"),
                "status": "must_define_before_project_steps",
            }
        execution_requirement = project.metadata.get("execution")
        if isinstance(execution_requirement, dict) and execution_requirement.get("assignment_required") is True:
            value["execution_requirement"] = {
                "assignment_required": True,
                "status": "must_handoff_to_project_assignment",
            }
        if details:
            value["steps"] = [
                {
                    "step_id": step.step_id,
                    "parent_step_id": step.parent_step_id,
                    "title": step.title,
                    "position": step.position,
                    "status": step.status.value,
                    "summary": step.summary,
                    "completed_units": step.completed_units,
                    "total_units": step.total_units,
                }
                for step in _service().store.list_steps(project.id)
            ]
            value["assets"] = [
                {
                    "id": asset.id,
                    "role": asset.role.value,
                    "kind": asset.kind,
                    "name": asset.name,
                    "status": asset.status.value,
                    "size": asset.size,
                    "mime_type": asset.mime_type,
                }
                for asset in _service().store.list_assets(project.id)
            ]
            value["resources"] = [
                {
                    "resource_type": resource.resource_type,
                    "resource_key": resource.resource_key,
                    "relation": resource.relation,
                }
                for resource in _service().store.list_resources(project.id)
            ]
        return value

    def _require_declared_process(project_id: str) -> None:
        project = _service().require_project(project_id, actor=_person_actor())
        requirement = project.metadata.get("delivery_process")
        if not isinstance(requirement, dict) or requirement.get("required") is not True:
            return
        process_service = getattr(agent, "process_service", None)
        if process_service is None:
            process_service = getattr(_core(), "process_service", None)
        process = (
            process_service.store.get_for_project(project_id)
            if process_service is not None
            else None
        )
        if process is not None:
            return
        count = requirement.get("requested_stage_count")
        count_text = f"{count} 阶段" if count else ""
        raise ValueError(
            f"用户明确要求{count_text}正式交付标准，但当前 Project 尚未建立 Process。"
            "请先调用 list_project_process_templates；有完全匹配的模板时使用 "
            "apply_project_process_template，否则使用 define_project_process。"
            "ProjectStep 只是 Agent 的工作地图，不能代替 Process。"
        )

    def _workspace_kind(value: str, workspace_uri: str) -> WorkspaceKind:
        normalized = value.strip().lower().replace("-", "_")
        if normalized in {item.value for item in WorkspaceKind}:
            return WorkspaceKind(normalized)
        if normalized in {"external", "external_directory", "linked_directory"}:
            return WorkspaceKind.LINKED
        if normalized in {"remote", "logical", "memory", "none"}:
            return WorkspaceKind.VIRTUAL
        # Model-generated labels such as local/filesystem/video describe what
        # the workspace is for, not a different persistence policy. Without
        # an explicitly linked directory they all safely mean Agent-managed.
        managed_aliases = {
            "", "local", "filesystem", "git", "directory",
            "agent_workspace", "workspace", "video", "disk", "standard",
            "asset_library", "project", "default",
        }
        if normalized in managed_aliases:
            if workspace_uri.strip() and normalized in {
                "local", "filesystem", "git", "directory",
            }:
                return WorkspaceKind.LINKED
            return WorkspaceKind.MANAGED
        if not workspace_uri.strip():
            return WorkspaceKind.MANAGED
        raise ValueError(
            "workspace_kind must be managed, linked, or virtual",
        )

    def _set_step_desired(
        project_id: str,
        *,
        step_id: str,
        title: str = "",
        status: str = "",
        position: int = -1,
        summary: str = "",
        completed_units: int = -1,
        total_units: int = -1,
        parent_step_id: str = "",
    ):
        """Apply an Agent's current judgment through legal local transitions."""
        service = _service()
        existing = service.get_step(project_id, step_id, actor=_person_actor())
        resolved_title = title.strip() or (existing.title if existing else "")
        if not resolved_title:
            raise ValueError("创建新的项目阶段时必须提供 title")
        target_status = (
            ProjectStepStatus(status.strip().lower())
            if status.strip()
            else (existing.status if existing else ProjectStepStatus.PENDING)
        )
        resolved_position = (
            position if position >= 0 else (existing.position if existing else 0)
        )
        resolved_summary = summary if summary else (existing.summary if existing else "")
        resolved_completed = (
            completed_units if completed_units >= 0
            else (existing.completed_units if existing else None)
        )
        resolved_total = (
            total_units if total_units >= 0
            else (existing.total_units if existing else None)
        )
        resolved_parent = (
            parent_step_id.strip() or (existing.parent_step_id if existing else None)
        )
        actor = _agent_actor()

        if (
            existing is not None
            and existing.title == resolved_title
            and existing.status is target_status
            and existing.position == resolved_position
            and existing.summary == resolved_summary
            and existing.completed_units == resolved_completed
            and existing.total_units == resolved_total
            and existing.parent_step_id == resolved_parent
        ):
            return existing

        return service.put_step(
            project_id,
            actor=actor,
            step_id=step_id,
            title=resolved_title,
            status=target_status,
            position=resolved_position,
            summary=resolved_summary,
            completed_units=resolved_completed,
            total_units=resolved_total,
            parent_step_id=resolved_parent,
        )

    @tool(
        name="create_project",
        description=(
            "为需要跨多轮对话、多个委托或多份工作资产的持续工作创建项目。"
            "项目只是工作容器，不会代替委托执行任务；一次性问答不要创建项目。"
            "workspace_kind 只能是 managed、linked、virtual；通常省略并使用 managed。"
        ),
    )
    def create_project(
        name: str,
        project_type: str,
        summary: str = "",
        workspace_kind: Literal["managed", "linked", "virtual"] = "managed",
        workspace_uri: str = "",
    ) -> str:
        person = _person_actor()
        core = _core()
        turn_id = str(getattr(core, "turn_id", "")).strip()
        digest = hashlib.sha256(
            f"{person.actor_id}\0{turn_id}\0{name.strip()}".encode("utf-8"),
        ).hexdigest()[:24]
        process_requirement = _delivery_process_requirement(core, name, summary)
        project = _service().create(
            name=name,
            project_type=project_type,
            summary=summary,
            actor=_agent_actor(),
            scope_type="person",
            scope_id=person.actor_id,
            workspace_kind=_workspace_kind(workspace_kind, workspace_uri),
            workspace_uri=workspace_uri,
            metadata=(
                {
                    "delivery_process": process_requirement,
                    "execution": {
                        "assignment_required": True,
                        "reason": "explicit_delivery_standard",
                    },
                }
                if process_requirement is not None
                else None
            ),
            idempotency_key=(f"project-create:{digest}" if turn_id else None),
        )
        if process_requirement is not None:
            dynamic_loader = getattr(core, "_dynamic_loader", None)
            activate = getattr(dynamic_loader, "activate_required_tools", None)
            if callable(activate):
                activate(_PROCESS_TOOL_NAMES)
        session_id = _session_id()
        if session_id:
            _service().bind_session(session_id, project.id, actor=_agent_actor())
            project = _service().require_project(project.id, actor=_agent_actor())
        _set_active(project.id)
        return json.dumps(_snapshot(project), ensure_ascii=False)

    @tool(
        name="list_projects",
        description="列出当前人物可见的项目，可按 active、completed 或 discontinued 状态筛选。",
    )
    def list_projects(status: str = "all", limit: int = 20) -> str:
        normalized = status.strip().lower()
        status_filter = None if normalized in {"", "all"} else ProjectStatus(normalized)
        projects = _service().list_for_actor(
            actor=_person_actor(), status=status_filter, limit=limit,
        )
        return json.dumps(
            [_snapshot(project) for project in projects], ensure_ascii=False,
        )

    @tool(
        name="inspect_project",
        description="查看一个项目的状态、阶段、工作资产和所关联资源。",
    )
    def inspect_project(project_id: str) -> str:
        project = _service().require_project(project_id, actor=_person_actor())
        return json.dumps(_snapshot(project, details=True), ensure_ascii=False)

    @tool(
        name="update_project",
        description=(
            "更新项目名称、说明、进度、等待原因或生命周期状态。"
            "状态只允许 active、completed、discontinued。"
        ),
    )
    def update_project(
        project_id: str,
        name: str = "",
        summary: str = "",
        progress_summary: str = "",
        current_step_id: str = "",
        waiting_reason: str = "",
        status: str = "",
    ) -> str:
        service = _service()
        person = _person_actor()
        current = service.require_project(project_id, actor=person)
        fields = {
            "name": name or None,
            "summary": summary or None,
            "progress_summary": progress_summary or None,
            "current_step_id": current_step_id or None,
            "waiting_reason": waiting_reason or None,
        }
        if status.strip() and status.strip().lower() != current.status.value:
            current = service.transition(
                project_id, ProjectStatus(status.strip().lower()),
                actor=_agent_actor(), expected_revision=current.revision,
                reason=waiting_reason,
            )
        if any(value is not None for value in fields.values()):
            current = service.update(
                project_id, actor=_agent_actor(),
                expected_revision=current.revision, **fields,
            )
        _set_active(project_id)
        return json.dumps(_snapshot(current), ensure_ascii=False)

    @tool(
        name="set_project_step",
        description=(
            "新增或更新项目的持久阶段。适合分镜、素材、合成、审阅等跨执行仍需保留的里程碑，"
            "不是某次工具调用的临时步骤。创建新阶段时必须提供 title；更新已有阶段时只需提供 "
            "project_id、step_id 和要改变的字段。阶段是可调整的认知地图，可直接修正状态、标题和顺序。"
        ),
    )
    def set_project_step(
        project_id: str,
        step_id: str,
        title: str = "",
        status: Literal[
            "pending", "running", "waiting_review",
            "completed", "needs_revision", "skipped",
        ] = "",
        position: int = -1,
        summary: str = "",
        completed_units: int = -1,
        total_units: int = -1,
        parent_step_id: str = "",
    ) -> str:
        _require_declared_process(project_id)
        step = _set_step_desired(
            project_id,
            step_id=step_id,
            title=title,
            status=status,
            position=position,
            summary=summary,
            completed_units=completed_units,
            total_units=total_units,
            parent_step_id=parent_step_id,
        )
        _set_active(project_id)
        return json.dumps({
            "project_id": step.project_id,
            "step_id": step.step_id,
            "title": step.title,
            "status": step.status.value,
            "summary": step.summary,
            "completed_units": step.completed_units,
            "total_units": step.total_units,
        }, ensure_ascii=False)

    @tool(
        name="remove_project_step",
        description=(
            "从项目认知地图中移除已经不适合当前计划的阶段。适合计划合并、删减或重构；"
            "这不是将未完成工作伪装为完成，需提供简短原因。"
        ),
    )
    def remove_project_step(
        project_id: str,
        step_id: str,
        reason: str = "",
    ) -> str:
        removed = _service().remove_step(
            project_id,
            step_id,
            actor=_agent_actor(),
            reason=reason,
        )
        _set_active(project_id)
        return json.dumps({
            "project_id": project_id,
            "step_id": step_id,
            "removed": removed,
        }, ensure_ascii=False)

    @tool(
        name="review_project",
        description=(
            "对当前项目做一次由 Agent 主导的阶段性复盘，不是固定工作流审批。"
            "适合在方案形成、计划改变、候选交付、用户确认或要求修改后使用。"
            "根据真实工具结果和用户决定，一次性校准阶段状态、偏差、下一步和等待原因；"
            "可以重新判断已有阶段，但不能把没有证据的工作写成已完成。"
            "必须区分技术检查、模型视觉检查和用户观看确认；没有实际观看证据时，"
            "不得声称已经看过或完成视觉验收。"
            "计划结构本身改变时，使用 set_project_step 或 remove_project_step 调整认知地图。"
            "review_json 必须是 JSON 对象，包含 assessment；可包含 progress_summary、"
            "current_step_id、waiting_reason、next_action、plan_changes、deviations、"
            "metadata_updates 和 steps。metadata_updates 用于同步时长等已经改变的项目事实。"
            "steps 是数组，每项包含 step_id、status，可选 summary/reason。"
        ),
    )
    def review_project(project_id: str, review_json: str) -> str:
        service = _service()
        project = service.require_project(project_id, actor=_person_actor())
        try:
            review = json.loads(review_json)
        except json.JSONDecodeError as exc:
            raise ValueError("review_json 必须是有效的 JSON 对象") from exc
        if not isinstance(review, dict):
            raise ValueError("review_json 必须是 JSON 对象")
        assessment = str(review.get("assessment") or "").strip()
        if not assessment:
            raise ValueError("项目复盘必须提供 assessment")

        raw_steps = review.get("steps") or []
        if not isinstance(raw_steps, list):
            raise ValueError("review_json.steps 必须是数组")
        existing_steps = {
            step.step_id: step for step in service.store.list_steps(project_id)
        }
        decisions: list[dict[str, Any]] = []
        for raw in raw_steps:
            if not isinstance(raw, dict):
                raise ValueError("review_json.steps 的每一项必须是对象")
            step_id = str(raw.get("step_id") or "").strip()
            if step_id not in existing_steps:
                raise ValueError(f"项目中不存在阶段: {step_id or '<empty>'}")
            before = existing_steps[step_id]
            target = str(raw.get("status") or before.status.value).strip()
            reason = str(raw.get("reason") or "").strip()
            summary = str(raw.get("summary") or "").strip() or reason
            saved = _set_step_desired(
                project_id,
                step_id=step_id,
                status=target,
                summary=summary,
            )
            decisions.append({
                "step_id": step_id,
                "from": before.status.value,
                "to": saved.status.value,
                "summary": saved.summary,
                "reason": reason,
            })

        def _string_list(key: str) -> list[str] | None:
            if key not in review:
                return None
            value = review.get(key) or []
            if not isinstance(value, list):
                raise ValueError(f"review_json.{key} 必须是数组")
            return [str(item).strip() for item in value if str(item).strip()]

        plan_changes = _string_list("plan_changes")
        deviations = _string_list("deviations")
        metadata_updates = review.get("metadata_updates")
        if metadata_updates is not None and not isinstance(metadata_updates, dict):
            raise ValueError("review_json.metadata_updates 必须是对象")
        next_action = str(review.get("next_action") or "").strip()
        progress_summary = str(
            review.get("progress_summary") or assessment,
        ).strip()
        current_step_id = (
            str(review.get("current_step_id") or "").strip()
            if "current_step_id" in review else project.current_step_id
        )
        if current_step_id and current_step_id not in existing_steps:
            raise ValueError(f"项目中不存在当前阶段: {current_step_id}")
        waiting_reason = (
            str(review.get("waiting_reason") or "").strip()
            if "waiting_reason" in review else project.waiting_reason
        )
        updated = service.record_review(
            project_id,
            actor=_agent_actor(),
            assessment=assessment,
            step_updates=decisions,
            plan_changes=plan_changes,
            deviations=deviations,
            metadata_updates=metadata_updates,
            next_action=next_action,
            progress_summary=progress_summary,
            current_step_id=current_step_id,
            waiting_reason=waiting_reason,
        )
        _set_active(project_id)
        saved_review = updated.metadata.get("last_review")
        if not isinstance(saved_review, dict):
            saved_review = {}
        return json.dumps({
            "project": _snapshot(updated),
            "review": {
                "assessment": assessment,
                "step_updates": decisions,
                "plan_changes": saved_review.get("plan_changes", []),
                "deviations": saved_review.get("deviations", []),
                "next_action": next_action,
                "metadata_updates": metadata_updates or {},
            },
        }, ensure_ascii=False)

    @tool(
        name="use_project",
        description="将当前会话切换到一个已有项目，使后续委托和产物可以归入该项目。",
    )
    def use_project(project_id: str) -> str:
        project = _service().require_project(project_id, actor=_person_actor())
        session_id = _session_id()
        if not session_id:
            raise ValueError("当前对话没有可绑定的 session_id")
        _service().bind_session(session_id, project.id, actor=_agent_actor())
        _set_active(project.id)
        return json.dumps(_snapshot(project), ensure_ascii=False)

    return [
        create_project,
        list_projects,
        inspect_project,
        update_project,
        set_project_step,
        remove_project_step,
        review_project,
        use_project,
    ]
