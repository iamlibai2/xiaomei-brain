"""PACE 可观测性指标：跟踪 PACE 运行效果和异常检测效率。

PACEMetrics 在每次 PACE 运行过程中累积统计，post_review 时持久化。
聚合指标跨多次运行，生成 Agent 级别的 PACE 效果报告。

存储：
    单次: ~/.xiaomei-brain/{id}/metacognition/metrics/{date}_{goal_id}.json
    聚合: ~/.xiaomei-brain/{id}/metacognition/metrics_summary.json
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
    """持久化单次 PACE 运行指标 + 更新聚合报告。

    Args:
        metrics: 单次运行指标
        agent_id: Agent ID
    """
    base_dir = Path.home() / ".xiaomei-brain" / agent_id / "metacognition"
    metrics_dir = base_dir / "metrics"
    metrics_dir.mkdir(parents=True, exist_ok=True)

    # 单次指标文件
    date_str = datetime.now().strftime("%Y-%m-%d")
    goal_short = metrics.goal_id[:8] if metrics.goal_id else "unknown"
    path = metrics_dir / f"{date_str}_{goal_short}.json"
    try:
        path.write_text(
            json.dumps(metrics.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("[Metrics] 单次指标已持久化: %s", path)
    except Exception as e:
        logger.warning("[Metrics] 持久化失败: %s", e)

    # 更新聚合报告
    _update_summary(base_dir / "metrics_summary.json", metrics)


def _update_summary(summary_path: Path, metrics: PACEMetrics) -> None:
    """增量更新聚合指标"""
    summary = {
        "total_runs": 0,
        "total_steps": 0,
        "total_llm_calls": 0,
        "total_tool_calls": 0,
        "total_elapsed": 0.0,
        "surprises_detected": {},
        "decisions": {
            "hard_rules": 0,
            "llm_checks": 0,
            "escalations": 0,
            "auto_advances": 0,
            "waiting_user": 0,
        },
        "goal_stats": {
            "total": 0,
            "completed": 0,
            "failed": 0,
            "sub_goals_completed": 0,
            "sub_goals_failed": 0,
        },
        "last_updated": "",
    }

    if summary_path.exists():
        try:
            loaded = json.loads(summary_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                summary.update(loaded)
        except Exception:
            pass

    summary["total_runs"] += 1
    summary["total_steps"] += metrics.total_steps
    summary["total_llm_calls"] += metrics.total_llm_calls
    summary["total_tool_calls"] += metrics.total_tool_calls
    summary["total_elapsed"] = round(summary["total_elapsed"] + metrics.total_elapsed, 1)

    for k, v in metrics.surprises_detected.items():
        summary["surprises_detected"][k] = summary["surprises_detected"].get(k, 0) + v

    summary["decisions"]["hard_rules"] += metrics.hard_rules_triggered
    summary["decisions"]["llm_checks"] += metrics.llm_checks_performed
    summary["decisions"]["escalations"] += metrics.escalations
    summary["decisions"]["auto_advances"] += metrics.auto_advances
    summary["decisions"]["waiting_user"] += metrics.waiting_user_exits

    summary["goal_stats"]["total"] += 1
    if metrics.goal_completed:
        summary["goal_stats"]["completed"] += 1
    else:
        summary["goal_stats"]["failed"] += 1
    summary["goal_stats"]["sub_goals_completed"] += metrics.sub_goals_completed
    summary["goal_stats"]["sub_goals_failed"] += metrics.sub_goals_failed

    summary["last_updated"] = datetime.now().isoformat()

    try:
        summary_path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        logger.warning("[Metrics] 聚合报告更新失败: %s", e)


def generate_report(agent_id: str) -> str:
    """生成 PACE 可观测性报告。

    Args:
        agent_id: Agent ID

    Returns:
        格式化的报告文本
    """
    summary_path = (
        Path.home() / ".xiaomei-brain" / agent_id / "metacognition" / "metrics_summary.json"
    )

    if not summary_path.exists():
        return "暂无 PACE 运行数据。至少完成一次 PACE 任务后才会生成报告。"

    try:
        s = json.loads(summary_path.read_text(encoding="utf-8"))
    except Exception as e:
        return f"读取指标文件失败: {e}"

    runs = s.get("total_runs", 0)
    if runs == 0:
        return "暂无有效运行数据。"

    steps = s.get("total_steps", 0)
    avg_steps = steps / runs if runs else 0
    completion_rate = (
        s.get("goal_stats", {}).get("completed", 0) / s.get("goal_stats", {}).get("total", 1) * 100
    )

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

    surprises = s.get("surprises_detected", {})
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

    decisions = s.get("decisions", {})
    total_decisions = sum(decisions.values())
    lines.append("║                                                  ║")
    lines.append("║  决策分布:                                        ║")
    if total_decisions > 0:
        decision_items = [
            ("hard_rules", "硬规则直接判定"),
            ("llm_checks", "LLM step_check"),
            ("auto_advances", "自动推进"),
            ("escalations", "ESCALATE"),
            ("waiting_user", "等待用户"),
        ]
        for key, label in decision_items:
            count = decisions.get(key, 0)
            pct = count / total_decisions * 100 if total_decisions else 0
            lines.append(f"║    {label}:  {count} ({pct:.0f}%){' ' * (27 - len(label))}║")

    lines.append("║                                                  ║")
    goal_stats = s.get("goal_stats", {})
    lines.append(f"║  任务完成率:        {goal_stats.get('completed', 0)}/{goal_stats.get('total', 0)} ({completion_rate:.0f}%){' ' * (19 - len(str(completion_rate)))}║")
    lines.append("╚══════════════════════════════════════════════════╝")

    if s.get("last_updated"):
        lines.append(f"\n最后更新: {s['last_updated']}")

    return "\n".join(lines)
