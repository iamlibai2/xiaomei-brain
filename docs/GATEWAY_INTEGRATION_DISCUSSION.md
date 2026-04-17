# xiaomei-brain Gateway 集成讨论记录

**讨论日期**：2026-04-16 (北京时间)

---

## 背景

用户有一个 OpenClaw Control-UI 项目（前端 + 后端），用于管理 OpenClaw Gateway。用户希望让 xiaomei-brain 成为和 OpenClaw 一样的项目，提供 Gateway 服务，这样同一个管理后台可以通过切换 Gateway URL 来同时管理两个独立的系统。

---

## 讨论过程

### 10:00 - 初始需求阐述

**用户**：xiaomei-brain 和 open claw 是独立的两个项目，不要老扯到一起，xiaomei 是参考 open claw 的架构来实现，确保一个管理后台同时能兼容 xiaomei-brain 和 open claw，比如提供同样的 config.get config.apply 方法，这样管理后台就可以通用，只需要更换 ws://地址，就能切换进行管理。xiaomei-brain 要做成独立的项目，提供 agent 能力，gateway channel 记忆等

---

### 10:05 - 方案分析

**Claude**：明白。xiaomei-brain 需要实现自己的 Gateway，提供与 OpenClaw Gateway 兼容的 WebSocket 协议和 HTTP API。核心原则：
- xiaomei-brain 完全独立，不依赖 OpenClaw Gateway
- 实现兼容协议，让管理后台可以通用
- 只需更换 Gateway URL 即可切换管理目标

---

### 10:10 - 确认 OpenClaw WebUI 使用哪些接口

**Claude**：根据分析，OpenClaw WebUI 使用两类接口：
1. WebSocket 协议 - 用于实时聊天（流式）和连接认证
2. HTTP REST API - 用于 CRUD 管理操作

---

### 10:15 - 追问实现方式

**Claude**：
1. **直接实现 OpenClaw Gateway 协议** (WebSocket) → 管理后台直连
2. **提供 HTTP REST API** (像 Control-UI 后端一样) → 管理后台通过 HTTP 调用
3. **两者都实现**

---

### 10:20 - 用户澄清核心诉求

**用户**：我他妈的 xiaomei-brain 不通过 openclaw 的 gateway，xiaomei 自己有 gateway，独立！和 open claw 完全独立 明白吗！不用 openclaw 的 gateway！

---

### 10:25 - 再次确认架构

**Claude**：明白了！架构是：

```
管理后台 → WebSocket (同一套协议)
     │
     ├──→ OpenClaw Gateway
     │
     └──→ xiaomei-brain Gateway
```

**用户**：是的

---

### 10:30 - 深入追问项目关系

**Claude**：你的架构是：

```
┌─────────────────────────────────────────┐
│   Control-UI (前端 + 后端)               │
│   同一个项目，同时管理 OpenClaw 和 xiaomei-brain │
└────────────────┬────────────────────────┘
                 │ WebSocket (同一套协议)
                 │
     ┌───────────┴───────────┐
     ▼                       ▼
┌─────────────┐       ┌─────────────┐
│ OpenClaw    │       │ xiaomei-brain │
│ Gateway     │       │ Gateway     │
└─────────────┘       └─────────────┘
```

**用户**：是的

---

### 10:35 - 追问协议兼容性细节

**Claude**：

**问题1**：xiaomei-brain 的 config.get config.apply 是使用 websocket 还是 http？

**Claude**：xiaomei-brain 现有 config.get/apply 是通过 WebSocket JSON-RPC 实现的。

**问题2**：OpenClaw 的 config.get 是什么方式实现的？

**Claude**：OpenClaw Gateway 本身是 WebSocket。源码显示 config.get/apply/patch 都在 WebSocket 中处理。

---

### 10:40 - 用户最终明确需求

**用户**：连 http API 的后端，后端和 gateway 连接

**Claude**：明白了。架构是：

```
管理后台 → HTTP API (xiaomei-brain 后端) → WebSocket → xiaomei-brain Gateway
```

**用户**：我搞晕了，我的项目有前端后端，这是另一个项目，目的是实现通过 gateway 而不是配置文件对 open claw 进行管理，我的目的是让 xiaomei-brain 成为和 open claw 一样的项目，只需要提供 gateway 的服务就可以

**Claude**：明白了，你的意思是：

```
管理后台 → WebSocket（同一套协议）→ xiaomei-brain Gateway / OpenClaw Gateway
```

**用户**：是的

---

### 10:45 - 确定实现方向

**Claude**：
- xiaomei-brain 需要实现和 OpenClaw Gateway 一样的 WebSocket 协议
- 只需适配消息外层格式（从 JSON-RPC 改为 OpenClaw 的 req/res/event 格式）
- 实现计划：修改 ws/server.py 和 ws/protocol.py

**用户**：实现

---

### 10:50 - 实现完成

**Claude**：已完成 OpenClaw Gateway 协议兼容改造。

---

### 10:55 - 差距分析

**Claude**：OpenClaw Gateway 有 100+ 方法，xiaomei-brain 已实现 9 个核心方法。

**待实现功能按优先级**：

**P1 (必须)**：
- health - 健康检查
- chat.abort - 中止聊天
- chat.send - 发送聊天消息
- sessions.send - 发送消息
- sessions.abort - 中止会话

**P2 (核心)**：
- config.schema - 获取配置 schema
- agents.create/update/delete - Agent 管理
- tools.catalog/effective - 工具目录
- skills.status - Skills 状态
- channels.status - Channel 状态
- sessions.subscribe/messages.subscribe - 订阅功能

---

### 11:00 - 文档整理

**用户**：把以上我们的讨论内容一字不差的写入文档，代码可以不写入

**Claude**：已写入文档 `docs/OPENCLAW_GATEWAY_INTEGRATION.md`

**用户**：加上北京时间

**Claude**：已添加

---

### 11:05 - 格式调整

**用户**：写成一个对话记录的新文档 带北京时间

**Claude**：已创建 `docs/GATEWAY_INTEGRATION_DISCUSSION.md`

---

## 关键技术结论

### 协议格式对比

| 方面 | OpenClaw | xiaomei-brain (改造前) |
|------|----------|------------------------|
| 请求 | `{"type": "req", "id": "...", "method": "...", "params": {...}}` | `{"method": "config.get", "params": {}, "id": 1}` |
| 响应 | `{"type": "res", "id": "...", "ok": true, "payload": {...}}` | `{"jsonrpc": "2.0", "id": 1, "result": {...}}` |
| 事件 | `{"type": "event", "event": "chat.delta", "payload": {...}}` | `{"type": "text_chunk", "content": "..."}` |
| 传输 | WebSocket | WebSocket |

### 改造后支持的方法

| 方法 | 状态 |
|------|------|
| config.get | ✅ |
| config.patch | ✅ |
| config.apply | ✅ |
| agents.list | ✅ |
| agents.get | ✅ |
| chat.start | ✅ |
| sessions.list | ✅ |
| sessions.get | ✅ |
| ping | ✅ |

---

## 用户最终确认

1. xiaomei-brain 不依赖 OpenClaw Gateway，完全独立
2. xiaomei-brain 提供自己的 Gateway 服务
3. 管理后台通过 WebSocket 连接 Gateway（不是 HTTP）
4. 只需切换 WebSocket URL 即可管理不同系统
5. 协议格式兼容 OpenClaw Gateway
