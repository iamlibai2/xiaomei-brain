# Assignment：人与 Agent 之间的工作委托

状态：第一阶段已完成。阶段 A（领域与存储）、阶段 B（当前对话内形成和更新委托）、阶段 C（隔离后台执行与恢复）、阶段 D（Gateway 协议）及阶段 E（Desktop 第一版）已于 2026-07-26 完成；阶段 F（飞书与钉钉投影）及第一阶段真实业务验收已于 2026-07-27 完成。

## 1. 一句话定义

`Assignment`（委托）是某个 Person 与 Agent 就一项可持续、可交付的工作形成的约定。

它不是一轮聊天，不是一次工具调用，也不是 Agent 内部的目标节点。它可以跨越多轮对话、多个渠道、Agent 重启和多次执行，并最终形成可验证的交付物。

```text
Person 提出工作
  → Agent 理解、澄清并决定是否接受
  → Agent 建立 Assignment
  → Agent 为完成它形成内部 Goal / 子目标
  → 后台持续执行
  → 等待补充、请求批准或报告进展
  → 交付 Artifact
  → 双方继续修改，或者完成
```

## 2. 为什么不能直接把现有 Goal 暴露给用户

项目已经存在 `PurposeEngine`、`Goal`、`GoalRun` 和 `PACE`。这些能力应当保留并复用，但 `Goal` 与 `Assignment` 表达的不是同一件事。

| 概念 | 回答的问题 | 所属范围 | 是否直接展示给外部 |
|---|---|---|---|
| Person | 我认识的这个人是谁 | Agent 的人物世界 | 是 |
| Session | 这段沟通发生在哪里 | 对话作用域 | 是 |
| Turn | 这一次输入和完整响应是什么 | 单轮交互 | 是 |
| Assignment | 我和对方约定完成什么工作 | 社会关系与工作约定 | 是 |
| Goal | 为了生活或完成工作，我当前追求什么 | Agent 内部目的系统 | 通常否 |
| Action | 某个有风险的具体操作是否获准 | 一次执行步骤 | 是 |
| Artifact | 工作产生了什么可读取的结果 | 会话或委托资产 | 是 |

一个 Agent 可以拥有不来自任何人的 Goal，例如学习、反省、关系维护和自我发展。一个 Assignment 也可能被 Agent 拆成多个 Goal 和子目标。因此不能将所有 Goal 都解释成“用户任务”，也不能让客户端直接创建或修改 Agent 的内部目标树。

第一阶段采用以下关系：

```text
Assignment 1 ── 0..1 Root Goal
Root Goal   1 ── 0..N Sub Goal
Assignment 1 ── 0..N Turn
Assignment 1 ── 0..N Artifact
Assignment 1 ── 0..N Interaction / Action
```

`Assignment` 是外部稳定边界；`Goal/PACE` 是内部执行机制。以后可以替换执行策略，而不破坏用户看到的委托历史。

## 3. 设计原则

### 3.1 一 Agent 一世界

委托存储在对应 Agent 自己的 `brain.db` 中。没有中央 Assignment 服务，也不由 Desktop 保存真实状态。

同一份工作如果交给两个 Agent，它们会分别形成自己的 Assignment、理解、经历和产物。

### 3.2 Agent 不是被动任务容器

Person 可以提出委托，Agent 可以：

- 直接接受；
- 先澄清目标；
- 说明能力边界后接受一部分；
- 拒绝不合适、危险或超出能力的工作。

客户端不能绕过 Agent，直接把任意记录强行写成“进行中”。

### 3.3 对话优先，界面辅助

创建、修改目标、追加资料、询问进度和要求停止，都应当可以通过自然对话完成。

Desktop 的卡片和按钮是同一领域能力的投影，用于查看状态和执行明确、可逆的快捷操作，不形成另一套业务逻辑。

### 3.4 状态必须持久化

Agent、Desktop 或渠道重启后，委托、关键进展、等待原因、交付物和执行检查点都不能丢失。

### 3.5 对话不能被后台工作阻塞

渠道接收、身份识别和消息入队不能执行耗时工作。Assignment 执行不能运行在 Living 主线程的同步调用栈内。

### 3.6 进度必须诚实

没有可靠依据时不展示虚假的百分比。优先展示：

- 当前阶段；
- 已完成步骤 / 总步骤；
- 正在做什么；
- 正在等待谁；
- 最近一次有效进展。

## 4. 领域模型

### 4.1 Assignment

第一阶段的核心字段：

```text
id
title
objective
status

requester_person_id
scope_type
scope_id

origin_channel
origin_session_id
origin_turn_id
root_goal_id

acceptance_criteria
constraints
requested_due_at

progress_summary
completed_steps
total_steps
waiting_reason
terminal_reason

revision
created_at
accepted_at
started_at
updated_at
completed_at
```

