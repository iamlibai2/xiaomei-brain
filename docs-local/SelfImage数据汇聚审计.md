# SelfImage 数据汇聚完整性审计

> 审计日期：2026-05-23
> 目标：核查 SelfImage 作为"意识本体"的数据汇聚完整性——哪些数据进来了，哪些在渲染，哪些断了。

## 一、数据流全景

```
Drive ──→ SelfBody (16 proxy properties) ──┐
Purpose ──→ SelfMind (5 proxy properties) ─┤
Interoception ──→ SelfBody (9 硬字段) ─────┤
L0 tick ──→ Perception / History ──────────┤
L1 digest ──→ Mind / History ──────────────┤
L2 fuel ──→ Mind / Intent / History ───────┤
InnerVoice ──→ Mind ───────────────────────┤
memory_window ──→ Memory / Mind ───────────┤
interaction ──→ Perception / Being ────────┤
Desk.drop() ──→ Desk ──────────────────────┤
                                            ↓
                                     SelfImage
                                            ↓
                                  inject_consciousness()
                                            ↓
                                     System Prompt
```

## 二、各模块字段完整性

### SelfBody（24 字段）

| 字段 | 来源 | 渲染 | 状态 |
|------|------|------|------|
| energy | Drive代理 | ✓ `_render_body()` | 正常 |
| mood | Drive代理 | ✓ `_render_body()` | 正常 |
| emotion_intensity | Drive代理 | ✗ | **遗漏**——只渲染了mood类型，没渲染强度 |
| desire_belonging/cognition/achievement/expression/survival | Drive代理 | ✓ | 正常 |
| dopamine/serotonin/cortisol/oxytocin/norepinephrine | Drive代理 | ✓ | 正常 |
| motivation_level | Drive代理 | ✗ | **遗漏**——RPE 驱动的动机水平完全没进 prompt |
| attention | 硬字段 | ✗ | **遗漏**——"与用户对话"/"等待用户"没进 prompt |
| cpu/memory/queue/latency/error_rate/token/memory_fullness/burning | Interoception | ✓ `_render_body()` | 正常（只显示 >0 的值） |
| thread_health | Interoception | ✗ | **遗漏**——线程健康状态没进 prompt |

**评分**：18/24 渲染。6 个遗漏：emotion_intensity、motivation_level、attention、thread_health + 2 个不重要。

### SelfMind（18 字段 + 渲染层问题）

| 字段 | 来源 | 渲染 | 状态 |
|------|------|------|------|
| primary_goal | Purpose代理 | ✗ | **静态 mock 覆盖**——LLM 看到的是"食品ERP" |
| goal_progress | Purpose代理 | ✗ | **静态 mock 覆盖** |
| active_goal_count | Purpose代理 | ✗ | 从未被任何渲染方法读取 |
| current_sub_goal | Purpose代理 | ✗ | 从未被任何渲染方法读取 |
| current_goal_depth | Purpose代理 | ✗ | 从未被任何渲染方法读取 |
| inner_thought | 多源写入 | ✗ | **静态 mock 覆盖** |
| inner_thought_history | 自算 | ✗ | 从未渲染 |
| social_perceptions | L2注入 | ✗ | **静态 mock 覆盖** |
| inner_voice | L2注入 | ✓ `_render_inner_voice()` | 正常（daily/reflect/task） |
| project_map | L2注入 | ✓ `_render_project_map()` | task 模式正常，daily/reflect 未渲染 |
| experience | L2注入 | ✓ `_render_experience()` | task 模式正常，daily/reflect 未渲染 |
| pace_reflections | 累积 | ✓ `_render_pace_reflections()` | 正常（daily/reflect） |
| memory_count/history/summaries | L1注入 | ✗ | 从未渲染，仅用于异常检测 |
| goal_progress_history | 自算 | ✗ | 从未渲染，仅用于异常检测 |
| last_inner_thought_time | 自算 | ✗ | 仅用于 L2 fuel 时序逻辑 |

**评分**：5/18 渲染，其中 3 个只在部分模式渲染。**核心问题：`_render_mind()` 整个方法是静态 mock，导致 Purpose 代理的 5 个字段 + inner_thought + social_perceptions 全部黑洞。**

### SelfPerception（7 字段）

| 字段 | 来源 | 渲染 | 状态 |
|------|------|------|------|
| environment | 自算 | ✓ `_render_environment()` | 正常 |
| agent_state | 推入 | ✓ `_render_environment()` | 正常 |
| user_idle_duration | 推入 | ✓ `_render_environment()` | 正常 |
| last_user_activity_content | 推入 | ✓ `_render_environment()` | 正常 |
| last_user_activity_time | 推入 | ✗ | 未渲染，仅用于 idle 计算 |
| agent_state_history | 自算 | ✗ | 未渲染，仅用于 L1 异常检测 |
| user_emotional_state | 硬字段 | ✗ | **死字段**——声明了但从未被写入过 |

**评分**：4/7 渲染。1 个死字段。

### SelfHistory（10 字段）

