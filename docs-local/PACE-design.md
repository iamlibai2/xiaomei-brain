# PACE 层设计

## 概述

PACE = **P**ause → **A**ssess → **C**hoose → **E**xecute

一种区别于 ReAct 的 Agent 执行模式。ReAct 是流水线式（LLM 输出 → 下一步），PACE 是认知回合制——每执行一步，停下来审视结果，再决定下一步。

```
ReAct = 快速反应，一路冲
PACE  = 冷静审视，步步稳
```

## 目录结构

```
src/xiaomei_brain/metacognition/
├── __init__.py          # 导出
├── types.py             # 数据类型（枚举 + dataclass）
├── rules.py             # 纯规则检测（零 LLM 成本）
├── reviewer.py          # LLM 检查 + 复盘
└── runner.py            # PACERunner：认知回合制循环
```

## 运行时架构

```
用户输入 → ConsciousLiving._handle_message()
              ↓
         TaskOrchestrator.handle_message()
              ├─ /intask → _task_mode = True
              ├─ 意图分析 → 创建 Task/Goal 树
              └─ _run_chat() ── 分派器 ──┬─ _run_react()    （闲聊）
                                          └─ _run_pace()     （任务模式）
                                               │
                                               ▼
                                         PACERunner.run()
```

## 认知回合制循环

```
进入任务
  │
  ├─ Pre-check: 目标是否模糊？（规则判断，零 LLM）
  │     ├─ escalate → 退出，让用户澄清
  │     └─ continue → 继续
  │
  ├─ 替换消息 → LLM 只看到当前子目标，不看到完整任务
  ├─ 注入边界约束 → "只做这一步，剩下的会安排你做"
  │
  └─ while True:
       │
       ├─ 1. 注入 nudge（上一轮的元认知提示）
       ├─ 2. Agent.stream() → 执行一步
       ├─ 3. 规则检测（6 条，零 LLM）
       │       TOOL_LOOP / TOOL_STORM / EMPTY_RESPONSE /
       │       NO_PROGRESS / REPEATED_OUTPUT / SLOW_STEP
       ├─ 4. _step_check → 三级判断
       │     ├─ 0 surprise → CONTINUE（免费）
       │     ├─ 硬规则触发 → 直接判定（零 LLM）
       │     │     TOOL_STORM (>10次) → RETRY_DIFFERENT
       │     │     EMPTY_RESPONSE → RETRY_DIFFERENT
       │     │     GAVE_UP → REPORT_PARTIAL
       │     └─ 模糊信号 → LLM step_check（无预算限制）
       │
       └─ 5. 根据 suggestion 分支：
             ├─ ESCALATE → on_confirm（有回调）/ 退出（无回调）
             ├─ REPORT_PARTIAL/CLARIFY → 尝试推进 / 退出
             ├─ RETRY_DIFFERENT/SIMPLIFY → 同子目标重试（递增 retry 计数）
             │     ├─ 同一子目标 ≥5 次重试 → ESCALATE
             │     └─ 连续 3 步 EMPTY_RESPONSE → 立刻 ESCALATE
             └─ CONTINUE → _maybe_auto_advance（三层自动推进）

finally: _do_post_review() → TaskLesson → cognitive_log + JSON 持久化
```

## 关键设计

### 消息替换（防"一次做完所有事"）

```
原始: "帮我在/tmp写一个ERP项目，完整架构..."
替换: "[系统] 子目标 1/9: 设计项目目录结构"
```

LLM 看不到完整任务描述，只能看到当前子目标。配合边界约束上下文：

```
【当前任务】只执行这一个子目标，不要做其他事情：
「设计项目目录结构」
进度：0/9 子目标已完成
【全局进度】
  →进行中 1. 设计项目目录结构
  ○ 2. 创建项目基础文件
  ...
```

### 三层自动推进

| 层级 | 条件 | 行为 |
|------|------|------|
| 1 | Agent 输出 `<PROGRESS>completed</PROGRESS>` | 正常推进 |
| 2 | 无 PROGRESS 但无异常 + 0工具调用 | 视作纯文本确认，自动完成 |
| 3 | 无 PROGRESS 但 LLM step_check 判定 continue | 信任 LLM，自动完成 |

### LLM 预算控制

- 规则触发 0 个 surprise → 跳过 LLM，直接 CONTINUE（自然节流）
- 硬规则（TOOL_STORM / EMPTY_RESPONSE / GAVE_UP）→ 直接判定，不走 LLM
- 只有模糊信号才走 LLM step_check（~200 tokens，成本可忽略）
- **不做上限和冷却期限制**：任务可能有 50+ 子目标、跨度 10 天，固定上限不合理

### 重试机制（v0.3 简化）

合并为**一个计数器** `current_goal_retries`（初始 0，推进子目标时归零）：

| 触发条件 | 行为 |
|----------|------|
| RETRY_DIFFERENT / SIMPLIFY | `current_goal_retries += 1`，同子目标重试 |
| 异常捕获（per-step try/except） | 构造 EMPTY_RESPONSE obs → 同样递增 retry 计数 |
| 同一子目标 ≥5 次重试 | ESCALATE，暂停任务 |
| 连续 3 步全是 EMPTY_RESPONSE | 立刻 ESCALATE（模型服务可能异常） |
| 推进到下一个子目标 | `current_goal_retries = 0`，重置 |

不再区分"连续空响应计数"和"重试计数"——空响应就是 RETRY_DIFFERENT 的一种，
和其他重试一样递增 `current_goal_retries`。多出来的"连续 3 步空响应"是一个
额外的熔断规则，防止模型服务出问题时无意义地消耗 5 次重试配额。

### 6 条纯规则（零 LLM 成本）