说明：

- 数据库属于单个 Agent，因此不重复存储 `agent_id`。
- `requester_person_id` 是 Agent 本地认识的 Person，不接受客户端自报 ID。
- `scope_type/scope_id` 表示委托发生的社会作用域，预留 `person`、`group`、`team`、`project` 和 `internal`。
- `origin_*` 只记录委托最初从哪里形成，不限制后续只能从该渠道继续。
- `root_goal_id` 连接现有 Purpose 系统；尚未开始内部规划时可以为空。
- `revision` 每次实质变更递增，客户端只接受更新版本的快照。
- `acceptance_criteria` 是双方认可的完成条件，不等同于 Agent 内部子目标。

第一阶段不增加固定的“法务、财务、文档、编码”等任务类型。能力分类以后通过标签或职责系统扩展，避免过早把领域写死。

### 4.2 AssignmentEvent

委托需要追加式事件历史，用来回答“什么时候发生了什么、由谁引起”。

```text
id
assignment_id
event_type
actor_type
actor_id
payload
idempotency_key
created_at
```

建议的内部事件：

```text
offered
clarification_requested
accepted
declined
started
progressed
waiting
resumed
artifact_linked
cancel_requested
cancelled
failed
completed
reopened
```

`actor_type` 至少支持 `person`、`agent`、`system`。事件历史不是模型思维链，只记录对工作有实际意义的事实。

### 4.3 AssignmentResource

附件、消息、Turn、Artifact 和 Goal 已有自己的存储，不复制内容，只建立引用：

```text
assignment_id
resource_type
resource_key
relation
metadata
created_at
```

例如：

```text
attachment / 输入资料
turn       / 需求澄清
artifact   / 最终交付
goal       / 内部执行根目标
session    / 参与过该委托的会话
```

服务层必须校验资源确实属于当前 Agent，并且当前 IdentityContext 有权访问；客户端不能提交任意文件路径。

### 4.4 AssignmentRun

一次委托可以因为重试、恢复或修改要求而经历多次执行：

```text
run_id
assignment_id
status
trigger_type
trigger_actor_id
checkpoint
safe_to_resume
started_at
updated_at
ended_at
error
```

`AssignmentRun` 是外部可恢复的工作执行；现有 `GoalRun` 继续记录内部 Goal/PACE 执行。二者通过 Assignment 的 `root_goal_id` 和 Run 元数据关联。

## 5. 生命周期

### 5.1 状态

```text
offered
clarifying
accepted
queued
in_progress
waiting_person
paused
completed
declined
cancelled
failed
```

推荐状态流：

```text
offered
  ├─→ clarifying ─→ accepted
  ├─→ accepted
  └─→ declined

accepted ─→ queued ─→ in_progress
                         ├─→ waiting_person ─→ queued
                         ├─→ paused ─────────→ queued
                         ├─→ completed
                         ├─→ failed
                         └─→ cancelled

completed ─→ reopened ─→ queued
```

### 5.2 “接受”与“开始”分开

Agent 接受委托表示认可目标和责任，但不代表已经获得执行所需的时间、资料和批准。

因此：

- `accepted`：已经形成约定；
- `queued`：具备执行条件，正在等待工作资源；
- `in_progress`：当前确实在执行；
- `waiting_person`：只有对方提供信息或选择后才能继续；
- `paused`：Agent 主动暂停、资源不足或系统恢复中。

### 5.3 完成与验收

第一阶段由 Agent 在满足 acceptance criteria 后标记 `completed`，并明确列出交付物。Person 后续要求修改时使用 `reopened`，继续原 Assignment，不创建一条无关的新工作。

未来如果企业需要严格验收，可增加 `delivered` 与 `accepted_by_requester`，第一阶段不引入这层复杂度。

### 5.4 取消语义

Person 提出的是 `cancel_requested`。Agent 通常立即停止，但仍通过 AssignmentService 完成：

- 设置取消令牌；
- 等待当前安全边界；
- 保存已完成进度；
- 标记未完成产物；
- 记录取消原因；
- 转为 `cancelled`。

Desktop 不直接杀死 Agent 线程。强制停止 Agent 属于本地运维能力，不属于 Assignment 协议。

## 6. 委托如何形成

### 6.1 不把每句话都变成委托

以下内容通常仍是普通 Turn：

- 简单问答；
- 一步即可完成且当轮交付的操作；
- 闲聊、讨论和观点交换；
- 不需要后续跟踪的临时请求。

以下信号适合形成 Assignment：

- 需要多个步骤或较长时间；
- 需要等待外部资料或用户决定；
- 有明确交付物；
- 可能跨越多轮对话；
- 用户明确要求后台完成、持续跟进或稍后交付；
- 工作中断后必须恢复。

