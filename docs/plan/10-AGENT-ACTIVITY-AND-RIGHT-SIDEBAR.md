# Agent 活动系统与 Desktop 统一右侧栏

状态：设计完成。阶段 A（Activity 领域与持久化）、阶段 B（自主行为与
Assignment 接入）和阶段 C（认知与梦境接入）已于 2026-07-28 实现；
阶段 D（Gateway 协议）与阶段 E（Desktop 统一右侧栏）已于同日实现；
阶段 F（产物与上下文）及补充阶段 G（Agent 当前状态投影）已于同日实现，
第一版完整工作台已经收束。

## 1. 一句话定义

`AgentActivity` 是 Agent 正在经历或执行的一次可观察过程。

它把委托执行、自主学习、Goal/PACE、闹钟、会话后记忆整理、InnerVoice、
DAG 压缩和梦境等不同内部机制，投影为统一的“开始—执行—暂停—完成”状态，
让外部可以理解 Agent 正在做什么，但不改变这些机制各自的领域含义。

Desktop 使用统一右侧栏承载 Agent 活动、产物和当前上下文。左侧继续负责
Agent/会话导航，中间继续负责人与 Agent 的交流。

```text
┌──────────────┬────────────────────────────┬──────────────────────┐
│ Agent / 会话  │ 对话                       │ Agent 详情             │
│              │                            │                      │
│ 小美          │ 人与 Agent 的主要交流       │ 活动 | 产物 | 上下文   │
│ 小明          │ Clarify / Action / 最终结果 │                      │
│              │                            │ Agent 当前在做什么     │
│              │                            │ 最近完成了什么         │
└──────────────┴────────────────────────────┴──────────────────────┘
```

## 2. 为什么现在需要它

项目已经存在多类后台过程：

- Assignment 通过 `IsolatedAssignmentRunner` 和独立 Agent Core 执行；
- 学习、Goal/PACE、闹钟和主动行为通过 `AutonomousBehaviorExecutor` 执行；
- InnerVoice、DAG 压缩和周期记忆提取由 `ConversationDriver` 在轮次后调度；
- 梦境由 `ConsciousLiving` 在 `dreaming` 状态执行；
- 工具、产物、Action 和 Assignment 已经能够通过 Gateway 向 Desktop 投递。

这些机制已经能够运行，但外部缺少一个统一答案：

> 这个 Agent 现在到底在做什么？

当前 Desktop 右侧只有一个专用于 Assignment 的 Drawer。它无法展示 Agent
自主学习、会话后整理和梦境，也无法把产物、上下文和 Agent 全局活动组织成
稳定的信息架构。

## 3. 设计原则

### 3.1 活动是观察层，不是新的任务系统

`AgentActivity` 不取代 Assignment、Goal、PACE、Dream 或 ExperienceStream。
它只描述某一次实际运行。

```text
Assignment（持续的工作约定）
  └─ ActivityRun（本次执行或恢复）

Goal（Agent 的内部追求）
  └─ ActivityRun（本次 PACE 推进）

一轮对话
  ├─ ActivityRun（本次记忆提取）
  ├─ ActivityRun（本次 InnerVoice 整理）
  └─ ActivityRun（本次 DAG 压缩）
```

一个 Assignment 可以对应多次 ActivityRun；ActivityRun 完成不一定意味着
Assignment 已完成。

### 3.2 一 Agent 一世界

活动真实状态存储在对应 Agent 自己的 `brain.db` 中。Desktop 不是状态真相源，
也不存在管理所有 Agent 活动的中央服务。

远程 Agent 的活动由远程 Agent 自己维护，Desktop 只通过 Gateway 获取投影。

### 3.3 对话保持干净

主对话只承载：

- 人与 Agent 的自然交流；
- Clarify；
- Action 审批；
- 需要人参与的暂停；
- 最终结果和重要产物。

工具轨迹、后台阶段、记忆整理和梦境执行详情主要进入右侧栏，避免用大量内部
日志污染会话。

