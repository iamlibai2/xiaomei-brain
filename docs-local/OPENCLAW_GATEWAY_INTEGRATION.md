# xiaomei-brain Gateway 架构设计

**文档更新时间**：2026-04-16 (北京时间)

## 目标

xiaomei-brain 作为独立项目，实现自己的 Gateway，提供与 OpenClaw Gateway 兼容的 WebSocket 协议和 HTTP API。
这样统一的管理后台可以通过切换 URL（ws:// 或 http://）来同时管理 OpenClaw 和 xiaomei-brain 两个独立的系统。

**核心原则**：
- xiaomei-brain 完全独立，不依赖 OpenClaw Gateway
- 实现兼容协议，让管理后台可以通用
- 只需更换 Gateway URL 即可切换管理目标

---

## 架构概览

```
┌─────────────────────────────────────────────────────────────────────┐
│                    统一管理后台 (Control UI)                        │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────┐    │
│  │  Config Manager  Skills Manager  Session Manager           │    │
│  └────────────────────────────────────────────────────────────┘    │
│                    │                                    │            │
│                    ▼                                    ▼            │
│         ┌──────────────────┐                    ┌──────────────────┐  │
│         │  OpenClaw        │                    │  xiaomei-brain   │  │
│         │  Gateway         │                    │  Gateway         │  │
│         │  (ws://...)      │                    │  (ws://...)      │  │
│         └────────┬─────────┘                    └────────┬─────────┘  │
│                  │                                      │             │
│                  ▼                                      ▼             │
│         ┌──────────────────┐                    ┌──────────────────┐  │
│         │  OpenClaw        │                    │  xiaomei-brain   │  │
│         │  Agents/Skills   │                    │  Agents/Channels │  │
│         └──────────────────┘                    └──────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 用户需求确认

用户明确说明：
1. xiaomei-brain 不通过 OpenClaw 的 Gateway，xiaomei 有自己的 Gateway，完全独立
2. 不依赖 OpenClaw Gateway
3. 管理后台（Control-UI）是另一个项目，目的是通过 Gateway 而不是配置文件对 OpenClaw 进行管理
4. xiaomei-brain 需要和 OpenClaw 提供一样的 Gateway 服务，这样同一个管理后台可以同时管理两个系统

---

## OpenClaw WebUI 分析

### OpenClaw WebUI 使用两类接口

#### 1. WebSocket 协议 (gateway-ws.ts)

客户端使用 `GatewayBrowserClient` 类进行通信：

**消息格式**：
```json
// 请求
{"type": "req", "id": "...", "method": "...", "params": {...}}

// 响应
{"type": "res", "id": "...", "ok": true, "payload": {...}}
{"type": "res", "id": "...", "ok": false, "error": {"code": "...", "message": "..."}}

// 事件推送
{"type": "event", "event": "...", "payload": {...}, "seq": number}
```

**连接握手**：
- 使用 Ed25519 设备签名进行身份认证
- 发送 `connect` 方法，包含 `minProtocol`, `maxProtocol`, `client`, `role`, `scopes`, `auth`, `device` 等参数
- 服务器返回 `hello-ok` 确认连接

**核心方法**：
- `connect` - 连接握手
- `chat.start/delta/done` - 聊天流式事件

#### 2. HTTP REST API (index.ts)

前端通过 `/api` 前缀调用 HTTP API：

| 类别 | 端点 |
|------|------|
| 认证 | /auth/login, /auth/logout, /auth/me |
| Agent | /agents, /agents/:id/profile, /agents/:id/soul |
| 配置 | /config, /config-files |
| Channel | /channels, /channels/:name |
| Binding | /bindings, /bindings/default-agent |
| Gateway | /gateway/status, /gateway/restart |
| Skills | /skills, /skills/:slug |
| Sessions | /sessions/:agentId |
| Models | /models, /models/:id |

---

## xiaomei-brain 现有能力

### WebSocket 配置管理

通过 WebSocket JSON-RPC 格式实现配置操作：

```json
// 请求
{"method": "config.get", "params": {"path": ""}, "id": 1}

// 响应
{"jsonrpc": "2.0", "id": 1, "result": {"value": {...}, "hash": "abc"}}
```

### config_provider.py 功能

- `get(path)` - 按路径获取配置
- `apply(new_config, base_hash)` - 完整替换
- `patch(partial, base_hash)` - 部分更新（JSON Merge Patch）
- `hash` - 配置版本哈希
- `subscribe(handler)` - 订阅变更通知

### 现有实现位置

- `ws/server.py` - WebSocket server
- `ws/protocol.py` - 协议定义
- `config_provider.py` - 配置管理

---

## 协议格式对比

### OpenClaw 格式 vs xiaomei-brain 格式

| 方面 | OpenClaw | xiaomei-brain (改造前) |
|------|----------|------------------------|
| 请求 | `{"type": "req", "id": "...", "method": "...", "params": {...}}` | `{"method": "config.get", "params": {}, "id": 1}` |
| 响应 | `{"type": "res", "id": "...", "ok": true, "payload": {...}}` | `{"jsonrpc": "2.0", "id": 1, "result": {...}}` |
| 事件 | `{"type": "event", "event": "chat.delta", "payload": {...}}` | `{"type": "text_chunk", "content": "..."}` |
| 传输方式 | WebSocket | WebSocket |

---

## 改造后实现

### ws/protocol.py

支持 OpenClaw 协议格式：

```python
# 请求
{"type": "req", "id": "xxx", "method": "config.get", "params": {}}