| 规则 | 条件 | 信号 |
|------|------|------|
| 工具循环 | 连续 ≥3 次调用同一工具 | TOOL_LOOP |
| 工具风暴 | 单步 > 10 次工具调用 | TOOL_STORM |
| 空响应 | 输出去掉 PROGRESS 后为空 | EMPTY_RESPONSE |
| 重复输出 | 连续 2 步相似度 > 0.9 | REPEATED_OUTPUT |
| 慢步骤 | 耗时 > 历史均值 3x | SLOW_STEP |
| 无进展 | 有工具调用但无 PROGRESS | NO_PROGRESS |

## 运行时韧性（v0.2）

### Exit/Re-enter 模式

PACE 执行中 `_chatting=True` 拦截所有新消息。需要用户输入时不能阻塞在循环内，必须退出循环 → 等待消息 → 重新进入。

复用 TaskOrchestrator 已有的确认状态机，新增 `pace_confirm` 类型：

```
PACE 检测到需要确认
  → on_confirm(checkpoint, question, options)
    → TaskOrchestrator 保存 checkpoint, 设置 _waiting_confirm
    → _chatting = False，返回
用户回复
  → handle_message → _handle_confirmation("pace_confirm")
    → 解析用户回答
    → _resume_pace(checkpoint, answer_context)
      → PACERunner 恢复 observations + budget
      → _run_pace() 再次进入，从断点继续
```

### 检查点（PACECheckpoint）

```python
@dataclass
class PACECheckpoint:
    goal_id: str
    step_index: int
    observations_json: str           # 序列化的观察历史
    budget_call_count: int           # LLM 调用计数
    budget_skip_until: int           # 冷却期
    budget_consecutive_continue: int # 连续 continue 计数
    consecutive_empty_count: int     # 空响应计数
    last_nudge: str                  # 最后一轮的提示
    saved_at: float
```

### 暂停/恢复链

```
暂停: /inchat → save_checkpoint → pause_goal → 聊天模式
恢复: "继续" → 检测 _pace_checkpoint → restore → PACE 从断点继续
确认: PACE 遇到问题 → on_confirm → 用户回复 → 注入 nudge 继续
出错: 异常 → EMPTY_RESPONSE obs → 自动重试（3次才 escalate）
空响应: RETRY_DIFFERENT → 重试（≥3次才 escalate）
```

### 回调机制

PACERunner 不持有 ConsciousLiving 引用，通过 callbacks dict 通信：

| 回调 | 用途 |
|------|------|
| `print_prompt` | CLI 提示符 |
| `cancel_check` | 用户取消（Ctrl+C） |
| `on_user_interaction` | 意识中心钩子 |
| `update_recent_conversations` | 对话缓存刷新 |
| `get_consciousness_state` | 意识状态 |
| `on_confirm` | 执行中需要用户确认（v0.2） |
| `_store_checkpoint` | 取消时保存检查点（v0.2） |

## 数据类型

### SurpriseType（意外信号）

TOOL_LOOP / TOOL_STORM / EMPTY_RESPONSE / REPEATED_OUTPUT / SLOW_STEP / NO_PROGRESS / GAVE_UP / VAGUE_GOAL

### StuckClass（障碍分类）

TOOL_LOOP / UNCLEAR / BLOCKED / OUT_OF_SCOPE / GAVE_UP

### MetaSuggestion（元认知建议）

CONTINUE / CLARIFY / SIMPLIFY / RETRY_DIFFERENT / REPORT_PARTIAL / ESCALATE

### StepObservation（步骤观察）

单步执行的完整记录：输出内容、工具调用、耗时、意外信号等。

### StepCheckResult（检查结果）

元认知的判断：建议 + 障碍分类 + 推理 + 提示注入。

### TaskLesson（复盘总结）

任务完成后的经验提取：有效做法、失败教训、能力认知、意外记录。

## 调用链

### 主动行为触发流程

1. **Drive 层**通过情感、激素、动机、欲望进行分析，如果满足触发主动行为的条件，通过 `ConsciousLiving._handle_message` 触发 `action_dispatcher.py`
2. **action_dispatcher.py** 主要处理通过发送 `LivingMessage` 给 Living 队列，通过 `_handle_message` 触发流程
3. **_handle_message** 首先检测是否是命令（`/intask` 等），如果不是命令再委托给 `TaskOrchestrator.handle_message()`
4. **handle_message** 首先检测是否是"继续"，如果不是"继续"再检测是否是确认状态，如果不是确认状态再检测是否有活跃目标 → 意图分析 → `_run_chat`
5. **_run_chat** 检测 `_task_mode` 是否为 `True`，如果为 `True` 则走 `_run_pace`，否则走 `_run_react`
6. **_run_pace** 中需要检测消息是否是目标消息，如果是目标消息则委托给 `PACERunner.run()`，否则打印错误日志

```
/ 主动行为触发流程：
/ 1. drive 层通过情感、激素、动机、欲望进行分析，如果满足触发主动行为了条件，就会通过 ConsciousLiving._handle_message 触发 action_dispatcher.py
/ 2. action_dispatcher.py 主要处理通过发送 LivingMessage 给 Living 队列，通过 _handle_message 触发的流程
/ 3. _handle_message 首先检测是否是命令（/intask 等），如果不是命令再委托给 TaskOrchestrator.handle_message()
/ 4. handle_message 首先检测是否是"继续"，如果不是 "继续" 再检测是否是确认状态，如果不是确认状态再检测是否有活跃目标 -> 意图分析 -> _run_chat
/ 5. _run_chat 检测 _task_mode 是否为 True，如果为 True 则走 _run_pace，否则走 _run_react
/ 6. _run_pace 中需要检测消息是否是目标消息，如果是目标消息则委托给 PACERunner.run()，否则打印错误日志
```
