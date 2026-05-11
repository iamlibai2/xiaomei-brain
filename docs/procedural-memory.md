# 过程记忆设计文档

## 概述

过程记忆解决的是"如何做"的问题——让 agent 学会做某类事情的正确流程，每次遇到同类需求时按固定的高质量步骤处理，而不是每次凭直觉摸索。

与情景记忆（"发生了什么"）、语义记忆（"世界是什么样的"）不同，过程记忆是可执行的：告诉 agent 在什么条件下该做什么事、怎么做、做完了怎么记录。

---

## 核心设计原则

1. **模拟人类学习方式**：过程中不总结，过程完成后才总结
2. **不需要确认激活**：LLM 生成后直接激活，不额外打断对话
3. **触发不需要向量**：关键词粗筛 O(N) 足够，语义泛化不是过程记忆的核心价值
4. **Dream 模块专注巩固**：提取逻辑统一到沉默期，Drem 不负责生成，只负责维护
5. **单次 LLM 调用生成**：从对话历史一次性生成完整 procedure 结构，不需要多次交互

---

## 数据结构

### procedures 表（SQLite）

```sql
CREATE TABLE procedures (
    id TEXT PRIMARY KEY,                -- "PROC-2026-001"
    name TEXT NOT NULL,                 -- "泡龙井茶"
    description TEXT,                   -- 自然语言描述，语义参考用
    trigger_config TEXT DEFAULT '{}',   -- JSON: 关键词粗筛条件
    steps TEXT NOT NULL DEFAULT '[]',   -- JSON array: 步骤序列

    scope TEXT DEFAULT 'agent',          -- 'agent': 所有用户共享 | 'user': 单用户私有

    execution_count INTEGER DEFAULT 0,  -- 执行次数
    execution_success_rate REAL DEFAULT 0.0,  -- 成功率
    weight REAL DEFAULT 0.5,             -- 动态权重，影响排序

    status TEXT DEFAULT 'active',        -- active | archived | deprecated

    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    last_executed REAL,

    version INTEGER DEFAULT 1,
    version_history TEXT DEFAULT '[]',  -- JSON: [{version, updated_at, changes}]
    execution_log TEXT DEFAULT '[]'     -- JSON: [{timestamp, result, user_feedback, notes}]
);
```

### trigger_config 结构

```json
{
  "type": "any",   -- all: 所有条件都满足 | any: 任一条件满足
  "conditions": [
    {"field": "user_message", "operator": "contains", "value": "泡茶"},
    {"field": "user_message", "operator": "contains", "value": "喝茶"}
  ]
}
```

支持的 operator：`contains` | `startswith` | `endswith` | `regex`

### steps 结构

```json
[
  {"id": "s1", "name": "温杯", "description": "用热水烫杯，提高茶香激发效果", "next": "s2", "fallback": "s1"},
  {"id": "s2", "name": "置茶", "description": "取3g龙井放入杯中", "next": "s3", "fallback": "s_ask_user"},
  {"id": "s3", "name": "注水", "description": "85度水温，沿杯壁缓缓注水1/3", "next": "s4", "fallback": "s_escalate"},
  {"id": "s4", "name": "出汤", "description": "静置30秒后注满杯，趁热饮用", "next": null, "fallback": null}
]
```

- `next`: 下一步的 step id，null 表示流程结束
- `fallback`: 失败时的重试或跳转目标

---

## 完整流程

```
用户对话
    ↓
对话结束 + 沉默期（用户 2-3 分钟无新消息）
    ↓
[ProcedureLearner] LLM 扫描对话历史
    - 检测到 teach intent（"以后帮我泡茶先问茶种"）
    - 或检测到复杂任务完成（子目标数 >= 3）
    ↓
有则 LLM 生成 procedure 结构
    ↓
直接激活，存入 procedures 表，status='active'
    ↓
下次用户输入
    ↓
[ProcedureMatcher] 关键词粗筛
    - 遍历所有 active procedure 的 trigger_config
    - type=any: 任一条件命中即入选
    - type=all: 所有条件都命中才入选
    ↓
匹配到的 procedure 按 weight 降序，取 top-3
    ↓
top-3 的 name + description + steps 摘要注入 context prompt
    ↓
LLM 自然推理，决定是否使用流程
    ↓
使用则按 steps 执行，与用户交互完成
    ↓
[ProcedureExecutor] 记录执行结果到 execution_log
    ↓
[Dream] 定期巩固：
    - 分析 execution_log，调整 execution_success_rate
    - 长期未执行（>N 天）的 procedure weight 衰减
    - weight 低于阈值则 archived
    - 发现相似的 procedure 建议合并
```

---

## 学习机制

### 触发时机

**唯一的触发时机：对话结束 + 沉默期**

对话进行中不总结，对话完成后统一分析。模拟人类的学习方式：过程结束后回顾提炼。

### teach intent 检测

LLM 扫描对话历史时判断：

```
prompt: """
对话历史：
{recent_messages}

判断这段对话中：
1. 用户是否在教 agent 一个标准流程（"以后遇到X要先Y"）
2. 用户是否在纠正 agent 的做法（"不是这样做的，应该..."）

回复格式（只输出 JSON）：
{
  "teach_intent": true/false,
  "teach_content": "用户教学内容的简要描述（无则空字符串）",
  "task_completion": true/false,
  "task_description": "完成的复杂任务描述（无则空字符串）"
}
"""
```