### 6.2 创建权在 Agent 内部

新增内部工具或领域调用：

```text
offer_assignment(...)
accept_assignment(...)
update_assignment(...)
complete_assignment(...)
```

它们由 Agent 的对话核心调用 `AssignmentService`，不是暴露给客户端任意写数据库的管理 RPC。

典型流程：

```text
Person: 分析这三份竞品资料，给管理层写报告
Agent: 识别为持续工作
Agent: 使用 Clarify 确认读者、格式和截止时间
Agent: 创建并接受 Assignment
Agent: 发送委托卡片
WorkScheduler: 将其加入执行队列
```

Agent 已经理解清楚且风险较低时，可以在回复中直接接受并创建，不要求 Person 再点一次确认。

## 7. 与现有 Purpose / Goal / PACE 的关系

### 7.1 保留 Purpose 的内部自主性

现有 `GoalType` 包含战略、阶段和可执行目标，`TaskType` 还包含学习、反省、关系维护与探索。这些目标不能全部变成 Assignment。

只有为了履行某项委托而形成的根 Goal 才关联 `assignment_id`。

```text
Assignment
  objective: 对比三款产品并交付管理层报告
  acceptance: 报告 + 对比表

Root Goal
  description: 完成竞品分析委托
  Sub Goal 1: 读取并整理资料
  Sub Goal 2: 比较定位、价格、目标客户
  Sub Goal 3: 生成报告和表格
  Sub Goal 4: 检查交付标准
```

### 7.2 第一阶段复用内容

可以复用：

- Goal 分解与依赖；
- Goal cognitive log；
- PACE 检查点；
- GoalRun；
- 工具执行；
- 完成后的知识提取。

需要改造：

- Goal 当前缺少 Person、Session、Turn 和 Assignment 边界；
- 当前执行会占用 Living/ConversationDriver 的同步路径；
- 工具 callback 存放在共享 Agent Core 上，不适合并发执行上下文；
- Clarify 和 Action 当前主要绑定 Turn，重启恢复能力不足；
- Artifact 只关联 Session/Turn，还不能稳定表达委托交付物；
- Goal 的状态不能直接作为外部工作状态。

### 7.3 不直接扩改历史 goals 表

第一阶段使用 `assignment_resources` 或 Assignment 自身的 `root_goal_id` 建立引用，不要求给已有 `goals` 表批量增加 Person 和 Session 字段。历史 Agent 数据继续原样加载。

## 8. 执行架构

### 8.1 三条工作通道

```text
                   ┌─ Conversation Lane：人类实时对话，高优先级
Inbound / Living ──┼─ Assignment Lane：已接受委托，后台执行
                   └─ Autonomy Lane：学习、梦境、反思，低优先级
```

它们共享同一个 Agent 的世界、身份、记忆和工具，但不能共享一组可变的运行时 callback。

### 8.2 Agent 本地 WorkScheduler

建议新增 Agent 内部组件：

```text
assignments/
├── models.py
├── store.py
├── service.py
├── scheduler.py
├── executor.py
├── execution_context.py
├── projector.py
└── tools.py
```

职责：

- `AssignmentService`：唯一领域写入口，校验状态转换并落库；
- `AssignmentStore`：SQLite 增量迁移和查询；
- `WorkScheduler`：恢复待执行委托、排序和分配执行资源；
- `WorkExecutor`：执行一个有边界的工作步骤；
- `ExecutionContext`：隔离 user/session/turn/assignment、callback、取消令牌和工具记录；
- `Projector`：把领域事件投影到 Gateway、Desktop 和 Channel；
- `tools.py`：供 Agent 自己创建、更新和完成委托。

这些组件属于 Agent 内部，不属于 Gateway，也不是 Desktop 的本地管理服务。

### 8.3 初始并发策略

第一阶段每个 Agent 同时只运行一个 Assignment Worker，但实时对话必须保持可接收、可排队。

不能直接让两个线程共享当前 `AgentInstance`，因为当前代码会在执行前修改：

```text
agent.user_id
agent.session_id
agent.turn_id
agent.on_tool_start
agent.on_tool_complete
agent.on_artifact
agent.on_tool_approval
```

这会造成不同工作之间的事件、产物和批准串线。

正确方向是让每次运行拥有独立 `ExecutionContext`，并由 Agent Core 工厂创建隔离的执行实例。共享的是模型配置、工具注册表和持久化服务，不共享当前 Turn 的可变字段。

第一阶段的资源策略：

- Conversation Executor：一个隔离上下文；
- Assignment Executor：并发数固定为 1；
- 自主行为：仅在没有实时对话和委托执行资源时运行；
- 对同一文件或高风险工具使用资源锁；
- 后续通过真实压力测试再增加多个 Assignment 并发。

