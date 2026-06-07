# Phase 1: 目标自主执行闭环 — 完整代码分析

> 分析日期: 2026-06-04
> 分析范围: 从用户输入到目标执行完毕的完整链路

---

## 一、总体架构

```
用户消息
  │
  ▼
ConversationDriver.handle_message()          ← 消息路由中枢
  │
  ├── PACE 等待恢复?
  ├── "继续"检测?
  ├── 等待确认?
  ├── ! 前缀 → _task_mode = True
  │
  ├── _task_mode=True + has_active_goal  ──→ 意图分析 + 任务执行
  ├── _task_mode=True + no_goal          ──→ 意图分析 + 创建目标
  └── _task_mode=False (聊天模式)         ──→ 聊天（LLM可调用create_goal工具）
       │
       ▼
  GoalManager                              ← 目标全生命周期管理
       │
       ├── analyze_intent()                ← LLM意图分类 + 目标分解
       ├── handle_task_intent()            ← 过滤/去重/创建/路由
       │     ├── _create_task_from_intent()  → PurposeEngine.add_goal()
       │     └── _route_goal_by_type()       → 分解 → 执行
       │
       ├── _run_chat()                     ← 分派到 PACE 或 ReAct
       │     ├── _task_mode=True  → _run_pace()  → PACERunner → CognitiveLoop
       │     └── _task_mode=False → _run_react() → Agent.stream()
       │
       └── PROGRESS tag 解析               ← LLM 自报进度 → 自动推进
```

## 二、三条目标创建与执行路径

### 路径 A: 任务模式 + 意图分析（明确的任务驱动）

**触发条件**: 用户先输入 `/intask` 或消息以 `!` 开头

**流程**:

1. `handle_message()` 检测到 `!` 前缀 → 设置 `_task_mode = True` (`conversation_driver.py:121-122`)

2. 用户发送任务描述，例如 `!帮我写一份agent行业调研报告`

3. `analyze_intent()` (`goal_manager.py:142-191`):
   - `!` 前缀走规则路径：直接创建 Goal，调用 `decompose_goal()` 分解子目标
   - 无 `!` 前缀走 LLM 路径：调用 `IntentUnderstanding.understand()`，两阶段 LLM pipeline（意图分类 → 目标分解）

4. 返回 `IntentResult`，包含 `intent_type=TASK`, `goals=[...]`, `sub_goals=[...]`

5. `handle_task_intent()` (`goal_manager.py:195-214`):
   - 过滤元目标（"意图识别"、"目标提取"等内部目标）
   - 检查是否modifies已有目标
   - LLM相似目标去重（与最近10个已完成目标比较）
   - `_create_task_from_intent()` → `PurposeEngine.add_goal()` 创建目标
   - `_route_goal_by_type()` → 分发执行

6. `_route_execution_with_sub_goals()` (`goal_manager.py:370-380`):
   - 调用 `purpose.decompose_goal()` 创建子目标
   - 激活第一个子目标
   - 调用 `_run_chat()` → PACE 或 ReAct 执行

7. **执行循环**:
   - **ReAct 路径**: `ConversationDriver._run_react()` (`conversation_driver.py:189-365`)
     - `while True` 循环：每次 LLM 回复后检查 PROGRESS tag
     - `should_auto_advance()` 判断是否切换到下一个子目标
     - 自动构造系统消息 `"[系统] 子目标：{next_goal.description}"` 继续循环
   - **PACE 路径**: `GoalManager._run_pace()` → `PACERunner.run()` → `CognitiveLoop`
     - PERCEIVE → ASSESS → DECIDE → ACT 四阶段
     - 硬规则检测（TOOL_STORM, TOOL_LOOP, EMPTY_RESPONSE 等）
     - LLM 预算控制（避免过度调用）
     - 卡住时 escalate 给用户

8. **完成**: 所有子目标完成 → 根目标标记完成 → `_clear_current_goal()` → 知识提取

### 路径 B: 聊天模式 + create_goal 工具（隐式目标创建）

**触发条件**: 普通聊天模式，用户说"帮我做X"，LLM 自主判断调用 `create_goal` 工具

**流程**:

1. `handle_message()` 走到聊天模式分支 (`conversation_driver.py:164-170`)
   - `intent_type` 强制设为 `CHAT`，`confidence=1.0`
   - 意图上下文为空字符串（`task_executor.build_intent_context()` 对 CHAT 返回 `""`）

