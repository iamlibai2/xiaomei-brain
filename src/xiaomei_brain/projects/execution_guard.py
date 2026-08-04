"""Project-specific policy for handing sustained work to an Assignment."""

from __future__ import annotations

from typing import Any

from xiaomei_brain.agent.completion import CompletionGuardResult


PROJECT_EXECUTION_FAILURE_MESSAGE = (
    "这个项目仍需要持续执行，但我没有成功建立后台委托。"
    "我已停止用口头计划代替实际执行；请检查 Project、Process 或 Assignment 状态后重试。"
)


class ProjectExecutionCompletionGuard:
    """Require a worker to own Projects marked for sustained delivery."""

    def __init__(self, project_service: Any, process_service: Any, assignment_service: Any) -> None:
        self.project_service = project_service
        self.process_service = process_service
        self.assignment_service = assignment_service

    def __call__(self, runtime: Any, _content: str) -> CompletionGuardResult | None:
        # An isolated Assignment runner already owns the continuation.
        if str(getattr(runtime, "active_assignment_id", "") or "").strip():
            return None
        project_id = str(getattr(runtime, "active_project_id", "") or "").strip()
        if not project_id:
            return None
        project = self.project_service.store.get_project(project_id)
        if project is None or project.status.value != "active":
            return None
        execution = project.metadata.get("execution")
        if not isinstance(execution, dict) or execution.get("assignment_required") is not True:
            return None
        if project.waiting_reason.strip():
            return None

        process_requirement = project.metadata.get("delivery_process")
        if (
            isinstance(process_requirement, dict)
            and process_requirement.get("required") is True
            and self.process_service.store.get_for_project(project_id) is None
        ):
            reason = (
                "用户要求的正式 Process 尚未建立。先查询模板并应用完全匹配的模板；"
                "没有匹配模板时使用 define_project_process。"
            )
        else:
            from xiaomei_brain.assignments.models import TERMINAL_ASSIGNMENT_STATUSES

            assignments = self.assignment_service.store.list_assignments(
                scope_type="project",
                scope_id=project_id,
                limit=20,
            )
            if any(
                item.status not in TERMINAL_ASSIGNMENT_STATUSES
                for item in assignments
            ):
                return None
            reason = (
                "这个 Project 明确要求持续交付，但还没有有效的项目范围 Assignment。"
                "请调用 accept_assignment，把项目目标与 Process 正式结果作为验收标准并 handoff。"
            )
        return CompletionGuardResult(
            key="project.assignment_handoff",
            reason=reason,
            failure_message=PROJECT_EXECUTION_FAILURE_MESSAGE,
        )
