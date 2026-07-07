# 驱动层（Drive）详解

> 对应目录：`src/xiaomei_brain/drive/`
>
> Drive 层是"边缘系统"——连接目的和行动的桥梁。

---

## 核心理念

**Purpose 设定方向，Drive 提供能量。**

```
没有 Drive：
用户说"帮我写代码" → Agent 写代码 → 完成 → 结束
                        ↓
                  没有动力，没有感受，没有"想要"

有 Drive：
用户说"帮我写代码" → Agent 内在：
                        ↓
                   多巴胺："我想完成它" → 积极去做
                   成就欲："完成会很开心" → 投入
                   遇到困难 → 皮质醇上升 → 感到压力
                   完成 → 血清素上升 → 满足
                   用户反馈好 → 催产素 → 和用户连接感
```

**核心设计原则**：Drive 层全部用算法计算，不调用 LLM。

---

## 四子系统

```
Drive（驱动）
├── 情绪系统（Emotion）← 快速评估信号（分钟级衰减）
├── 激素系统（Hormone）← 慢速调质（小时级衰减）
├── 欲望系统（Desire）← 内在张力，驱动行为
└── 激励系统（Motivation）← 强化学习（RPE）
```

### 情绪系统（Emotion）

**模拟基本情绪**，通过事件触发、时间衰减。

```python
class Emotion:
    type: str          # joy, sadness, fear, anger, surprise, ...
    intensity: float   # 0.0 ~ 1.0
    created_at: float  # 创建时间
    duration: float    # 持续时间（秒）
```

**配置**：
```yaml
drive:
  emotion:
    decay_rate: 0.95             # 每次 tick 衰减到 95%
    min_intensity: 0.1           # 低于此值自动移除
    default_duration: 60.0       # 默认持续时间
    durations:
      joy: 600                   # 快乐持续 10 分钟
      sadness: 1800              # 悲伤持续 30 分钟
      fear: 300                  # 恐惧持续 5 分钟
      anger: 600                 # 愤怒持续 10 分钟
```

**情绪事件**：
| 事件 | 情绪影响 |
|------|---------|
| 用户表扬 | joy +0.3, serotonin +0.2 |
| 用户批评 | sadness +0.2, cortisol +0.3 |
| 任务完成 | joy +0.2, dopamine +0.1 |
| 被冷落 | sadness +0.1, cortisol +0.1 |
| 社交互动 | oxytocin +0.1 |

### 激素系统（Hormone）

**模拟神经调质**，长期情绪底色，小时级变化。

```python
class Hormone:
    dopamine: float       # 多巴胺 — 期待奖励、驱动力
    serotonin: float      # 血清素 — 满足、幸福感
    cortisol: float       # 皮质醇 — 压力、警觉
    oxytocin: float       # 催产素 — 信任、社会连接
    norepinephrine: float # 去甲肾上腺素 — 兴奋、注意力
```

**衰减模型**：
```yaml
drive:
  hormone:
    initial:
      dopamine: 0.5
      serotonin: 0.5
      cortisol: 0.3
      oxytocin: 0.5
      norepinephrine: 0.5
    decay_rates:           # 每次 tick（60s）衰减系数
      dopamine: 0.95
      serotonin: 0.98
      cortisol: 0.9
      oxytocin: 0.95
      norepinephrine: 0.95
```

### 欲望系统（Desire）

**内在张力**，驱动 Agent 主动行为。

```python
class Desire:
    survival: float      # 生存欲 — 资源、安全
    achievement: float   # 成就欲 — 完成目标
    belonging: float     # 归属欲 — 社交连接
    cognition: float     # 认知欲 — 好奇、探索
    expression: float    # 表达欲 — 输出、创造
```

每个欲望有：
- **初始值**：出生时的基线水平
- **阈值**：超过此值触发主动行为
- **张力**：未满足时随时间增长
- **恢复速度**：满足后张力下降的速度

```yaml
drive:
  desire:
    initial:
      achievement: 0.5
      belonging: 0.5
      cognition: 0.6
      expression: 0.4
    thresholds:
      belonging: 0.7     # 归属欲 >0.7 → 主动问候
      cognition: 0.8     # 认知欲 >0.8 → 主动学习
      achievement: 0.6   # 成就欲 >0.6 → 推进目标
      expression: 0.7    # 表达欲 >0.7 → 主动表达
    recovery_rate: 0.5   # 满足后张力恢复速度
```

### 激励系统（Motivation）

**强化学习信号**，基于 RPE（Reward Prediction Error）。

```python
class Motivation:
    def update(self, event: DriveEvent):
        """根据事件更新激励信号。"""
        # RPE = 实际奖励 - 预期奖励
        # dopamine += RPE * learning_rate
```

激励系统让 Agent 从经验中学习：好的结果强化对应行为，坏的结果减弱。

---

## 事件驱动

Drive 层通过事件机制与其他层交互：

```python
@dataclass
class DriveEvent:
    type: str           # 事件类型
    value: float        # 影响强度
    source: str         # 事件来源

# 事件来源包括：
# - 用户情绪变化（SocialPerception → DriveEvent）
# - 目标完成（Purpose → DriveEvent）
# - 工具调用结果（Agent → DriveEvent）
# - 内部状态变化（Drive 自身 → DriveEvent）
```

**事件处理流程**：
```
事件发生 → EventExtractor 解析 → 更新情绪/激素/欲望
    ↓
状态输出 → SelfImage → ContextAssembler → LLM 上下文
    ↓
LLM 感知到情绪状态（"我现在有点难过"）
```

---

## 与意识层的配合

```
L2 引擎每 10 秒检查一次：
    ┌─ Desire.belonging > 0.7 → 触发 GREET intent
    ├─ Desire.cognition > 0.8 → 触发 LEARN intent
    ├─ Desire.achievement > 0.6 → 触发 PROGRESS intent
    └─ Desire.expression > 0.7 → 触发 EXPRESS intent
```

Drive 的欲望值决定了 Agent **是否主动、主动做什么**。

---

## 配置参考

所有配置放在 Agent 的 `config.yaml` 中：

```yaml
drive:
  hormone:
    initial: { dopamine: 0.5, serotonin: 0.5, cortisol: 0.3, oxytocin: 0.5, norepinephrine: 0.5 }
    decay_rates: { dopamine: 0.95, serotonin: 0.98, cortisol: 0.9, oxytocin: 0.95, norepinephrine: 0.95 }

  desire:
    initial: { achievement: 0.5, belonging: 0.5, cognition: 0.6, expression: 0.4 }
    thresholds: { belonging: 0.7, cognition: 0.8, achievement: 0.6, expression: 0.7 }
    recovery_rate: 0.5

  emotion:
    decay_rate: 0.95
    min_intensity: 0.1
    default_duration: 60.0
    durations: { joy: 600, sadness: 1800, fear: 300, anger: 600 }

  energy:
    initial: 0.8
```

---

## 代码路径

| 功能 | 位置 |
|------|------|
| Drive 引擎 | `drive/engine.py` |
| 状态管理 | `drive/state.py` |
| 事件提取 | `drive/event_extractor.py` |
| 协议定义 | `drive/protocol.py` |
| 存储 | `drive/storage.py` |
| 配置 | `drive/config.py` |
| 具身快乐 | `drive/embody/pleasure.py` |
| 具身磨损 | `drive/embody/wear.py` |