2. `_run_chat()` → `_run_react()` — 标准 ReAct 循环

3. LLM 在 ReAct 循环中调用 `create_goal(description="写agent行业调研报告")`

4. `create_goal` 工具 (`tools/builtin/goal.py:49-116`):
   - 校验描述长度 ≥ 10 字
   - 调用 `PurposeEngine.add_goal(description=..., goal_type=EXECUTABLE)`
   - `add_goal()` 内部：**如果 `current_goal is None`，自动 `set_current(goal.id)`** (`purpose_engine.py:254-255`)
   - **不做分解** — 只创建一个顶层 Goal，没有子目标
   - 返回 `"已创建任务「写agent行业调研报告」。目标将在聊天结束后自动推进。"`

5. LLM 看到工具返回结果，通常回复 "好的，我已经记录了这个任务，稍后帮你完成"

6. ReAct 循环结束（LLM 返回纯文本，无工具调用）

7. `_run_react()` 中:
   - `parse_progress_tag(content)` → `None`（聊天模式不输出 PROGRESS tag）
   - `should_auto_advance(None)` → `False`（progress_data 为空）
   - 循环退出

8. **目标已创建但未自动执行** — Goal 处于 ACTIVE 状态（被 `set_current` 激活），但没有触发执行循环

**"稍后执行"的触发方式**:
- 用户说"继续" → `handle_continue()` 检测 → `_resume_or_activate_goal()` → `_run_chat()` → ReAct
- 用户进入任务模式 `/intask`，然后发送消息 → 路径 A
- （理论上）成就欲驱动的 `progress_goal` 主动行为，但当前 `ProactiveOutput` 中未见此触发

### 路径 C: PACE 等待恢复

**触发条件**: PACE 执行中 Agent 等待用户反馈，用户回复

**流程** (`conversation_driver.py:90-109`):

1. `is_pace_waiting()` → True
2. 检测是否是"继续"语句
3. 如果 `_task_mode=True`:
   - 恢复 PACE 执行：创建 nudge 上下文（包含用户回复）
   - `_init_pace_runner()` + `_pace_runner._resume_nudge = nudge`
   - `_run_pace(msg, intent_context)`
4. 如果 `_task_mode=False`:
   - 恢复 ReAct 执行：拼接用户回复到 intent_context
   - `_run_react(msg, intent_context + nudge_context)`

---

## 三、子目标自动推进机制（ReAct 路径核心）

位于 `_run_react()` 的 `while True` 循环中 (`conversation_driver.py:203-338`):

```
while True:
    assembled = build_context(agent, current_msg.content, ...)

    # ReAct 执行一轮
    for chunk in agent.stream(messages=assembled, ...):
        chunks.append(chunk)
    content = "".join(chunks)

    # 解析 PROGRESS tag
    progress_data = parse_progress_tag(content)
    if progress_data and progress_data["status"] == "completed":
        # 存储子目标产出
        store_sub_goal_output(goal_id, summary)

        # 检查是否所有兄弟子目标已完成
        if all_done:
            complete_goal(root_goal)

        # 早期完成检测: >=2个子目标完成 + 产出已覆盖最终交付物
        elif sub_goal_covers_deliverable(summary, root_goal) and completed_count >= 2:
            skip_remaining_sub_goals()
            complete_goal(root_goal)

    # 判断是否继续推进
    if not should_auto_advance(progress_data):
        scheduler.tick(...)
        return  # 退出循环

    # 构造下一个子目标的系统消息
    next_goal = purpose.get_current()
    current_context = build_intent_context_for_goal(next_goal)
    current_msg = LivingMessage(
        content=f"[系统] 子目标：{next_goal.description}", ...)
    # 继续 while 循环
```

**`should_auto_advance()` 的条件** (`goal_manager.py:932-948`):
1. `progress_data` 不为空
2. `progress_data["status"] == "completed"`
3. 未被取消
4. PurposeEngine 存在
5. 当前目标存在
6. **当前目标有 `parent_id`**（是子目标，不是根目标）
7. 当前目标是 ACTIVE 状态
8. 当前目标进度为 0（刚激活，未执行过）

**关键约束**: 只有子目标才能自动推进。根目标没有 `parent_id`，不会触发 auto-advance。这意味着 `create_goal` 工具创建的顶层目标（无子目标分解）不会被自动推进。

