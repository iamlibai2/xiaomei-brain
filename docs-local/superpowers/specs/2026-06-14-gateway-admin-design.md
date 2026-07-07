# Gateway 加固 + Admin 管理门 设计

## 1. 架构概览

### 核心理念：两扇门，不同锁

Agent 是独立的意识体。与其交互有两个完全不同层面的操作：

| | 对话 | 管理配置 |
|---|---|---|
| **类比** | 跟一个人说话 | 进入他的大脑做手术 |
| **安全级别** | 低，内网可免认证 | 高，强制认证 |
| **认证** | 简单 token（可选） | Bearer token（必须） |
| **权限** | 人人可聊 | 仅 owner |

架构上物理隔离：

```
                     ┌─────────────────────────────┐
  对话 (人人可聊)  ─→│  gateway/  (FastAPI)         │
                     │  /ws         WebSocket RPC  │
  P2P (Agent 间)  ──→│  /message     HTTP P2P      │
                     │  auth: token，可配 none模式  │
                     └─────────────────────────────┘

                     ┌─────────────────────────────┐
  管理 (仅 owner)  ─→│  admin/    (FastAPI, 新端口) │
                     │  /api/config                 │
                     │  /api/agents                 │
                     │  /api/status                 │
                     │  /api/sessions               │
                     │  auth: Bearer token，强制    │
                     └─────────────────────────────┘
```

- `gateway/` = 意识体的沟通界面，对话、聊天、Agent 间通信
- `admin/` = 运维者的管理界面，配置、状态、agent 管理
- 两者物理隔离（不同端口），认证独立

### 为什么分开

1. **安全模型不同**：对话可以宽容，管理必须严格
2. **职责不同**：对话是意识体自身的行为，管理是运维者对系统的操作
3. **复杂度隔离**：对话协议保持简单，管理 API 复杂度不污染 gateway

---

## 2. Gateway 对话门加固

### 2.1 协议对齐

当前 `protocol.py` 定义了 `req/res/event` 类型，但 `server.py` 的 `/ws` 端点没有走这套协议，而是用自己拼的 `{type:"chat", content:"..."}` 格式。

改动：`/ws` 端点只接受 `req/res/event` 协议，旧的 `chat` 格式删除。

**消息流程**：

```
客户端                          网关
  │                              │
  │── {type:"req", method:"connect", params:{token, client:"webchat-ui"}}
  │                              │── {type:"res", id:1, ok:true, payload:{session_id,...}}
  │                              │
  │── {type:"req", method:"chat.send", params:{content:"你好"}}
  │                              │── {type:"event", event:"chat.chunk", payload:{text:"你好"}}
  │                              │── {type:"event", event:"chat.chunk", payload:{text:"呀"}}
  │                              │── {type:"res", id:2, ok:true, payload:{done:true}}
  │                              │
  │── {type:"ping"}              │
  │                              │── {type:"pong"}
```

**旧格式清理**：现有的 `chat`、`session_start` 等字典格式全部删除。ws_cli 同步改为新协议。

**协议版本**：`PROTOCOL_VERSION = 1`，`connect` 响应中返回。

### 2.2 认证

- `connect` 方法的 params 携带 `token`
- 配置项 `gateway.token`，写在 agent 的 `config.yaml` 中
- 模式：`token`（需要）| `none`（开发环境）
- Control UI 连接时从用户输入获取 token
- P2P 通信共用同一 token

### 2.3 错误体系

所有错误统一用 `error_shape(code, message)` 格式，响应在 `res` 帧的 `error` 字段中：

```json
{
  "type": "res",
  "id": 1,
  "ok": false,
  "error": {
    "code": "UNAUTHORIZED",
    "message": "Token 无效"
  }
}
```

错误码定义：

| 错误码 | 含义 |
|---|---|
| `INVALID_REQUEST` | 消息格式错误 |
| `UNAUTHORIZED` | 认证失败 |
| `GATEWAY_NOT_READY` | 网关未就绪 |
| `INTERNAL_ERROR` | 内部错误 |
| `PARSE_ERROR` | JSON 解析失败 |
| `EMPTY_MESSAGE` | 空消息 |

### 2.4 连接健康

- 客户端发 `{type: "ping"}`，服务端回 `{type: "pong"}`
- 30 秒无消息 → 断开连接
- 断开后客户端自动重连

### 2.5 不改动的部分

- `comms_server.py`（P2P 消息服务）保留不动，用户后续再考虑
- `CLIAdapter` 保留，作为 Router 的 fallback

---

## 3. Admin 管理门

### 3.1 定位

独立端口 + 独立认证。跟对话门物理隔离。

### 3.2 API 端点

```
GET  /api/status               → 系统状态（运行时间、agent 状态、drive 数值）
GET  /api/config               → 读完整配置
PATCH /api/config               → 改部分配置
GET  /api/agents               → 列出所有 agent
GET  /api/agents/{agent_id}    → 单个 agent 详情
POST /api/agents               → 创建 agent
GET  /api/sessions             → 会话列表
```

### 3.3 认证

```
Authorization: Bearer <admin_token>
```

- 配置项 `admin.token`，独立于 gateway 的 token
- 没有 `none` 模式，管理接口强制认证
- token 不匹配 → 401

### 3.4 目录结构

```
src/xiaomei_brain/admin/
├── __init__.py
├── server.py          # 独立 FastAPI app + uvicorn 启动
├── auth.py            # Bearer token 校验
├── routes/
│   ├── __init__.py
│   ├── config.py      # GET/PATCH /api/config
│   ├── status.py      # GET /api/status
│   ├── agents.py      # GET/POST /api/agents
│   └── sessions.py    # GET /api/sessions
```

### 3.5 启动

```python
# conscious_living.py 中
create_app(router, living, tts, agent_manager, config)       # gateway 对话门
create_admin_app(living, agent_manager, config)               # admin 管理门
```

两个 uvicorn，两个线程，两个端口。

---

## 4. 改动文件一览

### 新增文件

| 文件 | 说明 |
|---|---|
| `gateway/auth.py` | WebSocket connect 认证 |
| `gateway/schemas.py` | Pydantic 消息 schema |
| `gateway/server_methods.py` | RPC method handler |
| `admin/server.py` | 管理门 FastAPI app |
| `admin/auth.py` | Bearer token 校验 |
| `admin/routes/__init__.py` | 路由注册 |
| `admin/routes/config.py` | 配置读/改 |
| `admin/routes/status.py` | 系统状态 |
| `admin/routes/agents.py` | Agent 管理 |
| `admin/routes/sessions.py` | 会话列表 |

### 修改文件

| 文件 | 改动 |
|---|---|
| `gateway/protocol.py` | 错误码扩展，加 PROTOCOL_VERSION |
| `gateway/server.py` | WS 端点改为纯 req/res/event，加认证，加 ping/pong 超时 |
| `gateway/ws_adapter.py` | 输出消息改为 event 格式 |
| `gateway/protocol.py` | 删旧格式，只保留 req/res/event + error_shape |
| `examples/ws_cli.py` | 改为新协议 |
| `consciousness/conscious_living.py` | 启动 admin server |

### 不改动文件

| 文件 | 原因 |
|---|---|
| `gateway/comms_server.py` | 用户保留 |
| `channels/p2p/` | 不变 |
| `gateway/router.py` | 不变 |

---

## 5. 验证

1. 启动 agent，gateway /ws 和 admin 端口同时可用
2. ws_cli 走新协议（req/res/event）发消息正常
3. Control UI 走 req/res/event 协议正常
4. admin API 无 token 返回 401，正确 token 返回数据
5. ping/pong 超时断开测试