### 8.4 有边界的 WorkStep

Assignment Worker 不应一次拿着线程和 Agent Core 运行到整个委托结束。它执行一个可恢复步骤：

```text
加载 Assignment + checkpoint
→ 确定当前 Goal/步骤
→ 执行有限的 LLM/工具循环
→ 写入进展、产物和 checkpoint
→ 继续排队 / 等待 Person / 完成
```

这样才能：

- 在步骤边界响应取消；
- 避免某项工作长期饿死对话；
- Agent 重启后恢复；
- 对失败步骤重试而不是重做整项工作；
- 避免重复执行有副作用的工具。

### 8.5 重启恢复

Agent 启动时：

1. 加载非终态 Assignment；
2. 将遗留的 `in_progress` Run 标记为 interrupted；
3. 检查最近 checkpoint；
4. 只有 `safe_to_resume=true` 时自动重新排队；
5. 未确认是否安全的副作用步骤进入 `paused`，要求 Agent 或 Person 确认；
6. 不重复执行已经有完成记录和幂等键的工具步骤。

## 9. Interaction、Action 与 Assignment

不为委托重新发明 Clarify 和批准协议。

现有请求增加可选关联：

```text
assignment_id
run_id
```

含义：

- `interaction.*`：缺少信息或需要选择，Assignment 转为 `waiting_person`；
- `action.*`：需要批准有副作用的具体操作，Assignment 可以等待批准；
- 收到响应后恢复原 Assignment Run，而不是创建一轮无关工作。

第一阶段响应权限：

- 私人委托：仅 requester Person；
- 群聊委托：仅提出者可响应涉及个人权限的 Clarify/Action；
- 以后由 AccessPolicy 扩展审批人和替代处理人。

Pending Interaction/Action 最终必须持久化，否则 Agent 重启后卡片仍在而内部请求已经丢失。该改造与 Assignment 恢复一起实施。

## 10. Artifact 与附件

附件属于 Agent 的会话资产，继续由 Agent 授权读取。Assignment 只引用已经进入 Agent 资产链路的附件。

Artifact 继续使用现有不可变快照存储，不把文件二进制复制到 Assignment 表。`assignment_resources` 记录其角色：

```text
draft
supporting
final
superseded
```

修改报告时产生新 Artifact，并将旧版本标记为 `superseded`，而不是覆盖历史文件。Assignment 卡片默认展示最新 `final` 或 `draft`。

## 11. 上下文和记忆

### 11.1 不把所有委托塞进每轮上下文

普通聊天只注入一个很短的活跃委托索引，例如：

```text
当前与李白有关的工作：
- 竞品分析：等待补充第三份资料
- 周报整理：进行中，正在生成表格
```

只有明确继续某项委托时，才加载：

- objective 和 acceptance criteria；
- 最近有效 checkpoint；
- 关键 AssignmentEvent；
- 相关 Goal cognitive log；
- 关联附件与 Artifact 索引；
- 与当前步骤相关的历史 Turn。

### 11.2 记忆归属

Assignment 事件不是自动等同于长期记忆。

- 工作事实与进度留在 Assignment；
- 原始对话留在 messages；
- 群聊现场留在 group_messages；
- 完成后由现有知识提取判断哪些经历值得进入长期记忆；
- Agent 可以记住“我和某人完成过这件事”，但不能把整个报告重复写入记忆。

## 12. Gateway 协议

Assignment 真实状态在 Agent 内部。Desktop/TUI 通过 WebSocket RPC 查询，渠道通过同一领域事件投影。

第一阶段方法：

```text
assignment.list
assignment.get
assignment.request_cancel
assignment.request_resume
```

不提供客户端直接调用的 `assignment.create`、`assignment.set_status` 或 `assignment.complete`。创建和状态变化由对话核心与 AssignmentService 决定。

方法使用连接绑定的 `IdentityContext` 鉴权，不接受客户端在参数中自行提交 `person_id`。

外部事件尽量保持简单：

```text
assignment.changed
assignment.progress
```

`assignment.changed` 携带当前公开快照和 `revision`，客户端按新 revision 覆盖旧卡片。`assignment.progress` 用于高频但可丢失的执行提示；有业务意义的进展仍会持久化并最终产生 `assignment.changed`。

公开快照不包含：

- 模型思维链；
- 内部 Goal 的完整认知日志；
- 未授权文件路径；
- 其他 Person 的私有信息；
- 工具原始敏感参数。

## 13. Desktop 设计

不新增一个挤在左侧栏的“任务管理中心”。

### 13.1 对话内卡片

Assignment 在形成的那一刻自然出现在聊天流中：