---

## 四、PROGRESS 标签机制

系统通过 `<PROGRESS>` XML 标签让 LLM 自我报告进度 (`prompts/purpose.py:78-90`):

```xml
<PROGRESS>
{"status": "completed", "summary": "一句话总结本子目标的产出"}
</PROGRESS>

或

<PROGRESS>
{"status": "in_progress"}
</PROGRESS>
```

**指令注入方式**:
- `build_intent_context_for_goal()` — 为特定子目标构建上下文时注入
- `build_intent_context()` → `task_executor.build_intent_context()` — 通用意图上下文

**注意**: 聊天模式（CHAT intent）的 `build_intent_context()` 返回空字符串，不注入 PROGRESS 指令。所以聊天模式下 LLM 不会输出 PROGRESS tag。

**解析**: `parse_progress_tag()` 使用正则 `<PROGRESS>\s*(\{.*?\})\s*</PROGRESS>` 提取 JSON。

---

## 五、关键数据流

### Goal 生命周期

```
PENDING ──→ ACTIVE ──→ COMPLETED
  │           │
  │           └──→ PAUSED ──→ ACTIVE (恢复)
  │
  └──→ ABANDONED
```

### Goal 层级

```
Meaning (存在意义，从 identity.md 加载，不可变)
  └── Goal (顶层，用户可见)
        ├── SubGoal 1 (PENDING → ACTIVE → COMPLETED)
        ├── SubGoal 2 (PENDING → ACTIVE → COMPLETED)
        └── SubGoal 3 (PENDING → ...)

MAX_DEPTH = 2 (goal.py:322)
```

### 上下文构建

`build_intent_context_for_goal()` 构建的上下文包含:
```
任务目标: {parent.description}
【当前任务】只执行这一个子目标，不要做其他事情：
「{goal.description}」
完成标准: {acceptance_criteria}
进度：2/5 子目标已完成
【全局进度】
  ✓ 1. 第一步描述
  →进行中 2. 当前子目标
  ○ 3. 第三步描述
<PROGRESS> 指令
```

### 确认机制

两种确认类型:
1. **标准确认** (`_build_confirm_info`): 两 Tier — LLM 结构化选项 / 默认确认框
2. **PACE 确认** (`_on_confirm`): PACE 执行中遇到问题，询问用户

---

## 六、已发现的问题与改进点

### 问题 1: 聊天模式创建的目标不会自动执行

**现状**: `create_goal` 工具返回 "目标将在聊天结束后自动推进"，但实际上:
1. Goal 被创建并设为 `current_goal`（通过 `add_goal` 的自动激活）
2. 但 ReAct 循环已结束，不会自动启动新的执行循环
3. 没有代码在聊天结束后检查是否有待执行的目标

**根因**: `add_goal()` 不做分解，不触发执行。创建的顶层目标没有子目标，`should_auto_advance()` 要求 `parent_id` 不为空。

**影响**: 用户聊天中说"帮我做X"，Agent 记录了但不会主动执行。需要用户说"继续"或进入任务模式。

### 问题 2: `_task_mode` 状态管理的边界模糊

**现状**: `_task_mode` 由以下方式切换:
- `/intask` 命令 → `True`
- `!` 前缀消息 → `True`
- `/inchat` 命令 → `False`

但没有自动退出机制。任务完成后 `_task_mode` 依然为 `True`，下次消息仍走意图分析路径。

**影响**: 任务完成后用户发 "你好"，LLM 仍会做意图分析（虽然会正确分类为 CHAT）。

### 问题 3: 聊天模式 + create_goal 的 LLM 行为不确定

**现状**: `create_goal` 工具描述说 "调用后只反馈「已创建任务，稍后执行」"，但:
1. LLM 可能不遵守这个指令，直接开始执行
2. LLM 可能追问细节而不是创建目标
3. create_goal 需要 ≥10 字描述，LLM 可能在信息不足时也调用

**影响**: 行为依赖 LLM 的遵循程度，不够确定性。

### 问题 4: 早期完成检测的阈值可能不准确

**现状** (`_sub_goal_covers_deliverable`): 需要 ≥2 个子目标完成才触发早期完成。如果只有 2 个子目标且第一个就完成了全部工作，不会触发早期完成。

**影响**: 简单任务可能浪费一轮不必要的执行。

