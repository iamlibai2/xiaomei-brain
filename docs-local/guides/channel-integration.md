# 渠道接入指南

> 本文讲解如何将 Agent 接入新的消息渠道。

---

## 渠道系统架构

```
消息平台（飞书/钉钉/CLI/WebSocket）
    │
    ▼
ChannelAdapter（渠道适配器）
    │
    ├─ start() → 建立连接（长连接/Webhook/轮询）
    ├─ 收到消息 → living.put_message(text, user_id, session_id)
    │
    ▼
ConsciousLiving → Agent 处理
    │
    ▼
Router.route() → ChannelAdapter.send(reply, target)
```

---

## 核心接口

所有渠道适配器继承自 `ChannelAdapter`：

```python
class ChannelAdapter:
    """渠道适配器基类。"""

    def start(self) -> None:
        """启动渠道连接（长连接/轮询/Webhook）。"""

    def stop(self) -> None:
        """断开连接，清理资源。"""

    def send(self, message: str, target: str) -> None:
        """发送消息到指定目标。"""

    @property
    def name(self) -> str:
        """渠道名称（如 'feishu'、'dingtalk'）。"""
```

---

## 接入一个渠道的步骤

### 第一步：创建适配器

```python
# plugins/channels/my_channel/adapter.py

from xiaomei_brain.gateway.channel_adapter import ChannelAdapter

class MyChannelAdapter(ChannelAdapter):
    def __init__(self, config: dict):
        super().__init__()
        self.config = config
        self.name = "my_channel"

    def start(self):
        """建立连接并启动消息接收循环。"""
        # 例如：WebSocket 长连接、Webhook 服务器、轮询等
        self._running = True
        self._start_receiving()

    def stop(self):
        """断开连接。"""
        self._running = False
        self._cleanup()

    def send(self, message: str, target: str) -> None:
        """发送消息到指定用户/群聊。"""
        # target 通常是 user_id 或 channel_id
        self._api.send_message(target, message)

    def _on_message(self, raw_message: dict):
        """收到消息时，提取文本和用户信息，交给 Living。"""
        text = raw_message.get("content", "")
        user_id = raw_message.get("sender_id", "unknown")
        session_id = raw_message.get("conversation_id", "default")

        # 交给 ConsciousLiving 处理
        self.living.put_message(text, user_id, session_id)
```

### 第二步：注册渠道配置

在 `config.json` 中注册渠道配置：

```json
{
  "channels": {
    "my_channel": {
      "enabled": true,
      "accounts": {
        "default": {
          "token": "your-api-token",
          "secret": "your-api-secret"
        }
      }
    }
  },
  "bindings": [
    {
      "agentId": "xiaomei",
      "match": {
        "channel": "my_channel",
        "accountId": "default"
      }
    }
  ]
}
```

### 第三步：在启动时加载

ConsciousLiving 在初始化时会自动加载所有已启用并绑定了当前 Agent 的渠道。

---

## 参考实现

### CLI 渠道

> `plugins/channels/cli/adapter.py`

最简单的实现：stdin/stdout。

```python
class CLIAdapter(ChannelAdapter):
    def start(self):
        # CLI 没有"启动连接"的概念
        pass

    def send(self, message: str, target: str):
        # 直接 print 到终端
        print(f"\n  {message}")
```

### 飞书渠道

> `plugins/channels/feishu/adapter.py`

使用飞书开放平台的 WebSocket 长连接：

```python
class FeishuAdapter(ChannelAdapter):
    def start(self):
        # 使用 lark-oapi 建立长连接
        self.client = lark.Client(self.config)
        self.client.start_ws(self._handle_event)

    def _handle_event(self, event):
        # 解析飞书消息事件
        text = event.message.content
        user_id = event.message.sender_id
        session_id = event.message.chat_id

    def send(self, message: str, target: str):
        # 通过飞书 API 发送消息
        self.client.send_text(target, message)
```

### 钉钉渠道

> `plugins/channels/dingtalk/adapter.py`

使用钉钉 Stream 模式：

```python
class DingTalkAdapter(ChannelAdapter):
    def start(self):
        # 使用 dingtalk-stream 建立连接
        self.client = DingTalkClient(self.config)
        self.client.register_callback(self._handle_message)

    def send(self, message: str, target: str):
        self.client.send_message(target, message)
```

### P2P 渠道

> `plugins/channels/p2p/`

Agent 之间的点对点通信，基于 WebSocket：

```python
class P2PAdapter(ChannelAdapter):
    """Agent 间通信渠道。"""
    # 支持 Agent 发现、消息路由、目录服务
    # 用于多 Agent 协作场景
```

---

## 渠道配置 CLI

```bash
# 交互式添加渠道
xiaomei-brain channel add

# 列出已配置的渠道
xiaomei-brain channel list

# 移除渠道
xiaomei-brain channel remove <channel_name>
```

---

## 最佳实践

1. **异步消息接收**：用独立线程接收消息，不阻塞主循环
2. **速率限制**：对高频消息做合并或限流
3. **错误处理**：连接断开时自动重连，指数退避
4. **用户映射**：维护 peer_id ↔ user_id 的映射关系
5. **会话管理**：不同渠道的会话 ID 需要映射到统一的 session_id

---

## 代码路径

| 渠道 | 位置 |
|------|------|
| CLI | `plugins/channels/cli/` |
| 飞书 | `plugins/channels/feishu/` |
| 钉钉 | `plugins/channels/dingtalk/` |
| P2P | `plugins/channels/p2p/` |
| Gateway | `gateway/` (路由、连接管理) |
