"""Conversation tools for defining and satisfying optional Process contracts."""

from __future__ import annotations

import json
from typing import Any

from xiaomei_brain.projects import ProjectActor, ProjectActorType
from xiaomei_brain.tools.base import tool


def create_process_tools(agent: Any) -> list[Any]:
    def _core():
        return agent._get_agent()

    def _service():
        service = getattr(agent, "process_service", None)
        if service is None:
            service = getattr(_core(), "process_service", None)
        if service is None:
            raise RuntimeError("Process service is not initialized")
        return service

    def _templates():
        registry = getattr(agent, "_process_template_registry", None)
        if registry is None:
            registry = getattr(_core(), "process_template_registry", None)
        if registry is None:
            raise RuntimeError("Process template registry is not initialized")
        return registry

    def _person_actor() -> ProjectActor:
        person_id = str(getattr(_core(), "user_id", "") or "").strip()
        if not person_id or person_id == "global":
            raise ValueError("当前对话没有可验证的人物身份")
        return ProjectActor(ProjectActorType.PERSON, person_id)

    def _agent_actor() -> ProjectActor:
        return ProjectActor(ProjectActorType.AGENT, str(getattr(agent, "id", "agent")))

    def _require_visible_project(project_id: str):
        return _service().project_service.require_project(project_id, actor=_person_actor())

    @tool(
        name="list_project_process_templates",
        description=(
            "列出当前 Agent 已安装的正式交付标准模板。创建 Process 前先查询；"
            "如果用户明确指定阶段数量或标准名称，必须选择完全匹配的模板 ID，不能自行缩减或替换。"
        ),
    )
    def list_project_process_templates(project_id: str = "") -> str:
        project_type = ""
        if project_id.strip():
            project = _require_visible_project(project_id)
            project_type = str(getattr(project, "project_type", "") or "")
        return json.dumps({
            "templates": [
                item.public_dict()
                for item in _templates().list(project_type=project_type)
            ],
        }, ensure_ascii=False)

    @tool(
        name="apply_project_process_template",
        description=(
            "按模板 ID 为 Project 应用一份经过校验的正式交付标准。平台会原样应用模板中的阶段与要求；"
            "不要复制模板 JSON，也不要用 define_project_process 重写已存在的模板。"
        ),
    )
    def apply_project_process_template(project_id: str, template_id: str) -> str:
        project = _require_visible_project(project_id)
        template = _templates().require(template_id)
        project_type = str(getattr(project, "project_type", "") or "")
        if template.project_types and project_type not in template.project_types:
            raise ValueError(
                f"Process template {template.id} does not apply to Project type {project_type}"
            )
        process = _service().define(
            project_id,
            _templates().definition(template.id),
            actor=_agent_actor(),
        )
        return json.dumps(_service().snapshot(process), ensure_ascii=False)

    @tool(
        name="define_project_process",
        description=(
            "仅在没有合适模板时为 Project 自定义交付标准；已有模板必须使用 apply_project_process_template。"
            "Process 只规定正式阶段和每阶段必须提交什么，"
            "不会执行工具或规定 Agent 如何工作。process_json 包含 id、name、ordered 和 stages；"
            "每个阶段可包含 asset/evidence requirements。重新调用可依据用户决定修订标准。"
        ),
    )
    def define_project_process(project_id: str, process_json: str) -> str:
        _require_visible_project(project_id)
        try:
            definition = json.loads(process_json)
        except json.JSONDecodeError as exc:
            raise ValueError("process_json 必须是有效 JSON") from exc
        process = _service().define(project_id, definition, actor=_agent_actor())
        return json.dumps(_service().snapshot(process), ensure_ascii=False)

    @tool(
        name="inspect_project_process",
        description="查看一个 Project 当前采用的正式交付标准、各阶段提交和仍缺少的内容。",
    )
    def inspect_project_process(project_id: str) -> str:
        _require_visible_project(project_id)
        process = _service().require_for_project(project_id, actor=_agent_actor())
        return json.dumps(_service().snapshot(process), ensure_ascii=False)

    @tool(
        name="submit_process_stage",
        description=(
            "向 Project 当前 Process 的一个正式阶段提交结果。submission_json 可包含 summary、"
            "asset_ids 和 evidence。工具只检查 Process 明确声明的完整性，不评价创作质量。"
        ),
    )
    def submit_process_stage(
        project_id: str,
        stage_id: str,
        submission_json: str,
    ) -> str:
        _require_visible_project(project_id)
        try:
            payload = json.loads(submission_json)
        except json.JSONDecodeError as exc:
            raise ValueError("submission_json 必须是有效 JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError("submission_json 必须是 JSON 对象")
        raw_asset_ids = payload.get("asset_ids") or []
        evidence = payload.get("evidence") or {}
        if not isinstance(raw_asset_ids, list) or not isinstance(evidence, dict):
            raise ValueError("asset_ids 必须是数组，evidence 必须是对象")
        submission = _service().submit(
            project_id,
            stage_id,
            actor=_agent_actor(),
            summary=str(payload.get("summary") or ""),
            asset_ids=[str(item) for item in raw_asset_ids],
            evidence=evidence,
        )
        process = _service().require_for_project(project_id, actor=_agent_actor())
        return json.dumps({
            "submission": _service().submission_snapshot(submission),
            "process": _service().snapshot(process),
        }, ensure_ascii=False)

    return [
        list_project_process_templates,
        apply_project_process_template,
        define_project_process,
        inspect_project_process,
        submit_process_stage,
    ]
