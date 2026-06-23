"""LivingConfig: 意识生命体配置结构定义。

实际配置值由 config/agent_config.py 从 config.yaml 加载。
此处定义 dataclass 结构及默认值（作为 fallback）。
"""

from __future__ import annotations

from dataclasses import dataclass, field


# ── 意识层参数 ──────────────────────────────────────────────────────

@dataclass
class ConsciousnessConfig:
    """意识系统 L0-L3 参数"""
    l0_interval: float = 1.0          # L0 感知心跳间隔（秒）
    l1_threshold: int = 60             # L1 触发阈值（累积 L0 次数）
    l2_idle_trigger: float = 300.0    # L2 空闲触发（用户空闲秒数）
    l2_changes_trigger: int = 10       # L2 累积变化触发（条数）
    l2_cooldown: float = 300.0         # L2 冷却时间（秒）
    l2_periodic_interval: float = 1800.0  # L2 意图决策定期兜底（秒）
    l2_desire_thresholds: dict = field(default_factory=lambda: {
        "belonging": 0.6,
        "cognition": 0.6,
        "achievement": 0.5,
        "expression": 0.6,
    })                                 # L2 意图决策欲望驱动阈值
    l2_emergence_interval: float = 1800.0   # 意识涌现定期间隔（秒）
    l2_emergence_cooldown: float = 600.0    # 意识涌现冷却（秒）
    sleep_to_dream_threshold: float = 300.0  # 入梦触发（SLEEPING 持续秒数→入梦信号）
    l3_cooldown: float = 1800.0       # L3 沉思冷却（秒）
    sc_cooldown: float = 900.0              # social_cognition 冷却时间（秒）
    sc_interval: float = 3600.0             # social_cognition 定期兜底间隔（秒）
    sc_energy_threshold: float = 0.25       # social_cognition 最低能量阈值
    l2_check_interval: float = 10.0     # Layer 2 检查间隔（秒）
    l1_anomaly_enabled: bool = False   # L1 异常检测开关（False 时跳过所有异常检测）
    energy_low_threshold: float = 0.1  # 能量极低阈值（低于此值用flow最小上下文）
    dream_report_enabled: bool = True   # 苏醒时是否使用梦境报告（False 时苏醒走 WAIT fallback，梦境燃烧不受影响）
    energy_silent_threshold: float = 0.15  # 能量沉寂阈值（低于此值禁止主动行为）


# ── 生命周期参数 ────────────────────────────────────────────────────

@dataclass
class LivingParams:
    """Living 基类参数"""
    tick_interval: float = 1.0         # 心跳间隔（秒）
    surge_interval: float = 60.0       # 涌动间隔（秒）
    idle_short: float = 300.0         # 短空闲阈值（秒）→ IDLE
    idle_threshold: float = 10800.0    # 长空闲阈值（秒）→ SLEEPING
    dream_interval: float = 3000.0      # 梦境间隔（秒）
    max_context_tokens: int = 50000    # 上下文最大 token 数
    daily_token_budget: int = 0       # 每日 token 预算，0=不限制
    monthly_token_budget: int = 0     # 月度 token 预算，0=不限制
    daily_token_reset_hour: int = 4   # 每日 token 配额重置时间（0-23），默认凌晨 4 点
    comms_port: int = 0               # 0=自动分配, -1=禁用, >0=指定端口
    ws_port: int = -1                 # WebSocket Gateway 端口（-1=禁用, 0=自动分配, >0=指定端口）


# ── 欲望行为参数 ────────────────────────────────────────────────────

@dataclass
class ActionConfig:
    """ActionDispatcher 规则参数"""
    # 意图冷却时间（秒）
    intent_greet_cooldown: float = 3600.0
    intent_care_cooldown: float = 1800.0
    intent_reflect_cooldown: float = 7200.0
    intent_act_cooldown: float = 3600.0
    intent_work_cooldown: float = 60.0       # WORK 冷却短，允许频繁工作
    intent_learn_cooldown: float = 300.0    # 学习冷却 5 分钟
    intent_express_cooldown: float = 1800.0  # 表达冷却中等
    intent_progress_cooldown: float = 3600.0  # 推进目标冷却

    # 空闲触发
    idle_trigger_seconds: float = 1800.0  # 用户空闲多少秒触发问候
    idle_greet_cooldown: float = 1800.0   # 空闲问候冷却

    # 欲望冷却时间（秒）
    desire_greet_cooldown: float = 3600.0
    desire_learn_cooldown: float = 600.0   # 认知欲驱动学习冷却 10 分钟
    desire_achievement_cooldown: float = 3600.0
    desire_express_cooldown: float = 3600.0
    desire_talk_to_agent_cooldown: float = 60.0  # 主动和其他 agent 聊天冷却（测试：1分钟）

    # 欲望驱动行为开关
    learn_enabled: bool = True           # 认知欲驱动学习
    pleasure_enabled: bool = True        # 快乐中枢驱动行为


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
