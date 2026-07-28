"""Transport-neutral summary of one internal processing display cycle."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from xiaomei_brain.activity import ActivityStep


@dataclass(frozen=True)
class InternalProcessingItem:
    key: str
    label: str
    count: int
    unit: str
    detail: str = ""

    @property
    def summary(self) -> str:
        value = f"{self.count} {self.unit}".strip()
        return f"{value} · {self.detail}" if self.detail else value


@dataclass(frozen=True)
class InternalProcessingReport:
    """Safe result summary shared by CLI, Gateway and Activity."""

    items: tuple[InternalProcessingItem, ...]

    @classmethod
    def from_display(cls, payload: dict[str, Any]) -> "InternalProcessingReport":
        data = payload.get("data", payload)
        if not isinstance(data, dict):
            return cls(())
        items: list[InternalProcessingItem] = []

        def add(key: str, label: str, count: Any, unit: str, detail: str = "") -> None:
            if not key or not label:
                return
            try:
                value = int(count)
            except (TypeError, ValueError):
                return
            if value > 0:
                for index, existing in enumerate(items):
                    if existing.key == key:
                        items[index] = InternalProcessingItem(
                            key,
                            label,
                            existing.count + value,
                            unit,
                            detail or existing.detail,
                        )
                        return
                items.append(InternalProcessingItem(key, label, value, unit, detail))

        memory = data.get("memory")
        if isinstance(memory, list):
            labels = {
                "ADD": "记住新内容",
                "UPDATE": "更新已有记忆",
                "MERGE": "合并相关记忆",
                "DELETE": "遗忘已有记忆",
            }
            for index, raw in enumerate(memory):
                if not isinstance(raw, dict):
                    continue
                action = str(raw.get("action") or "").upper()
                label = labels.get(action)
                if not label:
                    continue
                add(
                    f"memory_{index + 1}_{action.lower()}",
                    label,
                    1,
                    "条",
                    str(raw.get("preview") or "")[:200],
                )
        if isinstance(data.get("inner_voice"), dict):
            add("inner_voice", "内在感受整理", 1, "次")
        social = (
            data.get("social_signal")
            or data.get("social_events")
            or data.get("social_perception")
        )
        if social:
            add("social_cognition", "社会感知整理", 1, "次")
        gaps = data.get("gaps")
        if isinstance(gaps, dict):
            add("knowledge_gaps", "识别知识盲区", gaps.get("count"), "个")
        inserts = data.get("inserts")
        if isinstance(inserts, dict):
            add("step_suggestions", "形成步骤建议", inserts.get("count"), "条")
        dag = data.get("dag")
        if isinstance(dag, dict):
            tokens = int(dag.get("summary_tokens") or 0)
            add(
                "dag",
                "压缩会话上下文",
                dag.get("msg_count"),
                "条消息",
                f"{tokens} tokens" if tokens else "",
            )
        periodic = data.get("periodic")
        if isinstance(periodic, dict):
            add("periodic_memory", "提取长期记忆", periodic.get("count"), "条")
        recall = data.get("recall")
        if isinstance(recall, dict):
            add("memory_recall", "召回相关记忆", recall.get("count"), "条")
        procedure = data.get("procedure")
        if isinstance(procedure, dict):
            add("procedure", "学习新流程", procedure.get("count"), "条")
        narrative = data.get("narrative")
        if isinstance(narrative, dict):
            add("narrative_learning", "学习叙事记忆", narrative.get("count"), "条")
        add("emergence_stored", "保存内心独白记忆", data.get("emergence_stored"), "篇")
        add("narr_extracted", "形成叙事记忆", data.get("narr_extracted"), "条")
        add("doubt_count", "记录自我不确定", data.get("doubt_count"), "条")
        processing = data.get("processing_results")
        if isinstance(processing, list):
            for raw in processing:
                if not isinstance(raw, dict):
                    continue
                add(
                    str(raw.get("key") or ""),
                    str(raw.get("label") or ""),
                    raw.get("count"),
                    str(raw.get("unit") or "次"),
                    str(raw.get("detail") or "")[:200],
                )
        return cls(tuple(items))

    @property
    def has_results(self) -> bool:
        return bool(self.items)

    @property
    def summary(self) -> str:
        return "；".join(f"{item.label} {item.count}{item.unit}" for item in self.items)

    def activity_steps(self) -> tuple[ActivityStep, ...]:
        return tuple(
            ActivityStep(
                id=item.key,
                title=item.label,
                status="completed",
                summary=item.summary,
            )
            for item in self.items
        )


def record_internal_processing_activity(
    living: Any,
    payload: dict[str, Any],
    *,
    session_id: str = "",
    turn_id: str = "",
    person_id: str = "",
) -> str:
    """Persist one completed, Agent-global cognitive Activity."""
    report = InternalProcessingReport.from_display(payload)
    service = getattr(living, "_activity_service", None)
    if service is None or not report.has_results:
        return ""
    activity = service.create(
        category="cognition",
        kind="internal_processing",
        title="本轮内部处理",
        source_type="internal_processing",
        source_id="",
        scope_type="person" if person_id else "agent",
        scope_id=person_id or "global",
        person_id=person_id or None,
        origin_session_id=session_id,
        origin_turn_id=turn_id,
        progress_summary=report.summary,
        steps=report.activity_steps(),
    )
    service.start(activity.id, summary="正在整理内部经验")
    service.report_progress(
        activity.id,
        summary=report.summary,
        current_step=report.items[-1].label,
        completed_steps=len(report.items),
        total_steps=len(report.items),
        steps=report.activity_steps(),
    )
    service.complete(activity.id, summary=report.summary)
    return activity.id