### 3.4 透明不等于暴露原始思维链

右侧栏展示：

- 为什么触发；
- 当前阶段；
- 使用了什么工具；
- 处理了什么范围的数据；
- 保存了什么记忆；
- 形成了什么结果。

不展示：

- 完整 system prompt；
- 模型逐 token 的隐藏推理；
- 未整理的原始 InnerVoice；
- 可能包含敏感信息的完整工具日志。

### 3.5 进度必须诚实

只有存在可靠总步骤时才显示百分比。否则展示：

- 当前阶段；
- 已完成步骤；
- 正在做什么；
- 等待原因；
- 已运行时间；
- 最近一次有效进展。

### 3.6 实时对话优先

后台活动在 LLM 调用、工具调用等安全边界让出执行权。已经发出的网络请求或
不可中断工具不强杀，而是在当前步骤结束后暂停。

### 3.7 界面借鉴而不照搬

WorkBuddy 使用左侧任务导航、中间对话、右侧结果/文件/变更/预览的三栏结构；
Codex 将后台 Agent 活动从主对话中分离，并允许用户打开独立活动查看进度和
结果。

参考：

- <https://www.codebuddy.cn/docs/workbuddy/Conversation>
- <https://www.codebuddy.cn/docs/workbuddy/Results>
- <https://learn.chatgpt.com/docs/agent-configuration/subagents>

本项目借鉴它们的“主对话保持干净、后台过程可以检查、结果集中呈现”，但不照搬
以任务或子 Agent 为中心的产品模型。小美的右侧栏以一个独立 Agent 的全部活动
为中心，包括工作、认知、睡眠和沟通。

## 4. 活动分类

### 4.1 工作活动 `work`

- `assignment_run`
- `autonomous_learning`
- `goal_pace`
- `alarm_action`
- `scheduled_work`

### 4.2 认知活动 `cognition`

- `memory_extraction`
- `inner_voice_reflection`
- `dag_compaction`
- `relationship_update`
- `experience_extraction`

轮次后发生的多个认知活动在存储上保持独立，通过相同的 `origin_turn_id`
关联；Desktop 将它们组合显示为“会话后整理”，避免每轮产生多张卡片。

### 4.3 睡眠活动 `sleep`

- `dream`
- `memory_consolidation`
- `pattern_extraction`
- `forgetting_and_reinforcement`

### 4.4 沟通活动 `communication`

- `proactive_expression`
- `care`
- `channel_delivery`

普通实时对话本身不进入活动列表；它已有 Turn 和 Message 生命周期。只有独立于
当前 Turn 的主动沟通才作为活动。

### 4.5 暂不展示的内部信号

以下信号仍可进入日志或 ExperienceStream，但不直接形成用户可见活动：

- 每次 Living tick；
- 没有产生实际行为的 Layer2 意图；
- 心跳和连接探测；
- 未达到阈值而立即跳过的压缩检查；
- 无结果、持续时间极短的内部判断。

## 5. 生命周期

### 5.1 状态

```text
queued ──→ running ──→ completed
  │            │
  │            ├──→ paused ──→ running
  │            ├──→ failed
  │            └──→ cancelled
  └────────────────→ cancelled
```

- `queued`：已产生，等待执行；
- `running`：正在执行；
- `paused`：执行现场仍存在，但暂时不继续；
- `completed`：本次运行正常结束；
- `failed`：本次运行无法继续；
- `cancelled`：本次运行被明确放弃。

“开始”和“恢复”是状态转换事件，不增加额外状态。

### 5.2 暂停原因

- `realtime_message`：让出资源，优先回复人类；
- `waiting_approval`：等待 Action 批准；
- `waiting_input`：等待 Person 补充信息；
- `waiting_resource`：等待模型、网络或外部资源；
- `agent_stopping`：Agent 正在停止；
- `self_paused`：Agent 自己决定暂缓；
- `interrupted`：进程非正常中止后恢复出的状态。

### 5.3 重启策略

Agent 启动时，所有遗留的 `running` 活动先转换为：

