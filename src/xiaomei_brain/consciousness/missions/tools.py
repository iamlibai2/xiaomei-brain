"""Conversation and Run tools for managing durable Missions."""

from __future__ import annotations

import json
import time
from typing import Any

from xiaomei_brain.tools.base import Tool
from xiaomei_brain.tools.execution_context import current_tool_execution

from .models import MissionStatus
from .service import MissionService


def _context_identity() -> tuple[str, str, str]:
    context = current_tool_execution()
    if context is None:
        return "", "", ""
    return context.person_id, context.session_id, context.turn_id


def _list_value(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            parsed = value.splitlines()
        return _list_value(parsed)
    return []


def create_mission_tools(service: MissionService) -> list[Tool]:
    def create_mission(**kwargs: Any) -> dict[str, Any]:
        person_id, session_id, turn_id = _context_identity()
        mission = service.create(
            title=kwargs.get("title", ""),
            objective=kwargs.get("objective", ""),
            accountable_person_id=person_id,
            origin_session_id=session_id,
            origin_turn_id=turn_id,
            skill_name=kwargs.get("skill_name", ""),
            success_criteria=_list_value(kwargs.get("success_criteria")),
            constraints=_list_value(kwargs.get("constraints")),
            permissions=_list_value(kwargs.get("permissions")),
            priority=float(kwargs.get("priority", 0.5)),
            created_by="agent",
            activate=bool(kwargs.get("activate", False)),
        )
        return {"ok": True, "mission": mission.to_dict()}

    def list_missions(**kwargs: Any) -> dict[str, Any]:
        missions = service.list(str(kwargs.get("status") or ""), int(kwargs.get("limit", 20)))
        return {"missions": [mission.to_dict() for mission in missions], "count": len(missions)}

    def get_mission(**kwargs: Any) -> dict[str, Any]:
        mission = service.require(str(kwargs.get("mission_id") or ""))
        events = service.store.list_events(mission.id, limit=int(kwargs.get("event_limit", 20)))
        return {
            "mission": mission.to_dict(),
            "events": [event.__dict__ for event in events],
        }

    def update_mission(**kwargs: Any) -> dict[str, Any]:
        changes: dict[str, Any] = {}
        for name in ("title", "objective", "skill_name"):
            if name in kwargs and kwargs[name] is not None:
                changes[name] = kwargs[name]
        if "priority" in kwargs and kwargs["priority"] is not None:
            changes["priority"] = float(kwargs["priority"])
        for name in ("success_criteria", "constraints", "permissions"):
            if name in kwargs and kwargs[name] is not None:
                changes[name] = _list_value(kwargs[name])
        mission = service.update_definition(str(kwargs.get("mission_id") or ""), **changes)
        return {"ok": True, "mission": mission.to_dict()}

    def control_mission(**kwargs: Any) -> dict[str, Any]:
        action = str(kwargs.get("action") or "").strip().lower()
        targets = {
            "activate": MissionStatus.ACTIVE,
            "resume": MissionStatus.ACTIVE,
            "pause": MissionStatus.PAUSED,
            "wait": MissionStatus.WAITING,
            "complete": MissionStatus.COMPLETED,
            "stop": MissionStatus.STOPPED,
        }
        if action not in targets:
            raise ValueError(f"Unsupported Mission action: {action}")
        mission = service.transition(
            str(kwargs.get("mission_id") or ""),
            targets[action],
            reason=str(kwargs.get("reason") or ""),
            waiting_for=kwargs.get("waiting_for"),
        )
        return {"ok": True, "mission": mission.to_dict()}

    def checkpoint_mission(**kwargs: Any) -> dict[str, Any]:
        delay = kwargs.get("next_run_in_seconds")
        next_run_at = time.time() + max(60, int(delay)) if delay is not None else None
        checkpoint = kwargs.get("checkpoint") or {}
        if isinstance(checkpoint, str):
            try:
                checkpoint = json.loads(checkpoint)
            except json.JSONDecodeError:
                checkpoint = {"notes": checkpoint}
        mission = service.checkpoint(
            str(kwargs.get("mission_id") or ""),
            summary=str(kwargs.get("summary") or ""),
            checkpoint=checkpoint if isinstance(checkpoint, dict) else {},
            next_run_at=next_run_at,
            status=str(kwargs.get("status") or "active"),
            waiting_reason=str(kwargs.get("waiting_reason") or ""),
            waiting_for=kwargs.get("waiting_for"),
            run_id=str(kwargs.get("run_id") or ""),
        )
        return {"ok": True, "mission": mission.to_dict()}

    def request_mission_learning(**kwargs: Any) -> dict[str, Any]:
        mission = service.request_learning(
            str(kwargs.get("mission_id") or ""),
            topic=str(kwargs.get("topic") or ""),
            reason=str(kwargs.get("reason") or ""),
            run_id=str(kwargs.get("run_id") or ""),
        )
        return {"ok": True, "mission": mission.to_dict(), "signal": "mission_learning_needed"}

    return [
        Tool(
            name="create_mission",
            description="创建一个需要跨多次自主行动持续推进的 Mission。默认进入 preparing；只有目标、边界、成功标准和全局 Skill 指南已经明确时才 activate。",
            parameters={"type": "object", "properties": {
                "title": {"type": "string"}, "objective": {"type": "string"},
                "skill_name": {"type": "string"},
                "success_criteria": {"type": "array", "items": {"type": "string"}},
                "constraints": {"type": "array", "items": {"type": "string"}},
                "permissions": {"type": "array", "items": {"type": "string"}},
                "priority": {"type": "number", "minimum": 0, "maximum": 1, "default": 0.5},
                "activate": {"type": "boolean", "default": False},
            }, "required": ["title", "objective"]}, func=create_mission,
            optional=True, category="mission",
        ),
        Tool(
            name="list_missions", description="列出 Agent 的长期 Mission。",
            parameters={"type": "object", "properties": {
                "status": {"type": "string", "enum": ["", *[item.value for item in MissionStatus]]},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20},
            }}, func=list_missions, optional=True, category="mission",
        ),
        Tool(
            name="get_mission", description="读取一个 Mission 的定义、检查点和最近事实事件。",
            parameters={"type": "object", "properties": {
                "mission_id": {"type": "string"},
                "event_limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20},
            }, "required": ["mission_id"]}, func=get_mission, optional=True, category="mission",
        ),
        Tool(
            name="update_mission", description="更新 Mission 的目标、成功标准、边界或绑定的全局 Skill 作业指南。",
            parameters={"type": "object", "properties": {
                "mission_id": {"type": "string"}, "title": {"type": "string"},
                "objective": {"type": "string"}, "skill_name": {"type": "string"},
                "success_criteria": {"type": "array", "items": {"type": "string"}},
                "constraints": {"type": "array", "items": {"type": "string"}},
                "permissions": {"type": "array", "items": {"type": "string"}},
                "priority": {"type": "number", "minimum": 0, "maximum": 1},
            }, "required": ["mission_id"]}, func=update_mission, optional=True, category="mission",
        ),
        Tool(
            name="control_mission", description="激活、恢复、暂停、等待、完成或停止 Mission。等待时必须说明原因和所需条件；恢复表示这些条件已经满足。激活前必须已绑定可用的全局 Skill。",
            parameters={"type": "object", "properties": {
                "mission_id": {"type": "string"},
                "action": {"type": "string", "enum": ["activate", "resume", "pause", "wait", "complete", "stop"]},
                "reason": {"type": "string"},
                "waiting_for": {"type": "array", "items": {
                    "type": "object", "properties": {
                        "type": {"type": "string"},
                        "key": {"type": "string"},
                        "description": {"type": "string"},
                    }, "required": ["type", "key", "description"],
                }},
            }, "required": ["mission_id", "action"]}, func=control_mission, optional=True, category="mission",
        ),
        Tool(
            name="checkpoint_mission", description="Mission Run 结束前保存真实进展、结构化检查点和状态。缺少人物输入、授权、资料或外部条件时必须设为 waiting，并填写 waiting_reason 和 waiting_for；waiting 不能设置下次运行时间。",
            parameters={"type": "object", "properties": {
                "mission_id": {"type": "string"}, "run_id": {"type": "string"},
                "summary": {"type": "string"}, "checkpoint": {"type": "object"},
                "status": {"type": "string", "enum": ["active", "waiting", "completed", "stopped"]},
                "waiting_reason": {"type": "string"},
                "waiting_for": {"type": "array", "items": {
                    "type": "object", "properties": {
                        "type": {"type": "string"},
                        "key": {"type": "string"},
                        "description": {"type": "string"},
                    }, "required": ["type", "key", "description"],
                }},
                "next_run_in_seconds": {"type": "integer", "minimum": 60},
            }, "required": ["mission_id", "summary", "status"]},
            func=checkpoint_mission, optional=True, category="mission",
        ),
        Tool(
            name="request_mission_learning",
            description="Mission 遇到需要系统学习后才能继续的知识缺口时，记录学习信号并让 Mission 等待。它不会直接启动学习；L2 将统一决定是否产生 LEARN 意图。",
            parameters={"type": "object", "properties": {
                "mission_id": {"type": "string"}, "run_id": {"type": "string"},
                "topic": {"type": "string"}, "reason": {"type": "string"},
            }, "required": ["mission_id", "topic", "reason"]},
            func=request_mission_learning, optional=True, category="mission",
        ),
    ]
