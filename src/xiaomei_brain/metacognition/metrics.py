"""PACE 可观测性指标：跟踪 PACE 运行效果和异常检测效率。

PACEMetrics 在每次 PACE 运行过程中累积统计，run 结束时由 close_run() 写入 goal_runs 表。
聚合指标跨多次运行，从 DB 查询生成 Agent 级别的 PACE 效果报告。

存储：
    单次: goal_runs 表（brain.db）
    聚合: 从 goal_runs 表 SQL 查询
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class PACEMetrics:
    """单次 PACE 运行的统计指标"""

    goal_id: str
    goal_description: str
    start_time: float = field(default_factory=time.time)
    end_time: float = 0.0

    # 执行统计
    total_steps: int = 0
    total_llm_calls: int = 0         # 含 step_check
    total_tool_calls: int = 0
    total_elapsed: float = 0.0

    # 规则检测统计
    surprises_detected: dict = field(default_factory=dict)
    # {"TOOL_LOOP": 3, "GAVE_UP": 1, "EMPTY_RESPONSE": 2}

    # 决策统计
    hard_rules_triggered: int = 0    # 硬规则直接判定次数
    llm_checks_performed: int = 0    # LLM step_check 次数
    escalations: int = 0             # ESCALATE 次数
    auto_advances: int = 0           # 自动推进次数
    waiting_user_exits: int = 0      # 等待用户退出次数

    # 成果统计
    sub_goals_completed: int = 0
    sub_goals_failed: int = 0
    goal_completed: bool = False

    def record_step(
        self,
        surprises: list[str],
        suggestion: str,
        tool_call_count: int = 0,
        elapsed: float = 0.0,
    ) -> None:
        """记录单步执行指标"""
        self.total_steps += 1
        self.total_tool_calls += tool_call_count
        self.total_elapsed += elapsed

        for s in surprises:
            key = s if isinstance(s, str) else getattr(s, "value", str(s))
            self.surprises_detected[key] = self.surprises_detected.get(key, 0) + 1

        if suggestion == "RETRY_DIFFERENT":
            self.hard_rules_triggered += 1
        elif suggestion == "ESCALATE":
            self.escalations += 1
        elif suggestion == "CONTINUE":
            self.auto_advances += 1

    def to_dict(self) -> dict:
        return {
            "goal_id": self.goal_id,
            "goal_description": self.goal_description[:200],
            "start_time": self.start_time,
            "end_time": self.end_time,
            "total_steps": self.total_steps,
            "total_llm_calls": self.total_llm_calls,
            "total_tool_calls": self.total_tool_calls,
            "total_elapsed": round(self.total_elapsed, 1),
            "surprises_detected": self.surprises_detected,
            "hard_rules_triggered": self.hard_rules_triggered,
            "llm_checks_performed": self.llm_checks_performed,
            "escalations": self.escalations,
            "auto_advances": self.auto_advances,
            "waiting_user_exits": self.waiting_user_exits,
            "sub_goals_completed": self.sub_goals_completed,
            "sub_goals_failed": self.sub_goals_failed,
            "goal_completed": self.goal_completed,
        }


def persist_metrics(metrics: PACEMetrics, agent_id: str) -> None:
    """[deprecated] 指标已在 close_run() 中持久化到 goal_runs 表。保留此函数避免 import 报错。"""
    pass


def generate_report(agent_id: str, goal_run_storage=None) -> str:
    """生成 PACE 可观测性报告。

    Args:
        agent_id: Agent ID
        goal_run_storage: GoalRunStorage 实例（从 DB 查询）。如果为 None，降级读取旧 JSON。

    Returns:
        格式化的报告文本
    """
    # 优先从 DB 查询
    if goal_run_storage is not None:
        s = goal_run_storage.get_summary(agent_id)
        aggregated_surprises = goal_run_storage.get_aggregated_surprises(agent_id)
        if s and s.get("total_runs", 0) > 0:
            return _format_report(s, aggregated_surprises)

    # 降级：读取旧 JSON 文件
    summary_path = (
        Path.home() / ".xiaomei-brain" / agent_id / "metacognition" / "metrics_summary.json"
    )
    if not summary_path.exists():
        return "暂无 PACE 运行数据。至少完成一次 PACE 任务后才会生成报告。"

    try:
        s = json.loads(summary_path.read_text(encoding="utf-8"))
    except Exception as e:
        return f"读取指标文件失败: {e}"

    if s.get("total_runs", 0) == 0:
        return "暂无有效运行数据。"

    return _format_report(s, s.get("surprises_detected", {}))


def _format_report(s: dict, surprises: dict) -> str:
    """格式化报告文本。兼容 DB 和 JSON 数据源。"""
    runs = s.get("total_runs", 0)
    steps = s.get("total_steps", 0)
    avg_steps = steps / runs if runs else 0

    # DB schema uses "completed" vs "failed"; JSON uses "goal_stats.completed"
    if "goal_stats" in s:
        completed = s["goal_stats"].get("completed", 0)
        total = s["goal_stats"].get("total", 1)
    else:
        completed = s.get("completed", 0)
        total = s.get("total_runs", 1)
    completion_rate = completed / total * 100 if total else 0

    lines = [
        "╔══════════════════════════════════════════════════╗",
        "║          PACE 可观测性报告                        ║",
        "╠══════════════════════════════════════════════════╣",
        f"║  总运行次数:        {runs:<3}                         ║",
        f"║  总步骤数:          {steps:<3}                         ║",
        f"║  平均步数/任务:     {avg_steps:.1f}                          ║",
        "║                                                  ║",
        "║  异常检测:                                        ║",
    ]

    surprise_labels = {
        "TOOL_LOOP": "TOOL_LOOP 拦截",
        "TOOL_STORM": "TOOL_STORM 拦截",
        "EMPTY_RESPONSE": "EMPTY_RESPONSE",
        "REPEATED_OUTPUT": "REPEATED_OUTPUT",
        "SLOW_STEP": "SLOW_STEP",
        "NO_PROGRESS": "NO_PROGRESS",
        "GAVE_UP": "GAVE_UP 拦截",
    }
    for key, label in surprise_labels.items():
        count = surprises.get(key, 0)
        if count > 0:
            lines.append(f"║    {label}:  {count} 次{' ' * (32 - len(label))}║")

    # DB schema uses "hard_rules" / "llm_checks" etc.; JSON uses "decisions.hard_rules"
    if "decisions" in s:
        decisions = s["decisions"]
        hard_rules = decisions.get("hard_rules", 0)
        llm_checks = decisions.get("llm_checks", 0)
        auto_advances = decisions.get("auto_advances", 0)
        escalations = decisions.get("escalations", 0)
        waiting_user = decisions.get("waiting_user", 0)
    else:
        hard_rules = s.get("hard_rules", 0)
        llm_checks = s.get("llm_checks", 0)
        auto_advances = s.get("auto_advances", 0)
        escalations = s.get("escalations", 0)
        waiting_user = s.get("waiting_user", 0)

    total_decisions = hard_rules + llm_checks + auto_advances + escalations + waiting_user
    lines.append("║                                                  ║")
    lines.append("║  决策分布:                                        ║")
    if total_decisions > 0:
        decision_items = [
            ("hard_rules", "硬规则直接判定", hard_rules),
            ("llm_checks", "LLM step_check", llm_checks),
            ("auto_advances", "自动推进", auto_advances),
            ("escalations", "ESCALATE", escalations),
            ("waiting_user", "等待用户", waiting_user),
        ]
        for key, label, count in decision_items:
            pct = count / total_decisions * 100 if total_decisions else 0
            lines.append(f"║    {label}:  {count} ({pct:.0f}%){' ' * (27 - len(label))}║")

    lines.append("║                                                  ║")
    lines.append(f"║  任务完成率:        {completed}/{total} ({completion_rate:.0f}%){' ' * (19 - len(str(completion_rate)))}║")
    lines.append("╚══════════════════════════════════════════════════╝")

    if s.get("last_updated"):
        lines.append(f"\n最后更新: {s['last_updated']}")

    return "\n".join(lines)
