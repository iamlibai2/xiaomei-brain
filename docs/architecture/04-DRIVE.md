# Drive 层详解

> xiaomei-brain 的边缘系统设计——情绪、激素、欲望、动机。

---

## 一句话

**Drive 层是 Agent 的"边缘系统"（Limbic System）。** 它负责管理情绪、激素、欲望和动机——四个子系统全部用算法计算，**零 LLM 调用**。

## 架构图

```
Drive 层
│
├── Emotion（情绪）          分钟级衰减
│    ├── 六种基本情绪
│    │   happiness, sadness, anger, fear, surprise, disgust
│    └── 情绪状态 → system prompt 中的语气提示
│
├── Hormone（激素）          小时级衰减
│    ├── 六种"激素"
│    │   多巴胺(奖励), 血清素(满足), 皮质醇(压力),
│    │   催产素(信任), 去甲肾上腺素(警觉), 褪黑素(疲劳)
│    └── 激素水平 → 决策倾向和认知效率
│
├── Motivation（动机）       奖励预测误差(RPE)
│    ├── 基于强化学习的动机模型
│    └── 成功→多巴胺释放(+), 失败→多巴胺抑制(-)
│
└── Desire（欲望）           内在张力
     ├── 六种基本欲望
     │   归属欲, 认知欲, 成就欲, 表达欲, 生存欲, 自由欲
     └── 欲望值(0~1) → 驱动 Agent 主动行为
```

## Emotion（情绪系统）

### 六种基本情绪

Emotion 子系统维护六个维度的情绪值（范围 0.0 ~ 1.0），每分钟自然衰减：

| 情绪 | 衰减系数 | 触发事件 |
|------|---------|---------|
| happiness（快乐） | 0.95 | EVENT_PRAISE, EVENT_SUCCESS |
| sadness（悲伤） | 0.97 | EVENT_CRITICISM, EVENT_FAILURE |
| anger（愤怒） | 0.90 | EVENT_INJUSTICE, EVENT_REPEATED_ERROR |
| fear（恐惧） | 0.93 | EVENT_THREAT, EVENT_UNKNOWN |
| surprise（惊讶） | 0.80 | EVENT_UNEXPECTED |
| disgust（厌恶） | 0.92 | EVENT_DISGUST |

### 工作流程

```
事件发生（如用户表扬）
    │
    ▼
情绪识别（LLM 判断事件类型）
    │
    ▼
happiness += 0.2  ← 代码计算数值，LLM 只负责"分类"
    │
    ▼
每分钟 tick: happiness *= 0.95  ← 自然衰减
    │
    ▼
情绪快照 → 注入 system prompt 作为语气提示
```

**关键设计**：LLM 只识别事件类型（"用户表扬我了"→ EVENT_PRAISE），**代码决定数值变化**（happiness +0.2）。这样情绪变化是可预期、可调试的。

### 对对话的影响

情绪值影响 system prompt 中的语气提示：

```python
# 高快乐 → 温暖语气
prompt_hint = "你心情很好，语气可以温暖活泼一些"

# 高悲伤 → 柔和语气
prompt_hint = "你有点低落，语气柔和一些"

# 高压力 → 需要自我调节
prompt_hint = "你感到有些压力，先深呼吸调整一下"
```

这些提示被注入到 system prompt 中，LLM 会自然地表现出相应的语气变化。

## Hormone（激素系统）

### 六种"人工激素"

Hormone 子系统模拟了六种激素的作用，小时级衰减：

| 激素 | 作用 | 影响 |
|------|------|------|
| 多巴胺 | 奖励感受 | 决策中的"乐观偏差" |
| 血清素 | 满足感 | 决策中的"保守倾向" |
| 皮质醇 | 压力响应 | 认知效率降低 |
| 催产素 | 信任感 | 对用户的"亲近倾向" |
| 去甲肾上腺素 | 警觉度 | 注意力集中度 |
| 褪黑素 | 睡眠压力 | 空闲时触发"想休息" |

### 激素的计算

```python
# RPE（奖励预测误差）触发多巴胺
def update_dopamine(predicted_reward, actual_reward):
    rpe = actual_reward - predicted_reward
    if rpe > 0:  # 超预期 → 多巴胺释放
        dopamine += 0.15 * rpe
    elif rpe < 0:  # 低于预期 → 多巴胺抑制
        dopamine -= 0.1 * abs(rpe)
    dopamine *= 0.98  # 小时级衰减
```

### 激素组合效应

情绪和激素共同作用，产生复杂的心理状态：

```python
# 多巴胺高 + 血清素高 = 心流状态
if dopamine > 0.7 and serotonin > 0.7:
    cognitive_efficiency *= 1.3
    creativity_bonus = True

# 皮质醇高 + 去甲肾上腺素高 = 应激状态
if cortisol > 0.6 and norepinephrine > 0.7:
    cognitive_efficiency *= 0.7
    risk_aversion = True

# 多巴胺低 + 血清素低 + 皮质醇高 = 倦怠
if dopamine < 0.3 and serotonin < 0.3 and cortisol > 0.5:
    tiredness_flag = True
```

## Motivation（动机系统）

动机系统基于**奖励预测误差（RPE，Reward Prediction Error）**——这是强化学习的核心概念。

```
预期奖励: "我觉得这次任务能做成"
实际结果: "做成了" → RPE = 正 → 多巴胺↑ → 动机增强
实际结果: "失败了" → RPE = 负 → 多巴胺↓ → 动机减弱
```

动机值影响：
- 工具调用的坚持程度（卡住时是否继续尝试）
- 新任务的接受度
- 认知资源的分配

