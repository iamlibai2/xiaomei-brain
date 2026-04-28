"""Task 数据模型 — 独立认知实体

Task 不是 Goal 的别名，而是一个自我完备的认知实体：
- 自己的 ID、生命周期、认知日志
- 认知日志增量累积（子目标完成时追加）
- 关联 Goal 子树（只对 EXECUTION 类型）

类型 → 处理策略：
- EXECUTION  → 关联 Goal，委托 PurposeEngine 子目标推进
- LEARNING   → 不拆子目标，直接学习
- REFLECTION → 委托反省流程（未来）
- RELATIONSHIP → 持久关注态
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from xiaomei_brain.purpose.goal import TaskType


class TaskStatus(Enum):
    """Task 生命周期状态"""
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    ABANDONED = "abandoned"


@dataclass
class CognitiveLogEntry:
    """认知日志条目 — 增量记录认知过程的关键时刻

    entry_type:
        - "decision":  关键决策（选了什么方案、为什么）
        - "discovery": 新发现（了解到什么）
        - "pitfall":   踩坑记录（遇到什么问题）
        - "output":    子目标产出
        - "note":      其他值得记录的认知
    """
    entry_type: str
    content: str
    timestamp: float = field(default_factory=time.time)
    sub_goal_id: str | None = None

    def to_dict(self) -> dict:
        return {
            "entry_type": self.entry_type,
            "content": self.content,
            "timestamp": self.timestamp,
            "sub_goal_id": self.sub_goal_id,
        }

    @classmethod
    def from_dict(cls, data: dict) -> CognitiveLogEntry:
        return cls(
            entry_type=data.get("entry_type", "note"),
            content=data.get("content", ""),
            timestamp=data.get("timestamp", 0),
            sub_goal_id=data.get("sub_goal_id"),
        )


@dataclass
class Task:
    """独立认知实体

    与 Goal 的关系：
    - goal_id 非空 → 这是一个 EXECUTION 类型的 Task，关联 PurposeEngine 中的顶层 Goal
    - goal_id 为空 → LEARNING/REFLECTION/RELATIONSHIP 类型，不经过 PurposeEngine

    认知日志：
    - 不在暂停时才生成快照，而是在子目标完成/发现/决策时增量追加
    - 暂停时只需标记状态，恢复时直接读取 cognitive_log
    """
    task_id: str
    description: str
    type: TaskType
    status: TaskStatus = TaskStatus.ACTIVE
    goal_id: str | None = None
    cognitive_log: list[CognitiveLogEntry] = field(default_factory=list)
    artifacts: list[dict] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    last_active_at: float = field(default_factory=time.time)
    parent_task_id: str | None = None

    # ── 工厂方法 ─────────────────────────────────

    @classmethod
    def create(
        cls,
        description: str,
        task_type: TaskType = TaskType.EXECUTION,
        goal_id: str | None = None,
        parent_task_id: str | None = None,
    ) -> Task:
        """创建新 Task"""
        return cls(
            task_id=uuid.uuid4().hex[:12],
            description=description,
            type=task_type,
            status=TaskStatus.ACTIVE,
            goal_id=goal_id,
            parent_task_id=parent_task_id,
        )

    # ── 生命周期 ─────────────────────────────────

    def pause(self) -> None:
        """暂停 Task"""
        self.status = TaskStatus.PAUSED
        self.last_active_at = time.time()

    def resume(self) -> None:
        """恢复 Task"""
        self.status = TaskStatus.ACTIVE
        self.last_active_at = time.time()

    def complete(self) -> None:
        """完成 Task"""
        self.status = TaskStatus.COMPLETED
        self.last_active_at = time.time()

    def abandon(self) -> None:
        """放弃 Task"""
        self.status = TaskStatus.ABANDONED
        self.last_active_at = time.time()

    def is_active(self) -> bool:
        return self.status == TaskStatus.ACTIVE

    def is_paused(self) -> bool:
        return self.status == TaskStatus.PAUSED

    def is_completed(self) -> bool:
        return self.status == TaskStatus.COMPLETED

    # ── 认知日志 ─────────────────────────────────

    def append_log(
        self,
        entry_type: str,
        content: str,
        sub_goal_id: str | None = None,
    ) -> CognitiveLogEntry:
        """追加认知日志条目"""
        entry = CognitiveLogEntry(
            entry_type=entry_type,
            content=content,
            sub_goal_id=sub_goal_id,
        )
        self.cognitive_log.append(entry)
        self.last_active_at = time.time()
        return entry

    # ── 产出物 ───────────────────────────────────

    def add_artifact(self, path: str, role: str = "output") -> None:
        """注册产出物"""
        self.artifacts.append({
            "path": path,
            "role": role,
            "created_at": time.time(),
        })
        self.last_active_at = time.time()

    # ── 上下文 ───────────────────────────────────

    def get_cognitive_context(self) -> str:
        """格式化 cognitive_log 为可注入 system prompt 的文本"""
        if not self.cognitive_log:
            return ""

        lines = [f"【任务认知日志 — {self.description}】"]
        lines.append("以下是执行过程中记录的关键认知，帮助你无缝继续：")
        lines.append("")

        type_labels = {
            "decision":  "💡 决策",
            "discovery": "🔍 发现",
            "pitfall":   "⚠️ 踩坑",
            "output":    "📦 产出",
            "note":      "📝 备注",
        }

        for entry in self.cognitive_log:
            label = type_labels.get(entry.entry_type, entry.entry_type)
            lines.append(f"{label}: {entry.content}")

        if self.artifacts:
            lines.append("")
            lines.append("📁 产出物索引：")
            for a in self.artifacts:
                lines.append(f"  - {a['path']} ({a['role']})")

        return "\n".join(lines)

    # ── 序列化 ───────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "description": self.description,
            "type": self.type.value,
            "status": self.status.value,
            "goal_id": self.goal_id,
            "cognitive_log": [e.to_dict() for e in self.cognitive_log],
            "artifacts": self.artifacts,
            "created_at": self.created_at,
            "last_active_at": self.last_active_at,
            "parent_task_id": self.parent_task_id,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Task:
        task_type_str = data.get("type", "execution")
        try:
            task_type = TaskType(task_type_str)
        except ValueError:
            task_type = TaskType.EXECUTION

        status_str = data.get("status", "active")
        try:
            status = TaskStatus(status_str)
        except ValueError:
            status = TaskStatus.ACTIVE

        return cls(
            task_id=data.get("task_id", ""),
            description=data.get("description", ""),
            type=task_type,
            status=status,
            goal_id=data.get("goal_id"),
            cognitive_log=[
                CognitiveLogEntry.from_dict(e)
                for e in data.get("cognitive_log", [])
            ],
            artifacts=data.get("artifacts", []),
            created_at=data.get("created_at", 0),
            last_active_at=data.get("last_active_at", 0),
            parent_task_id=data.get("parent_task_id"),
        )
