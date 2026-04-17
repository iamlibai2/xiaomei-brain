# 大脑架构设计：Basal Ganglia 层（丘脑-基底节）

> 创建时间：2026-04-17
> 状态：✅ 讨论完成，已保存

---

## 概述

Basal Ganglia 位于大脑皮层和爬行动物脑之间，负责**行为选择**和**注意力分配**。

```
┌─────────────────────────────────────────┐
│  大脑皮层（思考）                        │
│  Purpose / Metacognition / Drive        │
└────────────────┬────────────────────────┘
                 │ 决定做什么
                 ▼
┌─────────────────────────────────────────┐
│  丘脑-基底节                            │
│  决定怎么做、选择什么行动                 │
└────────────────┬────────────────────────┘
                 │ 选择并执行
                 ▼
┌─────────────────────────────────────────┐
│  Agent（爬行动物脑）                     │
│  执行选定的行动                          │
└─────────────────────────────────────────┘
```

---

## Basal Ganglia 的两个阶段

### 阶段1：习惯形成（学习）

```
重复的好行为变成自动化的习惯：

每次做 X 都得到好结果
    ↓
重复 N 次后
    ↓
X 变成习惯
    ↓
下次遇到类似情况
    ↓
自动执行，不需要思考
```

### 阶段2：行为选择（执行）

**行为选择 = 注意力分配**

实际上，注意力分配和行为选择是**同一个决策的两个角度**：

```
场景：我在写代码，用户发消息

问"注意力应该放哪？"：
  → 用户的新消息

问"具体做什么动作？"：
  → 暂停写代码，听用户说
    ↓
实际上是同一个决策：
  "选择关注用户 → 动作是回话"
```

**注意力分配 = 回答"关注哪件事"**
**行为选择 = 回答"做什么动作"**
**两者是同一决策**，可以合并为一个函数。

---

## 设计决定

| 项目 | 决定 |
|------|------|
| 行为选择机制 | 混合（价值 + 规则） |
| 习惯存储 | 单独存储，后期和 Skill 融合 |
| 注意力分配 | 与行为选择合并，不单独模块 |
| 规则 vs LLM | 简单情况用规则，复杂情况用 LLM |

## 技术实现原理

### 核心概念

```
Action Value（行动价值）：
    每个可能的行动有一个价值分数
    选择分数最高的

Habit（习惯）：
    {context: action} 的映射
    遇到类似 context 自动触发
```

---

## 1. 行为选择

```python
@dataclass
class ActionCandidate:
    action: str
    value: float           # 价值分数
    expected_reward: float # 预期奖励
    context: dict          # 上下文

class BasalGanglia:
    def __init__(self):
        self.action_values: dict[str, float] = {}

    def select_action(self, candidates: list[ActionCandidate]) -> str:
        """选择价值最高的行动"""
        if not candidates:
            return None

        # 评估每个候选行动
        for candidate in candidates:
            # 价值 = 预期奖励 - 执行成本
            candidate.value = candidate.expected_reward - self._get_action_cost(candidate.action)

        # 选择价值最高的
        selected = max(candidates, key=lambda c: c.value)
        return selected.action

    def _get_action_cost(self, action: str) -> float:
        """计算行动的执行成本"""
        costs = {
            "search": 0.3,      # 搜索成本较高
            "write_code": 0.2,
            "answer": 0.1,     # 回答成本低
            "explain": 0.1,
        }
        return costs.get(action, 0.2)
```

---

## 2. 注意力分配

```python
@dataclass
class AttentionState:
    focus_target: str           # 当前注意力焦点
    suppressed_targets: list[str]  # 被抑制的目标
    priority_order: list[str] # 优先级顺序

class BasalGanglia:
    def allocate_attention(self, signals: DriveSignals, context: dict) -> AttentionState:
        """分配注意力"""
        candidates = self._get_attention_candidates(context)

        # 基于 Drive 信号调整优先级
        if signals.stress_level > 0.7:
            # 压力大时，优先处理简单任务
            candidates = self._sort_by_complexity(candidates)
        else:
            # 正常时，按价值排序
            candidates = self._sort_by_value(candidates)

        return AttentionState(
            focus_target=candidates[0],
            suppressed_targets=candidates[1:],
            priority_order=candidates
        )
```

---

## 3. 习惯形成

### 设计决定：存储具体 action

```
选项A（采用）：存完整的具体 action
  habit = "执行 systemctl restart nginx"
  → 完全不需要 LLM，极快，低成本

选项B：存 action 类型
  habit = "执行系统命令"
  → Agent 执行时仍需 LLM 拼装具体命令
```

### 习惯存储结构