```text
竞品分析报告
进行中

正在整理价格和目标客户
已完成 2 / 4 个步骤
更新于 3 分钟前
```

状态变化更新同一张逻辑卡片，切换会话和重启后由 `assignment.get/list` 恢复。

### 13.2 Agent 详情中的工作区

每个 Agent 的详情或首页自然展示：

- 正在进行；
- 等待我；
- 最近完成。

最多先显示少量最近项目，按更新时间自然排序。没有归档、复杂筛选和项目管理看板。

### 13.3 详情抽屉

点击卡片打开抽屉，展示：

- 目标和完成标准；
- 当前状态与等待原因；
- 有意义的进展时间线；
- 输入资料；
- 最新交付物；
- “继续对话”“请求停止”等操作。

不展示内部 Goal 树和思维链。将来可以为分析模式提供更深的内部观察，但不属于普通工作界面。

### 13.4 通知

仅在以下情况产生系统通知：

- 需要 Person 回答 Clarify；
- 需要批准 Action；
- 委托完成；
- 委托失败或无法继续。

普通进度更新不弹 Windows 通知。

## 14. 渠道行为

所有渠道共享 AssignmentService，不各自创建任务逻辑。

### Desktop

- 完整卡片、列表、详情和 Artifact；
- 可从任何已认证 Desktop 会话继续；
- Agent 重启后恢复。

### 飞书

- 私聊和被 `@` 的群聊可以形成委托；
- 普通群消息只作为现场观察，不自动形成委托；
- 状态投影为简洁卡片；
- Clarify、Action 和完成通知继续使用渠道卡片；
- 群聊委托保留 requester Person 和 group scope。

### 钉钉

- 只有私聊或 `@ Agent` 的群消息能够提出或继续委托；
- 平台不推送未 `@` 的普通群聊，因此不能依赖完整群现场；
- 功能语义不变，只有上下文能力较弱。

### CLI/TUI

- 共享内部服务；
- CLI 仍可直接调用本地领域接口，不要求绕行 WebSocket；
- TUI 后续重构时消费同一公开快照。

## 15. 数据库迁移

使用现有 `SQLiteStore.schema_versions(component, version)` 增量升级：

```text
component = assignment_storage
version   = 1
```

第一阶段只新增：

```text
assignments
assignment_events
assignment_resources
assignment_runs
```

原则：

- 不删除或重建现有表；
- 不修改历史 `user_id`；
- 不把旧 Goal 自动迁移成 Assignment；
- 不把旧对话猜测为未完成委托；
- 历史 Agent 打开后只创建新表，原有数据保持不变；
- 数据库升级失败时 Agent 应明确报错，不能静默清空或新建替代数据库。

## 16. 第一阶段实施范围

第一阶段只把“研究与文档型数字同事”跑通：

1. 多份资料的读取、总结和比较；
2. 研究并生成报告；
3. 根据反馈持续修改 Word、Excel、PPT 或 Markdown 交付物。

不在第一阶段实现：

- 企业组织架构和岗位权限；
- 多 Agent 互相委托；
- 项目管理看板、工时和绩效；
- 多个 Assignment 并行执行；
- 自动判断复杂审批链；
- 个人微信渠道；
- 把所有旧 Goal 转成委托；
- 完整分析模式。

## 17. 分阶段实施顺序

### A. 领域与存储

- Assignment 模型和状态机；
- 增量数据库迁移；
- AssignmentService；
- 事件历史与资源引用；
- 单元测试覆盖非法状态转换和历史数据库升级。

### B. 对话形成委托

- Agent 内部 Assignment 工具；
- 从自然对话创建、澄清、接受、拒绝和完成；
- 连接 requester Person、Session、Turn、附件和 Artifact；
- 先在本地单会话验证。

### C. 后台执行与恢复

- ExecutionContext 隔离；
- WorkScheduler 和单 Worker；
- WorkStep、checkpoint、取消和重启恢复；
- 对话与委托执行互不串线；
- 自主行为不再阻塞人类消息。

### D. Gateway 与 Desktop

- `assignment.list/get/request_*`；
- `assignment.changed/progress`；
- 对话内卡片、Agent 工作区和详情抽屉；
- 重启、切换 Agent、跨会话恢复。

### E. 渠道投影

- 飞书卡片和通知；
- 钉钉文本/卡片降级；
- 从不同渠道继续同一 Assignment；
- Person 和群聊作用域验证。

### F. 第一批真实工作模板

- 竞品研究报告；
- 多文档对比；
- 报告持续修订；
- 真实附件、真实模型和真实 Office 产物验收。

## 18. 第一阶段验收场景

以“分析三份竞品资料并生成管理层报告”为基准：

