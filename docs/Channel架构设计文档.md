# Channel 架构设计文档

**作者**：xiaomei-brain 开发组
**日期**：2026-04-14
**状态**：技术讨论汇总

---

## 1. OpenClaw Channel 架构分析

### 1.1 Channel 本质

Channel 是 OpenClaw 的**平台适配器层**，连接各个消息平台（飞书、钉钉、Slack、Telegram 等）和 Agent。

每个 Channel 通过 `createChatChannelPlugin()` 构建，包含多个 Adapter：

| Adapter | 职责 |
|---------|------|
| `config` | 账号配置解析 |
| `security` | DM 策略、allowlist、配对验证 |
| `messaging` | 消息路由、目标解析 |
| `outbound` | 发送文本/媒体到平台 |
| `gateway` | 账号启动/停止（监听 Webhook/Polling） |
| `actions` | 消息操作（发送、编辑、反应） |
| `directory` | 用户/群列表 |

### 1.2 消息流程

```
平台事件 → gateway监听 → 解析为统一格式 → 安全检查 → Agent处理 → outbound发送
```

### 1.3 ChannelPlugin 接口（简化版）

```typescript
type ChannelPlugin<TResolvedAccount> = {
  id: ChannelId;
  meta: ChannelMeta;
  capabilities: ChannelCapabilities;
  config: ChannelConfigAdapter<ResolvedAccount>;
  setup: ChannelSetupAdapter;
  messaging?: ChannelMessagingAdapter;
  outbound?: ChannelOutboundAdapter;
  gateway?: ChannelGatewayAdapter<ResolvedAccount>;
  status?: ChannelStatusAdapter<ResolvedAccount, Probe, Audit>;
  lifecycle?: ChannelLifecycleAdapter;
  // ...
};
```

### 1.4 为什么 Channel 复杂（Complexity 8/10）

1. **30+ 可选 Adapter**：每个平台能力不同，接口庞大
2. **多账号隔离**：每个 Channel 支持多账号，每个账号独立状态
3. **安全模型**：DM allowlist、配对验证码、group 策略
4. **线程模型**：每个平台线程模型不同（Slack 用 thread_ts，飞书用 group_topic）
5. **API 多样性**：认证、消息格式、限流各有不同

### 1.5 OpenClaw 架构评价

- **价值**：设计思想（Adapter 组合、安全模型、生命周期管理）值得借鉴
- **局限**：Node.js/TypeScript 实现，xiaomei-brain 是 Python
- **建议**：参考其思想，但按 Python 风格简化实现

---

## 2. 路线 A vs 路线 B 对比

### 路线 A：各自独立适配器（简单直接）

```
飞书适配器  →  统一 InboundMsg  →  Agent  →  统一 OutboundMsg  →  飞书适配器
钉钉适配器  ↗                              ↖  钉钉适配器
微信适配器  ↗                              ↖  微信适配器
```

每个平台 adapter 独立编写，互相不感知。

```python
# 飞书适配器
class FeishuAdapter:
    def __init__(self, agent: Agent):
        self.agent = agent

    async def handle_feishu_webhook(self, payload: dict) -> dict:
        msg = InboundMsg(
            platform="feishu",
            sender=payload["sender"]["sender_id"]["open_id"],
            text=payload["message"]["content"],
            conversation_id=payload["message"]["chat_id"],
        )
        reply = await self.agent.stream(msg.text)
        return feishu_format_reply(reply)

# 钉钉适配器
class DingtalkAdapter:
    def __init__(self, agent: Agent):
        self.agent = agent

    async def handle_dingtalk_webhook(self, payload: dict) -> dict:
        msg = InboundMsg(
            platform="dingtalk",
            sender=payload["senderStaffId"],
            text=payload["text"]["content"],
            conversation_id=payload["conversationId"],
        )
        reply = await self.agent.stream(msg.text)
        return dingtalk_format_reply(reply)
```

### 路线 B：统一 Channel 抽象

定义抽象接口，平台适配器必须实现。

```python
class Channel(ABC):
    @abstractmethod
    async def start(self, on_message: Callable[[InboundMsg], Awaitable[OutboundMsg]]) -> None:
        """启动监听（webhook / polling / websocket）"""
        pass

    @abstractmethod
    async def send(self, to: str, msg: OutboundMsg) -> None:
        """向指定会话发送消息"""
        pass

    @abstractmethod
    def verify(self, challenge: str) -> str:
        """URL 验证（部分平台 webhook 需要）"""
        pass
```

### 核心区别

| 对比维度 | 路线 A（独立适配器） | 路线 B（统一 Channel 接口） |
|---------|------------------|------------------------|
| **接口约束** | 无统一接口，各自为政 | 必须实现 `Channel` 抽象 |
| **代码复用** | 每个 adapter 自己解析/格式化 | `start/send/verify` 默认逻辑可复用 |
| **新增平台** | 直接写新 adapter 类 | 实现 `Channel` 接口 + 注册 |
| **测试** | 需针对每个 adapter 单独测 | 可用 mock Channel 统一测试 |
| **复杂度** | 低，适合 1-3 个平台 | 中等，需要接口设计 |
| **适合场景** | 平台少、不需要统一管理 | 多平台、需要统一生命周期管理 |