```text
paused(reason=interrupted)
```

第一版不自动盲目重放。具体领域决定能否恢复：

- Assignment 使用已有 checkpoint 和安全恢复规则；
- Goal/PACE 使用已有 GoalRun/PACE checkpoint；
- 认知整理可以安全地重新调度；
- 可能产生外部副作用的行为必须先确认是否已经执行。

Activity 只保存状态和 checkpoint 引用，不复制各领域自己的恢复数据。

## 6. 领域模型

### 6.1 `ActivityRun`

建议新增表 `agent_activity_runs`：

```text
id
category
kind
title
status

source_type
source_id

scope_type
scope_id
person_id
origin_session_id
origin_turn_id
runtime_session_id

progress_summary
current_step
completed_steps
total_steps
steps

pause_reason
result_summary
error_code
error_message

checkpoint_type
checkpoint_ref
revision

created_at
started_at
updated_at
completed_at
```

说明：

- 数据库属于单个 Agent，不重复保存 `agent_id`；
- `source_type/source_id` 关联 Assignment、Goal、Alarm 或 Turn；
- `scope_type/scope_id` 表示活动属于 Agent 全局、Person、群聊或其他社会场景；
- `origin_session_id/origin_turn_id` 只记录来源，不限制活动只能在该会话显示；
- `runtime_session_id` 对应独立 Core 的内部 session；
- `steps` 第一版使用 JSON 数组，避免过早增加步骤表；
- `revision` 用于客户端去重和拒绝旧快照；
- `checkpoint_ref` 只引用原领域检查点。

### 6.2 Activity 与 ExperienceStream

`agent_activity_runs` 回答“现在是什么状态”；`ExperienceStream` 回答“经历过
什么”。

每次实质变化追加一条 ExperienceStream：

```text
type=activity_started
type=activity_progress
type=activity_paused
type=activity_resumed
type=activity_completed
type=activity_failed
```

`related_id` 保存 ActivityRun ID，`metadata` 保存结构化摘要。

不新增 ActivityEvent 表，避免与 ExperienceStream 重复。

### 6.3 Assignment 的关系

Assignment 已经使用统一的独立 Agent Core：

```text
IsolatedAssignmentRunner
  └─ AgentRuntimeFactory
       └─ 独立 Agent Core
```

保留 `IsolatedAssignmentRunner` 管理委托特有的审批、checkpoint、产物和恢复。
每次 Assignment 真正进入执行或恢复时创建一个 `assignment_run` Activity。

```text
Assignment 1 ── 0..N ActivityRun
```

Activity 完成时，Assignment 是否完成仍由 AssignmentService 和验收逻辑决定。

### 6.4 自主行为的关系

`AutonomousBehaviorExecutor` 在取出队列项后创建 ActivityRun，并将
`ActivityRunContext` 传给具体行为：

```python
ActivityRunContext
    .start()
    .report_progress(...)
    .set_steps(...)
    .pause(...)
    .resume()
    .complete(...)
    .fail(...)
    .cancelled()
    .wait_if_realtime_busy()
```

它继续通过 `AgentRuntimeFactory` 创建独立 Core。Activity 系统不创建第二套
Agent，也不改变 Agent Core。

### 6.5 会话后认知行为的关系

当前 `ConversationDriver` 中的轮次调度保持原有频率和触发逻辑：

- InnerVoice；
- DAG compact；
- periodic memory extraction。

每个真正执行的 hook 创建对应 Activity；没有达到执行阈值时不创建。它们共享
同一个 `origin_turn_id`，由 Desktop 组合成一项“会话后整理”。

第一版只增加可观察性，不强行把这些 hook 移入 `AutonomousBehaviorExecutor`。
后续如果确认多个后台线程会争抢模型或资源，再设计独立的认知执行队列。

### 6.6 梦境的关系

`ConsciousLiving._loop_dreaming()` 在 DreamEngine 真正开始前创建 `dream`
Activity，按 DreamEngine 已有阶段报告进度，完成后保存摘要。

