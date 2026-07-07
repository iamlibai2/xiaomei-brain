# 对话内部处理展示

## 目标

在每轮对话结束后，以折叠区块风格展示 LLM 内部处理结果：记忆提取、内心声音、DAG 压缩、Drive 变化、社交感知。

## 展示格式

```
  ── 本轮内部处理 ──
  │ 🧠 新增 2 条记忆: "用户喜欢Python" · "周末习惯爬山"
  │ 💭 内心声音: 用户今天状态很好，我应该更主动一些...
  │ 📦 DAG: 8 条消息 → 1 个摘要 (512 tokens)
  │ 📈 Drive: 归属欲 0.5→0.6 · 多巴胺 +0.2
  │ 👤 社交感知: 用户开心 (0.7)
  └────────
```

- 只显示有数据的行
- 标题行 dusty teal (`C_DIM`)
- 内容紧凑，一行一条

## 数据源与时机

| 行 | 来源 | 时机 |
|---|---|---|
| 🧠 记忆 | `Agent.stream()` 中 MEMORY block 提取结果 | 同步，当轮即显 |
| 💭 内心声音 | `InnerVoice.on_chat_turn()` thought 文本 | daemon，上轮触发本轮到 |
| 📦 DAG | `DAG.compact()` 压缩统计 | daemon，上轮触发本轮到 |
| 📈 Drive | InnerVoice EVENTS → Drive 变化 | 伴随内心声音 |
| 👤 社交感知 | InnerVoice SIGNAL 解析 | 伴随内心声音 |

## 架构

新增 `InternalDisplay` 组件，挂在 `ConversationDriver` 上：

```
ConversationDriver._run_react()
  ├── agent.stream() → MEMORY block 提取 → InternalDisplay.record_memory()
  ├── RoundScheduler.tick() → InnerVoice/DAG/Periodic 在 daemon 线程
  └── InternalDisplay.render() → 输出区块
```

`InternalDisplay` 是一个轻量 dataclass：
- `record_memory(actions)` — 记录本轮记忆操作
- `record_inner_voice(thought, drive_deltas, signal)` — 记录内心声音
- `record_dag_compact(msg_count, summary_tokens)` — 记录 DAG 压缩
- `record_periodic_extract(count)` — 记录定期提取
- `render()` — 有数据则输出格式化的区块，否则无输出

## 实现步骤

1. 创建 `src/xiaomei_brain/consciousness/internal_display.py` — InternalDisplay 类
2. 在 `ConversationDriver.__init__` 中创建 `InternalDisplay` 实例
3. 在 `Agent.stream()` 记忆提取后调用 `record_memory()`
4. 在 `ConversationDriver` 的 InnerVoice/DAG/定期提取回调中收集结果
5. 在 `ConversationDriver._run_react()` 末尾调用 `render()`
6. 在 CLI `run.py` 中将 `InternalDisplay.render()` 输出也发给 WS（可选）