### 建议

- 接 2-3 个平台：路线 A 更简单
- 接 5+ 平台、需要统一启停管理：路线 B 更合适

---

## 3. Channel / Gateway / Agent 三者关系

### 3.1 核心架构图

```
┌─────────────────────────────────────────────────────────┐
│                    xiaomei-brain                         │
│                                                         │
│  ┌──────────┐   1. 启动监听    ┌──────────┐            │
│  │  Gateway  │ ───────────────→ │  Channel │            │
│  │ (账号级)  │                  │ (平台适配) │            │
│  └──────────┘                  └─────┬─────┘            │
│         │                            │                   │
│         │                      2. 接收消息               │
│         │                            ↓                   │
│         │                     ┌──────────┐              │
│         │                     │  Agent   │              │
│         │                     │ (AI大脑)  │              │
│         │                     └────┬─────┘              │
│         │                          │                    │
│         │                    3. 生成回复                  │
│         │                            │                   │
│         └────────────────────────────┘                   │
│                          4. 发送                         │
└─────────────────────────────────────────────────────────┘
```

### 3.2 各自职责

| 组件 | 职责 | 类比 |
|------|------|------|
| **Agent** | 接收文本，生成回复（ReAct 循环） | 大脑 |
| **Channel** | 平台协议解析、消息格式化、发送 | 翻译官/接口层 |
| **Gateway** | 管理 Channel 的生命周期（启动/停止/心跳） | 管理员/看门人 |

### 3.3 实际例子：飞书消息流程

```
用户发消息到飞书
       ↓
飞书服务器 → POST /feishu/webhook
       ↓
FeishuChannel.verify()  验证 URL
       ↓
FeishuChannel 解析消息 → InboundMsg
       ↓
FeishuGateway.on_message()  回调
       ↓
Agent.stream(text) → LLM → 工具调用 → 回复
       ↓
FeishuChannel.send(to, OutboundMsg)  格式化并发送
       ↓
飞书服务器 → 推送消息给用户
```

### 3.4 Channel 如何启动

Channel 的启动由 Gateway 触发，不是独立启动的：

```python
# 启动流程
gateway = FeishuGateway(
    channel=FeishuChannel(app_id="xxx", app_secret="yyy"),
    account_id="alice_001",
    agent=agent  # 绑定一个 Agent
)
await gateway.start()  # → channel.start() → 开始监听 webhook/polling
```

### 3.5 多账号场景

```
FeishuGateway(alice)   → FeishuChannel(app_id=alice)   → Agent(alice)
FeishuGateway(bob)     → FeishuChannel(app_id=bob)     → Agent(bob)  # 不同记忆

DingtalkGateway(tom)   → DingtalkChannel              → Agent(tom)
```

一个 Channel 类，多个 Gateway 实例，每个账号独立运行、隔离状态。

---

## 4. Gateway 功能清单

### 4.1 生命周期管理

```python
async def start() -> None:      # 启动 Channel，开始监听
async def stop() -> None:        # 优雅关闭，清理资源
async def restart() -> None:     # 异常后重启
```

### 4.2 Channel 绑定

```python
def bind_channel(channel: Channel):     # 挂载具体平台适配器
def unbind_channel():                    # 卸载
```

### 4.3 Agent 路由

```python
def bind_agent(agent: Agent):            # 绑定处理脑
async def route_message(msg: InboundMsg) -> OutboundMsg:  # 消息→Agent→回复
```

### 4.4 账号状态管理

```python
account_id: str                         # 账号唯一标识
status: AccountStatus                   # online / offline / error
last_heartbeat: float                   # 最后活跃时间
```

### 4.5 心跳与健康检查

```python
async def heartbeat():                   # 定期发心跳，维持连接（部分平台需要）
async def health_check() -> bool:        # 检测 Channel 是否存活
```

### 4.6 消息队列（缓冲）

```python
async def enqueue(msg: InboundMsg):      # 收到消息入队
async def dequeue() -> InboundMsg:       # 取消息处理
# 防止高并发冲垮 Agent，支持限流
```

### 4.7 错误重试

```python
async def retry_on_failure(func, max_retries=3):
    # Channel 发送失败 / Agent 调用超时时自动重试
```

### 4.8 平台事件分发

```python
def on_event(event_type: str, handler):  # 注册事件处理器
# 例：feishu.on_event("im.message.receive_v1", handler)
```

### 4.9 配置管理

```python
config: ChannelConfig                    # 账号级别配置（token刷新策略、限流阈值）
async def reload_config():               # 热更新配置
```

### 4.10 日志与审计

