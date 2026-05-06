"""LivingConfig: 意识生命体的统一配置。

所有硬编码的数值阈值、关键词列表集中在此，支持从 YAML 文件加载。
ConsciousLiving 和各子系统从 LivingConfig 读取配置，不再硬编码。
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# ── 意识层参数 ──────────────────────────────────────────────────────

@dataclass
class ConsciousnessConfig:
    """意识系统 L0-L3 参数"""
    l0_interval: float = 1.0          # L0 感知心跳间隔（秒）
    l1_threshold: int = 60             # L1 触发阈值（累积 L0 次数）
    l2_idle_trigger: float = 300.0    # L2 空闲触发（用户空闲秒数）
    l2_changes_trigger: int = 10       # L2 累积变化触发（条数）
    l2_cooldown: float = 300.0        # L2 冷却时间（秒）
    l2_periodic_interval: float = 600.0  # L2 定期触发（秒）
    l3_dream_interval: float = 300.0   # L3 梦境触发（睡眠秒数）
    energy_low_threshold: float = 0.3  # 能量极低阈值


# ── 生命周期参数 ────────────────────────────────────────────────────

@dataclass
class LivingParams:
    """Living 基类参数"""
    tick_interval: float = 1.0         # 心跳间隔（秒）
    surge_interval: float = 60.0       # 涌动间隔（秒）
    idle_short: float = 30.0          # 短空闲阈值（秒）→ IDLE
    idle_threshold: float = 1800.0     # 长空闲阈值（秒）→ SLEEPING
    dream_interval: float = 300.0      # 梦境间隔（秒）
    max_context_tokens: int = 50000    # 上下文最大 token 数


# ── 欲望行为参数 ────────────────────────────────────────────────────

@dataclass
class ActionConfig:
    """ActionDispatcher 规则参数"""
    # 意图冷却时间（秒）
    intent_greet_cooldown: float = 3600.0
    intent_care_cooldown: float = 1800.0
    intent_reflect_cooldown: float = 7200.0
    intent_act_cooldown: float = 3600.0

    # 空闲触发
    idle_trigger_seconds: float = 1800.0  # 用户空闲多少秒触发问候
    idle_greet_cooldown: float = 1800.0   # 空闲问候冷却

    # 欲望冷却时间（秒）
    desire_greet_cooldown: float = 3600.0
    desire_learn_cooldown: float = 7200.0
    desire_achievement_cooldown: float = 3600.0
    desire_express_cooldown: float = 3600.0


# ── 上下文组装参数 ──────────────────────────────────────────────────

@dataclass
class ContextConfig:
    """上下文组装参数"""
    # 消息尾长度
    fresh_tail_count: int = 40         # daily 模式新鲜消息条数
    flow_tail_count: int = 4           # flow 模式新鲜消息条数
    reflect_tail_count: int = 12       # reflect 模式新鲜消息条数

    # DAG 压缩
    messages_per_compact: int = 8      # 每次压缩的消息条数
    reserved_fresh_count: int = 10     # 保留的新鲜消息条数
    compact_token_ratio: float = 0.5   # 未摘要消息 token 占比阈值
    compact_time_window: float = 7200.0  # 压缩时间窗口（秒）

    # 记忆召回
    daily_max_memories: int = 12       # daily 模式最大记忆数
    reflect_max_memories: int = 15     # reflect 模式最大记忆数
    daily_min_strength: float = 0.6    # daily 模式最低记忆强度
    reflect_min_strength: float = 0.4  # reflect 模式最低记忆强度

    # 模式判断
    short_input_threshold: int = 15    # 短输入字符数阈值


# ── 关键词配置 ──────────────────────────────────────────────────────

@dataclass
class KeywordConfig:
    """中文关键词列表（供 determine_mode 使用）"""
    reflect_keywords: list[str] = field(default_factory=lambda: [
        "答对了吗", "做错了", "纠正", "不对", "反省", "反思", "我错了吗",
    ])
    past_keywords: list[str] = field(default_factory=lambda: [
        "昨天", "之前", "上次", "以前", "记得", "刚才", "那一次",
    ])
    opinion_keywords: list[str] = field(default_factory=lambda: [
        "你觉得", "你怎么看", "建议", "推荐", "你更喜欢", "你觉得我",
    ])
    personal_keywords: list[str] = field(default_factory=lambda: [
        "我心情", "我好开心", "我很难过", "你能不能", "我想要", "我感觉",
    ])
    simple_patterns: list[str] = field(default_factory=lambda: [
        "算", "计算", "翻译", "几点", "什么意思", "？", "吗", "帮我",
    ])
    continue_patterns: list[str] = field(default_factory=lambda: [
        "继续", "接着做", "还做", "再做", "延续", "持续",
    ])


# ── 统一配置 ────────────────────────────────────────────────────────

@dataclass
class LivingConfig:
    """意识生命体统一配置"""
    consciousness: ConsciousnessConfig = field(default_factory=ConsciousnessConfig)
    living: LivingParams = field(default_factory=LivingParams)
    action: ActionConfig = field(default_factory=ActionConfig)
    context: ContextConfig = field(default_factory=ContextConfig)
    keywords: KeywordConfig = field(default_factory=KeywordConfig)

    @classmethod
    def from_yaml(cls, path: str) -> LivingConfig:
        """从 YAML 文件加载配置"""
        try:
            import yaml
        except ImportError:
            logger.warning("[LivingConfig] PyYAML 未安装，使用默认配置")
            return cls()

        if not os.path.exists(path):
            logger.info("[LivingConfig] 配置文件不存在: %s，使用默认值", path)
            return cls()

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except Exception as e:
            logger.warning("[LivingConfig] 加载失败: %s，使用默认值", e)
            return cls()

        config = cls()
        _apply_dict(config.consciousness, data.get("consciousness", {}))
        _apply_dict(config.living, data.get("living", {}))
        _apply_dict(config.action, data.get("action", {}))
        _apply_dict(config.context, data.get("context", {}))
        _apply_dict(config.keywords, data.get("keywords", {}))

        logger.info("[LivingConfig] 已从 %s 加载配置", path)
        return config

    def save_yaml(self, path: str) -> None:
        """保存配置到 YAML 文件"""
        try:
            import yaml
        except ImportError:
            logger.warning("[LivingConfig] PyYAML 未安装，无法保存")
            return

        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(self._to_dict(), f, default_flow_style=False, allow_unicode=True)
        logger.info("[LivingConfig] 配置已保存到 %s", path)

    def _to_dict(self) -> dict:
        """转为嵌套字典"""
        import dataclasses
        result = {}
        for fld in dataclasses.fields(self):
            val = getattr(self, fld.name)
            if dataclasses.is_dataclass(val):
                result[fld.name] = dataclasses.asdict(val)
            else:
                result[fld.name] = val
        return result


def _apply_dict(obj, data: dict) -> None:
    """将字典值应用到 dataclass 实例（只覆盖存在的字段）"""
    import dataclasses
    for key, value in data.items():
        if hasattr(obj, key):
            current = getattr(obj, key)
            if dataclasses.is_dataclass(current) and isinstance(value, dict):
                _apply_dict(current, value)
            else:
                setattr(obj, key, value)