Dream 仍属于 Agent 全局，不挂到某个 Person。

## 7. Gateway 交互协议

### 7.1 RPC 方法

```text
activity.current
activity.list
activity.get
```

第一版均为只读：

- `activity.current`：当前 Agent 正在运行或暂停的活动；
- `activity.list`：分页读取最近活动，可按 category/status/source 过滤；
- `activity.get`：读取完整步骤、结果和关联信息。

暂停、恢复和取消暂不增加按钮式 RPC。用户优先通过对话表达“先停一下”或
“继续刚才的学习”，由 Agent 识别并调用内部能力。Assignment 已有的明确恢复、
取消 RPC 保留。

### 7.2 事件

```text
activity.queued
activity.started
activity.progress
activity.paused
activity.resumed
activity.completed
activity.failed
activity.cancelled
```

每个事件都携带完整最新快照，而不只发送差量：

```json
{
  "activity": {
    "id": "activity_xxx",
    "category": "cognition",
    "kind": "memory_extraction",
    "title": "整理最近的对话记忆",
    "status": "running",
    "progress_summary": "正在判断哪些内容值得长期保存",
    "origin_session_id": "desktop-person_xxx",
    "origin_turn_id": "turn_xxx",
    "revision": 3,
    "updated_at": 1785000000.0
  }
}
```

客户端按 `id + revision` 去重。断线重连后通过 `activity.current/list` 恢复，
不依赖事件完整重放。

### 7.3 能力声明

Gateway capability 增加：

```text
activity.read
activity.events
```

旧客户端不请求活动即可继续使用，不需要发送双版本字段。

## 8. Desktop 统一右侧栏

### 8.1 信息架构

将现有 `AssignmentDrawer` 演进为常驻、可折叠的 `AgentRightSidebar`：

```text
AgentRightSidebar
├─ ActivityPanel
│  ├─ CurrentActivities
│  ├─ PostTurnActivityGroup
│  └─ RecentActivities
├─ ArtifactPanel
│  ├─ CurrentSessionArtifacts
│  ├─ AssignmentDeliverables
│  └─ ArtifactPreview
└─ ContextPanel
   ├─ CurrentPerson
   ├─ CurrentSession
   ├─ RelatedGoal
   ├─ AttachmentsAndReferences
   └─ MemoryUsageSummary
```

### 8.2 右侧栏作用域

必须严格区分范围：

- 活动：当前 Agent 全局；
- 会话后整理：来自任意渠道，但注明来源会话；
- 上下文：当前 Desktop 会话；
- 产物：默认当前会话，可切换“当前会话 / Agent 全部”；
- Assignment：全局活动中显示摘要，详情保持 Assignment 领域视图；
- Dream：Agent 全局，不属于 Person；
- 群聊活动：显示群聊名称和 scope，不误投影为当前私聊。

这能避免某个 Assignment 卡片出现在所有会话顶部的问题再次发生。

### 8.3 活动页

默认布局：

```text
小美 · 工作中

当前活动
┌────────────────────────────┐
│ 系统负载检查                │
│ 正在分析占用最高的进程      │
│ ● 执行中 · 32 秒            │
│                            │
│ ✓ 收集 CPU 和内存           │
│ ✓ 检查磁盘                  │
│ → 分析进程                  │
│ ○ 形成报告                  │
└────────────────────────────┘

后台认知
┌────────────────────────────┐
│ 会话后整理                  │
│ 提取记忆 · InnerVoice       │
└────────────────────────────┘

最近完成
  梦境与记忆整合        02:31
  学习飞书群聊机制      昨天
```

短于约 2 秒且没有有效结果的活动不在“当前活动”中闪烁，只进入最近历史或被
同 Turn 的会话后整理分组吸收。

### 8.4 产物页

借鉴现有 Assignment Drawer 和 WorkBuddy 结果区：

