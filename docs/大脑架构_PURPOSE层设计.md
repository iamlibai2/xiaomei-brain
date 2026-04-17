# 大脑架构设计：Purpose 层（目的系统）

> 创建时间：2026-04-17
> 状态：讨论完成，待实现

---

## 目标层级

```
┌─────────────────────────────────────────────────────────┐
│  第一层：存在意义（Meaning）← 预置，创造者定义             │
│  例："帮助用户解决问题，成为可靠的编程助手"                │
├─────────────────────────────────────────────────────────┤
│  第二层：阶段目标（Phase Goals）← 用户设定                │
│  例："学习项目结构"、"掌握用户偏好"                       │
├─────────────────────────────────────────────────────────┤
│  第三层：执行目标（Executable Goals）← Intent Understanding│
│  例："整理项目"、"修复bug"                               │
└─────────────────────────────────────────────────────────┘
```

---

## 目标类型

| 类型 | 说明 |
|------|------|
| `STRATEGIC` | 战略目标（对应存在意义） |
| `PHASE` | 阶段目标（中期，用户设定） |
| `EXECUTABLE` | 可执行目标（当前） |

---

## 目标状态

```
pending → active → completed
              ↓
          abandoned
```

| 状态 | 说明 |
|------|------|
| `PENDING` | 等待执行 |
| `ACTIVE` | 当前执行中 |
| `COMPLETED` | 已完成 |
| `ABANDONED` | 已放弃 |

---

## 目标生命周期

```
用户输入 → Intent Understanding → Goal(s)
              ↓
    一个 session 只有一个活跃目标
    其他进入 pending 队列
              ↓
    目标分解（自动完成）
              ↓
    Agent 执行 → 用户反馈 → 评价体系
              ↓
    长期目标持久化到全局记忆
```

---

## 设计决定

| 项目 | 决定 |
|------|------|
| Meaning 落地 | 结构化，方便编辑 |
| Phase Goals | 用户显式设置 |
| Goal Tree | 单父节点 |
| 活跃目标 | 一个 session 只有一个 |
| 目标分解 | 自动完成，用户反馈驱动改进 |
| 长期目标 | 持久化到全局记忆 |
| 反馈体系 | Purpose + Drive 交界 |
| Meaning 来源 | 第一版你和开发者来写 |
| Phase Goals 存储 | 配置文件，后期整合记忆 |
| Intent Understanding | 单独 LLM 调用 |

---

## 数据结构

```python
# purpose/meaning.py
@dataclass
class Meaning:
    """存在的意义 - 预置、不可变"""
    identity: str                    # "我是谁"
    values: list[str]               # ["可靠性", "效率", "用户利益优先"]
    constraints: list[str]          # ["不伤害用户", "保护隐私"]
    aspirations: list[str]          # ["成为最懂用户的助手"]

# purpose/goal.py
class GoalType(Enum):
    STRATEGIC = "strategic"       # 战略（对应 Meaning）
    PHASE = "phase"               # 阶段目标
    EXECUTABLE = "executable"     # 可执行

class GoalStatus(Enum):
    PENDING = "pending"
    ACTIVE = "active"
    COMPLETED = "completed"
    ABANDONED = "abandoned"

@dataclass
class Goal:
    id: str
    description: str
    goal_type: GoalType
    status: GoalStatus = GoalStatus.PENDING
    parent_id: Optional[str] = None
    priority: float = 0.5          # 用户指定的基础优先级
    progress: float = 0.0
    reinforcement_count: int = 0    # 用户多次提到的次数
    created_at: float = 0
    deadline: Optional[float] = None
    metadata: dict = field(default_factory=dict)
```

---

## Intent Understanding

```python
class IntentType(Enum):
    TASK = "task"           # 执行任务
    QUERY = "query"         # 提问
    CHAT = "chat"           # 闲聊
    CLARIFICATION = "clarification"  # 澄清

class GoalRelation(Enum):
    NEW = "new"                     # 新建
    SUB_GOAL_OF = "sub_goal_of"     # 关联到已有目标
    MODIFIES = "modifies"           # 修改已有目标

@dataclass
class IntentResult:
    intent_type: IntentType
    goals: list[Goal]              # 可能多个
    relation: GoalRelation
    target_goal_id: str | None
    confidence: float               # 置信度 0.0-1.0
    reasoning: str                 # LLM 的推理过程
```

---

## 优先级计算

```python
def calculate_priority(goal: Goal, context: Context) -> float:
    base = goal.explicit_priority  # 用户指定，权重最高

    # 动态因素
    recency_boost = goal.reinforcement_count * 0.05  # 用户多次提到 +0.05
    deadline_boost = max(0, (goal.deadline - now) / goal.deadline) * 0.1

    # 类型权重
    type_weight = {
        GoalType.EXECUTABLE: 0.3,
        GoalType.PHASE: 0.2,
        GoalType.STRATEGIC: 0.1,
    }[goal.goal_type]

    return min(1.0, base + recency_boost + deadline_boost + type_weight)
```

---

## 核心引擎接口

```python
class PurposeEngine:
    def __init__(self, meaning: Meaning, llm_client):
        self.meaning = meaning
        self.llm = llm_client
        self.goals: dict[str, Goal] = {}
        self.current_goal: Optional[Goal] = None
        self.pending_queue: list[str] = []  # pending goal IDs

    def understand(self, user_input: str, context: Context) -> IntentResult:
        """用户输入 → IntentResult（调用 LLM）"""
        ...

    def add_goal(self, goal: Goal) -> None:
        """添加目标"""
        ...

    def set_current(self, goal_id: str) -> None:
        """设置当前活跃目标"""
        ...

    def complete_current(self) -> None:
        """完成当前目标"""
        ...

    def get_next(self) -> Optional[Goal]:
        """获取下一个要执行的目标"""
        ...

    def abandon(self, goal_id: str, reason: str = "") -> None:
        """放弃目标"""
        ...
```

---

## 与其他层对接

```
用户输入 → PurposeEngine.understand()
              ↓ IntentResult
        PurposeEngine.set_current()
              ↓
        Agent.run(goal)  ← 传入当前 goal
              ↓
        Agent 完成 / 报告进度
              ↓
        PurposeEngine.complete_current()
              ↓
        Drive.evaluate(goal, feedback)  ← Drive 层
              ↓
        PurposeEngine 调整优先级/策略
```

---

## 文件结构

```
xiaomei_brain/purpose/
├── __init__.py
├── meaning.py          # Meaning 数据结构
├── goal.py             # Goal 数据结构
├── purpose_engine.py   # 核心引擎
├── intent.py           # Intent Understanding
├── persistence.py      # 持久化
└── config.py          # 配置
```

---

## 实现顺序

```
Phase 1: 数据结构
├── meaning.py
└── goal.py

Phase 2: 核心引擎
├── purpose_engine.py (不含 intent)
└── persistence.py

Phase 3: Intent Understanding
└── intent.py

Phase 4: 与 Agent 对接
└── 修改 Agent.run() 接收 goal 参数

Phase 5: 与 Drive 对接
└── 添加 evaluate() 回调
```

---

## 待细化事项

- [ ] Meaning 的具体内容（你和开发者来写）
- [ ] Phase Goals 的配置格式（YAML/JSON？）
- [ ] Intent Understanding 的 prompt 设计