### procedure 生成

检测到 teach intent 或 task_completion 时，调用 LLM 生成：

```
prompt: """
对话历史：
{relevant_history}

根据以上对话，生成一个标准流程：

1. name: 简短名称（5字以内）
2. description: 一句话描述用途
3. trigger_config: 关键词粗筛条件（任一条件命中即可触发）
   - type: "any" 或 "all"
   - conditions: 3-5 个条件，field 固定为 user_message
4. steps: 步骤序列（3-6步，每步包含 name + description）

只输出 JSON，不要解释。
"""
```

### 触发条件的生成

trigger_config 的条件由 LLM 根据对话内容自动生成：

- 用户说"以后泡茶先问茶种" → `contains: 泡茶`
- 用户说"帮我写个报告" → `contains: 报告`, `contains: 写个`, `contains: 总结`

不需要人工定义关键词，LLM 自己判断哪些词是触发这条流程的核心。

---

## 触发机制

### 关键词粗筛（唯一触发方式）

```
用户消息 → 遍历所有 active procedure → trigger_config 匹配 → weight 排序 → top-3
```

纯字符串匹配，无向量，无额外 LLM 调用，O(N) 时间复杂度。

当 procedure 数量超过 200 条时，再考虑加向量层做语义兜底。当前阶段不需要。

### context 注入格式

top-3 procedure 注入到 context assembler 的 system prompt：

```
## 可用标准流程
- [{procedure.name}] {procedure.description}
  步骤：{step1.name} → {step2.name} → ...
- ...
```

LLM 在推理时自己判断用哪个流程、按什么顺序执行。

### 为什么不强制执行 steps

steps 是 LLM 推理时的指导，不是代码级状态机。LLM 按步骤思考和执行，但保留灵活调整的空间。fallback 路径也是 LLM 自己判断，不是硬编码的跳转。

---

## 与其他模块的关系

### 与 Purpose 层（目标管理）

| | Purpose | Procedure |
|--|---------|-----------|
| 解决什么问题 | 目标是什么 | 做这件事的标准流程 |
| 核心数据结构 | 目标树（goal hierarchy） | 步骤序列（steps） |
| 触发时机 | 用户提出目标时 | 用户提出需求时 |
| 更新方式 | 目标完成/放弃时更新 | 执行日志驱动衰减 |
| 关系 | 独立正交，可组合 | 独立正交，可组合 |

两者独立使用，也可以组合：
- Purpose 规划目标（"写一本小说"）
- Procedure 提供执行步骤（"写工作报告的标准流程"）
- 具体写哪个章节、怎么推进，由 Purpose 层管理

### 与 Dream 模块（梦境巩固）

Dream 不负责提取，只负责巩固：

1. **执行日志分析**：统计各 procedure 的成功率
2. **weight 衰减**：长期未执行的 procedure 降低权重
3. **归档决策**：weight 低于阈值（如 0.1）则 archived
4. **合并建议**：发现 description 高度相似的 procedure，提示是否合并
5. **步骤验证**：检查已有 procedure 的 steps 是否仍然合理

### 与 memories 表

procedures 表独立于 memories 表，原因：

- 用途不同：memories 存"发生了什么"，procedures 存"怎么做"
- 访问模式不同：memories 频繁向量搜索，procedures 关键词扫描
- 生命周期不同：memories 衰减很慢，procedures 可能频繁更新 weight
- 迁移风险：混在一起会增加复杂度

---

## 边界情况处理

| 场景 | 处理方式 |
|------|----------|
| 没有匹配到任何 procedure | 正常对话，不注入流程提示 |
| 关键词命中但 LLM 判断不适合 | LLM 自行忽略，不强制执行 |
| 执行到一半用户纠正 | LLM 感知纠正内容，停止当前步骤 |
| 步骤执行失败 | LLM 自己决定 fallback 或询问用户 |
| 多条 procedure 都匹配 | top-3 按 weight 排序，LLM 选最合适的 |
| 用户当场教了错误的流程 | 下次沉默期 LLM 重新分析，自动覆盖 |
| procedure 超过 200 条 | 加向量索引层做语义兜底（后续迭代） |

---

## 实施顺序

### Phase 1: 存储层（最小可行）
- `procedures` 表创建迁移
- `store_procedure()` / `get_procedures()` / `match_procedures()` / `log_procedure_execution()`
- 不加 trigger_config，只存 name + description + steps

### Phase 2: 学习触发
- 沉默期触发机制（后台线程检测沉默）
- LLM teach intent 检测 + procedure 生成
- 直接激活，不 pending_review

### Phase 3: 触发执行
- 关键词粗筛实现
- context 注入
- LLM 按 steps 执行

### Phase 4: 巩固（已实现）
- Dream 模块接入：ProcedureConsolidationJob
- weight 衰减逻辑：根据 idle 时间自动衰减（每小时 WEIGHT_DECAY_BASE=0.999）
- execution_log 分析：结合显式标记（`<PROC>`）和推断两种方式
- 归档决策：weight<0.1 OR idle>30d+weight<0.3 OR 从未执行且创建>60d → archived

### 不在当前阶段
- 向量语义搜索（200+ 条 procedure 后再考虑）
- 多用户私有 procedure
- procedure 版本 diff 可视化