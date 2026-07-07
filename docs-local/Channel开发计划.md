# Channel Phase 1 开发计划

**状态**：待开始
**预计耗时**：2-3 天
**负责人**：开发团队

---

## 1. 消息数据结构设计

### 文件：`src/xiaomei_brain/channels/types.py`

```python
from dataclasses import dataclass
from typing import Any, Optional, list, dict
from datetime import datetime

@dataclass
class InboundMsg:
    """来自平台的入站消息"""
    platform: str           # "feishu" / "dingtalk" / "wechat"
    sender: str             # 发送者唯一标识
    sender_name: str       # 发送者显示名
    conversation_id: str    # 会话 ID（群聊或私聊）
    text: str               # 消息内容
    timestamp: float        # 消息时间戳（UTC）
    attachments: list[str]  # 附件 URL 列表
    extra: dict[str, Any]  # 平台特定扩展

@dataclass
class OutboundMsg:
    """向平台发送的出站消息"""
    text: str                   # 回复内容
    attachments: Optional[list[str]] = None
    extras: Optional[dict[str, Any]] = None  # 平台特定扩展（如飞书的卡片）

    def to_platform_dict(self) -> dict:
        """转换为平台要求的格式，子类可重写"""
        return {"text": self.text}
```

### 关键设计决策

1. **时间戳统一 UTC**：避免时区混乱，转成本地时区在处理层
2. **附件统一 URL**：平台负责下载，统一用 URL 方式
3. **extra 字段**：存放平台特定结构（如飞书的 `card` 字段）

---

## 2. Channel 抽象基类设计

### 文件：`src/xiaomei_brain/channels/base.py`

```python
from abc import ABC, abstractmethod
from typing import Callable, Awaitable, Optional
import logging

from .types import InboundMsg, OutboundMsg

logger = logging.getLogger(__name__)

class Channel(ABC):
    """平台适配器抽象基类"""

    def __init__(self, bot_token: str, app_id: str):
        self.bot_token = bot_token
        self.app_id = app_id
        self._message_handler: Optional[Callable[[InboundMsg], Awaitable[OutboundMsg]]] = None

    @abstractmethod
    async def start(self, on_message: Callable[[InboundMsg], Awaitable[OutboundMsg]]) -> None:
        """启动消息监听（webhook/polling/websocket）"""
        # 保存 on_message 回调
        self._message_handler = on_message
        # 具体实现由子类实现

    @abstractmethod
    async def send(self, to: str, msg: OutboundMsg) -> None:
        """发送消息到指定会话"""
        pass

    @abstractmethod
    def verify(self, challenge: str) -> str:
        """URL 验证（webhook 需要）"""
        pass

    async def stop(self) -> None:
        """停止监听，默认实现"""
        logger.info(f"Channel {self.__class__.__name__} stopped")

    @abstractmethod
    def platform_name(self) -> str:
        """返回平台名称"""
        pass
```

### 设计理由

1. **强类型约束**：强制子类实现必要方法
2. **回调机制**：`on_message` 由 Channel 接收消息后调用
3. **基础实现**：`stop()` 提供默认日志实现

---

## 3. Gateway 通用层设计

### 文件：`src/xiaomei_brain/channels/gateway.py`

```python
import asyncio
import time
from typing import Callable, Awaitable, Optional
import logging

from .base import Channel
from .types import InboundMsg, OutboundMsg

logger = logging.getLogger(__name__)

class Gateway:
    """Channel 通用管理器"""

    def __init__(self, channel: Channel, account_id: str):
        self.channel = channel
        self.account_id = account_id
        self.message_queue: asyncio.Queue = asyncio.Queue()
        self.running = False
        self._task: Optional[asyncio.Task] = None

    async def start(self):
        """启动 Channel 监听"""
        self.running = True
        await self.channel.start(self.handle_inbound)

    async def stop(self):
        """停止所有服务"""
        self.running = False
        if self._task:
            self._task.cancel()
        await self.channel.stop()

    async def handle_inbound(self, msg: InboundMsg) -> OutboundMsg:
        """处理入站消息（可添加限流/重试）"""
        # 基础限流：队列处理
        try:
            return await self.on_message(msg)
        except Exception as e:
            logger.error(f"Error processing message: {e}")
            return OutboundMsg(text="处理消息时发生错误，请稍后重试")

    async def on_message(self, msg: InboundMsg) -> OutboundMsg:
        """子类实现消息处理逻辑"""
        raise NotImplementedError

    async def send(self, to: str, msg: OutboundMsg) -> None:
        """发送消息"""
        await self.channel.send(to, msg)

    def get_stats(self) -> dict:
        """获取统计信息"""
        return {
            "account_id": self.account_id,
            "running": self.running,
            "queue_size": self.message_queue.qsize()
        }
```

