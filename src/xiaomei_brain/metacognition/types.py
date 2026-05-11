"""Metacognition 数据类型。

认知回合制：Observer → Judge → Nudge → Execute → Observer → ...
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum


# ── Enums ──────────────────────────────────────────────────────────────

class SurpriseType(Enum):
    """意外类型 — 规则检测到的异常信号"""
    TOOL_LOOP = "tool_loop"            # 连续 ≥3 次调用同一工具
    TOOL_STORM = "tool_storm"          # 单步工具调用 > 10 次
    EMPTY_RESPONSE = "empty_response"  # LLM 输出去掉 PROGRESS 标签后为空
    REPEATED_OUTPUT = "repeated_output"  # 连续 2 步输出高度相似
    SLOW_STEP = "slow_step"            # 单步耗时 > 历史均值 3x
    NO_PROGRESS = "no_progress"        # 有工具调用但没有 PROGRESS 标签
    GAVE_UP = "gave_up"                # LLM 明确表示做不到
    VAGUE_GOAL = "vague_goal"          # 目标描述过于模糊


class StuckClass(Enum):
    """障碍分类 — 是什么阻止了前进"""
    TOOL_LOOP = "tool_loop"      # 工具循环
    UNCLEAR = "unclear"          # 目标不清晰，不知道到底要什么
    BLOCKED = "blocked"          # 外部阻塞（权限、API 错误、网络等）
    OUT_OF_SCOPE = "out_of_scope"  # 超出能力范围
    GAVE_UP = "gave_up"          # Agent 自己放弃了


class MetaSuggestion(Enum):
    """元认知建议 — 下一步做什么"""
    CONTINUE = "continue"                # 一切正常，继续
    CLARIFY = "clarify"                  # 需要澄清目标
    SIMPLIFY = "simplify"                # 简化当前步骤
    RETRY_DIFFERENT = "retry_different"  # 换个方法重试
    REPORT_PARTIAL = "report_partial"    # 报告部分进展，询问用户
    ESCALATE = "escalate"                # 暂停任务，请求用户介入


# ── Dataclasses ────────────────────────────────────────────────────────

@dataclass
class StepObservation:
    """单个执行步骤的观察记录"""
    step_index: int
    goal_description: str
    llm_output: str                    # 去掉 PROGRESS 标签后的输出
    tool_calls: list[str]              # 工具调用名称列表
    tool_call_count: int
    elapsed_seconds: float
    has_progress_tag: bool
    progress_status: str | None        # "completed" / "in_progress" / None
    surprises: list[SurpriseType] = field(default_factory=list)
    raw_content: str = ""              # 含 PROGRESS 标签的完整输出
    timestamp: float = field(default_factory=time.time)


@dataclass
class StepCheckResult:
    """步骤检查结果 — Metacognition 的判断"""
    step_index: int
    suggestion: MetaSuggestion
    stuck_class: StuckClass | None = None
    reasoning: str = ""
    surprises: list[SurpriseType] = field(default_factory=list)
    nudge: str = ""                    # 注入到下一轮 Agent context 的提示
    should_continue: bool = True


@dataclass
class TaskLesson:
    """任务完成后的复盘总结"""
    task_id: str
    task_description: str
    what_worked: list[str] = field(default_factory=list)
    what_failed: list[str] = field(default_factory=list)
    surprises_encountered: list[str] = field(default_factory=list)
    capability_notes: list[str] = field(default_factory=list)
    total_steps: int = 0
    total_time: float = 0.0
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "task_description": self.task_description,
            "what_worked": self.what_worked,
            "what_failed": self.what_failed,
            "surprises_encountered": self.surprises_encountered,
            "capability_notes": self.capability_notes,
            "total_steps": self.total_steps,
            "total_time": self.total_time,
            "created_at": self.created_at,
        }


@dataclass
class PACECheckpoint:
    """PACE 执行检查点 — 支持暂停/恢复"""
    goal_id: str
    step_index: int
    observations_json: str           # JSON 序列化的 observations 列表
    budget_call_count: int = 0       # LLMBudget._count
    budget_skip_until: int = 0       # LLMBudget._skip_until_step
    budget_consecutive_continue: int = 0  # LLMBudget._consecutive_continue
    consecutive_empty_count: int = 0
    last_nudge: str = ""
    saved_at: float = field(default_factory=time.time)
