# Gateway 实时交互协议

> 状态：V2 实施中。本文记录改造前基线、稳定协议和分阶段实施方向。协议语义参考 Hermes TUI/Desktop Gateway，但不以线级兼容为目标。

## 1. 定位

Gateway 是某个正在运行的 Agent 与外界交流的接口层，不是 Agent 管理服务，也不是 Agent 本体。

它的职责是：

- 接收外部对话并送入 Agent；
- 将 Agent 的文字、工具过程和结构化交互实时送达外部；
- 维护连接、用户与会话之间的通信关系；
- 为断线重连提供可恢复的会话状态。

不属于 Gateway 的职责：

- 创建、启动、停止尚未运行的本地 Agent；
- 修改离线 Agent 的文件或配置；
- 充当管理多个 Agent 的中央服务；
- 在协议层创造 Agent 内部尚不存在的 Task 模型。

## 2. V1 基线（改造前）

### 2.1 传输与封装

- 传输：WebSocket，路径 `/ws`；
- 请求响应：JSON-RPC 2.0；
- 心跳：非 JSON-RPC 的 `{ "type": "ping" }` / `{ "type": "pong" }`；
- 事件：JSON-RPC notification，当前统一使用 `method: "event"`，事件名放在 `params.event`；
- `connect` 当前返回 `protocol_version: 1`。

### 2.2 当前 RPC 方法

| 方法 | 作用 |
|---|---|
| `connect` | Token 校验、绑定用户和会话 |
| `chat.send` | 接受一条对话消息并放入 Living 队列 |
| `chat.abort` | 中断当前 Agent 正在进行的生成 |
| `chat.history` | 按消息 ID 游标读取会话历史 |
| `chat.sessions` | 搜索、分页列出会话 |
| `interaction.respond` | 回答属于当前连接会话的结构化交互 |
| `identity.list` | 列出 Agent 配置的联系人身份 |

### 2.3 当前服务端事件

| 事件 | 当前载荷 | 说明 |
|---|---|---|
| `chat.chunk` | `{ text }` | 流式文字片段 |
| `session.message` | `{ text }` | Desktop 将它当成本轮回复结束 |
| `internal.display` | `{ text: JSON字符串 }` | 内部认知展示 |
| `tool.start` | `{ text: JSON字符串 }` | 工具开始 |
| `tool.complete` | `{ text: JSON字符串 }` | 工具结束 |
| `interaction.requested` | `{ text: JSON字符串 }` | Agent 请求用户回答 |
| `interaction.updated` | `{ text: JSON字符串 }` | 交互被回答、取消或超时 |

客户端存在 `chat.error`、`chat.aborted` 的处理或常量，但当前 ConversationDriver 的主要 WebSocket 输出路径没有形成稳定的对应事件闭环。

### 2.4 当前 Desktop 行为

- Electron 主进程为每个 Agent 维护一个 GatewayClient；
- Renderer 收到事件前，由 Electron 主进程额外附加它认为的当前 `session_id`；
- Renderer 以 Agent 为单位拼接一条流式消息；
- `session.message` 被用来推断本轮完成，并清除“工作中”；
- `tool.start/tool.complete` 当前直接忽略；
- `interaction.*` 会再次解析 `data.text` 内的 JSON；
- 切换会话通过断开并重新建立该 Agent 的 WebSocket 连接完成；
- 重连会重新调用 `connect`，但不会恢复正在进行的一轮对话快照。

## 3. 主要缺口

### 3.1 没有“对话轮次”标识

当前只有 `session_id`，没有 `turn_id`。流式文字、工具调用、交互请求和最终消息无法在协议层证明属于同一轮对话。

### 3.2 没有完整生命周期

正常路径依赖 `session.message` 猜测完成。下列情况可能使客户端一直显示工作中或得到错误状态：

- Agent 返回空的最终文本；
- LLM 或工具执行抛出异常；
- 用户中断；
- 连接在流式过程中断开；
- 交互等待跨越断线重连。

### 3.3 结构化数据被当作字符串传输

Router 与 ChannelAdapter 以 `text` 为中心，导致工具和交互事件先序列化成 JSON 字符串，再包进 `{ text }`。这使校验、版本兼容和客户端类型定义都很困难。

### 3.4 会话归属由客户端补充

大多数服务端事件自身不携带 `session_id`。Electron 主进程使用连接当前会话补充它；会话切换、重连或未来并发时存在错误归属风险。

