# 大脑架构设计：Metacognition 层（元认知）

> 创建时间：2026-04-17
> 状态：讨论完成，待实现

---

## 概述

元认知是"对自己认知的认知"，分为三个子模块：

```
┌─────────────────────────────────────────────────────────┐
│  Monitor（监控）                                        │
│  ├── 战略目标实现进度                                  │
│  ├── 中期目标实现进度                                  │
│  ├── 当前目标进度                                      │
│  ├── 认知状态（知道/不确定/不知道）                   │
│  └── 注意力状态（专注/走神/卡住）                     │
├─────────────────────────────────────────────────────────┤
│  Evaluator（评估）                                      │
│  ├── 目标完成质量                                     │
│  ├── 自我知识状态 ← 最重要                            │
│  └── 策略有效性                                       │
├─────────────────────────────────────────────────────────┤
│  Adjuster（调整）← 全部需要                            │
│  ├── 不确定时 → 请求澄清 / 请求帮助                    │
│  ├── 多次失败时 → 换策略 / 分解目标 / 放弃            │
│  ├── 时间过长时 → 调整预期 / 告知用户                 │
│  ├── 超出能力时 → 承认做不到                         │
│  └── 用户反馈差时 → 重新理解 / 换方法                 │
└─────────────────────────────────────────────────────────┘
```

---

## 触发时机

Metacognition 在三个时间点介入：

```
Agent.run(goal)
    │
    ├── Pre-execution: Metacognition.check()
    │       │  ← 执行前检查
    │       ├── Monitor: 我理解对了吗？
    │       ├── Evaluator: 我能做到吗？
    │       └── Adjuster: 如果不确定，请求澄清/帮助
    │
    ├── During execution: Metacognition.monitor()
    │       │  ← 执行中周期性/事件驱动
    │       ├── Monitor: 进度？注意力？认知状态？
    │       ├── Evaluator: 策略有效吗？我卡住了吗？
    │       └── Adjuster: 如果卡住，换策略/分解/求助
    │
    └── Post-execution: Metacognition.review()
            │  ← 执行后复盘
            ├── Monitor: 发生了什么？
            ├── Evaluator: 完成得好不好？
            └── Adjuster: 基于用户反馈调整
```

---

## 数据结构

```python
# metacognition/state.py

class CognitiveState(Enum):
    KNOW = "know"           # 确定知道
    UNCERTAIN = "uncertain" # 不确定
    DONT_KNOW = "dont_know" # 完全不知道

class AttentionState(Enum):
    FOCUSED = "focused"     # 专注
    DISTRACTED = "distracted" # 走神
    STUCK = "stuck"         # 卡住

class AdjustmentType(Enum):
    REQUEST_CLARIFICATION = "request_clarification"  # 请求澄清
    REQUEST_HELP = "request_help"                     # 请求帮助
    SWITCH_STRATEGY = "switch_strategy"               # 换策略
    DECOMPOSE_GOAL = "decompose_goal"                 # 分解目标
    ABANDON_GOAL = "abandon_goal"                     # 放弃目标
    ADJUST_EXPECTATION = "adjust_expectation"         # 调整预期
    ADMIT_INABILITY = "admit_inability"               # 承认做不到
    RE_UNDERSTAND = "re_understand"                   # 重新理解

@dataclass
class CognitiveStatus:
    cognitive_state: CognitiveState
    attention_state: AttentionState
    goal_progress: float          # 0.0-1.0
    time_spent: float             # 已花费时间
    failure_count: int = 0        # 连续失败次数
    uncertainty_topics: list[str] = field(default_factory=list)  # 不确定的主题

@dataclass
class Adjustment:
    type: AdjustmentType
    reason: str
    suggested_action: str  # "我帮你查一下资料"
```

---

## 核心引擎

```python
# metacognition/engine.py

class MetacognitionEngine:
    def __init__(self, llm_client):
        self.llm = llm_client
        self.status = CognitiveStatus(
            cognitive_state=CognitiveState.KNOW,
            attention_state=AttentionState.FOCUSED,
            goal_progress=0.0,
            time_spent=0.0,
        )

    def check(self, goal: Goal, context: Context) -> Optional[Adjustment]:
        """
        Pre-execution: 执行前检查
        返回 Adjustment 如果需要调整，否则 None
        """
        # 1. Monitor: 检查理解状态
        self._update_cognitive_state(goal, context)

        # 2. Evaluator: 评估是否能完成
        can_achieve, confidence = self._evaluate_ability(goal, context)

        if not can_achieve:
            return Adjustment(
                type=AdjustmentType.REQUEST_HELP,
                reason="超出能力范围",
                suggested_action="这个问题我需要查资料或请教他人"
            )

        if confidence < 0.7:
            return Adjustment(
                type=AdjustmentType.REQUEST_CLARIFICATION,
                reason="理解不够确定",
                suggested_action="我理解的是...，你对吗？"
            )

        return None

    def monitor(self, goal: Goal, context: Context) -> Optional[Adjustment]:
        """
        During execution: 执行中监控
        """
        # 检查是否卡住
        if self.status.failure_count >= 3:
            return Adjustment(
                type=AdjustmentType.SWITCH_STRATEGY,
                reason=f"连续失败 {self.status.failure_count} 次",
                suggested_action="我换个方法试试"
            )

        if self.status.attention_state == AttentionState.STUCK:
            return Adjustment(
                type=AdjustmentType.DECOMPOSE_GOAL,
                reason="在当前问题上卡住",
                suggested_action="我把这个问题分解成更小的部分"
            )

        # 检查时间是否过长
        if self.status.time_spent > self._get_time_threshold(goal):
            return Adjustment(
                type=AdjustmentType.ADJUST_EXPECTATION,
                reason="花费时间超过预期",
                suggested_action="这个问题比我预期的复杂，可能需要更多时间"
            )

        return None

    def review(self, goal: Goal, feedback: Feedback, context: Context) -> None:
        """
        Post-execution: 执行后复盘
        根据用户反馈调整内部状态
        """
        if feedback.is_negative:
            self.status.failure_count += 1
            # 可以调整未来策略
        else:
            self.status.failure_count = 0

        # 更新用户偏好模型（供 Purpose 层使用）
        self._update_user_preference(goal, feedback)

    def _update_cognitive_state(self, goal: Goal, context: Context):
        """Monitor: 更新认知状态"""
        prompt = f"""
你当前要完成的目标：{goal.description}
当前上下文：{context}

评估你的理解状态：
- 你确定你知道如何完成这个目标吗？
- 有什么不确定的地方？

输出：KNOW / UNCERTAIN / DONT_KNOW
"""
        result = self.llm.complete(prompt).strip()
        if "UNCERTAIN" in result:
            self.status.cognitive_state = CognitiveState.UNCERTAIN
        elif "DONT_KNOW" in result:
            self.status.cognitive_state = CognitiveState.DONT_KNOW
        else:
            self.status.cognitive_state = CognitiveState.KNOW

    def _evaluate_ability(self, goal: Goal, context: Context) -> tuple[bool, float]:
        """Evaluator: 评估是否能完成这个目标"""
        # 实现评估逻辑
        # 返回 (能否完成, 置信度 0.0-1.0)
        ...

    def _get_time_threshold(self, goal: Goal) -> float:
        """根据目标类型估算时间阈值（秒）"""
        thresholds = {
            GoalType.EXECUTABLE: 300,   # 5分钟
            GoalType.PHASE: 3600,       # 1小时
            GoalType.STRATEGIC: 86400,  # 1天
        }
        return thresholds.get(goal.goal_type, 300)
```