```python
@dataclass
class Habit:
    action: str           # 完整可执行的动作
    context_pattern: str  # 匹配的 context 模式
    count: int = 0       # 执行次数
    rewards: list = field(default_factory=list)  # 奖励历史
    avg_reward: float = 0.0

class HabitStore:
    def __init__(self):
        self.habits: dict[str, Habit] = {}

# 例子
habits = {
    "用户说重启服务": Habit(
        action="执行 systemctl restart nginx",
        context_pattern="用户说重启服务",
        count=5,
        rewards=[0.8, 0.9, 0.7, 0.8, 0.9],
        avg_reward=0.82
    ),
    "用户问时间": Habit(
        action="执行 date 命令",
        context_pattern="用户问时间",
        count=10,
        rewards=[0.9] * 10,
        avg_reward=0.9
    ),
}
```

### 习惯形成流程

**第1次：用户说"重启服务"**
```
用户："重启一下 Nginx"
    ↓
Basal Ganglia 检查习惯库
    ↓
没有匹配的习惯
    ↓
交给 Agent 执行：
  "执行 systemctl restart nginx"
    ↓
执行成功，用户满意
    ↓
Basal Ganglia 记录：
{
  context: "用户说重启服务",
  action: "执行 systemctl restart nginx",
  count: 1,
  rewards: [0.8],
  avg_reward: 0.8
}
```

**第2次：用户说"重启服务"**
```
用户："帮我重启下服务"
    ↓
Basal Ganglia 检查
    ↓
count=1 < 阈值(3)，继续作为普通候选
    ↓
Agent 执行 → 成功，奖励=0.7
    ↓
更新记录：count=2, avg_reward=0.75
```

**第3次及以后：习惯形成**
```
count >= 3 且 avg_reward > 0.6
    ↓
习惯形成！
habits["用户说重启服务"] = "执行 systemctl restart nginx"
```

### 习惯执行（自动化）

```
用户："重启服务"
    ↓
Basal Ganglia.match() 命中
    ↓
返回 action："执行 systemctl restart nginx"
    ↓
Agent 直接执行（0 LLM 调用）
```

### 习惯失效/更新

```
情况A：执行失败 → 奖励=0.0
    ↓
avg_reward 下降
    ↓
如果 avg_reward < 0.3
    ↓
删除习惯

情况B：用户换了命令
    ↓
旧习惯执行失败
    ↓
用户纠正："用 supervisorctl"
    ↓
形成新习惯
```

### 习惯 vs Skill 的区别

| | Habit（习惯） | Skill（技能） |
|---|---|---|
| 来源 | 从经验**学习**形成 | 显式**定义** |
| 存储 | 完整具体 action | 能力描述 + steps |
| 触发 | context 精确匹配 | agent 判断 |
| 灵活性 | 固定 mapping | 可描述复杂逻辑 |
| LLM 调用 | **0**（完全匹配时） | 需要判断 |

### 例子区分

```
Habit：
  "用户说重启服务" → "执行 systemctl restart nginx"
  "用户问时间" → "执行 date 命令"

Skill（代码重构）：
  description: "对代码进行重构，改善代码质量"
  steps:
    1. 分析代码结构
    2. 识别代码坏味道
    3. 制定重构计划
    ...
```

**简单重复 → Habit，复杂能力 → Skill**

---

## 4. LLM 介入时机

```
情况1：完全匹配 habit
  → 0 LLM 调用

情况2：部分匹配（需要适配）
  → 1 次 LLM 调用（适配具体内容）
  → 形成新 habit

情况3：完全不匹配
  → 正常流程（Purpose → Metacognition → Basal Ganglia）
  → LLM 介入做复杂决策
```

### 部分匹配示例

```
用户："重启 Apache"
    ↓
Basal Ganglia：没有完全匹配
    ↓
有类似 habit："用户说重启服务"
    ↓
问 LLM：
  "这是一个重启服务的请求，但具体是 Apache，
   原习惯是 nginx，action 应该怎么改？"
    ↓
LLM 返回："执行 systemctl restart httpd"
    ↓
执行成功 → 形成新 habit：
  "用户说重启Apache" → "执行 systemctl restart httpd"
```

---

## 5. 行为选择代码实现

### 核心逻辑（简化版）

