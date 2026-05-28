"""StateChangeBuffer: L1 → L2/L3 状态变化缓冲队列。

不属于 SelfImage——它是 Consciousness 层的调度信号，
不是"自我认知"的一部分。

Usage:
    buffer = StateChangeBuffer()
    # L1: 记录变化
    buffer.record({"energy_change": -0.05, "agent_state_change": {...}})
    # L2/L3: 检查并消费
    if buffer.should_trigger_l3():
        changes = buffer.consume()
"""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


class StateChangeBuffer:
    """状态变化缓冲队列。

    SelfImage.tick() 每秒对比快照，有差异就写入 buffer。
    L2/L3 读取并清空，决定是否需要 LLM 处理。
    """

    # 阈值配置
    L3_TRIGGER_COUNT: int = 15       # 累积超过此数量触发 L3
    L2_CHANGES_TRIGGER: int = 5      # sleeping 时累积超过此数量触发 L2
    MAX_SIZE: int = 30               # 最多保留条数

    # diff 阈值
    DIFF_IDLE_THRESHOLD_S: float = 10.0
    DIFF_ENERGY_THRESHOLD: float = 0.001
    DIFF_GOAL_THRESHOLD: float = 0.001

    def __init__(self) -> None:
        self._changes: list[dict[str, Any]] = []
        self._cycle_count: int = 0

    # ── 写入（L1）──────────────────────────────────────

    def tick(self, prev: dict[str, float | str],
             cur: dict[str, float | str]) -> None:
        """对比快照，有差异就记录。

        由 SelfImage.tick() 调用，每秒一次。
        """
        self._cycle_count += 1

        if not prev:
            self._changes.append({
                "cycle_id": self._cycle_count,
                "timestamp": time.time(),
                "changes": {"first_cycle": True, "message": "火焰刚点燃"},
            })
            self._trim()
            return

        diff = self._diff(prev, cur)
        if not diff:
            return

        self._changes.append({
            "cycle_id": self._cycle_count,
            "timestamp": time.time(),
            "changes": diff,
        })
        self._trim()
        logger.debug("[StateBuffer] 记录变化 #%d: %s",
                     self._cycle_count, list(diff.keys()))

    def _diff(self, prev: dict, cur: dict) -> dict[str, Any]:
        """对比快照差异。"""
        diff: dict[str, Any] = {}

        cur_age = cur["consciousness_age"]
        if cur_age - prev["consciousness_age"] > 0:
            diff["time_elapsed"] = cur_age - prev["consciousness_age"]

        cur_state = cur["agent_state"]
        if cur_state != prev["agent_state"]:
            diff["agent_state_change"] = {"from": prev["agent_state"], "to": cur_state}

        idle_diff = cur["user_idle_duration"] - prev["user_idle_duration"]
        if abs(idle_diff) > self.DIFF_IDLE_THRESHOLD_S:
            diff["user_idle_change"] = idle_diff

        energy_diff = cur["energy"] - prev["energy"]
        if abs(energy_diff) > self.DIFF_ENERGY_THRESHOLD:
            diff["energy_change"] = energy_diff

        cur_mem = cur["window_size"]
        if cur_mem != prev["window_size"]:
            diff["memory_change"] = cur_mem - prev["window_size"]

        goal_diff = cur["goal_progress"] - prev["goal_progress"]
        if abs(goal_diff) > self.DIFF_GOAL_THRESHOLD:
            diff["goal_change"] = goal_diff

        return diff

    def _trim(self) -> None:
        if len(self._changes) > self.MAX_SIZE:
            self._changes = self._changes[-self.MAX_SIZE:]

    # ── 读取（L2/L3 调度判断）──────────────────────────

    def should_trigger_l3(self) -> bool:
        """累积变化是否足够触发 L3 深度燃烧。"""
        return len(self._changes) > self.L3_TRIGGER_COUNT

    def should_trigger_l2(self) -> bool:
        """sleeping 状态下累积变化是否足够触发 L2。"""
        return len(self._changes) > self.L2_CHANGES_TRIGGER

    # ── 消费（L2/L3 处理后）────────────────────────────

    def consume(self) -> list[dict[str, Any]]:
        """读取并清空所有变化。"""
        changes = self._changes
        self._changes = []
        return changes

    def clear(self) -> None:
        """清空缓冲（不读取）。"""
        self._changes = []

    # ── 查询（不消费）──────────────────────────────────

    def __len__(self) -> int:
        return len(self._changes)

    def recent(self, n: int = 10) -> list[dict[str, Any]]:
        """获取最近 n 条变化（不清空），用于 LLM prompt 渲染。"""
        return self._changes[-n:]
