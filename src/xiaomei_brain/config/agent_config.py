"""AgentConfig: 进程级统一配置。

一个 agent 一个配置文件：~/.xiaomei-brain/{agent_id}/config.yaml

YAML 结构：
    drive:
      hormone:
        initial: {dopamine: 0.5, serotonin: 0.5, ...}
        decay_rates: {dopamine: 0.95, serotonin: 0.98, ...}
      desire:
        initial: {survival: 0.3, achievement: 0.5, ...}
        thresholds: {belonging: 0.7, cognition: 0.8, ...}
        recovery_rate: 0.05
      emotion: {decay_rate: 0.95, min_intensity: 0.1, default_duration: 60.0}
      motivation: {rpe_coefficient: 0.5, expected_update_weight: 0.2}
      energy: {initial: 0.8}
    consciousness:
      l0_interval: 1.0
      ...

Usage:
    config = load_agent_config("xiaomei")
    drive_cfg = config.drive        # DriveConfig
    living_cfg = config.consciousness  # LivingConfig
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ── 默认值（只在此处定义一次）──────────────────────────────────────────

HORMONE_INITIAL_DEFAULTS = {
    "dopamine": 0.5,
    "serotonin": 0.5,
    "cortisol": 0.3,
    "oxytocin": 0.5,
    "norepinephrine": 0.5,
}

HORMONE_DECAY_RATES_DEFAULTS = {
    "dopamine": 0.95,
    "serotonin": 0.98,
    "cortisol": 0.90,
    "oxytocin": 0.99,
    "norepinephrine": 0.95,
}

DESIRE_INITIAL_DEFAULTS = {
    "survival": 0.3,
    "achievement": 0.5,
    "belonging": 0.5,
    "cognition": 0.6,
    "expression": 0.4,
    "significance": 0.6,
}

DESIRE_THRESHOLDS_DEFAULTS = {
    "belonging": 0.7,
    "cognition": 0.8,
    "achievement": 0.6,
    "expression": 0.5,
    "significance_low": 0.3,
    "survival_threatened": 0.3,
    "survival_dying": 0.1,
    "survival_dead": 0.0,
}


def _deep_merge(base: dict, override: dict) -> dict:
    """递归合并字典，override 中的值覆盖 base"""
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def _config_dir(agent_id: str) -> Path:
    """Agent 配置目录"""
    return Path.home() / ".xiaomei-brain" / agent_id


def _config_path(agent_id: str) -> Path:
    """共享配置文件路径"""
    return _config_dir(agent_id) / "config.yaml"


def _drive_config_path(agent_id: str) -> Path:
    """旧 Drive 配置文件路径（用于迁移）"""
    return _config_dir(agent_id) / "drive" / "drive_config.yaml"


# ── AgentConfig ────────────────────────────────────────────────────────


@dataclass
class AdminConfig:
    """Admin 管理门配置。"""
    token: str = ""


@dataclass
class AgentConfig:
    """进程级统一配置。

    包含 drive / consciousness / admin 三大段。
    drive 段使用 drive.config.DriveConfig 结构。
    consciousness 段使用 consciousness.config.LivingConfig 结构。
    """
    drive: Any = field(default_factory=lambda: _default_drive_config())
    consciousness: Any = field(default_factory=lambda: _default_living_config())
    admin: AdminConfig = field(default_factory=AdminConfig)

    @classmethod
    def from_yaml(cls, agent_id: str) -> AgentConfig:
        """从共享配置文件加载。

        Args:
            agent_id: Agent ID（如 "xiaomei"）

        Returns:
            AgentConfig 实例。如果文件不存在则返回默认配置并自动创建文件。
        """
        path = _config_path(agent_id)

        # 如果共享配置不存在，尝试从旧驱动配置迁移
        if not path.exists():
            cls._migrate_if_needed(agent_id)
            # 如果迁移后还不存在，创建默认文件
            if not path.exists():
                _create_default_config_file(agent_id)
                logger.info("[AgentConfig] 已创建默认配置: %s", path)

        try:
            import yaml
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except Exception as e:
            logger.warning("[AgentConfig] 加载失败，使用默认配置: %s", e)
            return cls()

        drive_data = data.get("drive", {})
        consciousness_data = data.get("consciousness", {})
        admin_data = data.get("admin", {})

        drive_cfg = _build_drive_config(drive_data)
        living_cfg = _build_living_config(consciousness_data)
        admin_cfg = AdminConfig(token=admin_data.get("token", ""))

        config = cls(drive=drive_cfg, consciousness=living_cfg, admin=admin_cfg)
        logger.info("[AgentConfig] 已从 %s 加载", path)
        return config

    @classmethod
    def _migrate_if_needed(cls, agent_id: str) -> None:
        """如果存在旧的 drive_config.yaml，迁移内容到新的 config.yaml"""
        old_path = _drive_config_path(agent_id)
        if not old_path.exists():
            return

        try:
            import yaml
            with open(old_path, "r", encoding="utf-8") as f:
                old_data = yaml.safe_load(f) or {}

            # 构建新的 drive 段
            new_data = {"drive": _migrate_drive_data(old_data), "consciousness": {}}

            path = _config_path(agent_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            _save_yaml(path, new_data)

            # 重命名旧文件为 .bak
            bak_path = old_path.with_suffix(".yaml.bak")
            old_path.rename(bak_path)

            logger.info(
                "[AgentConfig] 已迁移 %s → %s",
                old_path, path,
            )
        except Exception as e:
            logger.warning("[AgentConfig] 迁移失败: %s", e)

    def to_dict(self) -> dict:
        """转为嵌套字典（用于 YAML 序列化）"""
        import dataclasses

        result: dict[str, Any] = {}

        # drive 段
        drive = {}
        dc = self.drive
        drive["hormone"] = {
            "initial": dict(getattr(dc.hormone, "defaults", HORMONE_INITIAL_DEFAULTS)),
            "decay_rates": dict(getattr(dc.hormone, "decay_rates", HORMONE_DECAY_RATES_DEFAULTS)),
        }

        desire = {}
        if hasattr(dc.desire, "survival"):
            desire["initial"] = {
                "survival": dc.desire.survival,
                "achievement": dc.desire.achievement,
                "belonging": dc.desire.belonging,
                "cognition": dc.desire.cognition,
                "expression": dc.desire.expression,
            }
        if hasattr(dc.desire, "thresholds"):
            desire["thresholds"] = dataclasses.asdict(dc.desire.thresholds)
        desire["recovery_rate"] = dc.desire.recovery_rate
        drive["desire"] = desire

        drive["emotion"] = dataclasses.asdict(dc.emotion)
        drive["motivation"] = dataclasses.asdict(dc.motivation)
        drive["energy"] = {"initial": 0.8}  # EnergyState 默认值

        result["drive"] = drive

        # consciousness 段
        result["consciousness"] = _living_config_to_dict(self.consciousness)

        return result

    def save(self, agent_id: str) -> None:
        """保存配置到文件"""
        path = _config_path(agent_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        _save_yaml(path, self.to_dict())
        logger.info("[AgentConfig] 已保存到 %s", path)


# ── 便捷函数 ───────────────────────────────────────────────────────────


def load_agent_config(agent_id: str) -> AgentConfig:
    """加载 Agent 统一配置。"""
    return AgentConfig.from_yaml(agent_id)


def save_agent_config(agent_id: str, config: AgentConfig) -> None:
    """保存 Agent 统一配置。"""
    config.save(agent_id)


# ── 内部辅助 ───────────────────────────────────────────────────────────


def _default_drive_config():
    """创建默认 DriveConfig"""
    from ..drive.config import DriveConfig, DesireConfig, DesireThresholds, EmotionConfig, HormoneConfig, MotivationConfig

    desire = DesireConfig(
        survival=DESIRE_INITIAL_DEFAULTS["survival"],
        achievement=DESIRE_INITIAL_DEFAULTS["achievement"],
        belonging=DESIRE_INITIAL_DEFAULTS["belonging"],
        cognition=DESIRE_INITIAL_DEFAULTS["cognition"],
        expression=DESIRE_INITIAL_DEFAULTS["expression"],
        significance=DESIRE_INITIAL_DEFAULTS["significance"],
        thresholds=DesireThresholds(
            belonging=DESIRE_THRESHOLDS_DEFAULTS["belonging"],
            cognition=DESIRE_THRESHOLDS_DEFAULTS["cognition"],
            achievement=DESIRE_THRESHOLDS_DEFAULTS["achievement"],
            expression=DESIRE_THRESHOLDS_DEFAULTS["expression"],
        ),
    )
    emotion = EmotionConfig()
    hormone = HormoneConfig(
        decay_rates=dict(HORMONE_DECAY_RATES_DEFAULTS),
        defaults=dict(HORMONE_INITIAL_DEFAULTS),
    )
    motivation = MotivationConfig()
    return DriveConfig(desire=desire, emotion=emotion, hormone=hormone, motivation=motivation)


def _default_living_config():
    """创建默认 LivingConfig"""
    from ..consciousness.config import LivingConfig
    return LivingConfig()


def _build_drive_config(data: dict):
    """从 YAML dict 构建 DriveConfig"""
    from ..drive.config import DriveConfig, DesireConfig, DesireThresholds, EmotionConfig, HormoneConfig, MotivationConfig

    # hormone
    h = data.get("hormone", {})
    hormone = HormoneConfig(
        decay_rates={**HORMONE_DECAY_RATES_DEFAULTS, **h.get("decay_rates", {})},
        defaults={**HORMONE_INITIAL_DEFAULTS, **h.get("initial", {})},
    )

    # desire
    d = data.get("desire", {})
    initial = d.get("initial", {})
    thresholds = d.get("thresholds", {})
    desire = DesireConfig(
        survival=initial.get("survival", DESIRE_INITIAL_DEFAULTS["survival"]),
        achievement=initial.get("achievement", DESIRE_INITIAL_DEFAULTS["achievement"]),
        belonging=initial.get("belonging", DESIRE_INITIAL_DEFAULTS["belonging"]),
        cognition=initial.get("cognition", DESIRE_INITIAL_DEFAULTS["cognition"]),
        expression=initial.get("expression", DESIRE_INITIAL_DEFAULTS["expression"]),
        significance=initial.get("significance", DESIRE_INITIAL_DEFAULTS["significance"]),
        thresholds=DesireThresholds(
            belonging=thresholds.get("belonging", DESIRE_THRESHOLDS_DEFAULTS["belonging"]),
            cognition=thresholds.get("cognition", DESIRE_THRESHOLDS_DEFAULTS["cognition"]),
            achievement=thresholds.get("achievement", DESIRE_THRESHOLDS_DEFAULTS["achievement"]),
            expression=thresholds.get("expression", DESIRE_THRESHOLDS_DEFAULTS["expression"]),
            survival_threatened=thresholds.get("survival_threatened", DESIRE_THRESHOLDS_DEFAULTS["survival_threatened"]),
            survival_dying=thresholds.get("survival_dying", DESIRE_THRESHOLDS_DEFAULTS["survival_dying"]),
            survival_dead=thresholds.get("survival_dead", DESIRE_THRESHOLDS_DEFAULTS["survival_dead"]),
            significance_low=thresholds.get("significance_low", DESIRE_THRESHOLDS_DEFAULTS.get("significance_low", 0.3)),
        ),
        recovery_rate=d.get("recovery_rate", 0.5),
        significance_decay_hourly=d.get("significance_decay_hourly", 0.02),
    )

    # emotion
    e = data.get("emotion", {})
    durations_defaults = {"joy": 600, "sadness": 1800, "fear": 300, "anger": 600}
    emotion = EmotionConfig(
        decay_rate=e.get("decay_rate", 0.95),
        min_intensity=e.get("min_intensity", 0.1),
        default_duration=e.get("default_duration", 60.0),
        switch_inertia=e.get("switch_inertia", 0.7),
        durations={**durations_defaults, **e.get("durations", {})},
    )

    # motivation
    m = data.get("motivation", {})
    motivation = MotivationConfig(
        rpe_coefficient=m.get("rpe_coefficient", 0.5),
        expected_update_weight=m.get("expected_update_weight", 0.2),
    )

    return DriveConfig(desire=desire, emotion=emotion, hormone=hormone, motivation=motivation)


def _build_living_config(data: dict):
    """从 YAML dict 构建 LivingConfig"""
    from ..consciousness.config import LivingConfig, ConsciousnessConfig, LivingParams, ActionConfig, ContextConfig, KeywordConfig

    config = LivingConfig()

    if data:
        cc = data
        config.consciousness = ConsciousnessConfig(
            l0_interval=cc.get("l0_interval", 1.0),
            l1_threshold=cc.get("l1_threshold", 60),
            l2_idle_trigger=cc.get("l2_idle_trigger", 300.0),
            l2_changes_trigger=cc.get("l2_changes_trigger", 10),
            l2_cooldown=cc.get("l2_cooldown", 300.0),
            l2_periodic_interval=cc.get("l2_periodic_interval", 1800.0),
            sleep_to_dream_threshold=cc.get("sleep_to_dream_threshold", cc.get("l3_dream_interval", 300.0)),
            l3_cooldown=cc.get("l3_cooldown", 1800.0),
            l2_check_interval=cc.get("l2_check_interval", 10.0),
            l1_anomaly_enabled=cc.get("l1_anomaly_enabled", False),
            dream_report_enabled=cc.get("dream_report_enabled", True),
            energy_low_threshold=cc.get("energy_low_threshold", 0.1),
            energy_silent_threshold=cc.get("energy_silent_threshold", 0.15),
            sc_cooldown=cc.get("sc_cooldown", 900.0),
            sc_interval=cc.get("sc_interval", 3600.0),
            sc_energy_threshold=cc.get("sc_energy_threshold", 0.25),
        )

        living = data.get("living", {})
        if living:
            config.living = LivingParams(
                tick_interval=living.get("tick_interval", 1.0),
                surge_interval=living.get("surge_interval", 60.0),
                idle_short=living.get("idle_short", 300.0),
                idle_threshold=living.get("idle_threshold", 10800.0),
                dream_interval=living.get("dream_interval", 3000.0),
                max_context_tokens=living.get("max_context_tokens", 50000),
                daily_token_budget=living.get("daily_token_budget", 0),
                monthly_token_budget=living.get("monthly_token_budget", 0),
                daily_token_reset_hour=living.get("daily_token_reset_hour", 4),
                comms_port=living.get("comms_port", 0),
                ws_port=living.get("ws_port", -1),
            )

        action = data.get("action", {})
        if action:
            config.action = ActionConfig(
                intent_greet_cooldown=action.get("intent_greet_cooldown", 3600.0),
                intent_care_cooldown=action.get("intent_care_cooldown", 1800.0),
                intent_reflect_cooldown=action.get("intent_reflect_cooldown", 7200.0),
                intent_act_cooldown=action.get("intent_act_cooldown", 3600.0),
                intent_work_cooldown=action.get("intent_work_cooldown", 60.0),
                intent_learn_cooldown=action.get("intent_learn_cooldown", 7200.0),
                intent_express_cooldown=action.get("intent_express_cooldown", 1800.0),
                intent_progress_cooldown=action.get("intent_progress_cooldown", 3600.0),
                idle_trigger_seconds=action.get("idle_trigger_seconds", 1800.0),
                idle_greet_cooldown=action.get("idle_greet_cooldown", 1800.0),
                desire_greet_cooldown=action.get("desire_greet_cooldown", 3600.0),
                desire_learn_cooldown=action.get("desire_learn_cooldown", 7200.0),
                desire_achievement_cooldown=action.get("desire_achievement_cooldown", 3600.0),
                desire_express_cooldown=action.get("desire_express_cooldown", 3600.0),
                desire_talk_to_agent_cooldown=action.get("desire_talk_to_agent_cooldown", 60.0),
                learn_enabled=action.get("learn_enabled", True),
                pleasure_enabled=action.get("pleasure_enabled", True),
            )

        context = data.get("context", {})
        if context:
            config.context = ContextConfig(
                fresh_tail_count=context.get("fresh_tail_count", 40),
                flow_tail_count=context.get("flow_tail_count", 4),
                reflect_tail_count=context.get("reflect_tail_count", 12),
                messages_per_compact=context.get("messages_per_compact", 8),
                reserved_fresh_count=context.get("reserved_fresh_count", 10),
                compact_token_ratio=context.get("compact_token_ratio", 0.5),
                compact_time_window=context.get("compact_time_window", 7200.0),
                daily_max_memories=context.get("daily_max_memories", 12),
                reflect_max_memories=context.get("reflect_max_memories", 15),
                daily_min_strength=context.get("daily_min_strength", 0.6),
                reflect_min_strength=context.get("reflect_min_strength", 0.4),
                short_input_threshold=context.get("short_input_threshold", 15),
            )

        keywords = data.get("keywords", {})
        if keywords:
            config.keywords = KeywordConfig(
                reflect_keywords=keywords.get("reflect_keywords", config.keywords.reflect_keywords),
                past_keywords=keywords.get("past_keywords", config.keywords.past_keywords),
                opinion_keywords=keywords.get("opinion_keywords", config.keywords.opinion_keywords),
                personal_keywords=keywords.get("personal_keywords", config.keywords.personal_keywords),
                simple_patterns=keywords.get("simple_patterns", config.keywords.simple_patterns),
                continue_patterns=keywords.get("continue_patterns", config.keywords.continue_patterns),
            )

    return config


def _living_config_to_dict(living_config) -> dict:
    """LivingConfig → dict"""
    import dataclasses
    result = dataclasses.asdict(living_config.consciousness)

    living_dict = dataclasses.asdict(living_config.living)
    action_dict = dataclasses.asdict(living_config.action)
    context_dict = dataclasses.asdict(living_config.context)
    keywords_dict = dataclasses.asdict(living_config.keywords)

    result["living"] = living_dict
    result["action"] = action_dict
    result["context"] = context_dict
    result["keywords"] = keywords_dict
    return result


def _migrate_drive_data(old_data: dict) -> dict:
    """将旧 drive_config.yaml 格式转换为新格式"""
    new: dict[str, Any] = {}

    # hormone
    new["hormone"] = {
        "initial": dict(HORMONE_INITIAL_DEFAULTS),
        "decay_rates": old_data.get("hormone", {}).get("decay_rates", HORMONE_DECAY_RATES_DEFAULTS),
    }

    # desire
    d = old_data.get("desire", {})
    new["desire"] = {
        "initial": {
            "survival": d.get("survival", DESIRE_INITIAL_DEFAULTS["survival"]),
            "achievement": d.get("achievement", DESIRE_INITIAL_DEFAULTS["achievement"]),
            "belonging": d.get("belonging", DESIRE_INITIAL_DEFAULTS["belonging"]),
            "cognition": d.get("cognition", DESIRE_INITIAL_DEFAULTS["cognition"]),
            "expression": d.get("expression", DESIRE_INITIAL_DEFAULTS["expression"]),
            "significance": d.get("significance", DESIRE_INITIAL_DEFAULTS["significance"]),
        },
        "thresholds": d.get("thresholds", DESIRE_THRESHOLDS_DEFAULTS),
        "recovery_rate": d.get("recovery_rate", 0.05),
    }

    # emotion
    e = old_data.get("emotion", {})
    new["emotion"] = {
        "decay_rate": e.get("decay_rate", 0.95),
        "min_intensity": e.get("min_intensity", 0.1),
        "default_duration": e.get("default_duration", 60.0),
        "switch_inertia": e.get("switch_inertia", 0.7),
        "durations": e.get("durations", {"joy": 600, "sadness": 1800, "fear": 300, "anger": 600}),
    }

    # motivation
    m = old_data.get("motivation", {})
    new["motivation"] = {
        "rpe_coefficient": m.get("rpe_coefficient", 0.5),
        "expected_update_weight": m.get("expected_update_weight", 0.2),
    }

    new["energy"] = {"initial": 0.8}
    return new


def _create_default_config_file(agent_id: str) -> None:
    """创建默认配置文件"""
    config = AgentConfig()
    config.save(agent_id)


def _save_yaml(path: Path, data: dict) -> None:
    """写入 YAML 文件（格式化，带注释和分隔符）"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(_format_config_yaml(data))