- 文件列表；
- 当前会话/全部产物切换；
- Assignment deliverables；
- 图片、PDF、Office 文件预览；
- 打开文件；
- 打开所在目录；
- 产物来源 Activity、Assignment、Turn；
- 同一产物的修订关系。

聊天中的 Artifact 卡片点击后，打开右侧栏产物页并定位对应文件。

### 8.5 上下文页

展示当前 Agent 与当前会话的可解释上下文：

- 当前 Person 和绑定渠道；
- session、群聊或私聊范围；
- 当前关联 Assignment/Goal；
- 本轮附件和引用；
- 本轮召回记忆的数量、类型和摘要；
- 当前模型与视觉路由；
- 当前可用能力摘要。

不直接暴露完整 prompt 或隐藏推理。

### 8.6 响应式行为

- 宽屏默认展开，建议宽度 360px；
- 支持拖动调整，范围约 300–520px；
- 中等宽度记住用户上次开关状态；
- 窄屏使用覆盖式 Drawer；
- 切换 Agent 时保留开关和页签，但内容立即切换到新 Agent；
- 切换会话时活动页不清空，上下文和默认产物范围随会话切换；
- 新的进行中活动到达时显示非侵入提示，不抢走当前页签。

## 9. 与现有代码的对应

### 9.1 后端可复用部分

- `src/xiaomei_brain/agent/runtime.py`
  - 统一创建独立 Core；
- `src/xiaomei_brain/consciousness/autonomous_executor.py`
  - 自主工作 Activity 的主要接入点；
- `src/xiaomei_brain/assignments/isolated_runner.py`
  - Assignment Activity 的接入点；
- `src/xiaomei_brain/consciousness/conversation_driver.py`
  - 会话后认知 Activity 的接入点；
- `src/xiaomei_brain/consciousness/conscious_living.py`
  - Dream Activity 的接入点；
- `src/xiaomei_brain/memory/experience_stream.py`
  - Activity 状态变化的时间线；
- `src/xiaomei_brain/gateway/event_projection.py`
  - Gateway/Channel 事件投影。

### 9.2 Desktop 可复用部分

- `renderer/components/home/AssignmentDrawer.tsx`
  - 演进为统一右侧栏，而不是再并列新增一个 Drawer；
- `renderer/components/home/AssignmentCard.tsx`
  - 保留 Assignment 摘要投影；
- `renderer/components/home/ChatTopbar.tsx`
  - 复用右侧栏开关；
- `renderer/store/core.ts`
  - 增加按 Agent 分桶的 Activity 状态；
- `main/gateway-client.ts`
  - 已支持统一事件订阅；
- `main/ipc-handlers.ts`、`main/preload.ts`
  - 增加 activity RPC bridge。

## 10. 建议新增和修改的文件

### 10.1 后端新增

```text
src/xiaomei_brain/activity/
├─ __init__.py
├─ models.py
├─ store.py
├─ service.py
└─ context.py

src/xiaomei_brain/gateway/methods/activities.py
tests/test_activity_service.py
tests/test_gateway_activities.py
```

### 10.2 后端修改

```text
src/xiaomei_brain/consciousness/autonomous_executor.py
src/xiaomei_brain/assignments/isolated_runner.py
src/xiaomei_brain/consciousness/conversation_driver.py
src/xiaomei_brain/consciousness/conscious_living.py
src/xiaomei_brain/memory/experience_stream.py
src/xiaomei_brain/gateway/server_methods.py
src/xiaomei_brain/gateway/event_projection.py
```

### 10.3 Desktop 新增

```text
renderer/components/right-sidebar/AgentRightSidebar.tsx
renderer/components/right-sidebar/ActivityPanel.tsx
renderer/components/right-sidebar/ActivityDetail.tsx
renderer/components/right-sidebar/ArtifactPanel.tsx
renderer/components/right-sidebar/ContextPanel.tsx
renderer/styles/right-sidebar.css
```

### 10.4 Desktop 修改

