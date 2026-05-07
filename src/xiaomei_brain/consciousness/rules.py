"""Rules: 动作触发规则定义。

所有动作（Intent 驱动、欲望驱动、目标驱动）统一在这里定义。
ActionDispatcher 遍历规则，基于 SelfImage 状态匹配并产出 ActionItem。

Usage:
    from .action_dispatcher import ActionDispatcher

    dispatcher = ActionDispatcher()
    dispatcher.load_rules(RULES)
    action_items = dispatcher.tick(self_image)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from .action_item import ActionItem
    from .self_image_proxy import SelfImage


logger = logging.getLogger(__name__)


@dataclass
class Rule:
    """单条触发规则。

     fluent API:
        Rule.when(condition).then(action_item).cooldown(key, seconds)

    Example:
        Rule.when(lambda si: si.intent_buffer.contains("GREET"))
            .then(ActionItem(action_type=ActionType.PROACTIVE, ...))
            .cooldown("greet_user", seconds=3600)
    """
    condition: Callable[[SelfImage], bool]
    action_item: ActionItem
    cooldown_key: str = ""
    cooldown_seconds: float = 0.0
    _enabled: bool = True

    def when(condition: Callable[[SelfImage], bool]) -> Rule:
        """条件工厂"""
        return Rule(condition=condition, action_item=None)  # type: ignore

    def then(self, action_item: ActionItem) -> Rule:
        """满足条件时的动作"""
        self.action_item = action_item
        return self

    def cooldown(self, key: str, seconds: float) -> Rule:
        """冷却配置"""
        self.cooldown_key = key
        self.cooldown_seconds = seconds
        return self

    def disable(self) -> Rule:
        """禁用此规则"""
        self._enabled = False
        return self

    def enabled(self) -> bool:
        return self._enabled


# ── 全局冷却记录（进程内共享）───────────────────────────────

_cooldown_last_fired: dict[str, float] = {}


def _is_cooldown_ready(key: str, seconds: float) -> bool:
    """检查冷却是否已过"""
    if not key or seconds <= 0:
        return True
    last = _cooldown_last_fired.get(key, 0)
    return (time.time() - last) >= seconds


def _record_fired(key: str) -> None:
    """记录动作已触发"""
    if key:
        _cooldown_last_fired[key] = time.time()


# ── 规则表 ─────────────────────────────────────────────────

RULES: list[Rule] = []


def _init_rules(drive_config: Any = None, living_config: Any = None) -> None:
    """初始化规则表（延迟导入避免循环依赖）

    Args:
        drive_config: DriveConfig 实例，提供欲望阈值。
        living_config: LivingConfig 实例，提供冷却时间、触发阈值等。
    """
    global RULES
    if RULES:
        return

    from .action_item import ActionItem, ActionType
    from .config import LivingConfig

    cfg = living_config or LivingConfig()
    ac = cfg.action
    cc = cfg.consciousness

    # 欲望阈值（从 DriveConfig 读取，或用默认值）
    if drive_config and hasattr(drive_config, 'desire') and hasattr(drive_config.desire, 'thresholds'):
        t = drive_config.desire.thresholds
        thr_belonging = t.belonging
        thr_cognition = t.cognition
        thr_achievement = t.achievement
        thr_expression = t.expression
    else:
        thr_belonging = 0.7
        thr_cognition = 0.8
        thr_achievement = 0.6
        thr_expression = 0.5

    # ── Intent 驱动 ─────────────────────────────────────

    # GREET 意图 → 主动问候
    RULES.append(
        Rule.when(lambda si: _has_intent(si, "GREET"))
            .then(ActionItem(
                action_type=ActionType.PROACTIVE,
                priority=0.8,
                content="",  # 由 ActionExecutor + LLM 生成
                reason="收到 GREET 意图",
                source="intent",
                cooldown_key="intent_greet",
                metadata={"intent_type": "GREET"},
            ))
            .cooldown("intent_greet", ac.intent_greet_cooldown)
    )

    # CARE 意图 → 主动关心
    RULES.append(
        Rule.when(lambda si: _has_intent(si, "CARE"))
            .then(ActionItem(
                action_type=ActionType.PROACTIVE,
                priority=0.7,
                content="",
                reason="收到 CARE 意图",
                source="intent",
                cooldown_key="intent_care",
                metadata={"intent_type": "CARE"},
            ))
            .cooldown("intent_care", ac.intent_care_cooldown)
    )

    # REFLECT 意图 → 触发 L3 深度燃烧
    RULES.append(
        Rule.when(lambda si: _has_intent(si, "REFLECT"))
            .then(ActionItem(
                action_type=ActionType.TRIGGER_L3,
                priority=0.9,
                content="",
                reason="收到 REFLECT 意图，触发深度反省",
                source="intent",
                cooldown_key="intent_reflect",
                metadata={"intent_type": "REFLECT"},
            ))
            .cooldown("intent_reflect", ac.intent_reflect_cooldown)
    )

    # ACT 意图 → 主动行动
    RULES.append(
        Rule.when(lambda si: _has_intent(si, "ACT"))
            .then(ActionItem(
                action_type=ActionType.PROACTIVE,
                priority=0.6,
                content="",
                reason="收到 ACT 意图",
                source="intent",
                cooldown_key="intent_act",
                metadata={"intent_type": "ACT"},
            ))
            .cooldown("intent_act", ac.intent_act_cooldown)
    )

    # LEARN 意图 → 主动学习
    RULES.append(
        Rule.when(lambda si: _has_intent(si, "LEARN"))
            .then(ActionItem(
                action_type=ActionType.TOOL,
                priority=0.6,
                content="learn_topic",
                reason="收到 LEARN 意图",
                source="intent",
                cooldown_key="intent_learn",
                metadata={"intent_type": "LEARN"},
            ))
            .cooldown("intent_learn", ac.intent_learn_cooldown)
    )

    # EXPRESS 意图 → 分享想法
    RULES.append(
        Rule.when(lambda si: _has_intent(si, "EXPRESS"))
            .then(ActionItem(
                action_type=ActionType.PROACTIVE,
                priority=0.6,
                content="",
                reason="收到 EXPRESS 意图",
                source="intent",
                cooldown_key="intent_express",
                metadata={"intent_type": "EXPRESS"},
            ))
            .cooldown("intent_express", ac.intent_express_cooldown)
    )

    # PROGRESS 意图 → 推进目标
    RULES.append(
        Rule.when(lambda si: _has_intent(si, "PROGRESS"))
            .then(ActionItem(
                action_type=ActionType.TOOL,
                priority=0.6,
                content="progress_goal",
                reason="收到 PROGRESS 意图",
                source="intent",
                cooldown_key="intent_progress",
                metadata={"intent_type": "PROGRESS"},
            ))
            .cooldown("intent_progress", ac.intent_progress_cooldown)
    )

    # 用户空闲 → 主动问候
    RULES.append(
        Rule.when(lambda si, t=ac.idle_trigger_seconds: si.perception.user_idle_duration > t)
            .then(ActionItem(
                action_type=ActionType.PROACTIVE,
                priority=0.7,
                content="",
                reason=f"用户空闲超过 {int(ac.idle_trigger_seconds)} 秒",
                source="idle",
                cooldown_key="idle_greet",
                metadata={"source": "idle", "idle_duration": ac.idle_trigger_seconds},
            ))
            .cooldown("idle_greet", ac.idle_greet_cooldown)
    )

    # ── System 触发 ─────────────────────────────────────

    # 能量极低 → 触发休息提示
    RULES.append(
        Rule.when(lambda si, t=cc.energy_low_threshold: _get_consciousness_facet(si).energy_level < t)
            .then(ActionItem(
                action_type=ActionType.NOTIFY,
                priority=0.4,
                content="能量不足，请注意休息",
                reason="能量极低，需要休息",
                source="system",
                cooldown_key="system_energy_low",
                metadata={},
            ))
            .cooldown("system_energy_low", 1800)
    )

    logger.info("[Rules] 已加载 %d 条触发规则", len(RULES))


# ── Helper 函数 ────────────────────────────────────────────

def _has_intent(si: SelfImage, intent_type: str) -> bool:
    """检查 SelfImage 是否有指定类型的 pending_intent"""
    pending = si.flame.intent_buffer
    return any(i.upper() == intent_type.upper() for i in pending)


class _DriveView:
    """Drive 状态视图，代理 SelfImage.body 的欲望字段"""
    def __init__(self, si: SelfImage):
        self._si = si

    @property
    def belonging(self) -> float:
        return self._si.body.desire_belonging

    @property
    def cognition(self) -> float:
        return self._si.body.desire_cognition

    @property
    def achievement(self) -> float:
        return self._si.body.desire_achievement

    @property
    def expression(self) -> float:
        return self._si.body.desire_expression


class _ConsciousnessView:
    """Consciousness 状态视图，代理 SelfImage 的意识相关字段"""
    def __init__(self, si: SelfImage):
        self._si = si

    @property
    def energy_level(self) -> float:
        return self._si.body.energy

    @property
    def intent_buffer(self) -> list[str]:
        return self._si.flame.intent_buffer

    @property
    def accumulated_changes(self) -> list[dict]:
        return self._si.flame.accumulated_changes


def _get_drive_facet(si: SelfImage):
    """从 SelfImage 获取 Drive 状态视图"""
    return _DriveView(si)


def _get_consciousness_facet(si: SelfImage):
    """从 SelfImage 获取 Consciousness 状态视图"""
    return _ConsciousnessView(si)