# 响应
{"type": "res", "id": "xxx", "ok": true, "payload": {...}}
{"type": "res", "id": "xxx", "ok": false, "error": {"code": "...", "message": "..."}}

# 事件
{"type": "event", "event": "chat.delta", "payload": {...}, "seq": 1}
```

### ws/server.py

已实现的方法：

| 方法 | 说明 | 状态 |
|------|------|------|
| `config.get` | 获取配置 (含 hash) | ✅ 已实现 |
| `config.patch` | 部分更新 | ✅ 已实现 |
| `config.apply` | 应用完整配置 | ✅ 已实现 |
| `agents.list` | Agent 列表 | ✅ 已实现 |
| `agents.get` | 获取单个 Agent | ✅ 已实现 |
| `chat.start` | 开始聊天 + 流式事件 | ✅ 已实现 |
| `sessions.list` | 会话列表 | ✅ 已实现 |
| `sessions.get` | 获取会话 | ✅ 已实现 |
| `ping` | 心跳检测 | ✅ 已实现 |

---

## OpenClaw 完整方法列表

### Base Methods (server-methods-list.ts)

```
health
doctor.memory.status
logs.tail
channels.status
channels.logout
status
usage.status
usage.cost
tts.status
tts.providers
tts.enable
tts.disable
tts.convert
tts.setProvider
config.get
config.set
config.apply
config.patch
config.schema
config.schema.lookup
exec.approvals.get
exec.approvals.set
exec.approvals.node.get
exec.approvals.node.set
exec.approval.request
exec.approval.waitDecision
exec.approval.resolve
wizard.start
wizard.next
wizard.cancel
wizard.status
talk.config
talk.speak
talk.mode
models.list
tools.catalog
tools.effective
agents.list
agents.create
agents.update
agents.delete
agents.files.list
agents.files.get
agents.files.set
skills.status
skills.bins
skills.install
skills.update
update.run
voicewake.get
voicewake.set
secrets.reload
secrets.resolve
sessions.list
sessions.subscribe
sessions.unsubscribe
sessions.messages.subscribe
sessions.messages.unsubscribe
sessions.preview
sessions.create
sessions.send
sessions.abort
sessions.patch
sessions.reset
sessions.delete
sessions.compact
last-heartbeat
set-heartbeats
wake
node.pair.request
node.pair.list
node.pair.approve
node.pair.reject
node.pair.verify
device.pair.list
device.pair.approve
device.pair.reject
device.pair.remove
device.token.rotate
device.token.revoke
node.rename
node.list
node.describe
node.pending.drain
node.pending.enqueue
node.invoke
node.pending.pull
node.pending.ack
node.invoke.result
node.event
node.canvas.capability.refresh
cron.list
cron.status
cron.add
cron.update
cron.remove
cron.run
cron.runs
gateway.identity.get
system-presence
system-event
send
agent
agent.identity.get
agent.wait
browser.request
chat.history
chat.abort
chat.send
```

### Gateway Events

```
connect.challenge
agent
chat
session.message
session.tool
sessions.changed
presence
tick
talk.mode
shutdown
health
heartbeat
cron
node.pair.requested
node.pair.resolved
node.invoke.request
device.pair.requested
device.pair.resolved
voicewake.changed
exec.approval.requested
exec.approval.resolved
update.available
```

---

## 待实现功能对比

### 已实现 (xiaomei-brain)

| 方法 | 说明 |
|------|------|
| config.get | 获取配置 |
| config.patch | 部分更新 |
| config.apply | 应用配置 |
| agents.list | Agent 列表 |
| agents.get | 获取 Agent |
| sessions.list | 会话列表 |
| sessions.get | 获取会话 |
| chat.start | 开始聊天 + 流式事件 |
| ping | 心跳 |

### 尚未实现 (OpenClaw 有)

| 方法 | 说明 | 优先级 |
|------|------|--------|
| config.schema | 获取配置 schema | P1 |
| config.set | 设置配置值 | P1 |
| agents.create | 创建 Agent | P2 |
| agents.update | 更新 Agent | P2 |
| agents.delete | 删除 Agent | P2 |
| agents.files.list | Agent 文件列表 | P3 |
| agents.files.get | 获取 Agent 文件 | P3 |
| agents.files.set | 设置 Agent 文件 | P3 |
| skills.status | Skills 状态 | P2 |
| skills.bins | Skills 依赖 | P3 |
| skills.install | 安装 Skill | P3 |
| skills.update | 更新 Skill | P3 |
| tools.catalog | 工具目录 | P2 |
| tools.effective | 有效工具列表 | P2 |
| channels.status | Channel 状态 | P2 |
| channels.logout | Channel 登出 | P3 |
| sessions.subscribe | 订阅会话变更 | P2 |
| sessions.unsubscribe | 取消订阅 | P3 |
| sessions.messages.subscribe | 订阅消息 | P2 |
| sessions.messages.unsubscribe | 取消订阅消息 | P3 |
| sessions.preview | 预览会话 | P3 |
| sessions.create | 创建会话 | P2 |
| sessions.send | 发送消息 | P1 |
| sessions.abort | 中止会话 | P1 |
| sessions.patch | 修改会话 | P2 |
| sessions.reset | 重置会话 | P2 |
| sessions.delete | 删除会话 | P2 |
| sessions.compact | 压缩会话 | P2 |
| exec.approvals.* | 执行审批相关 | P3 |
| models.list | 模型列表 | P2 |
| tts.status | TTS 状态 | P3 |
| tts.providers | TTS 提供商 | P3 |
| tts.enable | 启用 TTS | P3 |
| tts.disable | 禁用 TTS | P3 |
| tts.convert | TTS 转换 | P3 |
| tts.setProvider | 设置 TTS 提供商 | P3 |
| logs.tail | 日志尾巴 | P3 |
| health | 健康检查 | P1 |
| doctor.memory.status | 内存状态诊断 | P3 |
| chat.abort | 中止聊天 | P1 |
| chat.send | 发送聊天消息 | P1 |
| chat.history | 聊天历史 | P2 |

### 优先级建议

**P1 (必须)**：
- health - 健康检查
- chat.abort - 中止聊天
- chat.send - 发送聊天消息
- sessions.send - 发送消息
- sessions.abort - 中止会话

**P2 (核心)**：
- config.schema - 获取配置 schema
- agents.create - 创建 Agent
- agents.update - 更新 Agent
- agents.delete - 删除 Agent
- tools.catalog - 工具目录
- tools.effective - 有效工具列表
- skills.status - Skills 状态
- channels.status - Channel 状态
- sessions.subscribe - 订阅会话变更
- sessions.messages.subscribe - 订阅消息
- sessions.patch - 修改会话
- sessions.reset - 重置会话
- sessions.delete - 删除会话
- sessions.compact - 压缩会话
- models.list - 模型列表

**P3 (可选)**：
- agents.files.* - Agent 文件管理
- skills.bins - Skills 依赖
- skills.install - 安装 Skill
- skills.update - 更新 Skill
- channels.logout - Channel 登出
- sessions.preview - 预览会话
- sessions.unsubscribe - 取消订阅
- sessions.messages.unsubscribe - 取消订阅消息
- exec.approvals.* - 执行审批
- tts.* - TTS 相关
- logs.tail - 日志尾巴
- doctor.memory.status - 内存状态诊断
- chat.history - 聊天历史

---

## 文件结构

```
src/xiaomei_brain/
├── ws/
│   ├── __init__.py
│   ├── server.py              # WebSocket server (已改造支持 OpenClaw 协议)
│   ├── protocol.py            # 协议定义 (已改造)
│   ├── connection.py         # 连接管理
│   └── session.py             # 会话管理
├── config_provider.py          # 配置管理 (已有)
└── ...
```

---

## 启动方式

```bash
# 启动 Gateway 服务
PYTHONPATH=src python3 -m xiaomei_brain.ws.server

# 带配置启动
PYTHONPATH=src python3 -m xiaomei_brain.ws.server --config config/gateway.json
```

---

## 测试方式

```bash
# 启动服务后，使用 WebSocket 客户端测试

# OpenClaw 协议测试
# 发送:
{"type": "req", "id": "1", "method": "config.get", "params": {}}

# 预期响应:
{"type": "res", "id": "1", "ok": true, "payload": {"config": {...}, "hash": "..."}}
```

---

## 与 OpenClaw 的差异

| 功能 | OpenClaw | xiaomei-brain |
|------|----------|---------------|
| 架构 | 插件系统 | 内置 Channels |
| 模型支持 | 多 Provider | 内置 Agent |
| 工具系统 | 插件注册 | 工具注册表 |
| 配置 | JSON5 文件 | JSON 文件 |
| 协议 | WebSocket | WebSocket (兼容) |
| HTTP API | 有 | 无 (通过 WebSocket) |