### 3.5 中断是 Agent 全局的

`chat.abort` 的参数包含 `session_id`，但实际调用的是 Agent 全局 `living.abort_chat()`。当前 Agent 同时只允许一轮聊天，因此暂时可用，但协议语义并不精确。

### 3.6 拒绝原因丢失

Gateway 入站层能区分 `BUSY/THROTTLED/EMPTY/HANDLED`，`chat.send` 却只返回 `accepted: false`，Desktop 无法给出准确反馈。

### 3.7 重连只恢复连接，不恢复工作现场

历史消息可以重新读取，但正在流式生成的文本、运行中的工具和待回答交互没有统一快照接口。

### 3.8 多连接模型尚不完整

- 一个 `session_id` 当前只能映射到一个 WebSocket 连接；
- `user_id` 和部分会话状态会写入 Agent/Living 的可变全局字段；
- 当前 busy guard 避免了真正并发，但也掩盖了会话隔离问题。

### 3.9 Hermes 对照结论

Hermes 已验证以下交互模型可以同时支撑 TUI、Desktop、多个活动会话和断线恢复：

- JSON-RPC 请求响应与统一 `method: "event"` 事件通道；
- 事件使用 `type + session_id + payload` 表达类型、归属和载荷；
- 使用 `message.start/delta/complete` 构成确定的输出生命周期；
- 工具事件携带稳定 `tool_id` 和结构化载荷；
- Clarify、Approval 等阻塞交互通过请求 ID 恢复原执行过程；
- 重连后重新 resume 会话，并用持久历史、运行状态和 inflight 快照恢复现场。

小美采用上述经过验证的协议骨架，但保留自己的边界：Gateway 不负责管理尚未运行的 Agent；不同类型的人机请求继续统一表达为 `interaction.*`；对外只暴露稳定的持久 `session_id`，不复制 Hermes 的持久会话 ID 与运行时会话 ID 双重映射。

## 4. 稳定协议的标识模型

稳定协议首先建立以下关系，不引入 `task_id`：

```text
agent_id
  └─ session_id
       └─ turn_id
            ├─ message_id
            ├─ tool_call_id
            └─ interaction_id
```

- `agent_id`：事件来自哪个独立 Agent；
- `session_id`：持久对话边界；
- `turn_id`：一次用户输入及其完整响应过程；
- `message_id`：持久化消息 ID；
- `tool_call_id`：工具调用稳定 ID，不能只使用本轮数组下标；
- `interaction_id`：需要用户回答的结构化交互 ID；
- `client_request_id`：由客户端生成，用于 `chat.send` 重试去重。

## 5. 建议协议版本

旧格式已经声明 `protocol_version: 1`，新的稳定格式命名为 Gateway Protocol V2：

- V2 只保留一套规范字段，不在同一事件中夹带 V1 的 `event/data`；
- Desktop、TUI 和 CLI 客户端随仓库同步升级；
- `connect` 返回 `protocol_version: 2` 和 capabilities；
- 项目尚处 0.1 开发期，不承担旧客户端与新 Agent 混用的兼容成本。

示意：

```json
{
  "jsonrpc": "2.0",
  "id": "connect-1",
  "method": "connect",
  "params": {
    "token": "...",
    "client": { "name": "desktop", "version": "0.1.0" },
    "protocol_version": 2,
    "user_id": "libai"
  }
}
```

稳定形态中 `connect` 只建立与某个 Agent 的认证连接，会话由后续 RPC 显式指定。这样切换会话不再需要断开 WebSocket。

成功响应至少包含：

```json
{
  "protocol_version": 2,
  "agent": { "id": "xiaomei", "name": "小美" },
  "connection_id": "connection-...",
  "capabilities": [
    "message.lifecycle",
    "tool.lifecycle",
    "interaction.question",
    "session.resume"
  ]
}
```

`capabilities` 表示当前 Agent 实际支持什么，Desktop 不再仅凭版本号猜测功能。

## 6. V2 事件封装

V2 保留已经被小美和 Hermes 共同验证的统一事件通道：JSON-RPC notification 的 `method` 固定为 `event`，具体事件类型放在 `params.type`。这让客户端只需要一个协议入口，并能对未知事件自然前向兼容。