### 问题 5: PACE 和 ReAct 两套执行路径的差异

**现状**:
- **ReAct**: `_run_react()` 中的 while True 循环，PACE 由 GoalManager 通过 `_pace_waiting` 标记管理
- **PACE**: `PACERunner.run()` → `CognitiveLoop.run()`，有完整的 PERCEIVE→ASSESS→DECIDE→ACT 管道

两套路径的上下文构建、进度检测、错误处理不完全一致。

**影响**: 维护两套逻辑，行为可能有细微差异。

### 问题 6: 子目标错误处理只记录不恢复

**现状** (`_run_react():352-361`): 子目标执行异常时:
1. 记录到 `goal.append_log(entry_type="pitfall", ...)`
2. 调用 `handle_sub_goal_error()` — 错误 ≥3 次才放弃
3. 但不重试当前子目标，直接退出

**影响**: 网络抖动等临时错误会导致子目标被标记失败但不会自动重试。

---

## 七、完整调用链总结

### 任务模式执行一个子目标的完整调用链:

```
用户输入 "!帮我写报告"
  │
  ▼
ConversationDriver.handle_message()
  ├── _task_mode = True (detected !)
  └── GoalManager.analyze_intent("帮我写报告")
        └── IntentUnderstanding.understand()  ← LLM 调用 #1
              └── IntentUnderstanding.decompose_goal()  ← LLM 调用 #2
        → IntentResult(type=TASK, goals=[...], sub_goals=[...])
  │
  ▼
GoalManager.handle_task_intent(intent_result)
  ├── _filter_meta_goals()
  ├── _llm_check_similar_goal()  ← LLM 调用 #3 (可选)
  ├── _create_task_from_intent() → PurposeEngine.add_goal()
  └── _route_goal_by_type()
        └── _route_execution_with_sub_goals()
              ├── PurposeEngine.decompose_goal()  ← 创建子目标
              ├── set_current(first_sub_goal.id)
              └── _run_chat(msg, intent_context)
                    └── _run_pace() or _run_react()
  │
  ▼
_run_react() / _run_pace()
  ├── build_context()  ← 组装 system prompt + 意图上下文
  ├── Agent.stream()  ← LLM 调用 #4 (ReAct, 可能多次)
  │     ├── 工具调用 (shell, file_ops, web_search, ...)
  │     └── 文本输出 + <PROGRESS>{"status":"completed"}</PROGRESS>
  ├── parse_progress_tag() → {"status": "completed", "summary": "..."}
  ├── update_goal_progress() → complete_goal() + get_next_sibling()
  └── should_auto_advance() → True → 循环继续 → 下一个子目标
```

**一个简单任务的最少 LLM 调用次数**: ~4次（意图分类 + 目标分解 + 相似检测 + ReAct执行）
**带 PACE 的 LLM 调用次数**: 4次基础 + N次 step_check + 1次 post_review

### 聊天模式 + create_goal 的调用链:

```
用户输入 "帮我写报告"
  │
  ▼
ConversationDriver.handle_message()
  ├── _task_mode = False
  └── 聊天模式: IntentResult(type=CHAT, confidence=1.0)
  │
  ▼
_run_chat() → _run_react()
  ├── Agent.stream()  ← LLM 调用 #1
  │     ├── LLM 决定调用 create_goal(description="写agent行业调研报告")
  │     ├── create_goal 工具执行 → PurposeEngine.add_goal()
  │     └── LLM 看到结果 → "好的，已记录，稍后完成"
  └── parse_progress_tag() → None → 退出
```

**结果**: Goal 创建了但没有自动执行。需要用户主动 "继续" 或进入任务模式。

---

## 八、下一步改进建议（优先级排序）

1. **聊天模式创建目标后自动触发执行** — 在 `_run_react()` 结束后检查是否有新的未执行目标，如有则自动进入执行循环

2. **统一 PACE/ReAct 的进度管理** — 让两套路径共享相同的上下文构建和进度检测逻辑

3. **`_task_mode` 生命周期管理** — 任务完成后自动退出 task_mode，或根据当前是否有活跃目标来决定

4. **create_goal 工具的行为约束** — 通过 tool description 和 System Prompt 更精确地约束 LLM 何时调用 create_goal

5. **子目标错误自动重试** — 对网络类、超时类错误自动重试当前子目标