1. Person 从飞书或 Desktop 提出工作；
2. Agent 使用 Clarify 补齐读者、重点和格式；
3. 形成一个 Assignment，而不是把每轮追问创建成新任务；
4. Desktop 展示进行中卡片；
5. 后台执行时，Agent 仍能接收另一条人类消息；
6. 切换 Agent 后，两个 Agent 的工作状态不串线；
7. Agent 重启后恢复 Assignment 和安全检查点；
8. 需要批准的工具只暂停该 Assignment；
9. 完成后报告和对比表关联到同一 Assignment；
10. Person 从另一渠道要求修改时，原 Assignment 被 reopened；
11. 历史消息、群消息、梦境和记忆不会因为 Assignment 引用而混入错误作用域；
12. 升级一个已有 Agent 数据库不会丢失任何历史数据。

### 18.1 验收记录（2026-07-27）

- Desktop、飞书和钉钉均使用 Agent 中同一份 Assignment 权威状态，渠道不维护自己的任务状态机；
- 后台执行、对话隔离、安全检查点恢复、等待人物、取消/继续和原委托修订均有自动化回归测试；
- 飞书和钉钉均已真实验证状态卡片、卡片交互及完成后的原生文件投递；
- 状态卡片的外部消息标识和最后 revision 持久化在 Agent 数据库中，重启后继续更新同一张卡片，并拒绝旧事件重复投递；
- 真实文档/PPT 委托已验证创建、后台执行、产物形成、渠道接收及再次修改闭环；
- 既有 `messages`、`group_messages`、记忆、梦境和 Goal 数据结构没有因 Assignment 引用而改变。

### 18.2 第一版完成契约

一项委托只有同时满足以下条件，Runner 才能返回 `completed`：

1. 执行计划中的步骤全部完成；
2. 每条 `acceptance_criteria` 都已逐项核对，并记录“是否满足”和事实证据；
3. 所有完成标准均为满足；
4. 如果完成标准要求文件，必须产生真实、非空且已进入 Agent 资产存储的 Artifact；
5. 最终交付物已关联到该 Assignment，并可从原会话、Desktop 或支持文件消息的渠道读取。

缺少验收记录或存在未满足项时，委托进入可恢复的 `paused`，不会虚假标记完成。第一版不自动返工、不调用独立验收模型，也不增加额外任务管理界面；Person 可以在原委托上继续工作或要求修改。

## 19. 当前确定的关键决策

1. 产品概念使用“委托”，代码领域名使用 `assignment`。
2. Assignment 是外部工作约定，Goal 是 Agent 内部目标，两者不合并。
3. 每个 Agent 独立保存和执行自己的 Assignment。
4. 创建权属于 Agent 对话核心，客户端没有任意写状态的 RPC。
5. 第一阶段每 Agent 只有一个 Assignment Worker。
6. 工作执行必须与 Living 主线程和渠道接收解耦。
7. Assignment 引用现有消息、附件和 Artifact，不复制资产。
8. 不修改现有表的 `user_id`，只做新增式数据库升级。
9. Desktop 使用聊天卡片和 Agent 工作区，不新增复杂任务管理页面。
10. 第一阶段以研究、文档处理和可修改交付物为真实价值闭环。
11. 委托完成必须经过结构化验收；未通过时暂停，自动返工留待后续独立设计。

## 20. 预计文件改动

下面是完整方案预计涉及的文件。实施时按阶段提交，不一次性铺开所有改动。

### 20.1 阶段 A：领域与存储

新增：

```text
src/xiaomei_brain/assignments/__init__.py
src/xiaomei_brain/assignments/models.py
src/xiaomei_brain/assignments/store.py
src/xiaomei_brain/assignments/service.py

tests/test_assignment_models.py
tests/test_assignment_store.py
tests/test_assignment_service.py
```

职责：

- `models.py`：Assignment、AssignmentEvent、AssignmentResource、AssignmentRun 和状态转换；
- `store.py`：在现有 `brain.db` 中创建独立 `assignment_storage` schema；
- `service.py`：唯一领域写入口、revision、事件记录、权限上下文和资源引用；
- 第一批测试只验证模型、迁移、状态机和历史数据库安全升级。

本阶段不修改 `ConversationDB`、Purpose、Gateway 或 Desktop。

### 20.2 阶段 B：对话形成委托

新增：

```text
src/xiaomei_brain/assignments/tools.py
src/xiaomei_brain/assignments/context.py
```

修改：

```text
src/xiaomei_brain/consciousness/conscious_living.py
src/xiaomei_brain/consciousness/living.py
src/xiaomei_brain/consciousness/conversation_driver.py
src/xiaomei_brain/consciousness/context_pipeline.py
src/xiaomei_brain/agent/agent_manager.py
```

职责：