```python
class BasalGanglia:
    def __init__(self):
        self.habit_store = HabitStore()
        self.reward_estimator = RewardEstimator()

    def select_goal(self, context: str, candidates: list[str]) -> SelectedGoal:
        """
        从候选目标中选择（candidates 由 Purpose 层传入）
        1. 先检查习惯（0 LLM）
        2. 没有习惯，用价值评估
        3. 复杂情况用 LLM
        """
        # 1. 先检查习惯（0 LLM）
        habit = self.habit_store.match(context)
        if habit:
            return SelectedGoal(
                goal=habit,
                source="habit",
                llm_needed=False
            )

        # 2. 没有习惯，检查是否复杂到需要 LLM
        if self._is_complex(candidates):
            # 复杂情况：触发 LLM 判断
            llm_goal = self._llm_select(context, candidates)
            return SelectedGoal(
                goal=llm_goal,
                source="llm",
                llm_needed=True
            )

        # 3. 简单情况：用规则打分
        best_goal = self._rule_based_select(candidates)
        return SelectedGoal(
            goal=best_goal,
            source="rule",
            llm_needed=False
        )

    def _rule_based_select(self, candidates: list[str]) -> str:
        """基于规则的选中"""
        best = None
        best_value = -float('inf')

        for candidate in candidates:
            reward = self.reward_estimator.estimate(candidate)
            cost = self._get_cost(candidate)
            value = reward - cost

            if value > best_value:
                best_value = value
                best = candidate

        return best

    def _is_complex(self, candidates) -> bool:
        """判断是否需要 LLM 介入"""
        # 多个强信号冲突时
        # 新情况，没有历史参考时
        pass
```

### 价值评估计算

```python
@dataclass
class ActionCandidate:
    action: str
    expected_reward: float  # 预期奖励
    context: dict

def calculate_value(candidate: ActionCandidate, action_cost: float) -> float:
    """价值 = 预期奖励 - 执行成本"""
    return candidate.expected_reward - action_cost

# 执行成本表（可调整）
ACTION_COSTS = {
    "search": 0.3,      # 搜索成本高
    "write_code": 0.2,  # 写代码中等
    "answer": 0.1,     # 回答成本低
    "explain": 0.1,
}
```

### expected_reward 来源

```python
class RewardEstimator:
    def estimate(self, action: str, context: dict) -> float:
        # 1. 先查历史奖励
        history_reward = self._get_history_reward(action)
        if history_reward:
            return history_reward

        # 2. 没有历史，用规则估算
        rule_reward = self._get_rule_reward(action)
        if rule_reward:
            return rule_reward

        # 3. 都没有，用 LLM 判断
        return self._llm_estimate(action, context)
```

### action_cost 可调节

```python
def get_cost(action: str, signals: DriveSignals) -> float:
    base_cost = ACTION_COSTS.get(action, 0.2)

    # Drive 状态影响感知成本
    if signals.stress_level > 0.7:
        return base_cost * 1.5  # 压力大时成本感知更高

    if signals.motivation_level < 0.3:
        return base_cost * 1.2  # 动力低时成本更高

    return base_cost
```

### 候选行动由 Purpose 层传入

```
关键决定：Basal Ganglia 不生成候选，只选择

Purpose 层：
  "帮用户写代码"
      ↓
  分解为候选目标列表：
    candidates = ["确认需求", "设计结构", "写代码"]
      ↓
Basal Ganglia：
  输入 candidates → 选择最优 → 输出选定的目标
```

这样 Basal Ganglia 职责单一，复杂度降低。

---

## 6. 习惯形成代码实现

```python
@dataclass
class Habit:
    action: str           # 完整可执行的动作
    context_pattern: str # 匹配的 context 模式
    count: int = 0
    rewards: list = field(default_factory=list)
    avg_reward: float = 0.0

class HabitStore:
    HABIT_THRESHOLD_COUNT = 3    # 重复多少次
    HABIT_THRESHOLD_REWARD = 0.6 # 平均奖励要高于多少
    HABIT_DECAY_REWARD = 0.3     # 奖励低于多少删除习惯

    def __init__(self):
        self.habits: dict[str, Habit] = {}

    def record(self, context: str, action: str, reward: float):
        """记录一次行为"""
        key = self._normalize_context(context)

        if key not in self.habits:
            self.habits[key] = Habit(
                action=action,
                context_pattern=key,
            )

        h = self.habits[key]
        h.count += 1
        h.rewards.append(reward)
        h.avg_reward = sum(h.rewards) / len(h.rewards)

        # 检查形成习惯
        if h.count >= self.HABIT_THRESHOLD_COUNT and h.avg_reward > self.HABIT_THRESHOLD_REWARD:
            h.action = action  # 固化 action

        # 检查删除低效习惯
        if h.avg_reward < self.HABIT_DECAY_REWARD:
            del self.habits[key]

    def match(self, context: str) -> Optional[str]:
        """精确匹配习惯"""
        key = self._normalize_context(context)
        habit = self.habits.get(key)
        if habit and habit.count >= self.HABIT_THRESHOLD_COUNT:
            return habit.action
        return None

    def _normalize_context(self, context: str) -> str:
        return context.lower().strip()


@dataclass
class SelectedAction:
    action: str
    source: str  # "habit" | "rule" | "llm"
    llm_needed: bool
```