---

## 自我表达示例

Agent 可以说：

```
"我不确定我理解对了，你能确认一下吗？"
"这个问题我不确定，需要查资料"
"我觉得这样做可以，但我不确定"
"等等，我刚才理解错了，应该是..."
"这个方法好像不行，我换一个试试"
"这个问题可能需要更多信息"
"这个问题我可能做不到，原因是我对这块不熟悉"
```

---

## 与其他层对接

```
┌─────────────────────────────────────────────────────────┐
│  Metacognition                                         │
│    ↑                                                   │
│    └── 上层：Purpose 层                                │
│        战略/阶段/当前目标                              │
│    ↓                                                   │
│    └── 下层：Agent/Drive                               │
│        执行 + 反馈                                      │
└─────────────────────────────────────────────────────────┘

数据流：
Purpose.understand()
    ↓
Metacognition.check(goal) → 可能返回 Adjustment
    ↓
Agent.run(goal)
    ↓ 周期性
Metacognition.monitor(goal) → 可能返回 Adjustment
    ↓
Agent 完成
    ↓
Purpose.complete_current()
    ↓
Drive.evaluate(feedback)
    ↓
Metacognition.review(goal, feedback) → 更新内部状态
```

---

## 文件结构

```
xiaomei_brain/metacognition/
├── __init__.py
├── state.py           # CognitiveState, AttentionState, Adjustment 等
├── engine.py          # MetacognitionEngine 核心
├── monitor.py         # Monitor 子模块
├── evaluator.py       # Evaluator 子模块
└── adjuster.py        # Adjuster 子模块
```

---

## 实现顺序

```
Phase 1: 数据结构
└── state.py

Phase 2: 核心引擎（简化版）
└── engine.py (含 monitor/evaluator/adjuster)

Phase 3: 与 Purpose 对接
└── Purpose.check() 调用 Metacognition.check()

Phase 4: 与 Agent 对接
└── Agent.run() 周期性调用 Metacognition.monitor()

Phase 5: 与 Drive 对接
└── Drive.evaluate() 后调用 Metacognition.review()
```

---

## 设计决定

| 项目 | 决定 |
|------|------|
| Monitor 监控内容 | 战略/阶段/当前目标 + 认知状态 + 注意力状态 |
| Evaluator 评估内容 | 目标完成质量 + 自我知识状态（最重要）+ 策略有效性 |
| Adjuster 调整类型 | 全部 8 种调整类型都需要 |
| 触发时机 | 执行前、执行中（事件驱动）、执行后 |
| 反省频率 | 灵活，由事件触发，非固定频率 |
| 反省代价 | 由用户承担（可见的停顿） |
| 反省本质 | 就是反省，不神秘 |

---

## 补充说明

### 反省的本质

元认知 = 反省

```
= 做之前想一想会不会做
= 做之中想一想做得怎么样
= 做之后想一想下次怎么改进
```

不是什么神秘的东西，就是一个"检查点"机制。

### 反省的代价

反省需要付出代价（LLM 调用 = Token 消耗），但这是值得的。

反省时 Agent 会停顿，类似人反省时需要停顿一样。

### 反省频率

反省频率不固定，根据任务情况灵活调整：

```
正常执行时：不主动反省，保持"钝感"
触发条件时才反省：
  - 连续失败 N 次
  - 时间超过阈值
  - 用户明确质疑
  - 目标完成/放弃时
```

### 实现机制

Metacognition 不是一直运行的进程，而是被"调用"的：

```
Agent 在执行过程中...
    ↓
某个时机触发 Metacognition.check()
    ↓
Metacognition 用 LLM "想一想"：我现在什么状态？
    ↓
返回一个 Adjustment（可能为空）
    ↓
谁调用它，谁负责处理这个 Adjustment（通常是 Agent）
```
