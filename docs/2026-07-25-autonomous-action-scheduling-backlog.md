# 自主行为调度：待讨论事项

状态：暂缓设计，尚未决定实现方案，不修改现有线程模型。

## 问题来源

2026-07-25 真实测试飞书 Clarify 时，飞书消息已经被 Channel 正常接收、完成 Person
识别并进入 Living 消息队列，但 Agent 正在执行自主学习，直到学习结束前都无法处理该消息。

当前实现中：

- Layer2 在独立线程中产生意图。
- 意图交给 `ActionDispatcher`。
- `ActionDispatcher.process_queue()` 由 Living 主线程调用。
- 行为处理器在该调用栈内同步执行。

因此，“意图决策在独立线程”不等于“行为执行在独立线程”。

## 受影响的行为

不仅是 `learn_topic`。下列自主行为都可能在 Living 主线程中进行耗时调用：

- `learn_topic`
- `work`
- `alarm`
- `progress_goal`
- `talk_to_agent`
- `meta_skill_pull`
- `pleasure_release`
- 经 `ActionDispatcher` 触发的 `trigger_l3`
- 需要调用 LLM 生成内容的主动问候、关心、表达和聊天

`notify`、简单状态修改和已有内容的主动发送通常是短操作。

## 后续讨论原则

不要只为学习增加特殊线程或临时抢占逻辑。后续应从整体上讨论：

1. Living 主线程是否只负责生命状态与人类消息调度。
2. 哪些自主行为应交给独立执行器。
3. 人类对话与自主行为能否并发使用同一个 Agent Core、LLM、工具和数据库。
4. 自主行为的串行、取消、暂停、恢复和 Agent 停止语义。
5. 行为结果如何安全地回写记忆、经验流、Desk、Drive 和 Channel。

在上述边界讨论清楚前，保留现状，不开始线程模型改造。