---

## 与 Metacognition 的协作

### 职责区分

| | Metacognition | Basal Ganglia |
|---|---|---|
| 问的问题 | "我现在状态如何？做得好吗？" | "我应该做什么？" |
| 做的事 | 监控、评估 | 行为选择（包含注意力） |
| 输出 | 状态报告 | 选定的 action |
| 方向 | 向内看自己 | 向外做决策 |

### 协作流程

```
Metacognition（监控）：
"我现在是什么状态？我做得怎么样？"
    ↓ 报告状态
Basal Ganglia（决策）：
"基于当前状态，我应该做什么？"
    ↓ 决定 action
Agent（执行）：
"执行选定的 action"
```

### 协作示例

```
用户说话 + Agent 在写代码
    ↓
Metacognition 监控：
"我（Agent）现在注意力在哪里？"
→ 答案："在写代码上"
→ 状态：专注 / 走神 / 卡住

Basal Ganglia 决策：
"基于当前状态，我应该做什么？"
→ 选择："用户说话更重要，暂停写代码，回话"
→ 输出：action = "回话"

Agent 执行：
"执行回话"
```

---

## 与其他层的关系

```
┌─────────────────────────────────────────┐
│  Purpose / Metacognition / Drive       │
│  决定做什么                             │
└────────────────┬────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────┐
│  Basal Ganglia                          │
│  学习阶段：习惯形成                      │
│  执行阶段：行为选择（=注意力分配）       │
└────────────────┬────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────┐
│  Agent                                  │
│  执行选定的行动                          │
└─────────────────────────────────────────┘
```

---

## 文件结构

```
xiaomei_brain/basal_ganglia/
├── __init__.py
├── state.py           # 状态数据结构
├── habit.py           # 习惯形成
├── action_selector.py # 行为选择（包含注意力分配）
└── engine.py          # 核心引擎
```

> 注意：原 attention.py 已合并到 action_selector.py

---

## 这层解决的核心问题

### 目标：高质量完成任务

前几层解决的是：
- **Purpose**：做什么
- **Metacognition**：理解对了吗？能完成吗？
- **Drive**：有没有动力做

**Basal Ganglia 解决的是**：现在具体做哪个？

```
同一时刻，可能有多个"合理"的行动在争夺：

情况：
  - 正在写代码
  - 用户发来新消息
  - 突然想起有个更重要的事

前三层会给出：
  - Purpose：我的目标是完成这个项目
  - Metacognition：我现在进展如何
  - Drive：我有动力

但它们不会回答：
  - "我现在是继续写代码，还是先回消息？"
  - "这三个任务，先做哪个效率最高？"
  ↓
这个选择 → Basal Ganglia
```

### 类比

| 层 | 作用 |
|---|---|
| Purpose | "我的人生目标是成为好医生" |
| Metacognition | "我现在学习效率怎么样？" |
| Drive | "我真想出去玩，但完成作业会很开心" |
| **Basal Ganglia** | **"现在是看书还是打球？先做哪科作业？"** |

### 一句话总结

```
Basal Ganglia = 调度器

新情况 → 打分选最优
老情况 → 直接执行（习惯）

行为选择 = 注意力分配（同一个决策的两个角度）
```

---

## LLM 调用量分析

### 有无这层的对比

**没有 Basal Ganglia（直接执行）**：
```
用户："帮我写ERP系统"
    ↓
一个 LLM 调用（理解 + 规划 + 执行 + 回答）→ 一次性完成
```

**有 Basal Ganglia（结构化）**：
```
用户："帮我写ERP系统"
    ↓
Purpose.understand() → 1次 LLM
Metacognition.check() → 1次/目标
Agent 执行
Metacognition.review() → 1次/目标
```

### 实际增量

| 层 | LLM 增量 | 说明 |
|---|---|---|
| Purpose | 0 | 替换为结构化调用 |
| Metacognition | 少量 | 避免大返工 |
| Drive | 0 | 规则驱动，无LLM |
| **Basal Ganglia** | **0** | **规则驱动，无LLM** |
| Memory | 0 | 无LLM |

**结论**：Basal Ganglia 层本身不增加 LLM 调用量，它是规则驱动的。

---

## 完整流程示例：处理"帮我写ERP系统"

