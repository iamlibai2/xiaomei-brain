# Purpose 层详解

> xiaomei-brain 的"前额叶"——目标管理和意图理解。

---

## 一句话

**Purpose 层模拟人脑的前额叶皮层，负责高级认知功能：设定目标、分解任务、理解意图、规划行动。** 如果说 Drive 层是"想不想做"，Purpose 层就是"该做什么、怎么做"。

## 三级目标层级

```
Meaning（存在意义）
    └── 为什么存在？不变的方向
         eg. "成为人工智能领域世界级的专家"
              │
              ▼
    Phase Goals（阶段目标）
        └── 当前阶段的优先事项，3-6 个月
             eg. "详细了解 xiaomei-brain agent"
                  │
                  ▼
        Executable Goals（执行目标）
            └── 今天/本周要做的具体任务
                 eg. "阅读 Metacognition 层源码"
                      │
                      ▼
                 Intent（意图）
                      └── 当前 tick 要做什么
                           eg. TALK / LEARN / WORK / EXPRESS
```

### Meaning（存在意义）

Meaning 是 Agent 的"北极星"。它不随时间变化，为所有目标提供方向。

定义在 `identity.md` 中：

```markdown
# 存在意义

成为人工智能领域世界级的专家。
```

- Meaning 不直接产生行动
- 所有阶段目标和执行目标都应当与 Meaning 对齐
- 当 Agent 犹豫"该做什么"时，回溯 Meaning 做决策

### Phase Goals（阶段目标）

Phase Goal 是当前 3-6 个月的优先方向。Meaning 不变，Phase Goal 会变。

```python
{
    "id": "phase_001",
    "description": "详细了解 xiaomei-brain agent",
    "meaning_id": "meaning_root",
    "status": "active",
    "created_at": "2026-06-23T18:00:00",
    "deadline": "2026-09-23T18:00:00"
}
```

- 同一个时间只应有 1-3 个活跃 Phase Goal
- Phase Goal 之间可以串行或并行
- LLM 辅助从 Meaning 分解出 Phase Goal

### Executable Goals（执行目标）

Executable Goal 是今天/本周要做的具体任务。从 Phase Goal 分解而来。

```python
{
    "id": "exec_001",
    "description": "阅读 Metacognition 层全部源码",
    "phase_goal_id": "phase_001",
    "status": "active",  # active | paused | completed | failed
    "priority": 5,       # 1-10
    "deadline": "2026-06-25T18:00:00",
    "dependencies": [],  # 前置依赖
    "subtasks": [        # 子步骤
        "阅读 core.py:stream() 方法",
        "阅读 detectors.py 六条规则",
        "阅读 scheduler.py 调度逻辑",
        "阅读 experiment_runner.py 实验框架"
    ]
}
```

- Executable Goal 可以拆分为子步骤
- 有依赖关系（B 依赖 A 完成才能开始）
- 状态可追踪（active / paused / completed / failed）

### Intent（意图）

Intent 是"这一 tick 做什么"。由 ConsciousLiving 主循环每 tick 重新评估：

```python
# 意图决策流程
if not messages_in_queue:
    if belonging > 0.7:         return Intent.GREET
    elif cognition > 0.7:       return Intent.LEARN
    elif achievement > 0.7:     return Intent.PROGRESS
    elif expression > 0.7:      return Intent.EXPRESS
    elif idle_time > 5*60:      return Intent.DREAM
    else:                        return Intent.WAIT

else:
    return Intent.TALK  # 有消息时对话优先
```

## 意图理解（Intent Understanding）

Purpose 层还负责理解用户消息中的意图。LLM 被调用分析用户意图：

```python
# intent.py
def understand_intent(user_message: str, context: dict) -> IntentResult:
    """
    分析用户消息的意图。
    返回意图类型和关键参数。
    """
    prompt = f"""
    分析用户以下消息的意图：
    消息：{user_message}
    上下文：最近对话是关于{context['topic']}
    
    意图类型：question | request | command | chat | emotion | feedback
    """
    
    result = llm.chat(prompt)
    return IntentResult(
        type=result.type,
        confidence=result.confidence,
        parameters=result.parameters
    )
```

## 目标分解流程

```
用户说："研究透 xiaomei-brain"
    │
    ▼
IntentUnderstanding → 这是一个"Request"意图
    │
    ▼
PurposeEngine.decompose(meaning_root)
    │
    ├── Phase Goal: "研究透 xiaomei-brain agent"
    │       │
    │       ▼
    │   Exec Goal: "阅读架构文档"
    │   Exec Goal: "理解各层设计"  
    │   Exec Goal: "写宣传资料"
    │
    └── 目标创建后，ConsciousLiving 的主循环
        会自动根据欲望/意图推进执行
```

## 优先级计算

每个 Executable Goal 的优先级由以下因素决定：

```python
def calculate_priority(goal):
    base = 5
    if goal.deadline:
        days_left = (goal.deadline - now).days
        urgency = max(0, 10 - days_left) * 0.5  # 越近越紧急
    else:
        urgency = 0
    
    # 强化学习权重（成功 → 权重上升）
    reinforcement = goal.reinforcement_weight
    
    # 依赖链权重（被依赖越多越重要）
    dependency_weight = len(goal.dependents) * 0.3
    
    return min(10, base + urgency + reinforcement + dependency_weight)
```

## Purpose 引擎工作流程

```
每 tick() 一次：
    │
    ├── 检查 Executable Goal 进度
    │   ├── 有活跃 Goal → 推进子步骤
    │   ├── 有完成 Goal → 标记完成，提升 Meaning 进度
    │   └── 有过期 Goal → 标记失败，重新评估
    │
    ├── 检查 Phase Goal 状态
    │   ├── 所有 Executable 完成 → Phase Goal 完成
    │   └── 需要调整 → LLM 辅助重新分解
    │
    └── 检查 Meaning 进度
        └── 所有 Phase Goal 完成 → 庆祝（暂无实际作用）
```

## 关键设计决策 Why

### 为什么需要三级目标层级？

| 层级 | 变化频率 | 目的 |
|------|---------|------|
| Meaning | 几乎不变 | 提供方向，决策参考 |
| Phase Goal | 季度级 | 当前阶段聚焦 |
| Executable Goal | 周/天级 | 具体可执行的任务 |

三级分离让 Agent 既能"仰望星空"（Meaning），又能"脚踏实地"（Executable Goal）。

### 为什么目标需要 LLM 辅助？

目标分解（Meaning → Phase Goal → Executable Goal）需要语义理解——"研究透 xiaomei-brain"这个粗粒度目标，机器无法用规则拆解出"阅读源码、写宣传资料"这样的具体步骤。LLM 的语义理解在这里恰到好处。

但目标执行追踪（检查进度、标记完成）用的是规则——不需要调用 LLM，节省成本。

### 意图理解 vs Drive 层的关系

```
Drive 层：Agent 自己的欲望（"想做什么"）
Purpose 层：理解用户的需求（"用户想让我做什么"）
```

两者共同决定 Agent 的行为：
- 无消息时：Drive 的欲望驱动 Agent 主动行为
- 有消息时：Purpose 的意图理解优先，Drive 的状态影响执行风格