| 字段 | 来源 | 渲染 | 状态 |
|------|------|------|------|
| consciousness_age | 自算 | ✓ `_render_history()` | 正常 |
| last_dream_summary | 推入 | ✓ `_render_history()` | 正常（但有写入 bug） |
| emotional_trajectory/goal_rhythm/consciousness_rhythm | L1 digest | ✓ `_render_history()` | 正常 |
| accumulated_changes | 自算 | ✓ `_render_history()` | 正常（显示最近 5 项变化） |
| cycle_count | 自算 | ✗ | 未渲染 |
| interpreted_changes | L2注入 | ✗ | **遗漏**——L2 语义解释版的变化从未渲染，只渲染了原始 diff |
| last_llm_fuel_time | L2注入 | ✗ | 仅用于时序逻辑 |
| growth_events | 推入 | ✓ `_render_being()` | 正常（最近 3 条） |

**评分**：6/10 渲染。

### Being（9 字段）

| 字段 | 来源 | 渲染 | 状态 |
|------|------|------|------|
| name/birth_date/personality | talent.md | ✓ | 正常 |
| self_cognition | talent.md | ✓ | 正常 |
| growth_events | history | ✓ | 正常 |
| learning_interests | talent.md | ✗ | **遗漏**——声明了、解析了、存了，但从未渲染 |
| relationship_status/depth/trust_level/history | 自算 | ✗ | **全部遗漏**——关系数据完全没进 prompt |

**评分**：5/9 渲染。关系追踪完全黑暗。

### SelfHistory 写入 Bug

```python
# core.py line 626: 直接赋值（无截断）
self.history.last_dream_summary = summary
# ...
# core.py line 632: update_dream_summary（截断到 200 字符）——立即覆盖 line 626
self.history.update_dream_summary(summary)
```

Line 626 是死写，应删除。

### Conflict: inner_thought 四源竞争

| 写入方 | 方式 | 记录历史 |
|--------|------|---------|
| L1 digest | `update_inner_thought()` | ✓ |
| L2 emergence | `update_inner_thought()` | ✓ |
| being() tool | `update_inner_thought()` | ✓ |
| ActionExecutor | **直接赋值** `si.mind.inner_thought = ...` | ✗ |

ActionExecutor 使用直接赋值，绕过了 `update_inner_thought()`，不记录历史、不更新时间戳。

### Redundant: perception.agent_state 双写

`Consciousness.tick_L0()` 先设置 `self.perception.agent_state`，然后立即调用 `self.self_image.tick(perception)`，其中 `update_from_perception()` 再次设置相同的值。不是 bug，但是冗余。

## 三、按模式统计渲染覆盖

| 模式 | 渲染方法数 | 覆盖模块 |
|------|-----------|---------|
| flow | 5 | header, being, essence, body, environment |
| daily | 12 | +mind(静态mock), inner_voice, desk, memory, experience_timeline, pace_reflections, history |
| task | 10 | +mind(静态mock), experience, inner_voice, desk, project_map, intent, experience_timeline, environment. **不含 memory** |
| reflect | 12 | 同 daily（代码注释：后续可差异化） |
| legacy | 5 | header, being_legacy, essence, memory(legacy), experience_timeline |

task 模式不渲染 `_render_memory()` 是有意设计，但代价是任务模式下 LLM 看不到任何长期记忆、DAG 摘要、过程记忆。

## 四、数据写入冲突汇总

| 严重度 | 冲突 | 影响 |
|--------|------|------|
| 🔴 严重 | `_render_mind()` 静态 mock | Purpose/社交感知/内思想全部黑洞 |
| 🟡 中等 | `inner_thought` 4源写入，1个绕过历史 | 历史记录不完整 |
| 🟡 中等 | `intent.is_active()` 为 True 但渲染空字符串 | 有意图队列时 LLM 看不到列表内容 |
| 🟢 轻微 | `last_dream_summary` 死写 | 浪费一行代码 |
| 🟢 轻微 | `agent_state` 双写 | 冗余但不影响正确性 |

## 五、优先级建议

### P0：立即修复

1. **恢复 `_render_mind()` 动态版** —— 移除静态 mock。Purpose 代理数据是最重要的意识输入之一，当前完全黑洞。

### P1：本轮补齐

2. **`_render_body()` 加上 `motivation_level`** —— 一行代码。RPE 动机水平是重要的内驱力信号。
3. **`_render_body()` 加上 `emotion_intensity`** —— 情绪不只是类型，强度决定表达烈度。
4. **`_render_being()` 加上关系字段** —— relationship_status/depth 已经积累了大量数据，LLM 应该知道。
5. **`_render_history()` 加上 `interpreted_changes`** —— L2 语义解释比原始 diff 更有价值。

### P2：需要讨论

6. **inner_thought 写入统一** —— ActionExecutor 应该走 `update_inner_thought()` 而不是直接赋值。
7. **task 模式是否加入部分 memory** —— 至少 DAG 摘要应该在 task 模式中出现。
8. **intent_buffer 渲染** —— 有队列时应该遍历渲染，而非只读顶层字段。
9. **清理死字段** —— `user_emotional_state`、`trust_level`、`event_extractor.py`。
