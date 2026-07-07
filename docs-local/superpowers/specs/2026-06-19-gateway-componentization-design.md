# Gateway 组件化设计

## 背景

当前 xiaomei-brain 的入站消息路径绕过了 `gateway/` 模块。5 条入站路径（CLI、WS、飞书、钉钉、Agent Comms）全部直接调用 `living.put_message()`，Gateway 只做出站路由和 WS 服务。这使得 Gateway 无法成为独立组件，也无法实现"闭关"（关闭对外通道）等类人意识行为。

## 设计理念

Gateway = 感官/运动神经（接收信号、过滤噪声、送达）
Consciousness = 意识（理解、决定、回应）

Gateway 是类人意识体对外的统一界面。它管理所有通道的启停，做机械层面的入站预处理，将纯净消息送入意识层。

## 架构

### 改造前

```
CLI/WS/Feishu/DingTalk ──► living.put_message() ──► queue ──► MessageGateway ──► ConversationDriver
                            ▲                            ▲              ▲
                        限流+sanitize               Living 内部      命令/元技能/身份
```

### 改造后

```
CLI ─────────────────┐
WS ──────────────────┤
Feishu ──────────────┼──► Gateway.accept(msg)
DingTalk ────────────┤         │
Agent Comms ─────────┘         ├─ sanitize（清洗）
                                ├─ 空消息过滤
                                ├─ token 认证
                                ├─ 限流检查
                                ├─ busy 检查
                                ├─ identity 解析
                                ├─ session 路由
                                ├─ 数据命令（/db /memory /dag）
                                └─ living.put_message(cleaned)
                                              │
                                              ▼
                                    queue → Consciousness
                                              │
                                              ├─ /intask, /inchat
                                              ├─ 元技能匹配（"去学XX"）
                                              └─ ConversationDriver
```

## 职责划分

| 职责 | Gateway | Consciousness |
|------|:---:|:---:|
| 输入清洗（sanitize） | ✓ 机械 | |
| 空消息过滤 | ✓ 机械 | |
| Token 认证 | ✓ 凭证校验 | |
| 限流（throttle） | ✓ 信号过滤 | |
| Busy 检查（读 _chatting） | ✓ 检查 | ✓ 设置 _chatting |
| Identity 解析（user_id → display_name） | ✓ 感官识别 | |
| 会话路由（哪个 session） | ✓ 管道工 | |
| 数据命令（/db /memory /dag） | ✓ 纯查询，不走 LLM | |
| 意图命令（/intask /inchat） | | ✓ 改变意识模式 |
| 元技能匹配（"去学 XX 技能"） | | ✓ 需要语义理解 |
| 回复内容决策 | | ✓ 完全意识决定 |
| 出站路由 | ✓ deliver | |
| 通道生命周期 | ✓ 启动/关闭编排 | |

## 新增/修改文件

### 新增

- `gateway/inbound.py` — Gateway 类 + RawMessage / AcceptResult 类型

### 修改

- `gateway/__init__.py` — 导出 Gateway
- `gateway/router.py` — 修复 Router.route() 使其可用于入站路由
- `consciousness/message_gateway.py` — 精简为只处理 /intask + 元技能
- `consciousness/living.py` — put_message() 移除 sanitize/限流/busy 逻辑
- `consciousness/conscious_living.py` — 通道启停编排移交 Gateway
- `channels/feishu/adapter.py` — living.put_message() → gateway.accept()
- `channels/dingtalk/adapter.py` — 同上
- `cli/run.py` — 同上
- `gateway/server_methods.py` — 同上
- `consciousness/agent_comms.py` — 同上

## 核心类型

```python
# gateway/inbound.py

@dataclass
class RawMessage:
    """Gateway 接受的原始入站消息。"""
    content: str
    source: str = ""              # "human" | "agent" | "system"
    channel: str = "cli"          # "cli" | "ws" | "feishu" | "dingtalk" | "comms"
    peer_id: str = ""             # 发送方标识
    peer_type: str = "human"      # "human" | "agent"
    images: list[str] = field(default_factory=list)
    urgent: bool = False

@dataclass
class Accepted:
    """消息通过 Gateway，准备入队。"""
    living_message: object

@dataclass
class Rejected:
    """消息被 Gateway 拒绝。"""
    reason: str              # BUSY / THROTTLED / UNAUTHORIZED / HANDLED / EMPTY
    silent: bool = False     # True = 不通知发送方

AcceptResult = Accepted | Rejected
```

## Gateway 类接口

```python
class Gateway:
    def __init__(self, living, router, config)
    def register_channel(self, name: str, adapter: ChannelAdapter) -> None
    def open_channels(self) -> None       # 逐个 adapter.setup()
    def close_channels(self) -> None      # 逐个 adapter.shutdown()
    def is_open(self) -> bool
    def accept(self, raw: RawMessage) -> AcceptResult  # 唯一入站入口
```

## 代码搬家清单

### 搬到 Gateway（gateway/inbound.py）

| 功能 | 来源 |
|------|-----|
| sanitize | `consciousness/living.py` put_message() |
| 空消息过滤 | `consciousness/message_gateway.py` handle() |
| token 认证 | `gateway/server_methods.py` _handle_connect() |
| 限流 throttle | `consciousness/living.py` put_message() |
| busy 检查 | `consciousness/message_gateway.py` handle() |
| identity 解析 | `consciousness/message_gateway.py` _resolve_identity() |
| session 路由 | `gateway/router.py` route()（修复后启用） |
| /db /memory /dag 命令 | `consciousness/message_gateway.py` _try_handle_command() |
| Channel 启停编排 | `consciousness/conscious_living.py` _setup_comms() / _on_stop() |

### 留在 Consciousness

| 功能 | 文件 |
|------|-----|
| /intask /inchat | `consciousness/message_gateway.py` |
| 元技能匹配 | `consciousness/message_gateway.py` |
| ConversationDriver 调用 | `consciousness/conversation_driver.py` |

### 废弃/精简

| 文件 | 处理 |
|------|-----|
| `consciousness/message_gateway.py` | 精简为 /intask + 元技能 |
| `gateway/auth.py` | 不变，Gateway 引用 |

## 调用方改动

所有 5 处 `living.put_message()` → `gateway.accept()`：

```python
# 改造前
living.put_message(text, source="human", session_id=session_id)

# 改造后
result = gateway.accept(RawMessage(
    content=text,
    source="human",
    channel="feishu",
    peer_id=sender,
    peer_type="human",
))
# result: Accepted(living_message) | Rejected(reason)
```

## 验证

```bash
# 1. 插件加载 + 通道注册
PYTHONPATH=src python3 -c "
from xiaomei_brain.gateway.inbound import Gateway
g = Gateway(...)
print('channels:', list(g._channels.keys()))
"

# 2. 现有测试无回归
PYTHONPATH=src python3 -m pytest tests/ -x -q

# 3. CLI 交互
PYTHONPATH=src python3 -m xiaomei_brain run xiaomei --cli

# 4. 自动化测试
PYTHONPATH=src python3 examples/test_conscious_living.py
```

## 不做的事

- 本次不改闭关状态机——close_channels() 作为接口暴露，由 Consciousness 按需调用
- 本次不改 busy 消息排队——维持当前策略（拒绝入队），排队缓存后续迭代