def _format_config_yaml(data: dict) -> str:
    """生成格式化的 YAML 字符串，包含注释和分隔符。

    不使用 yaml.dump()，因为需要保留注释和分组说明。
    """
    lines = []
    _w = lines.append

    _w("# ============================================================")
    _w("#  xiaomei-brain 进程配置")
    _w("# ")
    _w("#  位置: ~/.xiaomei-brain/{agent_id}/config.yaml")
    _w("#  首次启动时自动生成，可手动编辑。修改后重启生效。")
    _w("# ============================================================")
    _w("")

    # ── drive ──
    drive = data.get("drive", {})
    _w("# ────────────────────────────────────────────────────────────")
    _w("#  Drive 层 — 边缘系统")
    _w("#  情绪 / 激素 / 激励 / 欲望 / 能量")
    _w("#  数值均为 0.0 ~ 1.0")
    _w("# ────────────────────────────────────────────────────────────")
    _w("drive:")

    # hormone
    hormone = drive.get("hormone", {})
    _w("  # ── 激素（慢速调质，小时级衰减）─────────────────────────")
    _w("  hormone:")
    _w("    # 初始值（启动/重置时的状态）")
    _w("    initial:")
    _fmt_initial = hormone.get("initial", {})
    _w(f"      dopamine:    {_fmt_initial.get('dopamine', 0.5)}     # 多巴胺 — 期待奖励，增强动机")
    _w(f"      serotonin:   {_fmt_initial.get('serotonin', 0.5)}     # 血清素 — 满足感，稳定情绪")
    _w(f"      cortisol:    {_fmt_initial.get('cortisol', 0.3)}     # 皮质醇 — 压力激素")
    _w(f"      oxytocin:    {_fmt_initial.get('oxytocin', 0.5)}     # 催产素 — 社会连接，信任")
    _w(f"      norepinephrine: {_fmt_initial.get('norepinephrine', 0.5)}  # 去甲肾上腺素 — 警觉，快速响应")
    _w("    # 衰减率（每小时乘以该系数）")
    _w("    decay_rates:")
    _fmt_decay = hormone.get("decay_rates", {})
    _w(f"      dopamine:    {_fmt_decay.get('dopamine', 0.95)}")
    _w(f"      serotonin:   {_fmt_decay.get('serotonin', 0.98)}")
    _w(f"      cortisol:    {_fmt_decay.get('cortisol', 0.90)}")
    _w(f"      oxytocin:    {_fmt_decay.get('oxytocin', 0.99)}")
    _w(f"      norepinephrine: {_fmt_decay.get('norepinephrine', 0.95)}")

    # desire
    desire = drive.get("desire", {})
    _w("  # ── 欲望（内在张力，驱动目标行为）───────────────────────")
    _w("  desire:")
    _w("    # 基础张力（初始值 / 回落目标值）")
    _w("    initial:")
    _fmt_desire_init = desire.get("initial", {})
    _w(f"      survival:    {_fmt_desire_init.get('survival', 0.3)}     # 生存欲 — 资源、安全")
    _w(f"      achievement: {_fmt_desire_init.get('achievement', 0.5)}     # 成就欲 — 完成目标")
    _w(f"      belonging:   {_fmt_desire_init.get('belonging', 0.5)}     # 归属欲 — 社交连接")
    _w(f"      cognition:   {_fmt_desire_init.get('cognition', 0.6)}     # 认知欲 — 好奇、探索")
    _w(f"      expression:  {_fmt_desire_init.get('expression', 0.4)}     # 表达欲 — 输出、创造")
    _w("    # 触发阈值（欲望超过该值 → 生成主动行为意图）")
    _w("    thresholds:")
    _fmt_thresh = desire.get("thresholds", {})
    _w(f"      belonging:   {_fmt_thresh.get('belonging', 0.7)}     # 归属欲阈值 → 主动问候")
    _w(f"      cognition:   {_fmt_thresh.get('cognition', 0.8)}     # 认知欲阈值 → 主动学习")
    _w(f"      achievement: {_fmt_thresh.get('achievement', 0.6)}     # 成就欲阈值 → 推进目标")
    _w(f"      expression:  {_fmt_thresh.get('expression', 0.5)}     # 表达欲阈值 → 主动输出")
    _w(f"      survival_threatened: {_fmt_thresh.get('survival_threatened', 0.3)}   # 生存欲 → 受威胁状态")
    _w(f"      survival_dying:      {_fmt_thresh.get('survival_dying', 0.1)}   # 生存欲 → 濒死状态")
    _w(f"      survival_dead:       {_fmt_thresh.get('survival_dead', 0.0)}   # 生存欲 → 死亡")
    _w(f"    recovery_rate: {desire.get('recovery_rate', 0.5)}     # 回升速度（每小时，乘法）")

    # emotion
    emotion = drive.get("emotion", {})
    _w("  # ── 情绪（快速响应，分钟级衰减）─────────────────────────")
    _w("  emotion:")
    _w(f"    decay_rate:       {emotion.get('decay_rate', 0.95)}   # 每分钟衰减系数")
    _w(f"    min_intensity:    {emotion.get('min_intensity', 0.1)}   # 低于此强度回归 NEUTRAL")
    _w(f"    default_duration: {emotion.get('default_duration', 60.0)}  # 默认持续时间（秒）")
    _w(f"    switch_inertia:   {emotion.get('switch_inertia', 0.7)}   # 情绪切换惯性（0.1=好哄，0.9=极其固执）")
    _w("    # 各情绪持续时间（秒）")
    _fmt_durations = emotion.get("durations", {"joy": 600, "sadness": 1800, "fear": 300, "anger": 600})
    _w("    durations:")
    _w(f"      joy:     {_fmt_durations.get('joy', 600)}    # 开心")
    _w(f"      sadness: {_fmt_durations.get('sadness', 1800)}  # 悲伤")
    _w(f"      fear:    {_fmt_durations.get('fear', 300)}    # 恐惧")
    _w(f"      anger:   {_fmt_durations.get('anger', 600)}    # 愤怒")

    # motivation
    motivation = drive.get("motivation", {})
    _w("  # ── 激励（RPE 奖励预测误差）─────────────────────────────")
    _w("  motivation:")
    _w(f"    rpe_coefficient:         {motivation.get('rpe_coefficient', 0.5)}   # RPE 缩放系数")
    _w(f"    expected_update_weight:  {motivation.get('expected_update_weight', 0.2)}   # 预期更新权重")

    # energy
    energy = drive.get("energy", {})
    _w("  # ── 能量（综合身心状态，由激素派生）─────────────────────")
    _w("  energy:")
    _w(f"    initial: {energy.get('initial', 0.8)}              # 初始/重置能量值")

    _w("")

    # ── consciousness ──
    consciousness = data.get("consciousness", {})
    _w("# ────────────────────────────────────────────────────────────")
    _w("#  Consciousness 层 — 意识系统")
    _w("#  L0 ~ L3 心跳参数 / 生命周期 / 行为 / 上下文 / 关键词")
    _w("# ────────────────────────────────────────────────────────────")
    _w("consciousness:")

    # L0-L3 params
    _w("  # ── 分层心跳参数 ────────────────────────────────────────")
    _w(f"  l0_interval:          {consciousness.get('l0_interval', 1.0)}     # L0 骨架维护间隔（秒）")
    _w(f"  l1_threshold:         {consciousness.get('l1_threshold', 60)}      # L1 异常检测触发（累积 L0 次数）")
    _w(f"  l1_anomaly_enabled:   {str(consciousness.get('l1_anomaly_enabled', False)).lower()}  # L1 异常检测开关")
    _w(f"  l2_check_interval:    {consciousness.get('l2_check_interval', 10.0)}    # L2 检查间隔（秒）")
    _w(f"  l2_idle_trigger:      {consciousness.get('l2_idle_trigger', 300.0)}   # L2 空闲触发（用户空闲秒数）")
    _w(f"  l2_changes_trigger:   {consciousness.get('l2_changes_trigger', 10)}     # L2 累积变化触发（条数）")
    _w(f"  l2_cooldown:          {consciousness.get('l2_cooldown', 300.0)}   # L2 冷却时间（秒）")
    _w(f"  l2_periodic_interval: {consciousness.get('l2_periodic_interval', 1800.0)}  # L2 定期触发（秒）")
    _w(f"  sleep_to_dream_threshold: {consciousness.get('sleep_to_dream_threshold', consciousness.get('l3_dream_interval', 300.0))}   # 入梦触发（睡眠秒数→入梦）")
    _w(f"  l3_cooldown:          {consciousness.get('l3_cooldown', 1800.0)}  # L3 沉思冷却（秒）")
    _w(f"  sc_cooldown:          {consciousness.get('sc_cooldown', 900.0)}    # social_cognition 冷却（秒）")
    _w(f"  sc_interval:          {consciousness.get('sc_interval', 3600.0)}   # social_cognition 定期兜底（秒）")
    _w(f"  sc_energy_threshold:  {consciousness.get('sc_energy_threshold', 0.25)}   # social_cognition 最低能量")
    _w(f"  energy_low_threshold: {consciousness.get('energy_low_threshold', 0.1)}    # 能量极低阈值（低于→flow 最小上下文）")
    _w(f"  energy_silent_threshold: {consciousness.get('energy_silent_threshold', 0.15)}  # 能量沉寂阈值（低于→禁止主动行为）")

    # living
    living = consciousness.get("living", {})
    _w("  # ── 生命周期参数 ────────────────────────────────────────")
    _w("  living:")
    _w(f"    tick_interval:      {living.get('tick_interval', 1.0)}     # 心跳间隔（秒）")
    _w(f"    surge_interval:     {living.get('surge_interval', 60.0)}    # 涌动间隔（秒）")
    _w(f"    idle_short:         {living.get('idle_short', 300.0)}   # 短空闲阈值（秒）→ IDLE")
    _w(f"    idle_threshold:     {living.get('idle_threshold', 10800.0)}  # 长空闲阈值（秒）→ SLEEPING")
    _w(f"    dream_interval:     {living.get('dream_interval', 3000.0)}   # 梦境间隔（秒）")
    _w(f"    max_context_tokens: {living.get('max_context_tokens', 50000)}  # 上下文最大 token 数")
    _w(f"    comms_port:         {living.get('comms_port', 0)}      # 0=自动分配, -1=禁用")
    _w(f"    ws_port:            {living.get('ws_port', -1)}      # WebSocket 端口（-1=禁用）")

    # action
    action = consciousness.get("action", {})
    _w("  # ── 行为冷却时间（秒）───────────────────────────────────")
    _w("  action:")
    _w(f"    intent_greet_cooldown:    {action.get('intent_greet_cooldown', 3600.0)}  # 主动问候")
    _w(f"    intent_care_cooldown:     {action.get('intent_care_cooldown', 1800.0)}  # 主动关怀")
    _w(f"    intent_reflect_cooldown:  {action.get('intent_reflect_cooldown', 7200.0)}  # 反思")
    _w(f"    intent_act_cooldown:      {action.get('intent_act_cooldown', 3600.0)}  # 行动")
    _w(f"    intent_work_cooldown:     {action.get('intent_work_cooldown', 60.0)}    # 工作（冷却短）")
    _w(f"    intent_learn_cooldown:    {action.get('intent_learn_cooldown', 7200.0)}  # 学习")
    _w(f"    intent_express_cooldown:  {action.get('intent_express_cooldown', 1800.0)}  # 表达")
    _w(f"    intent_progress_cooldown: {action.get('intent_progress_cooldown', 3600.0)}  # 推进目标")
    _w(f"    idle_trigger_seconds:     {action.get('idle_trigger_seconds', 1800.0)}  # 空闲后触发问候")
    _w(f"    idle_greet_cooldown:      {action.get('idle_greet_cooldown', 1800.0)}  # 空闲问候冷却")
    _w(f"    desire_greet_cooldown:    {action.get('desire_greet_cooldown', 3600.0)}  # 欲望问候冷却")
    _w(f"    desire_learn_cooldown:    {action.get('desire_learn_cooldown', 7200.0)}  # 欲望学习冷却")
    _w(f"    desire_achievement_cooldown: {action.get('desire_achievement_cooldown', 3600.0)}  # 欲望成就冷却")
    _w(f"    desire_express_cooldown:  {action.get('desire_express_cooldown', 3600.0)}  # 欲望表达冷却")
    _w(f"    desire_talk_to_agent_cooldown: {action.get('desire_talk_to_agent_cooldown', 60.0)}  # Agent 间聊天冷却")

    # context
    context = consciousness.get("context", {})
    _w("  # ── 上下文组装参数 ──────────────────────────────────────")
    _w("  context:")
    _w(f"    fresh_tail_count:      {context.get('fresh_tail_count', 40)}   # daily 模式新鲜消息条数")
    _w(f"    flow_tail_count:       {context.get('flow_tail_count', 4)}     # flow 模式新鲜消息条数")
    _w(f"    reflect_tail_count:    {context.get('reflect_tail_count', 12)}   # reflect 模式新鲜消息条数")
    _w(f"    messages_per_compact:  {context.get('messages_per_compact', 8)}     # 每次压缩的消息条数")
    _w(f"    reserved_fresh_count:  {context.get('reserved_fresh_count', 10)}    # 保留的新鲜消息条数")
    _w(f"    compact_token_ratio:   {context.get('compact_token_ratio', 0.5)}   # 未摘要 token 占比阈值")
    _w(f"    compact_time_window:   {context.get('compact_time_window', 7200.0)}  # 压缩时间窗口（秒）")
    _w(f"    daily_max_memories:    {context.get('daily_max_memories', 12)}    # daily 模式最大记忆数")
    _w(f"    reflect_max_memories:  {context.get('reflect_max_memories', 15)}    # reflect 模式最大记忆数")
    _w(f"    daily_min_strength:    {context.get('daily_min_strength', 0.6)}   # daily 模式最低记忆强度")
    _w(f"    reflect_min_strength:  {context.get('reflect_min_strength', 0.4)}   # reflect 模式最低记忆强度")
    _w(f"    short_input_threshold: {context.get('short_input_threshold', 15)}    # 短输入字符数阈值")

    # keywords
    keywords = consciousness.get("keywords", {})
    _w("  # ── 模式识别关键词 ──────────────────────────────────────")
    _w("  keywords:")
    _w("    # 反思模式触发词")
    _w(f"    reflect_keywords: {_fmt_list(keywords.get('reflect_keywords', []))}")
    _w("    # 回忆/过去触发词")
    _w(f"    past_keywords: {_fmt_list(keywords.get('past_keywords', []))}")
    _w("    # 征求意见触发词")
    _w(f"    opinion_keywords: {_fmt_list(keywords.get('opinion_keywords', []))}")
    _w("    # 个人情感触发词")
    _w(f"    personal_keywords: {_fmt_list(keywords.get('personal_keywords', []))}")
    _w("    # 简单任务触发模式")
    _w(f"    simple_patterns: {_fmt_list(keywords.get('simple_patterns', []))}")
    _w("    # 延续任务触发词")
    _w(f"    continue_patterns: {_fmt_list(keywords.get('continue_patterns', []))}")

    _w("")
    return "\n".join(lines)


def _fmt_list(items: list) -> str:
    """将列表格式化为 YAML 行内数组"""
    if not items:
        return "[]"
    inner = ", ".join(repr(item) if isinstance(item, str) and _needs_quoting(item) else item
                      for item in items)
    return f"[{inner}]"


def _needs_quoting(s: str) -> bool:
    """判断字符串是否需要 YAML 引号"""
    import re
    return bool(re.search(r'[:#\{\}\[\],&*!|>\'"@`\-]|\s', s)) or s in ("true", "false", "null", "yes", "no")