- 在 Agent 启动时装配 AssignmentService；
- 注册只供 Agent 内部使用的委托工具；
- LivingMessage/执行上下文携带可选 `assignment_id`；
- 对话理解形成委托，并关联 requester Person、Session、Turn 和附件；
- 只在继续某项委托时加载其详细上下文。

### 20.3 阶段 C：后台执行与恢复

新增：

```text
src/xiaomei_brain/assignments/scheduler.py
src/xiaomei_brain/assignments/executor.py
src/xiaomei_brain/assignments/execution_context.py

tests/test_assignment_scheduler.py
tests/test_assignment_recovery.py
tests/test_assignment_execution_isolation.py
```

修改：

```text
src/xiaomei_brain/agent/core.py
src/xiaomei_brain/consciousness/conscious_living.py
src/xiaomei_brain/consciousness/conversation_driver.py
src/xiaomei_brain/consciousness/action_dispatcher.py
src/xiaomei_brain/consciousness/interaction_broker.py
src/xiaomei_brain/consciousness/action_broker.py
```

职责：

- 将耗时委托从 Living 主线程移出；
- 隔离每次执行的 session、turn、assignment、callback 和取消令牌；
- 第一阶段每 Agent 只运行一个 Assignment Worker；
- 持久化等待中的 Clarify/Action；
- 实现 checkpoint、取消、失败和重启恢复；
- 自主行为与实时对话按优先级调度。

这是风险最大的阶段，必须先完成执行隔离测试，不能直接在线程中复用当前共享 Agent Core。

实现说明（2026-07-26）：

- `accept_assignment` 在领域记录和资源关联完成后立即将委托置为 `queued` 并提交后台 Scheduler，不再依赖模型额外调用 `start_assignment`；
- 工具结果通过内部 handoff 控制信号把执行权从实时 ReAct 转交给隔离 Runner；Agent Core 保存干净的工具结果、回复接收确认后立即结束当前执行链，禁止模型在同一 Turn 继续前台完成委托；
- 接受时仍缺少必要信息，可以同时写入持久 `pending_interaction`；同一 Person 在来源会话中的下一条回复会由 Gateway 标记并由 ConversationDriver 直接恢复后台 Scheduler，不再进入实时 ReAct；
- 普通回复只能恢复 `pending_interaction`，永远不能批准 `pending_action`；后台遇到待批准 Action 后在该工具边界立即停止，不再继续调用其他工具或生成混杂结果；
- 当前不再把整个 Shell 设为待批准能力：通过 Shell 自身危险命令检查的调用直接执行，明确危险的命令仍硬拒绝；Action 审批协议保留给未来具备清晰风险边界的具体能力；
- 后台文件工具固定使用当前 Agent workspace 的相对路径，禁止猜测 `~/.xiaomei-brain/global` 或用 Shell 探测工作目录；
- `wait_assignment` 和 `complete_assignment` 不再自动补造 `queued → started` 事件，只有真实处于 `in_progress` 的委托才能等待或完成；
- 每次后台运行重新创建独立 LLMClient、Agent Core、ToolRegistry、Session 和 Turn；
- 后台只复制显式白名单中的文件、网页和受策略约束的 Shell 工具，不复制 Clarify、Goal、Assignment、Session、Memory、身体或通讯工具；
- Clarify 和待批准 Action 不阻塞复用实时 Broker，而是写入 AssignmentRun 安全检查点；人物回复后由 Agent 明确携带回复或 approve/deny 决定恢复；
- Action 批准与工具名、完整参数绑定且只消费一次，普通回复不能被当作批准；
- 实时对话繁忙时，后台 Runner 会在 LLM/工具步骤边界主动让出执行权；
- Agent 停止、进程异常、排队后尚未创建 Run、LLM 欠费等路径均有确定的持久状态和恢复行为。

### 20.4 阶段 D：Gateway 协议

新增：

```text
src/xiaomei_brain/gateway/methods/assignments.py
tests/test_gateway_assignments.py
```

修改：

```text
src/xiaomei_brain/gateway/methods/__init__.py
src/xiaomei_brain/gateway/server_methods.py
src/xiaomei_brain/gateway/schemas.py
src/xiaomei_brain/gateway/event_projection.py
src/xiaomei_brain/gateway/router.py
```

职责：

- 注册 `assignment.list/get/request_cancel/request_resume`；
- 在 `connect.capabilities` 中声明 Assignment 能力；
- 使用连接绑定的 IdentityContext 授权查询和操作；
- 将 Assignment 事件投影到正确的 Person、Session 和 Channel。

实施结果（2026-07-26）：