```
用户："帮我写一套ERP系统"
    ↓
┌─────────────────────────────────────┐
│  Metacognition.check()              │
│  → 发现需要澄清                      │
│  → Adjustment(REQUEST_CLARIFICATION) │
└─────────────────────────────────────┘
    ↓ 询问用户
用户："订单+库存，Python FastAPI"
    ↓
┌─────────────────────────────────────┐
│  Purpose.understand()              │
│  → Phase Goal：订单和库存模块        │
│  → 6个 Executable Goals            │
└─────────────────────────────────────┘
    ↓
┌─────────────────────────────────────┐
│  Metacognition.check()              │
│  → 每个目标执行前检查                │
└─────────────────────────────────────┘
    ↓
┌─────────────────────────────────────┐
│  Basal Ganglia.select_action()      │
│  → 在候选行动中选择最优              │
│  → 例如："先问技术栈"而非"直接写"   │
└─────────────────────────────────────┘
    ↓
┌─────────────────────────────────────┐
│  Agent 执行                          │
│  → 调用工具，写代码                  │
└─────────────────────────────────────┘
    ↓
┌─────────────────────────────────────┐
│  Drive.on_event()                  │
│  → 更新动力状态                      │
└─────────────────────────────────────┘
    ↓
┌─────────────────────────────────────┐
│  Memory 记录                         │
│  → 存入经验                          │
└─────────────────────────────────────┘
    ↓
┌─────────────────────────────────────┐
│  Metacognition.review()             │
│  → 复盘：做得好不好？                │
└─────────────────────────────────────┘
    ↓ 继续下一个目标
```

### Basal Ganglia 在流程中的具体作用

```
第一个目标：确认技术栈
    ↓
候选行动：
  - 直接开始写 → 价值高，但风险高（可能不符合用户预期）
  - 先问用户 → 价值高，风险低
    ↓
Basal Ganglia 选择："先问用户用什么技术栈"
    ↓
用户回答后，继续下一个目标...
```

---

## 与其他层的协作总结

```
┌─────────────────────────────────────────────────┐
│  Metacognition（监控）                           │
│  "我现在状态如何？做得好吗？"                  │
└─────────────────────┬───────────────────────────┘
                      ↓ 报告状态
┌─────────────────────────────────────────────────┐
│  Purpose（方向）                                 │
│  "我要完成什么目标"                             │
└─────────────────────┬───────────────────────────┘
                      ↓ 目标
┌─────────────────────────────────────────────────┐
│  Drive（动力）                                   │
│  "我有动力做吗？我感觉如何？"                   │
└─────────────────────┬───────────────────────────┘
                      ↓ 动力信号
┌─────────────────────────────────────────────────┐
│  Basal Ganglia                                  │
│  学习阶段：习惯形成                              │
│  执行阶段：行为选择（注意力分配 + 选 action）   │
└─────────────────────┬───────────────────────────┘
                      ↓ 选择 action
┌─────────────────────────────────────────────────┐
│  Agent（执行）                                   │
│  "执行选定的 action"                            │
│  → 如果需要生成内容，调用 LLM                    │
└─────────────────────────────────────────────────┘
```

### 重要澄清：Agent 的角色

**设计修正（2026-04-17）**

```
实际情况：
  Agent = LLM + 工具执行
  LLM 是核心决策者

Basal Ganglia 的结果处理方式：
  1. 确定性 action → 直接执行（不需要 LLM）
     例如：查时间、重启服务、执行确定命令

  2. 非确定性 → 放入上下文 → 交给 LLM 处理
     例如：写代码、回答问题、复杂推理
```

**区分标准**：

| 情况 | 处理方式 |
|------|---------|
| 确定性命令（查时间、重启服务） | Basal Ganglia → 直接执行 |
| 复杂推理、生成内容 | Basal Ganglia → 上下文 → LLM |

**各层 LLM 调用**：

| 层 | 需要 LLM |
|---|---------|
| Metacognition | ✅ |
| Purpose | ✅ |
| Basal Ganglia | ⚠️ 复杂才用 |
| Drive | ❌ 纯规则 |
| Memory | ⚠️ 生成摘要才用 |
| Agent | ✅ LLM 是核心 |

---

## 关键洞察

1. **LLM 是共同核心**：各层判断大多需要 LLM
2. **Basal Ganglia 结果两种去向**：放入上下文（大多数）或直接执行（确定性）
3. **习惯是核心加速器**：完全不需要 LLM，0 调用
4. **Agent = LLM + 工具执行**：LLM 决定做什么，Agent 执行
5. **确定性 action 直接执行**：不需要 LLM 介入
6. **候选由 Purpose 层传入**：Basal Ganglia 只负责选择，不生成候选，降低复杂度
