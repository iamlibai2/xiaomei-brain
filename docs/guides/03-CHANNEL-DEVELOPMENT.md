# 渠道接入指南

> 把 Agent 接入到飞书、钉钉、公众号等消息渠道。

---

## 架构概述

渠道层（Channels）是 Agent 与外界通信的入口和出口。xiaomei-brain 使用"适配器模式"——每个渠道是一个 adapter，统一实现消息收发接口。

```
用户 → [飞书/钉钉/CLI...] → Channel Adapter → Gateway/Router → Agent
                                                      │
用户 ← [飞书/钉钉/CLI...] ← Channel Adapter ← Gateway/Router ← Agent
```

## 内置渠道

| 渠道 | 状态 | 说明 |
|------|------|------|
| CLI | ✅ 稳定 | 终端交互 |
| 飞书 | ✅ 稳定 | 飞书/ Lark 机器人 |
| 钉钉 | ✅ 稳定 | 钉钉 Stream 模式 |
| WebSocket | 🔧 开发中 | WebSocket 双向通信 |
| P2P | 🔧 开发中 | 点对点通信 |

## 开发一个新渠道

创建一个 Adapter 类，实现 `send()` 和 `receive()` 接口：

```python
# plugins/channels/wechat/__init__.py
from xiaomei_brain.gateway import ChannelAdapter, Message

class WeChatAdapter(ChannelAdapter):
    """微信公众号 Adapter"""
    
    def __init__(self, config: dict):
        self.app_id = config["app_id"]
        self.app_secret = config["app_secret"]
        self.token = config["token"]
    
    async def send(self, message: Message) -> bool:
        """发送消息到微信"""
        # 调用微信公众平台 API 发送消息
        access_token = self._get_access_token()
        response = requests.post(
            f"https://api.weixin.qq.com/cgi-bin/message/custom/send",
            params={"access_token": access_token},
            json={
                "touser": message.user_id,
                "msgtype": "text",
                "text": {"content": message.content}
            }
        )
        return response.status_code == 200
    
    async def receive(self) -> Message | None:
        """接收微信消息（通过 webhook）"""
        # 通常是 Flask/FastAPI 路由接收微信的回调
        # 这里只是一个示例
        pass
    
    @property
    def name(self) -> str:
        return "wechat"
```

### 注册渠道

渠道文件放在 `plugins/channels/` 目录下，系统自动发现并注册：

```
plugins/channels/
├── cli/
│   └── adapter.py
├── feishu/
│   └── adapter.py
├── dingtalk/
│   └── adapter.py
└── wechat/           ← 你的新渠道
    └── __init__.py
```

Gateway 在初始化时会扫描 `plugins/channels/` 目录，自动加载所有 Adapter。

### 飞书 Adapter 示例（完整）

飞书 Adapter 是 xiaomei-brain 最成熟的渠道实现，可以作为参考：

```python
# plugins/channels/feishu/adapter.py（简化版）

class FeishuAdapter(ChannelAdapter):
    """飞书机器人 Adapter"""
    
    def __init__(self, config: dict):
        self.app_id = config["app_id"]
        self.app_secret = config["app_secret"]
        self._app_access_token = None
    
    def _get_app_access_token(self) -> str:
        """获取飞书 tenant access token"""
        if self._app_access_token:
            return self._app_access_token
            
        response = requests.post(
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            json={
                "app_id": self.app_id,
                "app_secret": self.app_secret
            }
        )
        self._app_access_token = response.json()["tenant_access_token"]
        return self._app_access_token
    
    def send(self, user_id: str, content: str) -> bool:
        """发送消息给指定用户"""
        token = self._get_app_access_token()
        response = requests.post(
            "https://open.feishu.cn/open-apis/im/v1/messages",
            params={"receive_id_type": "open_id"},
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            },
            json={
                "receive_id": user_id,
                "msg_type": "text",
                "content": json.dumps({"text": content})
            }
        )
        return response.status_code == 200
    
    def start_polling(self, message_handler):
        """启动消息轮询（长连接）"""
        # 使用飞书 WebSocket 或 Webhook
        pass
```

## 消息格式

所有渠道的消息统一格式化为：

```python
@dataclass
class Message:
    user_id: str       # 用户唯一标识
    session_id: str    # 会话标识
    content: str       # 消息文本
    channel: str       # 渠道名（飞书/钉钉/CLI...）
    metadata: dict     # 额外元数据
```

Gateway 负责 `user_id` 的跨渠道映射（同一用户在飞书和 CLI 可能 ID 不同）。

## 路由规则

消息路由由 `gateway/router.py` 的规则代码决定，LLM 不参与：

```python
class Router:
    def __init__(self):
        # peer_id → user_id 映射
        self.peer_map: dict[str, str] = {}
    
    def register_peer(self, peer_id: str, user_id: str, channel: str):
        """注册一个渠道-用户映射"""
        self.peer_map[peer_id] = user_id
    
    def route(self, message: Message) -> str | None:
        """确定消息应该发给哪个 Agent（或 None = 广播）"""
        # 规则路由，LLM 不参与
        if message.content.startswith("/"):
            return None  # 命令消息，不转发
        if message.user_id in self.peer_map:
            return self.peer_map[message.user_id]  # 定向转发
        return None  # 广播到所有 Agent
```

## 最佳实践

1. **幂等发送**：渠道发送应该有重试机制，但避免重复发送
2. **消息格式化**：不同渠道的消息格式不同（Markdown vs 纯文本 vs 富文本），Adapter 应该做格式转换
3. **长连接 vs Webhook**：飞书/钉钉推荐长连接（消息推送），微信推荐 Webhook
4. **错误隔离**：一个渠道的异常不应影响其他渠道
5. **统一消息队列**：所有渠道的消息进入同一个 queue，按序处理
