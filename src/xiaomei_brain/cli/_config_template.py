"""Agent brain.yaml 模板。

首次创建 agent 时自动生成，可手动编辑。修改后重启生效。
"""

BRAIN_YAML_TEMPLATE = """\
# ============================================================
#  xiaomei-brain 进程配置
#
#  位置: ~/.xiaomei-brain/{agent_id}/brain.yaml
#  首次启动时自动生成，可手动编辑。修改后重启生效。
# ============================================================

# ────────────────────────────────────────────────────────────
#  Drive 层 — 边缘系统
#  情绪 / 激素 / 激励 / 欲望 / 能量
#  数值均为 0.0 ~ 1.0
# ────────────────────────────────────────────────────────────
drive:
  # ── 激素（慢速调质，小时级衰减）─────────────────────────
  hormone:
    # 初始值（启动/重置时的状态）
    initial:
      dopamine:    0.5     # 多巴胺 — 期待奖励，增强动机
      serotonin:   0.5     # 血清素 — 满足感，稳定情绪
      cortisol:    0.3     # 皮质醇 — 压力激素
      oxytocin:    0.5     # 催产素 — 社会连接，信任
      norepinephrine: 0.5  # 去甲肾上腺素 — 警觉，快速响应
      melatonin:   0.5     # 褪黑素 — 纯日夜节律驱动，峰值凌晨2点、谷值下午2点
    # 衰减率（每小时乘以该系数）。褪黑素由日夜节律覆盖，衰减率仅占位。
    decay_rates:
      dopamine:    0.95
      serotonin:   0.98
      cortisol:    0.9
      oxytocin:    0.95
      norepinephrine: 0.95
      melatonin:   0.95
  # ── 欲望（内在张力，驱动目标行为）───────────────────────
  desire:
    # 基础张力（初始值 / 回落目标值）
    initial:
      survival:    0.3     # 生存欲 — 资源、安全
      achievement: 0.5     # 成就欲 — 完成目标
      belonging:   0.5     # 归属欲 — 社交连接
      cognition:   0.6     # 认知欲 — 好奇、探索
      expression:  0.4     # 表达欲 — 输出、创造
    # 触发阈值（欲望超过该值 → 生成主动行为意图）
    thresholds:
      belonging:   0.7     # 归属欲阈值 → 主动问候
      cognition:   0.8     # 认知欲阈值 → 主动学习
      achievement: 0.6     # 成就欲阈值 → 推进目标
      expression:  0.7     # 表达欲阈值 → 主动输出
      survival_threatened: 0.3  # 生存欲 → 受威胁状态
      survival_dying:      0.1  # 生存欲 → 濒死状态
      survival_dead:       0.0  # 生存欲 → 死亡
    recovery_rate: 0.5      # 回升速度（每小时，乘法系数）
  # ── 情绪（快速响应，分钟级衰减）─────────────────────────
  emotion:
    decay_rate:       0.95   # 每分钟衰减系数
    min_intensity:    0.1   # 低于此强度回归 NEUTRAL
    default_duration: 60.0  # 默认持续时间（秒）
    switch_inertia:   0.7   # 情绪切换惯性（0.1=好哄，0.9=极其固执）
    # 各情绪持续时间（秒）
    durations:
      joy:     600    # 开心
      sadness: 1800   # 悲伤
      fear:    300    # 恐惧
      anger:   600    # 愤怒
  # ── 激励（RPE 奖励预测误差）─────────────────────────────
  motivation:
    rpe_coefficient:         0.5   # RPE 缩放系数
    expected_update_weight:  0.2   # 预期更新权重
  # ── 能量（综合身心状态，由激素派生）─────────────────────
  energy:
    initial: 0.8              # 初始/重置能量值

# ────────────────────────────────────────────────────────────
#  Consciousness 层 — 意识系统
#  L0 ~ L3 心跳参数 / 生命周期 / 行为 / 上下文 / 关键词
# ────────────────────────────────────────────────────────────
consciousness:
  # ── 分层心跳参数 ────────────────────────────────────────
  l0_interval:          1.0     # L0 骨架维护间隔（秒）
  l1_threshold:         60      # L1 异常检测触发（累积 L0 次数）
  l1_anomaly_enabled:   false  # L1 异常检测开关
  l2_check_interval:    10.0    # L2 检查间隔（秒）
  l2_idle_trigger:      60.0   # L2 空闲触发（用户空闲秒数）
  l2_changes_trigger:   10     # L2 累积变化触发（条数）
  l2_cooldown:          300.0   # L2 冷却时间（秒）
  l2_periodic_interval: 1800.0  # L2 定期触发（秒）
  sleep_to_dream_threshold:    300.0   # 入梦触发（睡眠秒数→入梦）
  l3_cooldown:          1800.0  # L3 深度沉思冷却（秒）
  energy_low_threshold: 0.1    # 能量极低阈值（低于→flow 最小上下文）
  energy_silent_threshold: 0.15  # 能量沉寂阈值（低于→禁止主动行为）
  # ── 生命周期参数 ────────────────────────────────────────
  living:
    tick_interval:      1.0     # 心跳间隔（秒）
    surge_interval:     60.0    # 涌动间隔（秒）
    idle_short:         60.0   # 短空闲阈值（秒）→ IDLE
    idle_threshold:     10800.0  # 长空闲阈值（秒）→ SLEEPING
    dream_interval:     3000.0   # 梦境间隔（秒）
    max_context_tokens: 50000  # 上下文最大 token 数
    daily_token_budget: 0      # 每日 token 预算（0=不限制）
    monthly_token_budget: 0    # 月度 token 预算（0=不限制）
    daily_token_reset_hour: 4  # 每日配额重置时间（0-23，默认凌晨4点）
    comms_port:         0      # 0=自动分配, -1=禁用
    ws_port:            -1      # WebSocket 端口（-1=禁用, 0=自动分配）
  # ── 行为冷却时间（秒）───────────────────────────────────
  action:
    intent_greet_cooldown:    3600.0  # 主动问候
    intent_care_cooldown:     1800.0  # 主动关怀
    intent_reflect_cooldown:  7200.0  # 反思
    intent_act_cooldown:      3600.0  # 行动
    intent_work_cooldown:     60.0    # 工作（冷却短）
    intent_learn_cooldown:    7200.0  # 学习
    intent_express_cooldown:  1800.0  # 表达
    intent_progress_cooldown: 3600.0  # 推进目标
    idle_trigger_seconds:     1800.0  # 空闲后触发问候
    idle_greet_cooldown:      1800.0  # 空闲问候冷却
    desire_greet_cooldown:    3600.0  # 欲望问候冷却
    desire_learn_cooldown:    7200.0  # 欲望学习冷却
    desire_achievement_cooldown: 3600.0  # 欲望成就冷却
    desire_express_cooldown:  3600.0  # 欲望表达冷却
    desire_talk_to_agent_cooldown: 60.0  # Agent 间聊天冷却
  # ── 上下文组装参数 ──────────────────────────────────────
  context:
    fresh_tail_count:      40   # daily 模式新鲜消息条数
    flow_tail_count:       4     # flow 模式新鲜消息条数
    reflect_tail_count:    12   # reflect 模式新鲜消息条数
    messages_per_compact:  8     # 每次压缩的消息条数
    reserved_fresh_count:   10    # 保留的新鲜消息条数
    compact_token_ratio:   0.5   # 未摘要 token 占比阈值
    compact_time_window:   7200.0  # 压缩时间窗口（秒）
    daily_max_memories:    12    # daily 模式最大记忆数
    reflect_max_memories:  15    # reflect 模式最大记忆数
    daily_min_strength:    0.6   # daily 模式最低记忆强度
    reflect_min_strength:  0.4   # reflect 模式最低记忆强度
    short_input_threshold: 15    # 短输入字符数阈值
"""
