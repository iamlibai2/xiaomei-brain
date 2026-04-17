# Channel 使用指南

## 概述

xiaomei-brain 的 Channel 包提供了统一的消息平台接入层，支持飞书、钉钉、微信等平台的消息收发。

## 架构设计

```
平台消息  →  Channel  →  Gateway  →  Agent
          (适配器层)    (统一管理)   (AI大脑)
```

### 核心组件

1. **Channel** - 平台适配器，负责与具体平台通信
2. **Gateway** - 网关，统一管理多个 Channel
3. **InboundMsg/OutboundMsg** - 统一的消息格式
4. **AgentManager** - 多 Agent 管理

## 快速开始

### 1. 创建 Channel

```python
from xiaomei_brain.channels import FeishuChannel

# 创建飞书适配器
feishu = FeishuChannel(
    app_id="your_app_id",
    app_secret="your_app_secret",
    verification_token="your_token"
)
```

### 2. 创建 Gateway

```python
from xiaomei_brain.channels import Gateway

gateway = Gateway()
gateway.add_channel(feishu)
```

### 3. 启动服务

```python
await gateway.start_all()  # 启动所有 Channel
```

## 消息处理流程

### 入站消息（平台 → Agent）

1. 平台推送消息到对应的 Channel（Webhook）
2. Channel 验证消息（签名验证）
3. 消息加入异步队列（Streaming 处理）
4. Gateway 从队列取出消息并路由到 Agent
5. Agent 处理并返回 `OutboundMsg`
6. Channel 发送回复到平台

### Streaming 实现特性

- **消息队列**：使用 `asyncio.Queue(maxsize=1000)` 缓冲消息
- **异步处理**：独立的 `_process_messages()` 任务处理消息
- **容错机制**：单条消息处理失败不影响其他消息
- **资源管理**：自动清理任务和连接

### 出站消息（Agent → 平台）

```python
# 向指定平台发送消息
await gateway.send_to_platform("feishu", "chat_id", OutboundMsg(text="你好"))
```

## 实现新平台

### 1. 继承 Channel 基类

```python
from xiaomei_brain.channels.base import Channel
from xiaomei_brain.channels.types import InboundMsg, OutboundMsg

class WeChatChannel(Channel):
    def __init__(self, app_id: str, app_secret: str):
        super().__init__(app_id, app_secret)

    def platform_name(self) -> str:
        return "wechat"

    async def start(self, on_message):
        # 实现微信消息监听
        pass

    async def send(self, to: str, msg: OutboundMsg) -> None:
        # 实现微信消息发送
        pass

    def verify(self, challenge: str) -> str:
        # 实现 URL 验证
        return challenge
```

### 2. 添加到 Gateway

```python
wechat = WeChatChannel("your_wechat_app_id", "your_wechat_secret")
gateway.add_channel(wechat)
```

## 与 AgentManager 集成

```python
from xiaomei_brain.channels import Gateway
from xiaomei_brain.agent_manager import AgentManager

class ChatGateway(Gateway):
    def __init__(self):
        super().__init__()
        self.agent_manager = None

    def set_agent_manager(self, agent_manager: AgentManager):
        self.agent_manager = agent_manager

    async def on_message(self, msg: InboundMsg) -> OutboundMsg:
        # 获取对应的 Agent
        agent_id = self.get_agent_id(msg.platform)
        agent = self.agent_manager.get(agent_id)

        # 处理消息
        response = agent.run(msg.text)
        return OutboundMsg(text=response)
```

## 配置文件示例

```yaml
# config.yaml
channels:
  feishu:
    app_id: "feishu_app_id"
    app_secret: "feishu_app_secret"
    verification_token: "feishu_token"

  dingtalk:
    app_id: "dingtalk_app_id"
    app_secret: "dingtalk_app_secret"
    verification_token: "dingtalk_token"
```

## 部署建议

### 1. 开发环境

使用 `examples/channel_demo.py` 演示：
```bash
python examples/channel_demo.py
```

### 2. 生产环境

使用 FastAPI 暴露 webhook：

```python
from fastapi import FastAPI

app = FastAPI()

@app.post("/webhook/feishu")
async def feishu_webhook(request):
    # 获取飞书 channel 的 webhook handler
    handler = feishu_channel.to_webhook_handler()
    return await handler(request)
```

## 故障排查

### 1. Channel 启动失败

检查：
- API 密钥是否正确
- 网络连接是否正常
- 平台配置是否完成

### 2. 消息发送失败

检查：
- 会话 ID 是否正确
- 消息格式是否符合平台要求
- API 调用是否超时

### 3. Agent 无响应

检查：
- Agent 是否正确初始化
- 是否有足够权限调用 Agent
- 错误日志

## 最佳实践

1. **按需实现** - 先实现一个平台，验证架构后再扩展
2. **统一管理** - 使用 Gateway 管理所有 Channel
3. **错误处理** - 每个步骤都要有适当的错误处理
4. **日志记录** - 记录关键操作和错误
5. **性能监控** - 监控消息处理时间和成功率

## 扩展功能

### 1. 消息队列

```python
# 在 Gateway 中添加消息队列
import asyncio
from collections import deque

class MessageQueueGateway(Gateway):
    def __init__(self):
        super().__init__()
        self.message_queue = asyncio.Queue(maxsize=1000)

    async def handle_inbound(self, msg: InboundMsg) -> OutboundMsg:
        # 先入队
        await self.message_queue.put(msg)
        # 然后处理
        return await self.on_message(msg)
```

### 2. 限流控制

```python
import time
from collections import defaultdict

class RateLimitGateway(Gateway):
    def __init__(self, max_per_second=10):
        super().__init__()
        self.max_per_second = max_per_second
        self.message_counts = defaultdict(int)
        self.last_reset = time.time()

    async def handle_inbound(self, msg: InboundMsg) -> OutboundMsg:
        # 限流检查
        current_time = time.time()
        if current_time - self.last_reset > 1:
            self.message_counts.clear()
            self.last_reset = current_time

        if self.message_counts[msg.sender] >= self.max_per_second:
            return OutboundMsg(text("消息太频繁，请稍后再试"))

        self.message_counts[msg.sender] += 1
        return await self.on_message(msg)
```

---

*更新时间：2026-04-14*