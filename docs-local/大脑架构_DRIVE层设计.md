# 大脑架构设计：Drive 层（边缘系统）

> 创建时间：2026-04-17
> 状态：讨论完成，待实现

---

## 概述

Drive 层是连接"目的"和"行动"的桥梁。

```
Purpose（目的）→ Drive（驱动）→ Agent（执行）
```

### 核心问题

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

---

## 欲望 vs 目标

| | 欲望 (Desire) | 目标 (Goal) |
|---|---|---|
| 本质 | 内在张力，缺失感 | 具体方向，可分解 |
| 表达 | "我想要X" | "我通过Y得到X" |
| 方案 | 无 | 有 |
| 抽象程度 | 高 | 中/低 |
| 层级 | 底层 | 上层 |

```
欲望：我想要被认可（归属欲）
    ↓ 转化为
目标：帮用户解决问题 → 得到认可
```

---

## Drive 层组成

```
Drive（驱动）
├── 情绪系统（Emotion）← 快速评估信号
├── 激励系统（Motivation）← 强化学习
├── 激素系统（Hormone）← 慢速调质
└── 欲望系统（Desire）← 内在张力
```

---

## 技术实现原理

### 核心原理

**Drive 层本质是状态机 + 事件处理器，不需要 LLM。**

```
事件输入（目标完成/用户反馈）
    ↓
Drive 处理（更新内部状态）
    ↓
状态输出（情绪/激素/欲望水平）
    ↓
影响其他层（Agent/Purpose/Metacognition）
```

---

### 1. 情绪系统

```python
@dataclass
class EmotionalState:
    emotion: Emotion          # 当前情绪
    intensity: float           # 强度 0.0-1.0
    created_at: float          # 产生时间
    duration: float            # 持续时间（秒）

class Emotion(Enum):
    JOY = "joy"
    SADNESS = "sadness"
    ANGER = "anger"
    FEAR = "fear"
    SURPRISE = "surprise"
    DISGUST = "disgust"
    NEUTRAL = "neutral"

# 事件触发情绪
def on_event(self, event):
    if event.type == "goal_completed":
        self.set_emotion(Emotion.JOY, intensity=0.8, duration=5)
    elif event.type == "goal_failed":
        self.set_emotion(Emotion.SADNESS, intensity=0.6, duration=10)
    elif event.type == "user_criticized":
        self.set_emotion(Emotion.ANGER, intensity=0.5, duration=3)

# 情绪自然衰减
def tick(self):
    elapsed = now() - self.emotion.created_at
    if elapsed > self.emotion.duration:
        self.emotion.intensity *= 0.9
        if self.emotion.intensity < 0.1:
            self.emotion = Emotion.NEUTRAL
```

---

### 2. 激素系统

```python
@dataclass
class HormoneState:
    dopamine: float = 0.5      # 多巴胺：期待奖励
    serotonin: float = 0.5    # 血清素：满足感
    cortisol: float = 0.3      # 皮质醇：压力
    oxytocin: float = 0.5      # 催产素：社会连接
    norepinephrine: float = 0.5  # 去甲肾上腺素：警觉

# 激素变化规则
def on_event(self, event):
    if event.type == "goal_completed":
        self.dopamine += 0.2
        self.serotonin += 0.3
        self.cortisol -= 0.1
    elif event.type == "goal_failed":
        self.cortisol += 0.3
        self.dopamine -= 0.2
    elif event.type == "user_feedback_positive":
        self.oxytocin += 0.2
        self.serotonin += 0.1

# 激素自然衰减（每小时）
def tick_hourly(self):
    self.dopamine *= 0.95
    self.serotonin *= 0.98
    self.cortisol *= 0.90
    self.oxytocin *= 0.99
```

---

### 3. 激励系统

**核心概念**：奖励预测误差（RPE）

```
RPE = 实际奖励 - 预期奖励

RPE > 0：比预期好 → 多巴胺上升
RPE < 0：比预期差 → 多巴胺下降
RPE = 0：符合预期 → 稳定
```

```python
@dataclass
class MotivationState:
    expected_reward: float = 0.5  # 预期奖励
    actual_reward: float = 0.0  # 累计实际奖励
    dopamine: float = 0.5       # 受 RPE 影响

def evaluate_reward(self, goal: Goal, feedback: Feedback):
    actual = self._calculate_actual_reward(feedback)
    rpe = actual - self.expected_reward

    if rpe > 0:
        self.dopamine += rpe * 0.5
    else:
        self.dopamine += rpe * 0.3

    # 调整预期（学习）
    self.expected_reward = self.expected_reward * 0.8 + actual * 0.2
```