```json
{
  "jsonrpc": "2.0",
  "method": "event",
  "params": {
    "type": "message.delta",
    "session_id": "session-123",
    "turn_id": "turn-456",
    "payload": { "text": "你好" }
  }
}
```

公共字段的意义：

- `type`：稳定的事件类型；
- `session_id`：事件所属的持久会话；所有会话级事件必填；
- `turn_id`：事件所属轮次；消息、工具和交互事件必填；
- `payload`：按事件类型校验的结构化载荷。

`agent_id` 不需要在每个事件中重复，因为一条 WebSocket 只连接一个独立 Agent，Desktop 已经知道该连接的归属。第一阶段也不引入 `stream_id/sequence/event_id` 和事件回放日志；断线恢复使用服务端权威快照。若以后真实出现跨连接合流、漏事件诊断或事件订阅需求，再增加可选事件元数据。

## 7. 对话生命周期

一轮普通对话应形成确定状态机：

```text
chat.send
  → accepted
  → message.start
  → message.delta *
  → tool.start / tool.complete *
  → interaction.requested / interaction.updated *
  → message.complete(status = complete | interrupted | error)
```

Turn 状态：

```text
accepted → running ⇄ waiting_user
                   ├→ complete
                   ├→ interrupted
                   └→ error
```

### 7.1 `chat.send`

请求：

```json
{
  "session_id": "session-123",
  "content": "帮我分析这段代码",
  "user_id": "libai",
  "client_request_id": "desktop-uuid"
}
```

成功响应：

```json
{
  "accepted": true,
  "turn_id": "turn-456",
  "session_id": "session-123",
  "status": "accepted"
}
```

Agent 正忙时返回稳定 JSON-RPC 错误，而不是只有 `accepted: false`：

```json
{
  "code": -32010,
  "message": "Agent is busy",
  "data": { "reason": "AGENT_BUSY", "active_turn_id": "turn-..." }
}
```

### 7.2 Message 事件

- `message.start`：Agent 开始产生本轮输出；
- `message.delta`：本轮新增的一段文本；
- `message.complete`：本轮唯一终态，携带最终 `message_id`、最终内容和 `status`；
- 独立 `error` 事件只表示连接、协议或无法归入已接受 Turn 的内部错误，不代替 Turn 终态。

`message.complete.status` 为 `complete | interrupted | error`。失败时 `payload.error` 携带稳定错误码和适合展示的消息；即使最终文本为空也必须发送该事件。

无论最终文本是否为空，每个已接受的 Turn 都必须且只能收到一个终态事件。

### 7.3 `session.interrupt`

请求必须指定：

```json
{
  "session_id": "session-123",
  "turn_id": "turn-456"
}
```

服务端验证当前活动 Turn 的归属。重复中断应当幂等；成功响应只表示中断请求被接受，最终状态由 `message.complete(status = "interrupted")` 确认。

## 8. 工具生命周期

工具事件全部绑定 `turn_id` 和稳定的 `tool_call_id`：

- `tool.start`
- `tool.complete`

载荷直接是结构化对象：

```json
{
  "tool_call_id": "tool-...",
  "name": "webget",
  "arguments": { "url": "https://example.com" },
  "started_at": 1784650000000
}
```

`tool.complete` 无论成功或失败都必须闭合对应的 `tool.start`，结果应区分：

- 给用户展示的 `summary`；
- 可选的结构化 `result`；
- 是否截断 `truncated`；
- 失败时稳定的 `error`；没有错误表示正常完成。

协议层不应默认把完整、可能很大的工具结果推给 Desktop。

## 9. 结构化交互生命周期

保留现有命名：

- `interaction.requested`
- `interaction.updated`
- RPC `interaction.respond`

在现有字段上补充：

- `turn_id`；
- `kind`；
- `authority`；
- `expires_at`；
- 可选的输入约束；
- 稳定终态 `answered/cancelled/expired`。

`interaction.respond` 必须同时验证连接身份、`session_id`、`turn_id` 和 `interaction_id`。交互回答不是一条新的聊天消息，而是恢复原 Turn。

## 10. 会话恢复与切换

新增 `session.resume` RPC。它既用于打开历史会话，也用于 WebSocket 重连后恢复现场，返回最近一段持久历史、分页游标、当前状态和 inflight 权威快照：

