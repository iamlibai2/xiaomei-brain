# Channel 架构设计文档

## 架构概览

```
平台消息  →  Channel  →  Gateway  →  Agent
          (适配器层)    (统一管理)   (AI大脑)
```

## 统一 Gateway 管理

**核心设计**：所有平台共用一个 Gateway 实例

```python
# 创建 Gateway
gateway = Gateway()

# 添加所有平台的 Channel
gateway.add_channels([
    FeishuChannel(...),
    DingtalkChannel(...),
    WeChatChannel(...)
])

# 统一启动所有 Channel
await gateway.start_all()

# 统一停止
await gateway.stop_all()
```

### 优势

1. **统一监控**：所有 Channel 状态集中管理
2. **资源复用**：共享连接池、消息队列等
3. **简化管理**：一个入口管理所有平台
4. **错误处理统一**：所有平台的错误可以统一处理

## 按需实现策略

### 第一阶段：飞书验证

```python
# 先实现飞书，验证架构
feishu = FeishuChannel(app_id, app_secret, token)
gateway = Gateway()
gateway.add_channel(feishu)

await gateway.start_all()  # 验证架构
```

### 第二阶段：逐步扩展

```python
# 验证通过后，逐步添加其他平台
dingtalk = DingtalkChannel(...)
wechat = WeChatChannel(...)

gateway.add_channels([dingtalk, wechat])
```

## 详细设计

### 1. 消息数据结构

```python
@dataclass
class InboundMsg:
    platform: str        # 平台标识
    sender: str          # 发送者ID
    sender_name: str     # 发送者名称
    conversation_id: str # 会话ID
    text: str           # 消息内容
    timestamp: float    # 时间戳
    attachments: List[str]  # 附件
    extra: Dict[str, Any]  # 扩展数据

@dataclass
class OutboundMsg:
    text: str                            # 回复内容
    attachments: Optional[List[str]] = None  # 附件
    extras: Optional[Dict[str, Any]] = None  # 扩展数据
```

### 2. Channel 抽象

```python
class Channel(ABC):
    @abstractmethod
    async def start(self, on_message): ...  # 启动监听
    @abstractmethod
    async def send(self, to, msg): ...       # 发送消息
    @abstractmethod
    def verify(self, challenge): ...         # URL验证
    @abstractmethod
    def platform_name(self): ...             # 平台名称
```

### 3. Gateway 管理

```python
class Gateway:
    def __init__(self):
        self.channels: List[Channel] = []
        self.running = False

    def add_channels(self, channels: List[Channel]):  # 批量添加
    async def start_all(self):                      # 统一启动
    async def stop_all(self)                       # 统一停止
    async def send_to_platform(self, platform, to, msg)  # 指定平台发送
```

## 与现有架构集成

### 1. AgentManager 集成

```python
class ChatGateway(Gateway):
    def __init__(self):
        super().__init__()
        self.agent_manager = None

    def set_agent_manager(self, agent_manager: AgentManager):
        self.agent_manager = agent_manager

    async def on_message(self, msg: InboundMsg) -> OutboundMsg:
        # 根据 platform 路由到对应 agent
        agent_id = self.get_agent_id(msg.platform)
        agent = self.agent_manager.get(agent_id)

        # 处理消息
        response = agent.run(msg.text)
        return OutboundMsg(text=response)
```

### 2. Session 隔离

每个 Agent 独立：
- 记忆存储在 `agents/{agent_id}/memory/`
- 会话存储在 `agents/{agent_id}/sessions/`
- talent.md 提供系统提示词

## 部署方式

### 1. Webhook 模式（带 Streaming 支持）

```python
# 平台推送消息到 webhook
@app.post("/webhook/feishu")
async def feishu_webhook(request):
    # 使用 channel 内置的 webhook handler
    handler = feishu_channel.to_webhook_handler()
    return await handler(request)
```

#### Streaming 处理流程：
1. **消息接收**：Webhook 接收平台推送
2. **签名验证**：验证请求真实性
3. **消息解析**：转换成 `InboundMsg`
4. **队列缓冲**：消息进入异步队列
5. **异步处理**：独立任务处理队列消息
6. **路由分发**：发送到对应的 Agent

### 2. 长连接模式（流式响应）

```python
# 对于支持长连接的平台，可以返回流式响应
async def streaming_response(request):
    # 创建 SSE 响应
    async def event_stream():
        # 处理消息并返回流式响应
        for chunk in processor.stream_process(msg):
            yield f"data: {chunk}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
```

## 扩展点

### 1. 自定义消息处理

```python
class CustomGateway(Gateway):
    async def on_message(self, msg: InboundMsg) -> OutboundMsg:
        # 添加业务逻辑
        if msg.platform == "feishu" and "管理员" in msg.sender_name:
            return await self.handle_admin_message(msg)

        # 默认处理
        return await super().on_message(msg)
```

### 2. 中间件模式

```python
class MiddlewareGateway(Gateway):
    def __init__(self):
        super().__init__()
        self.middlewares = []

    def add_middleware(self, middleware):
        self.middlewares.append(middleware)

    async def handle_inbound(self, msg: InboundMsg) -> OutboundMsg:
        # 应用中间件
        for middleware in self.middlewares:
            msg = await middleware.process(msg)

        return await self.on_message(msg)
```

## 监控和日志

### 1. 统计信息

```python
stats = gateway.get_stats()
# {
#   "running": True,
#   "channels_count": 3,
#   "channels": ["feishu", "dingtalk", "wechat"]
# }
```

### 2. 错误处理

```python
try:
    await gateway.start_all()
except Exception as e:
    logger.error(f"启动失败: {e}")
    # 自动重试
    await gateway.stop_all()
    await gateway.start_all()
```

## 总结

这个设计实现了：

1. **统一管理**：一个 Gateway 管理所有平台
2. **按需扩展**：先实现一个平台验证，再逐步添加
3. **松耦合**：Channel 和 Agent 独立，易于替换和测试
4. **多 Agent 支持**：每个平台可以绑定不同的 Agent
5. **易于维护**：统一的启动/停止/监控机制

---