```text
renderer/components/MainShell.tsx
renderer/components/home/HomePage.tsx
renderer/components/home/ChatTopbar.tsx
renderer/components/home/AssignmentDrawer.tsx
renderer/store/core.ts
renderer/types.ts
main/gateway-client.ts
main/ipc-handlers.ts
main/preload.ts
```

`AssignmentDrawer.tsx` 的详情内容应拆为可复用的 Assignment Detail，再嵌入
统一右侧栏；完成后删除旧 Drawer 外壳。

## 11. 分阶段实现

### 阶段 A：Activity 领域与持久化

- 新增模型、Store、Service 和增量建表；
- 实现状态转换、revision、ExperienceStream 写入；
- Agent 重启时收束遗留 running 状态；
- 完成单元测试。

交付结果：后端能够可靠记录活动，但 Desktop 尚不展示。

### 阶段 B：接入自主行为与 Assignment

- `AutonomousBehaviorExecutor` 创建和更新 Activity；
- 学习、Goal/PACE、闹钟报告阶段；
- Assignment 每次执行/恢复创建 `assignment_run`；
- 保证独立 Core、Assignment checkpoint 和 Activity 状态边界清晰。

交付结果：工作类活动具备真实生命周期。

### 阶段 C：接入认知和梦境

- 记忆提取；
- InnerVoice；
- DAG compact；
- DreamEngine；
- 相同 Turn 的认知活动具备统一关联信息；
- 不为跳过和无结果检查制造噪声。

交付结果：用户可以知道 Agent 在对话后和睡眠中做了什么。

### 阶段 D：Gateway 协议

- activity.current/list/get；
- activity.* 事件；
- capability；
- 重连恢复和 revision 去重测试。

交付结果：所有 WebSocket 客户端可以读取和订阅活动。

### 阶段 E：Desktop 统一右侧栏

- 先完成 Activity 页；
- 把 Assignment Drawer 迁入统一右侧栏；
- 完成作用域切换和响应式布局；
- 保持对话、Clarify、Action 和流式消息行为不变。

交付结果：右侧栏能够实时展示工作、认知和睡眠活动。

### 阶段 F：产物和上下文

- 统一产物列表与预览；
- Artifact 卡片联动；
- 当前 Person/session/Goal/附件/记忆使用摘要；
- 清理旧的重复入口。

交付结果：形成完整三栏工作台。

实现说明：

- `artifact.list/get` 按已验证 Person 隔离，只暴露本人和全局产物；
- 产物页支持当前会话/全部范围、图片预览、文件打开；
- 对话中的 Artifact 卡片可直接打开产物页并定位对应产物；
- 上下文页只展示当前协议可确认的信息，不推测不存在的 Goal 或记忆；
- 原独立 Assignment Drawer 已移除，委托详情统一进入右侧栏。

### 阶段 G：Agent 当前状态投影

- 直接复用 `LivingState`，展示 dormant、waking、awake、idle、working、
  sleeping、dreaming；
- 通过 `agent.state.get` 恢复当前状态，通过 `agent.state.changed` 实时更新；
- Layer2 意图决策期间展示轻量关注状态，并保留最近一次可解释意图摘要；
- 不保存或展示模型思维链，不把高频 WAIT 判断写入 Activity 历史；
- Desktop 组合本地运行状态、生命状态、当前关注和正在执行的 Activity。

交付结果：用户不仅能看到 Agent 在执行什么，也能理解它此刻是清醒、空闲、
睡眠、做梦，还是正在判断下一步。

### 补充：统一内部处理报告

- CLI 的“本轮内部处理”升级为正式的 `InternalProcessingReport`；
- Layer2 意识涌现、社会认知、L3 深度反思、L4 深度联想、InnerVoice、
  DAG、记忆提取、流程学习和叙事学习使用同一份结构；
- 一次展示周期只形成一个 Agent 全局 `internal_processing` Activity；
- 各项结果作为 Activity 步骤展示，不再为每个钩子制造零散认知 Activity；
- 内心独白记忆、NARR 叙事记忆和自我不确定只展示数量与安全摘要。

### 补充：记忆可解释性第一版