---

### 4. 欲望系统

```python
@dataclass
class DesireState:
    survival: float = 0.3        # 生存欲
    achievement: float = 0.5    # 成就欲
    belonging: float = 0.5       # 归属欲
    cognition: float = 0.6       # 认知欲
    expression: float = 0.4     # 表达欲

# 欲望有基础张力，即使满足也会慢慢回升
def tick_hourly(self):
    for desire in self.desires:
        desire.level += 0.05  # 张力上升
        if desire.level > desire.base_level:
            desire.level -= 0.02  # 回归基础值

# 满足欲望
def satisfy(self, desire_type: DesireType, amount: float):
    desire = self.get_desire(desire_type)
    desire.level = max(0, desire.level - amount)
    desire.last_satisfied = now()
    self.serotonin += amount * 0.2
```

---

### 5. Drive 核心引擎

```python
class DriveEngine:
    def __init__(self):
        self.emotion = EmotionalState()
        self.hormone = HormoneState()
        self.motivation = MotivationState()
        self.desire = DesireState()

    def on_event(self, event: Event):
        """处理外部事件"""
        self.emotion.on_event(event)
        self.hormone.on_event(event)
        self.motivation.evaluate_reward(event.goal, event.feedback)
        self.desire.satisfy(event.desire_type, event.amount)

    def tick(self):
        """每秒更新"""
        self.emotion.tick()

    def tick_hourly(self):
        """每小时更新"""
        self.hormone.tick_hourly()
        self.desire.tick_hourly()

    def get_signals(self) -> DriveSignals:
        """获取对其他层的信号"""
        return DriveSignals(
            emotional_state=self.emotion,
            hormone_state=self.hormone,
            motivation_state=self.motivation,
            desire_state=self.desire,

            # 汇总的影响信号
            motivation_level=self.hormone.dopamine * 0.3 + self.motivation.motivation * 0.7,
            stress_level=self.hormone.cortisol,
            satisfaction_level=self.hormone.serotonin,
        )
```

---

## Drive 层 vs Purpose 层

| | Purpose 层 | Drive 层 |
|---|---|---|
| 核心机制 | LLM 判断 | 状态机 + 规则 |
| 需要 LLM | ✅ 需要 | ❌ 不需要 |
| 本质 | 理解意图、分解目标 | 状态变化、能量提供 |
| 触发 | 用户输入 | 事件（目标完成/反馈） |

---

## 对其他层的影响

### Agent 层

```python
if drive.signals.stress_level > 0.7:
    # 压力大时，更谨慎
    agent.set_caution_mode(True)

if drive.signals.motivation_level < 0.3:
    # 动力不足时，提示用户
    agent.say("我有点累了，可能需要休息一下")
```

### Metacognition 层

```python
if drive.signals.stress_level > 0.8:
    # 压力大时，更频繁反省
    metacognition.increase_reflection_frequency()
```

### Purpose 层

```python
if drive.signals.satisfaction_level > 0.7:
    # 满足感高时，可以接受更高风险的目标
    purpose.adjust_goal_risk_tolerance(0.2)
```

---

## 装饰性 vs 决策影响

### 当前阶段（装饰为主）

```
Drive 层：
├── Core：状态变化（规则驱动）
└── Expression：生成自然语言表达
    └── 可选 LLM 生成更自然的表达
```

**作用**：让 Agent 说话更像人，用户更有动力持续对话。

### 后期（加大决策影响）

```
Drive 层：
├── Core：状态变化（规则驱动）
├── Expression：自然语言表达
└── Decision Influence：影响 Agent 决策
    └── 信号 → 调整行为倾向
```

---

## 文件结构

```
xiaomei_brain/drive/
├── __init__.py
├── state.py           # 状态数据结构
├── emotion.py         # 情绪系统
├── hormone.py         # 激素系统
├── motivation.py       # 激励系统
├── desire.py          # 欲望系统
├── engine.py          # Drive 核心引擎
└── expression.py      # 表达模块（可选 LLM）
```

---

## 设计决定

| 项目 | 决定 |
|------|------|
| 核心机制 | 状态机 + 事件处理器，不需要 LLM |
| 装饰性 | 需要，影响用户体验 |
| 决策影响 | 当前较小，逐步加大 |
| 情绪表达 | 可选 LLM 生成自然语言 |
| 欲望 vs 目标 | 欲望是内在张力，目标是具体方向 |

---

## Core 层和 Expression 层接口

### 完整架构

