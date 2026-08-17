"""Application service for the autonomous Mission domain."""

from __future__ import annotations

import time
from typing import Any, Callable

from .models import Mission, MissionRunStatus, MissionStatus
from .store import MissionStore


class InvalidMissionTransition(ValueError):
    pass


_ALLOWED_TRANSITIONS: dict[MissionStatus, frozenset[MissionStatus]] = {
    MissionStatus.PREPARING: frozenset({MissionStatus.ACTIVE, MissionStatus.PAUSED, MissionStatus.STOPPED}),
    MissionStatus.ACTIVE: frozenset({MissionStatus.WAITING, MissionStatus.PAUSED, MissionStatus.COMPLETED, MissionStatus.STOPPED}),
    MissionStatus.WAITING: frozenset({MissionStatus.ACTIVE, MissionStatus.PAUSED, MissionStatus.COMPLETED, MissionStatus.STOPPED}),
    MissionStatus.PAUSED: frozenset({MissionStatus.ACTIVE, MissionStatus.STOPPED}),
    MissionStatus.COMPLETED: frozenset(),
    MissionStatus.STOPPED: frozenset(),
}


class MissionService:
    def __init__(
        self,
        store: MissionStore,
        *,
        skill_exists: Callable[[str], bool] | None = None,
    ) -> None:
        self.store = store
        self._skill_exists = skill_exists or (lambda name: bool(name))

    def create(
        self,
        *,
        title: str,
        objective: str,
        accountable_person_id: str = "",
        origin_session_id: str = "",
        origin_turn_id: str = "",
        skill_name: str = "",
        success_criteria: list[str] | tuple[str, ...] = (),
        constraints: list[str] | tuple[str, ...] = (),
        permissions: list[str] | tuple[str, ...] = (),
        priority: float = 0.5,
        created_by: str = "agent",
        activate: bool = False,
    ) -> Mission:
        title = str(title or "").strip()
        objective = str(objective or "").strip()
        skill_name = str(skill_name or "").strip()
        if not title:
            raise ValueError("Mission title cannot be empty")
        if not objective:
            raise ValueError("Mission objective cannot be empty")
        if activate:
            self._require_skill(skill_name)
        status = MissionStatus.ACTIVE if activate else MissionStatus.PREPARING
        mission = self.store.create_mission({
            "title": title,
            "objective": objective,
            "status": status.value,
            "priority": max(0.0, min(float(priority), 1.0)),
            "accountable_person_id": str(accountable_person_id or ""),
            "origin_session_id": str(origin_session_id or ""),
            "origin_turn_id": str(origin_turn_id or ""),
            "skill_name": skill_name,
            "success_criteria": self._clean_list(success_criteria),
            "constraints": self._clean_list(constraints),
            "permissions": self._clean_list(permissions),
            "next_run_at": time.time() if activate else None,
            "created_by": str(created_by or "agent"),
            "progress_summary": "等待完善作业指南和行动边界" if not activate else "等待首次自主推进",
        })
        self.store.add_event(
            mission.id,
            "created",
            "Mission 已创建" if activate else "Mission 已创建，等待讨论和激活",
            details={"created_by": mission.created_by, "status": status.value},
        )
        return mission

    def require(self, mission_id: str) -> Mission:
        return self.store.require_mission(str(mission_id or "").strip())

    def list(self, status: str = "", limit: int = 100) -> list[Mission]:
        if status:
            status = MissionStatus(status).value
        return self.store.list_missions(status=status, limit=limit)

    def update_definition(self, mission_id: str, **changes: Any) -> Mission:
        mission = self.require(mission_id)
        if mission.is_terminal:
            raise InvalidMissionTransition("A completed or stopped Mission cannot be edited")
        allowed = {
            "title", "objective", "priority", "skill_name",
            "success_criteria", "constraints", "permissions",
        }
        cleaned = {key: value for key, value in changes.items() if key in allowed and value is not None}
        for key in ("success_criteria", "constraints", "permissions"):
            if key in cleaned:
                cleaned[key] = self._clean_list(cleaned[key])
        if "skill_name" in cleaned:
            cleaned["skill_name"] = str(cleaned["skill_name"] or "").strip()
        updated = self.store.update_mission(mission.id, **cleaned)
        self.store.add_event(updated.id, "definition_updated", "Mission 定义或作业指南已更新")
        return updated

    def transition(
        self,
        mission_id: str,
        target: MissionStatus | str,
        *,
        reason: str = "",
        waiting_for: Any = None,
    ) -> Mission:
        mission = self.require(mission_id)
        target = MissionStatus(target)
        if target == mission.status:
            return mission
        if target not in _ALLOWED_TRANSITIONS[mission.status]:
            raise InvalidMissionTransition(
                f"Mission cannot change from {mission.status.value} to {target.value}",
            )
        changes: dict[str, Any] = {"status": target.value}
        now = time.time()
        if target == MissionStatus.ACTIVE:
            self._require_skill(mission.skill_name)
            changes.update(
                next_run_at=now,
                completed_at=None,
                waiting_reason="",
                waiting_for=[],
            )
        elif target == MissionStatus.WAITING:
            waiting_reason = str(reason or "").strip()
            conditions = self._clean_waiting_for(waiting_for)
            if not waiting_reason:
                raise ValueError("A waiting Mission requires waiting_reason")
            if not conditions:
                raise ValueError("A waiting Mission requires at least one waiting_for condition")
            changes.update(
                next_run_at=None,
                waiting_reason=waiting_reason,
                waiting_for=conditions,
            )
        elif target in (MissionStatus.PAUSED, MissionStatus.STOPPED, MissionStatus.COMPLETED):
            changes["next_run_at"] = None
        if target in (MissionStatus.STOPPED, MissionStatus.COMPLETED):
            changes["completed_at"] = now
        if reason:
            changes["progress_summary"] = reason
        updated = self.store.update_mission(mission.id, **changes)
        self.store.add_event(
            updated.id,
            f"status_{target.value}",
            reason or f"Mission 状态变为 {target.value}",
        )
        return updated

    def checkpoint(
        self,
        mission_id: str,
        *,
        summary: str,
        checkpoint: dict[str, Any] | None = None,
        next_run_at: float | None = None,
        status: MissionStatus | str | None = None,
        waiting_reason: str = "",
        waiting_for: Any = None,
        run_id: str = "",
    ) -> Mission:
        mission = self.require(mission_id)
        changes: dict[str, Any] = {
            "progress_summary": str(summary or "").strip(),
            "checkpoint": checkpoint or {},
            "last_run_at": time.time(),
            "next_run_at": next_run_at,
        }
        target = MissionStatus(status) if status else mission.status
        if target == MissionStatus.ACTIVE:
            self._require_skill(mission.skill_name)
        if target != mission.status:
            if target not in _ALLOWED_TRANSITIONS[mission.status]:
                raise InvalidMissionTransition(
                    f"Mission cannot change from {mission.status.value} to {target.value}",
                )
            changes["status"] = target.value
        if target == MissionStatus.WAITING:
            reason = str(waiting_reason or "").strip()
            conditions = self._clean_waiting_for(waiting_for)
            if not reason:
                raise ValueError("A waiting Mission requires waiting_reason")
            if not conditions:
                raise ValueError("A waiting Mission requires at least one waiting_for condition")
            if next_run_at is not None:
                raise ValueError("A waiting Mission cannot have next_run_at")
            changes.update(
                next_run_at=None,
                waiting_reason=reason,
                waiting_for=conditions,
            )
        else:
            changes.update(waiting_reason="", waiting_for=[])
        if target in (MissionStatus.COMPLETED, MissionStatus.STOPPED):
            changes.update(next_run_at=None, completed_at=time.time())
        updated = self.store.update_mission(mission.id, **changes)
        self.store.add_event(
            updated.id,
            "checkpoint",
            updated.progress_summary,
            run_id=run_id,
            details={"status": updated.status.value, "next_run_at": updated.next_run_at},
        )
        return updated

    def due_signals(self, *, now: float | None = None, limit: int = 10) -> list[dict[str, Any]]:
        timestamp = time.time() if now is None else float(now)
        return [{
            "type": "mission_due",
            "source": "mission",
            "source_id": mission.id,
            "mission_id": mission.id,
            "title": mission.title,
            "objective": mission.objective,
            "priority": mission.priority,
            "accountable_person_id": mission.accountable_person_id,
            "origin_session_id": mission.origin_session_id,
            "progress_summary": mission.progress_summary,
            "next_run_at": mission.next_run_at,
        } for mission in self.store.list_due(timestamp, limit=limit)]

    def request_learning(self, mission_id: str, *, topic: str, reason: str, run_id: str = "") -> Mission:
        mission = self.require(mission_id)
        topic = str(topic or "").strip()
        if not topic:
            raise ValueError("Mission learning topic cannot be empty")
        updated = self.checkpoint(
            mission.id,
            summary=reason or f"等待学习：{topic}",
            checkpoint={**mission.checkpoint, "learning_topic": topic},
            next_run_at=None,
            status=MissionStatus.WAITING,
            waiting_reason=reason or f"等待学习：{topic}",
            waiting_for=[{
                "type": "learning",
                "key": "mission_learning",
                "description": topic,
            }],
            run_id=run_id,
        )
        self.store.add_event(
            mission.id,
            "learning_needed",
            topic,
            run_id=run_id,
            details={"reason": reason},
        )
        return updated

    def learning_signals(self, limit: int = 10) -> list[dict[str, Any]]:
        signals: list[dict[str, Any]] = []
        for mission in self.list(status=MissionStatus.WAITING.value, limit=100):
            events = self.store.list_events(mission.id, limit=30)
            latest_needed = next((event for event in events if event.event_type == "learning_needed"), None)
            latest_completed = next((event for event in events if event.event_type == "learning_completed"), None)
            if latest_needed is None:
                continue
            if latest_completed is not None and latest_completed.created_at > latest_needed.created_at:
                continue
            signals.append({
                "type": "mission_learning_needed",
                "source": "mission",
                "source_id": mission.id,
                "mission_id": mission.id,
                "topic": latest_needed.summary,
                "reason": str(latest_needed.details.get("reason") or mission.progress_summary),
                "priority": mission.priority,
            })
        signals.sort(key=lambda item: -float(item["priority"]))
        return signals[:max(1, int(limit))]

    def learning_completed(self, mission_id: str, *, topic: str, summary: str = "") -> Mission:
        mission = self.require(mission_id)
        self.store.add_event(
            mission.id,
            "learning_completed",
            summary or topic,
            details={"topic": topic},
        )
        if mission.status == MissionStatus.WAITING:
            return self.store.update_mission(
                mission.id,
                status=MissionStatus.ACTIVE.value,
                progress_summary=summary or f"已完成所需学习：{topic}",
                waiting_reason="",
                waiting_for=[],
                next_run_at=time.time(),
            )
        return self.require(mission.id)

    def start_run(self, mission_id: str, trigger_intent_id: str, runtime_session_id: str):
        mission = self.require(mission_id)
        if mission.status not in (MissionStatus.ACTIVE, MissionStatus.WAITING):
            raise InvalidMissionTransition("Only an active or waiting Mission can start a Run")
        run = self.store.create_run(mission.id, trigger_intent_id, runtime_session_id)
        self.store.add_event(mission.id, "run_started", "Mission 开始一次自主推进", run_id=run.id)
        return run

    def finish_run(self, run_id: str, status: MissionRunStatus, **kwargs: Any):
        run = self.store.finish_run(run_id, status, **kwargs)
        self.store.add_event(
            run.mission_id,
            f"run_{status.value}",
            run.result_summary or run.error_message or f"Run {status.value}",
            run_id=run.id,
        )
        return run

    def _require_skill(self, skill_name: str) -> None:
        if not skill_name:
            raise ValueError("An active Mission requires a global Skill guide")
        if not self._skill_exists(skill_name):
            raise ValueError(f"Mission Skill is not installed or available: {skill_name}")

    @staticmethod
    def _clean_list(values: Any) -> list[str]:
        if isinstance(values, str):
            values = [line for line in values.splitlines() if line.strip()]
        if not isinstance(values, (list, tuple)):
            return []
        return [str(value).strip() for value in values if str(value).strip()]

    @staticmethod
    def _clean_waiting_for(values: Any) -> list[dict[str, str]]:
        if not isinstance(values, (list, tuple)):
            return []
        conditions: list[dict[str, str]] = []
        for index, value in enumerate(values, 1):
            if isinstance(value, str):
                description = value.strip()
                if not description:
                    continue
                conditions.append({
                    "type": "external_condition",
                    "key": f"condition_{index}",
                    "description": description,
                })
                continue
            if not isinstance(value, dict):
                continue
            condition_type = str(value.get("type") or "external_condition").strip()
            key = str(value.get("key") or f"condition_{index}").strip()
            description = str(value.get("description") or "").strip()
            if not description:
                continue
            conditions.append({
                "type": condition_type,
                "key": key,
                "description": description,
            })
        return conditions