- 已注册 `assignment.list/get/request_cancel/request_resume`，并由方法目录自动声明 `assignment.read/control/events` 能力；
- 所有方法只从连接绑定的 `IdentityContext` 构造 Person actor，忽略客户端自行提交的身份字段；
- `request_cancel` 和 `request_resume` 只记录人物请求，实际取消、排队和恢复由 Agent 的 Scheduler 执行；
- 恢复操作会验证安全 checkpoint，待批准 Action 必须精确选择 `approve/deny`，待回答 Clarify 必须提供非空回复；
- `assignment.changed/progress` 已进入 Gateway 公开事件目录，内部人物路由字段会在发送前剥离；
- Assignment 事件优先投影到该 Person 最近活跃渠道，并以原 Session 作为回退；CLI 来源不会阻断后来连接的 Desktop 接收更新；
- `assignment.get` 返回公开快照、事实事件和已脱敏资源索引，不暴露内部文件路径、请求人物 ID 或执行 checkpoint。

### 20.5 阶段 E：Desktop

新增：

```text
src/xiaomei_brain/desktop/renderer/components/home/AssignmentCard.tsx
src/xiaomei_brain/desktop/renderer/components/home/AssignmentDrawer.tsx
src/xiaomei_brain/desktop/renderer/components/home/AgentWorkSection.tsx
src/xiaomei_brain/desktop/renderer/styles/assignments.css
```

修改：

```text
src/xiaomei_brain/desktop/main/preload.ts
src/xiaomei_brain/desktop/main/ipc-handlers.ts
src/xiaomei_brain/desktop/renderer/types.ts
src/xiaomei_brain/desktop/renderer/store/core.ts
src/xiaomei_brain/desktop/renderer/components/home/HomePage.tsx
src/xiaomei_brain/desktop/renderer/i18n/locales/zh-CN.json
src/xiaomei_brain/desktop/renderer/i18n/locales/en-US.json
```

职责：

- Electron IPC 转发 Assignment RPC；
- 每个 Agent 独立缓存 Assignment 快照；
- 处理 revision 和重连恢复；
- 在消息流、Agent 工作区和详情抽屉展示；
- 等待 Person、完成和失败时触发已有通知机制。

不新增左侧栏一级页面。

实施结果（2026-07-26）：

- Electron IPC 已转发 Assignment 查询、详情、取消请求和恢复请求；
- Zustand 按 Agent 隔离缓存公开快照，并严格按 `revision` 接受新版本；
- 每次连接/切换 Agent 后从 Agent 重新加载，因此不依赖 Desktop 本地消息存储恢复委托；
- 最近委托自然显示在当前聊天区域，右侧 Agent 工作区提供委托列表、详情、完成标准、事件记录和资源索引；
- 等待人物时可回答 Clarify，或对后台待批准 Action 做一次性批准/拒绝；
- 等待人物、完成和失败会复用现有 Windows 通知，后台 Agent 更新会增加未读数；
- 未增加左侧栏一级入口，也没有把委托做成需要用户维护的复杂任务管理页面。

### 20.6 阶段 F：飞书与钉钉投影

修改：

```text
src/xiaomei_brain/plugins/channels/feishu/adapter.py
src/xiaomei_brain/plugins/channels/feishu/client.py
src/xiaomei_brain/plugins/channels/dingtalk/adapter.py
src/xiaomei_brain/plugins/channels/dingtalk/client.py
```

可能新增：

```text
tests/test_feishu_assignments.py
tests/test_dingtalk_assignments.py
```

职责：

- 飞书展示委托状态卡片；
- 钉钉按平台能力降级为卡片或文本；
- 渠道只投影同一 AssignmentEvent，不实现自己的任务状态机；
- 验证跨渠道继续、Person 隔离和群聊作用域。

实施结果（2026-07-27）：

- 飞书和钉钉都使用可更新的单张委托状态卡片，卡片绑定持久化到 `assignment_channel_messages`；
- 等待 Clarify 或 Action 时直接在渠道卡片中响应，并恢复对应的安全检查点；
- 完成后的 Artifact 从 Agent 会话资产存储读取，再通过平台原生文件消息投递，不向渠道暴露宿主机路径；
- 旧 revision 不会覆盖新状态，也不会在 Agent 重启或事件重投后重复发送产物；
- 实际测试位于 `tests/test_feishu_identity_link.py`、`tests/test_dingtalk_identity_link.py` 和 `tests/test_dingtalk_client.py`。

### 20.7 明确不修改

第一阶段不计划修改或重建：

```text
src/xiaomei_brain/memory/conversation_db.py
src/xiaomei_brain/purpose/goal.py
src/xiaomei_brain/purpose/persistence.py
```

AssignmentStore 虽然使用同一个 `brain.db`，但拥有独立 schema version 和新增表。现有 messages、group_messages、goals、artifacts 以及历史 `user_id` 数据保持原状。