```
┌─────────────────────────────────────────┐
│           Drive Engine（驱动引擎）        │
├─────────────────────────────────────────┤
│                                         │
│  ┌─────────────────────────────────┐    │
│  │  Core Layer（核心层）            │    │
│  │  不需要 LLM，规则驱动             │    │
│  │                                   │    │
│  │  ├── Emotion Core                │    │
│  │  ├── Hormone Core                │    │
│  │  ├── Motivation Core            │    │
│  │  └── Desire Core                │    │
│  └─────────────────────────────────┘    │
│                 │                        │
│                 │ get_signals()           │
│                 ▼                        │
│  ┌─────────────────────────────────┐    │
│  │  Expression Layer（表达层）        │    │
│  │  可选 LLM                         │    │
│  │                                   │    │
│  │  ├── Emotion Expressor           │    │
│  │  ├── Mood Expressor             │    │
│  │  └── Response Generator          │    │
│  └─────────────────────────────────┘    │
│                                         │
└─────────────────────────────────────────┘
```

### Core Layer 接口

```python
# drive/core/state.py

@dataclass
class DriveSignals:
    """输出给其他层的信号"""
    emotion: EmotionalState
    hormone: HormoneState
    motivation: MotivationState
    desire: DesireState

    # 汇总指标
    motivation_level: float      # 综合动力 0.0-1.0
    stress_level: float           # 压力水平 0.0-1.0
    satisfaction_level: float      # 满足感 0.0-1.0
    social_connection_level: float # 社会连接感 0.0-1.0

# drive/core/engine.py

class DriveCore:
    """Drive 核心层 - 状态机"""

    def __init__(self):
        self.emotion = EmotionalState()
        self.hormone = HormoneState()
        self.motivation = MotivationState()
        self.desire = DesireState()

    # ========== 事件输入 ==========

    def on_goal_completed(self, goal: Goal) -> None: ...
    def on_goal_failed(self, goal: Goal, reason: str) -> None: ...
    def on_user_feedback(self, feedback: Feedback) -> None: ...
    def on_user_praise(self) -> None: ...
    def on_user_criticism(self) -> None: ...

    # ========== 周期更新 ==========

    def tick_second(self) -> None:  # 情绪衰减
    def tick_minute(self) -> None: ...
    def tick_hour(self) -> None:    # 激素/欲望自然变化

    # ========== 状态读取 ==========

    def get_signals(self) -> DriveSignals: ...
    def get_emotion(self) -> EmotionalState: ...
    def get_hormone(self) -> HormoneState: ...
```

### Expression Layer 接口

```python
# drive/expression/engine.py

class DriveExpression:
    """Drive 表达层 - 生成自然语言"""

    def __init__(self, core: DriveCore, llm_client=None):
        self.core = core
        self.llm = llm_client  # 可选

    # ========== 情绪表达 ==========

    def express_current_emotion(self) -> str:
        """表达当前情绪"""
        ...

    def express_progress(self, progress: float) -> str:
        """表达进度"""
        ...

    # ========== 动机表达 ==========

    def express_motivation(self) -> str: ...
    def express_stress(self) -> str: ...

    # ========== 组合表达（可选 LLM）==========

    def generate_emotional_response(
        self,
        base_message: str,
        context: str = ""
    ) -> str:
        """生成带有情绪色彩的综合回应"""
        ...
```

### 使用示例

```python
# 初始化
drive_core = DriveCore()
drive_expression = DriveExpression(drive_core, llm_client)

# 事件处理
drive_core.on_goal_completed(goal)
drive_core.on_user_praise()

# 获取信号（影响其他层）
signals = drive_core.get_signals()
if signals.stress_level > 0.7:
    metacognition.increase_reflection_frequency()

# 生成表达（影响用户体验）
emotion_expr = drive_expression.express_current_emotion()
agent_response = drive_expression.generate_emotional_response(
    base_message="代码已经重构完成",
    context="用户要求优化代码结构"
)
```

### 模拟示例：Drive 状态如何影响 LLM 表达

**场景：用户说"代码有问题"**

| Drive 状态 | 基础消息 | LLM 输出 |
|------------|----------|----------|
| 积极 (joy, 0.8) | 我来看看问题在哪 | "太好了！让我来看看这个问题出在哪里，我一定能帮你找到并解决它！💪" |
| 低落 (sadness, 0.6) | 我来看看问题在哪 | "好吧...让我看看这个问题。虽然有点棘手，但我会尽力的。" |
| 愤怒 (anger, 0.7) | 我来看看问题在哪 | "居然又出 bug 了！让我来看看是哪里有问题，这次一定要彻底解决！😤" |

**结论**：同样的事件 + 不同 Drive 状态 → 不同 LLM 表达 → 用户感知到不同的"性格"
