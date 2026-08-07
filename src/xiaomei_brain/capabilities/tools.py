"""Agent-facing introspection tools for the capability layer."""

from __future__ import annotations

import json
import time
import uuid
from typing import TYPE_CHECKING, Any

from xiaomei_brain.tools.base import Tool, tool
from xiaomei_brain.tools.execution_context import current_tool_execution

if TYPE_CHECKING:
    from xiaomei_brain.agent.instance import AgentInstance


_STATUS_LABELS = {
    "not_acquired": "未获得",
    "disabled": "已关闭",
    "preparing": "准备中",
    "needs_setup": "需要完善",
    "ready": "可用",
    "degraded": "部分可用",
    "unavailable": "暂不可用",
    "error": "异常",
}

_SECTION_LABELS = {
    "models": "模型",
    "media": "媒体服务",
    "search": "联网搜索",
    "channels": "渠道与绑定",
    "capabilities": "能力",
}


def create_capability_tools(agent: "AgentInstance") -> list[Tool]:
    """Create a truthful business-level capability inspection tool."""

    def current_person_id() -> str:
        """Use the identity sealed into this tool invocation by Agent Core."""
        context = current_tool_execution()
        return str(context.person_id or "").strip() if context is not None else ""

    @tool(
        name="capability_status",
        description=(
            "查询当前 Agent 真正具备的业务能力及其状态。"
            "当用户问你会做什么、某项任务能否完成、为什么某能力不可用，"
            "或任务需要额外配置时使用。不要用插件、Skill、Tool 名称代替业务能力。"
        ),
    )
    def capability_status(query: str = "", capability_id: str = "") -> str:
        """Inspect current capabilities by task description or exact ID."""
        registry = getattr(agent, "_capability_registry", None)
        if registry is None:
            return json.dumps({"error": "能力体系尚未初始化"}, ensure_ascii=False)

        person_id = current_person_id()
        if capability_id.strip():
            view = registry.get(capability_id.strip(), person_id=person_id)
            views = [view] if view is not None else []
        elif query.strip():
            views = registry.resolve(query.strip(), limit=5, person_id=person_id)
        else:
            views = registry.list(person_id=person_id)

        values: list[dict[str, Any]] = []
        for view in views:
            setup = [
                {
                    "label": action.get("label", "前往配置"),
                    "location": f"Agent 设置 > {_SECTION_LABELS.get(action.get('section', ''), action.get('section', ''))}",
                }
                for action in view.actions
                if action.get("section")
            ]
            values.append({
                "id": view.id,
                "name": view.name,
                "status": view.status.value,
                "status_label": _STATUS_LABELS.get(view.status.value, view.status.value),
                "summary": view.summary,
                "available_outcomes": [
                    outcome.name for outcome in view.outcomes if outcome.available
                ],
                "limitations": list(dict.fromkeys(
                    limitation
                    for outcome in view.outcomes
                    for limitation in outcome.limitations
                )),
                "setup": setup,
            })

        return json.dumps({
            "query": query,
            "matched": values,
            "message": "没有找到与该任务匹配的已知能力" if not values else "",
        }, ensure_ascii=False)

    @tool(
        name="request_capability_setup",
        description=(
            "当一个具体任务因为 Agent 的业务能力未配置、未启用或尚未准备好而无法继续时，"
            "在当前 Desktop 会话中展示前往对应设置页的配置卡片。"
            "例如联网搜索服务未配置、媒体服务缺少配置。"
            "仅在任务确实被配置阻塞时使用；查询能力状态时先使用 capability_status。"
        ),
    )
    def request_capability_setup(capability_id: str, reason: str = "") -> str:
        """Publish a session-scoped setup card without changing configuration."""
        registry = getattr(agent, "_capability_registry", None)
        if registry is None:
            return json.dumps({"error": "能力体系尚未初始化"}, ensure_ascii=False)

        person_id = current_person_id()
        view = registry.get(capability_id.strip(), person_id=person_id)
        if view is None:
            return json.dumps({"error": "没有找到该能力"}, ensure_ascii=False)
        if view.status.value in {"ready", "degraded"}:
            return json.dumps({
                "capability_id": view.id,
                "status": view.status.value,
                "message": "该能力当前可用，无需打开配置页",
            }, ensure_ascii=False)
        if view.status.value == "disabled":
            action = {
                "type": "open_settings",
                "section": "capabilities",
                "target": view.id,
                "label": "启用此能力",
            }
        elif view.actions:
            action = dict(view.actions[0])
        else:
            return json.dumps({
                "capability_id": view.id,
                "status": view.status.value,
                "message": "该能力当前不可用，但没有可执行的页面配置入口",
            }, ensure_ascii=False)

        core = agent._get_agent()
        session_id = str(getattr(core, "session_id", "") or "")
        turn_id = str(getattr(core, "turn_id", "") or "")
        user_id = person_id or str(getattr(core, "user_id", "global") or "global")
        source_message_id = next((
            message.get("id")
            for message in reversed(getattr(core, "_last_all_messages", []) or [])
            if message.get("role") == "user" and isinstance(message.get("id"), int)
        ), None)
        living = getattr(agent, "_living", None)
        event_hub = getattr(living, "_event_hub", None)
        if event_hub is None or not session_id:
            return json.dumps({
                "capability_id": view.id,
                "status": view.status.value,
                "message": "当前入口无法展示配置卡片",
                "setup": action,
            }, ensure_ascii=False)

        request_id = f"capability-setup-{uuid.uuid4().hex}"
        payload = {
            "id": request_id,
            "kind": "capability_setup",
            "capability_id": view.id,
            "capability_name": view.name,
            "capability_status": view.status.value,
            "summary": reason.strip() or f"{view.name}尚未准备好，完成配置后即可继续使用。",
            "session_id": session_id,
            "turn_id": turn_id,
            "user_id": user_id,
            "action": action,
            "source_message_id": source_message_id,
            "resume_status": "pending" if source_message_id is not None else "unavailable",
            "created_at": time.time(),
        }
        db = getattr(agent, "conversation_db", None)
        if db is not None and source_message_id is not None:
            db.update_message_metadata(source_message_id, {
                "capability_blocked": {
                    "active": True,
                    "capability_id": view.id,
                    "request_id": request_id,
                    "blocked_at": payload["created_at"],
                },
            })
        event_hub.publish(
            "capability.setup.requested",
            payload,
            session_id=session_id,
            turn_id=turn_id,
        )
        return json.dumps({
            "capability_id": view.id,
            "status": view.status.value,
            "message": "已在当前 Desktop 会话中展示配置入口",
            "request_id": request_id,
        }, ensure_ascii=False)

    return [capability_status, request_capability_setup]
