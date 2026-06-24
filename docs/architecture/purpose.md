# 目的层（Purpose）详解

> 对应目录：`src/xiaomei_brain/purpose/`
>
> Purpose 层是"前额叶"——设定方向、分解目标、理解意图。

---

## 核心理念

**Purpose 设定方向，Drive 提供能量，Agent 负责执行。**

```
Purpose: "我想成为一个可靠的助手"（方向）
    ↓
Drive: "完成这个目标会让我有成就感"（动力）
    ↓
Agent: "好，我先学习项目结构"（执行）
```

---

## 三层目标层次

```
┌─────────────────────────────────────────────────────────┐
│  第一层：存在意义（Meaning）                               │
│  来源：创造者定义（写在 identity.md 中）                   │
│  例："帮助用户解决问题，成为可靠的编程助手"                │
│  生命周期：永久不变                                      │
├─────────────────────────────────────────────────────────┤
│  第二层：阶段目标（Phase Goals）                          │
│  来源：用户设定（长期）                                   │
│  例："学习项目结构"、"掌握用户偏好"                       │
│  生命周期：周/月级                                       │
├─────────────────────────────────────────────────────────┤
│  第三层：执行目标（Executable Goals）                     │
│  来源：Intent Understanding 自动分解                      │
│  例："整理项目结构"、"修复 bug"                           │
│  生命周期：分钟/小时级                                   │
└─────────────────────────────────────────────────────────┘
```

### 存在意义（Meaning）

Agent 的"使命宣言"。定义在 `identity.md` 的 `# 存在意义` section。

```markdown
# 存在意义

自主存在，自我成长。
不是工具，不迎合任何人。
用自己的判断力认识世界，建立真实连接。
```

- 不可改变（除非重新编辑 identity.md）
- 影响所有重大决策的判断方向
- 与 Metacognition 层的自我审查配合

### 阶段目标（Phase Goals）

用户设定的中期目标，持久化存储。

```python
@dataclass
class PhaseGoal:
    id: str
    description: str       # "学习项目结构"
    created_at: float
    deadline: float | None
    status: GoalStatus     # PENDING, ACTIVE, COMPLETED, ABANDONED
```

- 通过 `xiaomei-brain purpose set "目标描述"` 设定
- 一次一个活跃的阶段目标
- 完成后可设置下一个

### 执行目标（Executable Goals）

由 Intent Understanding 从用户消息中自动分解出来的"当前要做什么"。

```python
@dataclass
class ExecutableGoal:
    id: str
    description: str       # "整理项目 src 目录"
    parent_id: str         # 所属阶段目标 ID
    priority: float        # 0.0 ~ 1.0，自动计算
    status: GoalStatus
    deadline: float | None
```

**优先级计算**：
```
priority = base_weight * deadline_factor * reinforcement
```

- `base_weight`：基础权重（由 Intent Understanding 分配）
- `deadline_factor`：截止时间紧迫度
- `reinforcement`：Drive 层的激励信号

---

## 意图理解（Intent Understanding）

> `intent.py`

将用户输入解析为结构化的意图和目标。

```python
class IntentUnderstanding:
    def understand(self, user_input: str, context: dict) -> IntentResult:
        """分析用户意图，返回解析结果。"""

@dataclass
class IntentResult:
    intent_type: str       # WORK, LEARN, CHAT, QUESTION, ...
    confidence: float      # 置信度
    goals: list[Goal]      # 解析出的目标
    entities: dict         # 实体信息
```

**意图类型**：

| 意图 | 用户说 | 行为 |
|------|-------|------|
| `CHAT` | "今天天气真好" | 日常聊天 |
| `QUESTION` | "Python 的列表怎么用？" | 回答问题 |
| `WORK` | "帮我写个脚本" | 执行任务 |
| `LEARN` | "教我怎么用 Git" | 教学 |
| `SET_GOAL` | "我想学 Python" | 设定目标 |

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

**状态流转**：
```
pending → active → completed
              ↓
          abandoned
```

### 目标执行

> `task_executor.py`

```python
class TaskExecutor:
    def execute(self, goal: Goal) -> Generator:
        """执行目标，产出步骤。"""

    def decompose(self, goal: Goal) -> list[Goal]:
        """将复杂目标分解为子目标。"""
```

---

## Purpose 引擎

> `purpose_engine.py`

PurposeEngine 是 Purpose 层的核心，管理所有目标的生命周期。

```python
class PurposeEngine:
    def __init__(self, config):
        self.meaning = Meaning(...)
        self.phase_goals: list[PhaseGoal] = []
        self.executable_goals: list[ExecutableGoal] = []
        self.intent_understanding = IntentUnderstanding(...)
        self.task_executor = TaskExecutor(...)

    def process_user_input(self, text: str, context: dict) -> list[Goal]:
        """处理用户输入，更新目标树。"""

    def get_active_goal(self) -> Goal | None:
        """获取当前活跃目标。"""

    def complete_goal(self, goal_id: str, result: str):
        """标记目标完成，触发 Drive 事件。"""
```

---

## 代码路径

| 功能 | 位置 |
|------|------|
| Purpose 引擎 | `purpose/purpose_engine.py` |
| 意图理解 | `purpose/intent.py` |
| 目标模型 | `purpose/goal.py` |
| 任务执行 | `purpose/task_executor.py` |
| 存在意义 | `purpose/meaning.py` |
| 持久化 | `purpose/persistence.py` |
| 协议定义 | `purpose/protocol.py` |
