"""Execute one bounded Mission Run inside an already isolated Agent Core."""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Callable

from xiaomei_brain.consciousness.context_pipeline import build_simple_context

from .models import MissionRunStatus, MissionStatus
from .service import MissionService

logger = logging.getLogger(__name__)


class MissionRunner:
    """Advance one durable Mission without owning a thread or long-lived Core."""

    def __init__(
        self,
        service: MissionService,
        consciousness: Any,
        *,
        skill_loader: Any = None,
        send_proactive: Callable[..., bool] | None = None,
    ) -> None:
        self.service = service
        self.consciousness = consciousness
        self.skill_loader = skill_loader
        self.send_proactive = send_proactive

    def execute(
        self,
        mission_id: str,
        runtime: Any,
        *,
        intent_id: str = "",
        cancel_check: Callable[[], bool] | None = None,
        activity_context: Any = None,
    ) -> bool:
        mission = self.service.require(mission_id)
        if mission.status not in (MissionStatus.ACTIVE, MissionStatus.WAITING):
            logger.info("[MissionRunner] Mission cannot enter a Run: %s (%s)", mission.id, mission.status.value)
            return False
        skill = self._load_skill(mission.skill_name)
        runtime_session_id = str(getattr(runtime, "session_id", "") or f"mission:{mission.id}")
        run = self.service.start_run(mission.id, intent_id, runtime_session_id)
        try:
            if activity_context is not None:
                activity_context.report_progress(
                    summary=f"正在推进 Mission：{mission.title}",
                    current_step="mission_run",
                )

            prompt = self._system_prompt(mission, run.id, skill)
            messages = [
                {"role": "system", "content": prompt},
                {
                    "role": "assistant",
                    "content": (
                        "这是一次有边界的自主工作片段。先读取事实和检查点，再决定本次最有价值的行动。"
                        "不要改做其他任务；结束前必须调用 checkpoint_mission。"
                    ),
                },
            ]
            result = runtime.react_nodb(
                messages=messages,
                cancel_check=cancel_check,
                max_steps=50,
                label=f"mission:{mission.id}",
                exp_stream=getattr(runtime, "exp_stream", None),
                summarize=True,
            )
            refreshed = self.service.require(mission.id)
            if refreshed.last_run_at is None or refreshed.last_run_at < run.started_at:
                # The model may finish without calling the checkpoint tool. Do
                # not invent domain progress; preserve only its final report and
                # schedule a later review instead of immediately looping.
                fallback_status = mission.status
                checkpoint_kwargs = {
                    "summary": str(result or "本次 Run 已结束，但未留下结构化检查点")[:1000],
                    "checkpoint": {"unstructured_result": str(result or "")[:4000]},
                    "status": fallback_status,
                    "run_id": run.id,
                }
                if fallback_status == MissionStatus.WAITING:
                    checkpoint_kwargs.update({
                        "next_run_at": None,
                        "waiting_reason": mission.waiting_reason,
                        "waiting_for": list(mission.waiting_for),
                    })
                else:
                    checkpoint_kwargs["next_run_at"] = time.time() + 86400
                refreshed = self.service.checkpoint(mission.id, **checkpoint_kwargs)
            result_summary = str(result or refreshed.progress_summary)[:2000]
            if activity_context is not None:
                activity_context.report_progress(
                    summary=result_summary or f"Mission 已推进：{mission.title}",
                    current_step="completed",
                )
            self.service.finish_run(
                run.id,
                MissionRunStatus.COMPLETED,
                result_summary=result_summary,
                checkpoint=refreshed.checkpoint,
            )
            delivered = self._notify_if_needed(refreshed, str(result or ""))
            if activity_context is not None and delivered is not None:
                activity_context.report_delivery(
                    delivered=delivered,
                    target=(
                        refreshed.origin_session_id
                        or refreshed.accountable_person_id
                    ),
                )
            return True
        except Exception as exc:
            status = MissionRunStatus.INTERRUPTED if cancel_check and cancel_check() else MissionRunStatus.FAILED
            self.service.finish_run(
                run.id,
                status,
                error_message=str(exc),
            )
            # One failed Run is a fact, not permission for a tight retry loop.
            if status == MissionRunStatus.FAILED:
                self.service.store.update_mission(mission.id, next_run_at=time.time() + 3600)
            raise

    def _load_skill(self, skill_name: str) -> dict[str, Any]:
        if self.skill_loader is None:
            raise RuntimeError("Mission Skill loader is unavailable")
        skill = self.skill_loader.view_skill(skill_name)
        if not skill:
            raise RuntimeError(f"Mission Skill is unavailable: {skill_name}")
        self.skill_loader.record_usage(skill_name)
        return skill

    def _system_prompt(self, mission: Any, run_id: str, skill: dict[str, Any]) -> str:
        identity_context = build_simple_context(
            self.consciousness,
            mode="task",
            user_input=mission.objective,
            user_id=mission.accountable_person_id or None,
            session_id=mission.origin_session_id or None,
        )
        recent_events = self.service.store.list_events(mission.id, limit=12)
        event_lines = "\n".join(
            f"- {event.event_type}: {event.summary}" for event in reversed(recent_events)
        ) or "- 暂无历史事件"
        guide = str(skill.get("runtime_content") or skill.get("content") or "")
        return "\n\n".join([
            identity_context,
            "<mission>",
            f"mission_id: {mission.id}",
            f"run_id: {run_id}",
            f"title: {mission.title}",
            f"objective: {mission.objective}",
            f"accountable_person_id: {mission.accountable_person_id or '-'}",
            f"success_criteria: {json.dumps(list(mission.success_criteria), ensure_ascii=False)}",
            f"constraints: {json.dumps(list(mission.constraints), ensure_ascii=False)}",
            f"permissions: {json.dumps(list(mission.permissions), ensure_ascii=False)}",
            f"checkpoint: {json.dumps(mission.checkpoint, ensure_ascii=False)}",
            f"last_progress: {mission.progress_summary or '-'}",
            f"waiting_reason: {mission.waiting_reason or '-'}",
            f"waiting_for: {json.dumps(list(mission.waiting_for), ensure_ascii=False)}",
            "recent_events:",
            event_lines,
            "</mission>",
            "<mission_rules>",
            "- Mission 是长期责任，本次只完成一个真实、有边界的推进片段。",
            "- Skill 是工作方法，不是授权。permissions 未明确允许的对外发布、付费、删除和不可逆操作不得执行。",
            "- 缺少责任人物输入、账号连接、授权、资料或其他外部条件时，不得保持 active 或定时重试；必须用 checkpoint_mission 进入 waiting，并填写 waiting_reason 和 waiting_for。",
            "- 需要系统性学习时，使用 checkpoint_mission 将状态设为 waiting，并在 summary 中写清知识缺口；不要在本 Run 内无限搜索。",
            "- 需要现有学习系统介入时，调用 request_mission_learning；它只产生信号，由 L2 决定是否学习。",
            "- 完成、等待或继续推进都必须调用 checkpoint_mission，保存事实、下一步和下次运行间隔。",
            "</mission_rules>",
            f"<mission_skill name=\"{mission.skill_name}\">\n{guide}\n</mission_skill>",
        ])

    def _notify_if_needed(self, mission: Any, result: str) -> bool | None:
        if self.send_proactive is None or not mission.accountable_person_id:
            return None
        if mission.status not in (MissionStatus.WAITING, MissionStatus.COMPLETED):
            return None
        message = mission.waiting_reason or mission.progress_summary or result
        if not message:
            return None
        try:
            return bool(self.send_proactive(
                message[:2000],
                user_id=mission.accountable_person_id,
                session_id=mission.origin_session_id or None,
            ))
        except Exception:
            logger.exception("[MissionRunner] Failed to notify accountable Person")
            return False