### 关键特性

1. **消息队列**：缓冲高并发消息，防止 Agent 被冲垮
2. **错误处理**：统一捕获异常，防止 Channel 崩溃
3. **统计接口**：方便监控 Channel 状态

---

## 4. Feishu Channel 实现（示例）

### 文件：`src/xiaomei_brain/channels/feishu.py`

```python
import json
import aiohttp
from typing import Dict, Any, Callable, Awaitable
import logging

from .base import Channel
from .types import InboundMsg, OutboundMsg

logger = logging.getLogger(__name__)

class FeishuChannel(Channel):
    """飞书平台适配器"""

    def __init__(self, bot_token: str, app_id: str, verification_token: str):
        super().__init__(bot_token, app_id)
        self.verification_token = verification_token
        self.webhook_url = f"https://open.feishu.cn/open-apis/bot/v2/hook/{bot_token}"

    def platform_name(self) -> str:
        return "feishu"

    async def start(self, on_message: Callable[[InboundMsg], Awaitable[OutboundMsg]]) -> None:
        """启动 webhook 监听"""
        await super().start(on_message)
        # 在实际部署中，这里应该配置外部 webhook 地址
        # 或启动本地服务器接收飞书推送
        logger.info(f"FeishuChannel started at {self.webhook_url}")

    def verify(self, challenge: str) -> str:
        """飞书 webhook URL 验证"""
        return challenge

    async def send(self, to: str, msg: OutboundMsg) -> None:
        """发送消息到飞书"""
        payload = msg.to_platform_dict()
        data = {
            "chat_id": to,
            "msg_type": "text",
            "content": {"text": msg.text}
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type={self._get_receive_type(to)}",
                json=data,
                headers={"Authorization": f"Bearer {self.bot_token}"}
            ) as resp:
                if resp.status != 200:
                    logger.error(f"Failed to send message: {await resp.text()}")
                else:
                    logger.info("Message sent successfully")

    def _get_receive_type(self, conversation_id: str) -> str:
        """根据 ID 判断接收类型"""
        # 简单判断：如果有 open_id 表示用户
        return "open_id" if "ou_" in conversation_id else "chat_id"
```

---

## 5. 项目结构调整

```
src/xiaomei_brain/
├── channels/
│   ├── __init__.py           # 导出 types, Channel, Gateway
│   ├── types.py              # InboundMsg/OutboundMsg
│   ├── base.py               # Channel 抽象基类
│   ├── gateway.py            # Gateway 通用层
│   ├── feishu.py             # 飞书适配器（示例）
│   ├── dingtalk.py           # 钉钉适配器（待实现）
│   └── wechat.py             # 微信适配器（待实现）
├── agent_manager.py          # 现有，保持不变
├── agent.py                  # 现有，保持不变
└── ...
```

---

## 6. 向后兼容

Phase 1 实现完全向后兼容：

1. **现有 Agent 不动**：不修改 `agent.py` 和 `agent_manager.py`
2. **接入可选**：Channel 层与现有 Agent 独立，可以按需集成
3. **示例代码**：提供 how-to 示例，但不修改现有示例

---

## 7. 测试计划

### 1. 单元测试
- Channel 基类接口测试
- Feishu Channel 集成测试（模拟飞书事件）
- Gateway 限流和错误处理测试

### 2. 集成测试
- Channel ↔ Agent 流程测试
- 多 Channel 并发测试

### 3. 文档
- API 文档（生成 docstring）
- 使用示例（how-to）

---

## 8. 实现顺序

1. **Day 1**：消息数据结构 + Channel 基类 + Gateway 通用层
2. **Day 2**：Feishu Channel 实现 + 基础测试
3. **Day 3**：集成测试 + 文档 + 验收

---

## 9. 风险评估

### 高风险
- 飞书 API 变更：需要及时更新
- 并发性能：Gateway 队列可能成为瓶颈

### 缓解措施
- 添加 API 版本控制
- Gateway 队列大小可配置

---

## 10. 验收标准

- [ ] Channel 接口定义清晰，强制子类实现必要方法
- [ ] Feishu Channel 能正确解析飞书 webhook 格式
- [ ] Gateway 能正确路由消息到 Agent
- [ ] 包含基础单元测试（>80% 覆盖率）
- [ ] 提供使用示例代码

---
*计划创建时间：2026-04-14*