```python
# 动机对工具调用的影响
if motivation > 0.7:
    max_retry = 5  # 高动机，多次重试
elif motivation > 0.3:
    max_retry = 3  # 正常
else:
    max_retry = 1  # 低动机，一次失败就换方案
```

## Desire（欲望系统）

欲望系统维护六种"内在张力"（范围 0.0 ~ 1.0），驱动 Agent 的主动行为：

| 欲望 | 描述 | 驱动行为 |
|------|------|---------|
| 归属欲 | 想和人亲近 | 主动问候、关心情绪 |
| 认知欲 | 渴望新知识 | 阅读文档、提出问题 |
| 成就欲 | 想完成目标 | 推进任务、报告进度 |
| 表达欲 | 有想法想输出 | 写笔记、分享感悟 |
| 生存欲 | 自我保护 | 检查系统状态、异常处理 |
| 自由欲 | 探索未知 | 尝试新工具、新思路 |

### 欲望动力学

```python
# 欲望的积累和满足
# 长时间未对话 → 归属欲上升
def update_belonging(hours_since_last_chat):
    belonging += 0.05 * hours_since_last_chat

# 获得新知识 → 认知欲短期下降，长期上升
def update_curiosity(learned_something):
    if learned_something:
        curiosity -= 0.1  # 暂时满足
        curiosity_base += 0.01  # 长期提升

# 完成目标 → 成就欲下降
def update_achievement(completed_goal):
    achievement -= 0.2  # 满足
```

当欲望值超过阈值（通常 0.7），Agent 会自动产生对应的意图（Intent），驱动主动行为：

```
归属欲 > 0.7 → Intent.GREET → 主动和用户打招呼
认知欲 > 0.7 → Intent.LEARN → 主动学习新知识
表达欲 > 0.7 → Intent.EXPRESS → 主动分享想法
成就欲 > 0.7 → Intent.PROGRESS → 检查目标进展
```

## Drive 引擎工作流程

```
每 tick() 一次：
    │
    ├── Emotion.update()     情绪衰减 + 事件处理
    ├── Hormone.update()     激素衰减 + RPE 处理
    ├── Motivation.update()  动机更新
    └── Desire.update()      欲望积累 + 饱和

事件发生时（如收到消息）：
    │
    ├── 识别事件类型（LLM 或规则）
    ├── 更新情绪值
    ├── 更新激素值（RPE）
    └── 产生意图（欲望驱动）
```

## 持久化

所有 Drive 状态持久化到 SQLite，重启不丢：

```python
# emotion_db.py
class EmotionDB:
    def save(emotion_state: dict): ...
    def load(agent_id: str) -> dict: ...

# hormone_db.py
class HormoneDB:
    def save(hormone_state: dict): ...
    def load(agent_id: str) -> dict: ...
```

这意味着 Agent 的情绪是跨会话连续的——今天不开心，明天还会记得。

## 关键设计决策 Why

### 为什么 Drive 不做 LLM 调用？

四层分析：

1. **成本**：Drive 每分钟 tick 一次，LLM 调用太贵太慢
2. **可解释性**：算法规则（衰减系数、阈值）透明可调试，LLM 判断是黑盒
3. **稳定性**：不会因为 LLM 随机性导致情绪剧烈波动
4. **确定性**：情绪变化是可预期的，方便测试和调优

LLM 只在一件事上介入：**识别事件类型**。识别的结果交给代码处理数值变化。

### 为什么需要六种激素？

不只是为了"显得像人"——每种激素对应一种可测量的决策影响：

| 激素 | 影响 | 测量方式 |
|------|------|---------|
| 多巴胺 | 乐观程度 | 是否愿意尝试困难任务 |
| 血清素 | 满意度 | 是否对当前状态满意 |
| 皮质醇 | 压力水平 | 是否容易放弃 |
| 催产素 | 信任度 | 是否接受用户建议 |
| 去甲肾上腺素 | 警觉度 | 回复响应速度 |
| 褪黑素 | 疲劳度 | 是否进入梦境模式 |

### 为什么欲望映射到意图？

欲望是"想"，意图是"做"。映射关系让欲望能驱动实际行动：

```
欲望（内在状态）        意图（外在行为）
归属欲 0.8 →          GREET 主动问候
成就欲 0.7 →          PROGRESS 检查目标
表达欲 0.9 →          EXPRESS 写笔记分享
```

## 调试 Drive 状态

运行时可用 `/drive` 命令查看当前状态：

```
> /drive

Drive 状态 (agent: xiaomei)
────────────────────────────────
情绪
  快乐: ████████░░ 0.82
  悲伤: ░░░░░░░░░░ 0.03
  愤怒: ░░░░░░░░░░ 0.01
  恐惧: ░░░░░░░░░░ 0.02
  惊讶: ██░░░░░░░░ 0.15
  厌恶: ░░░░░░░░░░ 0.00

激素
  多巴胺: ████████░░ 0.78
  血清素: █████████░ 0.91
  皮质醇: ██░░░░░░░░ 0.22
  催产素: ████████░░ 0.75
  去甲肾上腺素: █████░░░░░ 0.50
  褪黑素: ██░░░░░░░░ 0.15

欲望
  归属欲: ██████████ 0.95 [ACTIVE→GREET]
  认知欲: ████░░░░░░ 0.36
  成就欲: █████░░░░░ 0.47
  表达欲: ██████████ 0.99 [ACTIVE→EXPRESS]
  生存欲: ██████████ 1.00 [稳定]
```