- 本轮即时记忆操作保留 `ADD/UPDATE/MERGE/DELETE` 的安全内容摘要，并作为
  `internal_processing` Activity 的具体步骤展示；
- 对话产生的内部处理 Activity 关联原始 Person、Session 和 Turn，避免把人物
  记忆摘要广播给其他 Person；
- `MemoryWindow` 将本次回答前实际召回并注入上下文的长期记忆投影为安全引用；
- 安全引用随 assistant message metadata 持久化，并由 `message.complete` 和
  `chat.history` 使用同一数据形状；
- Desktop 在回答下方展示召回数量，点击后在右侧栏查看记忆摘要、来源、标签和
  形成时间；
- 界面明确说明“被召回并提供给 Agent”不等于模型逐条直接引用；
- 不暴露 embedding、检索分数、原始思维链、InnerVoice、梦境或私有叙事内容；
- 本阶段不实现 Goal 详情、记忆编辑、删除、搜索或批量管理。

### 补充：当前 Person 的长期记忆

- 增加只读 `memory.list` RPC，不增加推送事件；
- Person 身份只能来自 Gateway 已认证的连接上下文，客户端提交的 `person_id`
  不参与查询；
- 只展示准确归属于当前 Person、状态为 active、类型为 common 且来源允许公开
  的长期记忆；
- 不展示 global、其他 Person、梦境、InnerVoice、内部经验或私有叙事；
- 不新增或迁移数据库表，直接使用长期记忆现有字段；
- Desktop 右侧栏增加“记忆”页，按最近形成或使用时间自然排序，支持刷新和分页；
- 每条记忆只展示安全摘要、形成方式、标签、形成时间和最近使用时间；
- 不提供来源会话跳转，避免为当前阶段增加额外溯源关系和迁移成本。

## 12. 第一轮验收

### 12.1 工作活动

1. 创建耗时 Assignment；
2. 右侧栏出现进行中 Activity；
3. 切换会话后 Activity 仍存在；
4. Assignment 详情和 Activity 运行详情可以互相定位；
5. 完成后产物进入产物页。

### 12.2 自主行为

1. 触发学习、闹钟或 Goal/PACE；
2. 右侧栏实时显示阶段；
3. 此时发送消息，实时对话正常回复；
4. 后台行为安全让出并继续；
5. Activity 不串入 Person/session。

### 12.3 会话后认知

1. 连续完成足够轮次以触发 InnerVoice、DAG 和周期记忆提取；
2. 右侧栏显示“会话后整理”；
3. 展开后可看到实际执行的子活动；
4. 未达到阈值的检查不产生噪声卡片；
5. 不展示原始隐藏推理。

### 12.4 梦境

1. 进入 sleeping/dreaming；
2. 右侧栏显示 Dream Activity；
3. 梦境完成后显示整理范围和结果摘要；
4. Activity 属于 Agent 全局；
5. 重启后历史仍可查询。

### 12.5 重启与断线

1. 活动运行中停止 Agent；
2. 重启后显示 paused/interrupted；
3. Assignment/Goal 根据自己的 checkpoint 决定能否恢复；
4. Desktop 断线重连后通过 RPC 恢复最新快照；
5. 不重复显示旧 revision。

## 13. 本阶段明确不做

- 不建立中央 Agent 管理服务；
- 不把 Assignment、Goal 和 Dream 合并成一种领域对象；
- 不创建第二套 Agent Core；
- 不引入通用工作流编排器；
- 不展示原始思维链；
- 不增加复杂优先级调度；
- 不实现多个自主行为并行；
- 不在第一版提供大量暂停、恢复、重试按钮；
- 不把右侧栏变成原始日志查看器。

## 14. 最终目标

> 用户可以继续像与一个人交流一样使用 Agent，同时通过右侧栏清楚了解这个
> Agent 正在工作、学习、整理记忆、形成内在反思还是进入梦境；这些可观察信息
> 来自 Agent 自己的真实状态，而不是 Desktop 猜测或伪造。