```json
{
  "session_id": "session-123",
  "messages": [],
  "history_cursor": "message-321",
  "status": "waiting",
  "inflight": {
    "turn_id": "turn-456",
    "user": "帮我分析这段代码",
    "assistant": "已经完成第一步……",
    "streaming": true,
    "started_at": 1784650000000
  },
  "active_tools": [],
  "pending_interactions": [
    { "id": "interaction-...", "kind": "question", "status": "pending" }
  ]
}
```

Desktop 重连顺序：

1. WebSocket 建立；
2. `connect` 认证并协商协议；
3. 对当前打开的会话调用 `session.resume`；
4. 使用响应中的持久消息、inflight 和待交互项替换或合并本地状态；
5. 合并时以服务端 ID 去重，不依赖文本相等判断。

如果 Agent 进程已经重启，服务端返回的 inflight 为空；客户端放弃本地旧流式现场，以持久历史和新的会话快照为准。

同一条 Agent WebSocket 可以承载多个 `session_id`。所有对话 RPC 显式携带 `session_id`，所有会话事件由服务端携带真实 `session_id`。Desktop 切换会话只改变当前展示，不再重建连接。第一阶段仍可保持一个 Agent 同时只执行一个 Turn，但协议和路由不能依赖“连接当前会话”推断归属。

## 11. 历史消息规范化

`chat.history` 的每个元素至少包含：

```json
{
  "message_id": "message-321",
  "session_id": "session-123",
  "turn_id": "turn-456",
  "role": "assistant",
  "type": "text",
  "content": "最终回答",
  "created_at": 1784650000000
}
```

结构化交互可以继续作为时间线记录返回，但必须使用相同的公共字段和 `type: "interaction"`，避免 Desktop 根据数据库 `role` 猜测类型。

工具过程第一阶段不要求写入聊天历史；以后如需恢复完整工作过程，应设计独立的 Turn 事件记录，而不是把工具结果伪装成聊天消息。

## 12. 服务端内部改造方向

当前 `Router.deliver(text, msg_type)` 是文本优先接口。稳定协议需要引入结构化出站模型，例如：

```text
Agent / ConversationDriver
  → OutboundEvent
  → Router.deliver_event()
  → ChannelAdapter.send_event()
```

其中：

- WebSocket Adapter 保留完整结构，编码为协议事件；
- CLI/TUI Adapter 可以渲染成文字或卡片；
- 飞书等不支持完整过程的渠道可以只展示必要摘要；
- 旧 `send(text)` 在迁移期保留作为兼容入口。

这样 Gateway 不再从字符串中反向猜测 Agent 发生了什么。

## 13. 实施顺序

### 阶段 A：协议骨架与正常闭环

1. 定义 V2 Pydantic 事件模型和公共 envelope；
2. `connect` 增加版本协商和 capabilities；
3. 为 `LivingMessage` 和对话执行链增加 `turn_id`；
4. 发出 `message.start/delta/complete`，保证每个已接受 Turn 恰好一个终态；
5. 让 Desktop 按 `agent_id + session_id + turn_id` 管理流式状态；
6. 同步升级 Desktop、TUI 和 CLI Gateway 客户端。

### 阶段 B：工具与交互结构化

1. 工具调用使用稳定 ID；
2. 移除 `data.text` 中的二次 JSON；
3. Desktop 展示简洁的工具状态；
4. Interaction 绑定 Turn 并可从快照恢复。

### 阶段 C：重连恢复

1. 增加活动 Turn registry；
2. 实现 `session.resume` 的历史、inflight 和待交互快照；
3. Desktop 在 WebSocket 重连后自动 resume 当前会话；
4. 覆盖断线、Agent 重启和重复请求测试；事件序号与回放按实际需要后置。

### 阶段 D：扩展能力

按实际产品需要再增加附件、产出物、Agent 主动消息和 Goal 状态；不提前引入任务管理界面或管理模式。

## 14. 验收原则

- 每个成功接受的 Turn 恰好有一个终态；
- 任一事件都能结合其 WebSocket 连接和自身字段确定 Agent、会话和 Turn 归属；
- 结构化事件不需要客户端再次 `JSON.parse(data.text)`；
- Desktop 切换 Agent 或会话不会串流；
- 断线后能恢复“正在响应、等待用户或已结束”的真实状态；
- 同一个 `client_request_id` 重试不会执行两次；
- CLI、Desktop 与其他渠道消费同一语义事件，而不是各自猜测执行状态。
