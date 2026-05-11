"""Attention: 意识注意力选择。

决定"此刻意识关注什么"——从身体信号、认知状态、环境变化中，
按概率加权选出最值得关注的信号，生成记忆召回查询词。

核心原则：
- 概率加权：强信号概率高，弱信号也有机会
- 初现加重：刚跨过阈值的信号额外加权
- 追踪历史：记录上次快照，检测"新出现"的变化

Usage:
    from .attention import select_attention

    query, signals = select_attention(
        body=si.body,
        mind=si.mind,
        perception=si.perception,
        last_snapshot=si._last_attention_snapshot,
    )
    si._last_attention_snapshot = signals  # 保存快照供下次对比
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from .self_modules import SelfBody, SelfMind, SelfPerception

logger = logging.getLogger(__name__)


# ── 信号阈值 ──────────────────────────────────────────────

# 欲望超过此值才有机会被关注
DESIRE_THRESHOLD = 0.3

# 跨过阈值的信号，给予的额外加权倍数
EMERGENCE_BOOST = 1.5

# 上次关注过的信号，轻微衰减（避免连续重复）
RECENCY_DECAY = 0.7


@dataclass
class AttentionSignal:
    """一个可关注的信号。"""

    key: str           # 信号标识，如 "desire_belonging"
    label: str         # 中文描述，如 "归属欲偏高"
    weight: float      # 当前权重（含 boost）
    emerged: bool = False  # 是否初现


def select_attention(
    body: "SelfBody | None" = None,
    mind: "SelfMind | None" = None,
    perception: "SelfPerception | None" = None,
    last_snapshot: dict[str, float] | None = None,
) -> tuple[str, dict[str, float]]:
    """选择此刻意识关注什么，返回 (query, snapshot)。

    步骤：
    1. 收集所有信号
    2. 计算权重（含初现加重 / 重复衰减）
    3. 概率加权抽签
    4. 组装查询词
    """
    last = last_snapshot or {}
    signals: list[AttentionSignal] = []

    # ── 1. 身体信号：欲望 ──────────────────────────────
    if body:
        _collect_desire_signals(body, signals, last)

    # ── 2. 认知信号：目标进展 ──────────────────────────────
    if mind:
        _collect_goal_signals(mind, signals, last)

    # ── 3. 环境信号：状态变化 ──────────────────────────────
    if perception:
        _collect_state_signals(perception, signals, last)

    # ── 4. 兜底：心情 ──────────────────────────────────
    if body and body.mood:
        base_w = _sigmoid_normalize(body.emotion_intensity, center=0.3, scale=5)
        signals.append(AttentionSignal(
            key="mood",
            label=f"心情{body.mood}",
            weight=max(0.1, base_w),
        ))

    if not signals:
        return "平静，等待中", {}

    # ── 权重归一化 ──────────────────────────────────
    total = sum(s.weight for s in signals)
    if total <= 0:
        return "平静，等待中", {}

    # ── 加权抽签：选 2~3 个信号 ─────────────────────────
    n_pick = min(3, len(signals))
    picked = _weighted_sample(signals, n_pick)

    # ── 组装查询词 ──────────────────────────────────
    query = "，".join(s.label for s in picked)
    snapshot = {s.key: s.weight for s in signals}

    logger.info(
        "[Attention] 选中 %d/%d 信号: %s (emerged=%s)",
        len(picked), len(signals),
        " | ".join(f"{s.key}({s.weight:.2f}{'*' if s.emerged else ''})" for s in picked),
        [s.key for s in picked if s.emerged],
    )

    return query, snapshot


# ── 信号收集 ──────────────────────────────────────────────

def _collect_desire_signals(body, signals: list, last: dict) -> None:
    """从欲望收集中选信号。"""
    desires = [
        ("desire_belonging",   "归属欲", body.desire_belonging),
        ("desire_cognition",   "认知欲", body.desire_cognition),
        ("desire_achievement", "成就欲", body.desire_achievement),
        ("desire_expression",  "表达欲", body.desire_expression),
    ]
    for key, name, val in desires:
        if val < DESIRE_THRESHOLD:
            continue
        base_w = val  # 欲望值本身作为基础权重
        emerged = _is_emerged(key, val, last, DESIRE_THRESHOLD)
        weight = _apply_boosts(base_w, emerged, key)
        signals.append(AttentionSignal(
            key=key,
            label=f"{name}偏高",
            weight=weight,
            emerged=emerged,
        ))


def _collect_goal_signals(mind, signals: list, last: dict) -> None:
    """从目标及其进展收集信号。"""
    if mind.primary_goal and mind.goal_progress > 0:
        base_w = mind.goal_progress
        emerged = _is_emerged("goal_progress", mind.goal_progress, last, 0.05)
        weight = _apply_boosts(base_w, emerged, "goal_progress")
        signals.append(AttentionSignal(
            key="goal_progress",
            label=f"目标{mind.primary_goal[:12]}有进展",
            weight=weight,
            emerged=emerged,
        ))

    if mind.primary_goal and mind.goal_progress < 0.01:
        # 目标无进展，本身就是值得关注的信号
        emerged = _is_emerged("goal_stalled", 1.0, last, 0.5)
        weight = _apply_boosts(0.3, emerged, "goal_stalled")
        signals.append(AttentionSignal(
            key="goal_stalled",
            label=f"目标{mind.primary_goal[:12]}待推进",
            weight=weight,
            emerged=emerged,
        ))


def _collect_state_signals(perception, signals: list, last: dict) -> None:
    """从环境状态收集信号。"""
    state = perception.agent_state
    if state and state != "awake":
        signals.append(AttentionSignal(
            key=f"state_{state}",
            label=f"状态{state}",
            weight=0.2,
        ))

    idle = perception.user_idle_duration
    if idle > 300:  # 空闲超过5分钟
        idle_m = int(idle / 60)
        emerged = _is_emerged("user_idle", idle, last, 300)
        weight = _apply_boosts(min(0.5, idle / 7200), emerged, "user_idle")
        signals.append(AttentionSignal(
            key="user_idle",
            label=f"用户空闲{idle_m}分钟",
            weight=weight,
            emerged=emerged,
        ))


# ── 权重计算 ──────────────────────────────────────────────

def _is_emerged(key: str, val: float, last: dict, threshold: float) -> bool:
    """检测信号是否"初现"——上次低于阈值，这次高于。"""
    prev = last.get(key)
    if prev is None:
        return False  # 没有历史，不做判断
    return prev < threshold and val >= threshold


def _apply_boosts(base_weight: float, emerged: bool, key: str) -> float:
    """应用初现加重和重复衰减。"""
    w = base_weight
    if emerged:
        w *= EMERGENCE_BOOST
    return max(0.05, w)


def _weighted_sample(signals: list[AttentionSignal], n: int) -> list[AttentionSignal]:
    """加权不放回抽样，选 n 个信号。"""
    if n >= len(signals):
        return list(signals)

    pool = list(signals)
    picked: list[AttentionSignal] = []

    for _ in range(n):
        total = sum(s.weight for s in pool)
        if total <= 0:
            break
        r = random.uniform(0, total)
        cumulative = 0.0
        for i, s in enumerate(pool):
            cumulative += s.weight
            if cumulative >= r:
                picked.append(s)
                pool.pop(i)
                break

    return picked


def _sigmoid_normalize(x: float, center: float = 0.5, scale: float = 5.0) -> float:
    """将值映射到 [0, 1]，center 处为 0.5。"""
    import math
    try:
        return 1.0 / (1.0 + math.exp(-scale * (x - center)))
    except OverflowError:
        return 0.0 if x < center else 1.0