```python
def get_message_history(): list          # 账号的消息记录
def get_stats(): AccountStats            # 收发消息统计
```

---

## 5. Gateway 演化历史

### 5.1 早期：Gateway 独自承担所有功能

```
┌─────────────────────────────┐
│         Gateway              │
│                             │
│  - 解析平台协议（飞书/钉钉）  │
│  - 管理账号生命周期           │
│  - 连接 Agent                │
│  - 消息发送                  │
│  - 心跳/健康检查             │
│  - 错误重试                  │
└─────────────────────────────┘
```

**问题**：
- 飞书 Gateway 和钉钉 Gateway 代码 80% 相似
- 每接一个新平台要复制粘贴改大量代码
- 无法统一管理（启动 5 个平台要写 5 套不同的启动逻辑）

### 5.2 后来：Channel 抽象出现

把 **平台相关** 的代码抽成 `Channel`，Gateway 只负责通用的运维：

```
┌─────────────┐      ┌──────────────┐
│  Gateway    │ ───→ │   Channel    │
│  (通用逻辑)  │      │  (平台相关)   │
│             │      │              │
│ - 启停管理   │      │ - 协议解析   │
│ - 心跳      │      │ - 消息收发   │
│ - 重试      │      │ - 签名验证   │
│ - 限流      │      │ - 格式转换   │
│ - 路由 Agent │      │              │
└─────────────┘      └──────────────┘
```

### 5.3 对比：Gateway 改革前 vs 改革后

| 功能 | 改革前（Gateway独揽） | 改革后（Gateway + Channel） |
|------|---------------------|---------------------------|
| 解析飞书消息格式 | Gateway 内 | Channel |
| 解析钉钉消息格式 | Gateway 内 | Channel |
| 发送飞书消息 | Gateway 内 | Channel |
| 发送钉钉消息 | Gateway 内 | Channel |
| 飞书 URL 验证 | Gateway 内 | Channel |
| 钉钉 URL 验证 | Gateway 内 | Channel |
| 账号启停 | Gateway | Gateway |
| 心跳保活 | Gateway | Gateway |
| 错误重试 | Gateway | Gateway |
| Agent 路由 | Gateway | Gateway |
| 消息限流 | 无 | Gateway |
| 多账号隔离 | 无 | Gateway |

### 5.4 本质总结

**Channel = Gateway 里"平台相关"的那部分代码被抽离出来**

- Gateway 越来越薄，只做**跨平台通用的运维**
- Channel 越来越厚，承载**各平台特有的协议细节**

---

## 6. xiaomei-brain 实现建议

### 6.1 推荐架构

采用 **路线 B（统一 Channel 抽象）+ Gateway 分层**：

```python
# 统一消息格式
@dataclass
class InboundMsg:
    platform: str           # "feishu" / "dingtalk" / "wechat"
    sender: str             # 发送者 ID
    text: str               # 消息内容
    conversation_id: str    # 会话 ID

@dataclass
class OutboundMsg:
    text: str               # 回复内容
    media: list[str]        # 可选：媒体附件
    extra: dict             # 平台特定扩展

# Channel 抽象
class Channel(ABC):
    @abstractmethod
    async def start(self, on_message: Callable[[InboundMsg], Awaitable[OutboundMsg]]) -> None: ...

    @abstractmethod
    async def send(self, to: str, msg: OutboundMsg) -> None: ...

    @abstractmethod
    def verify(self, challenge: str) -> str: ...

# Gateway 通用层
class Gateway:
    def __init__(self, channel: Channel, agent: Agent, account_id: str):
        self.channel = channel
        self.agent = agent
        self.account_id = account_id

    async def start(self):
        await self.channel.start(self.on_message)

    async def on_message(self, inbound: InboundMsg) -> OutboundMsg:
        reply_text = await self.agent.stream(inbound.text)
        return OutboundMsg(text=reply_text)
```

### 6.2 与现有架构对接

现有 xiaomei-brain 多 Agent 架构：

```
AgentManager
  └── AgentInstance (id="xiaomei", memory独立, session独立)
        └── Agent (ReAct 循环)
```

Channel 层接入时：

```python
# 飞书账号 "xiaomei" 绑定到 AgentInstance("xiaomei")
gateway = FeishuGateway(
    channel=FeishuChannel(app_id="飞书应用ID"),
    agent=agent_manager.build_agent("xiaomei", config),
    account_id="xiaomei_feishu_01"
)
await gateway.start()
```

---

## 7. 待实现

- [ ] 定义 `InboundMsg` / `OutboundMsg` 统一数据结构
- [ ] 定义 `Channel` 抽象基类
- [ ] 实现 `FeishuChannel`（飞书平台适配器）
- [ ] 实现 `Gateway` 通用层
- [ ] 与现有 AgentManager 集成
- [ ] 多账号路由支持

---

*文档由对话记录自动汇总生成  |  2026-04-14*
