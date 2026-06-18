# Gateway Componentization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Gateway the sole inbound message entry point, moving preprocessing (sanitize, throttle, identity, commands) from Living/MessageGateway into a new `gateway/inbound.py` Gateway class.

**Architecture:** Create `Gateway` class in `gateway/inbound.py` with `accept()` as the single entry point. All 5 caller sites (CLI, WS, Feishu, DingTalk, AgentComms) switch from `living.put_message()` to `gateway.accept()`. Gateway does mechanical preprocessing, then delegates to `living.put_message()` for queue insertion. MessageGateway is slimmed to only /intask, /inchat, meta-skill handling.

**Tech Stack:** Python 3.12+, dataclasses, existing `LivingMessage`, `Router`, `ChannelAdapter`, `IdentityManager`

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `gateway/inbound.py` | **Create** | Gateway class, RawMessage, AcceptResult types |
| `gateway/__init__.py` | Modify | Export Gateway, RawMessage, AcceptResult |
| `gateway/server_methods.py` | Modify | `_handle_chat_send`: `living.put_message()` → `gateway.accept()` |
| `consciousness/conscious_living.py` | Modify | Create Gateway instance; channel lifecycle via Gateway |
| `consciousness/message_gateway.py` | Modify | Remove empty/busy/identity/agent-commands; keep /intask + meta-skill |
| `consciousness/living.py` | Modify | `put_message()` remove sanitize + throttle |
| `channels/feishu/adapter.py` | Modify | `living.put_message()` → `gateway.accept()` |
| `channels/dingtalk/adapter.py` | Modify | `living.put_message()` → `gateway.accept()` |
| `cli/run.py` | Modify | `living.put_message()` → `gateway.accept()` |
| `consciousness/agent_comms.py` | Modify | `living.put_message()` → `gateway.accept()` |
| `tests/test_gateway_inbound.py` | **Create** | Unit tests for Gateway.accept() |

---

### Task 1: Create Gateway class — types + skeleton

**Files:**
- Create: `src/xiaomei_brain/gateway/inbound.py`
- Create: `tests/test_gateway_inbound.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_gateway_inbound.py
"""Gateway.accept() 单元测试"""
import pytest
from xiaomei_brain.gateway.inbound import Gateway, RawMessage, Accepted, Rejected

class FakeLiving:
    """Minimal fake for testing Gateway."""
    def __init__(self):
        self._chatting = False
        self.user_id = "global"
        self.session_id = "main"
        self.messages = []
        self._interoception_signals = None

    def put_message(self, content, user_id=None, session_id=None, source="", images=None, urgent=False):
        self.messages.append({
            "content": content, "user_id": user_id, "session_id": session_id,
            "source": source, "images": images or [],
        })

class FakeRouter:
    def route(self, msg):
        return None  # Will be set up per test
    def register_adapter(self, name, adapter):
        pass

class TestGatewayAccept:
    def test_passthrough_normal_message(self):
        g = Gateway(FakeLiving(), FakeRouter(), config=None)
        result = g.accept(RawMessage(content="你好", source="human", channel="cli"))
        assert isinstance(result, Accepted)
        assert result.living_message.content == "你好"

    def test_reject_empty_message(self):
        g = Gateway(FakeLiving(), FakeRouter(), config=None)
        result = g.accept(RawMessage(content="   ", source="human", channel="cli"))
        assert isinstance(result, Rejected)
        assert result.reason == "EMPTY"
        assert result.silent is True

    def test_reject_busy(self):
        living = FakeLiving()
        living._chatting = True
        g = Gateway(living, FakeRouter(), config=None)
        result = g.accept(RawMessage(content="你好", source="human", channel="cli"))
        assert isinstance(result, Rejected)
        assert result.reason == "BUSY"

    def test_sanitize_applied(self):
        living = FakeLiving()
        g = Gateway(living, FakeRouter(), config=None)
        # Surrogate characters should be stripped
        result = g.accept(RawMessage(content="hello\ud800world", source="human", channel="cli"))
        assert isinstance(result, Accepted)
        assert "\ud800" not in result.living_message.content

    def test_human_messages_never_throttled(self):
        living = FakeLiving()
        living._interoception_signals = type("Sig", (), {"throttle": True})()
        g = Gateway(living, FakeRouter(), config=None)
        result = g.accept(RawMessage(content="你好", source="human", channel="cli"))
        assert isinstance(result, Accepted)

    def test_non_human_throttled(self):
        living = FakeLiving()
        living._interoception_signals = type("Sig", (), {"throttle": True})()
        g = Gateway(living, FakeRouter(), config=None)
        result = g.accept(RawMessage(content="system alert", source="agent", channel="comms"))
        assert isinstance(result, Rejected)
        assert result.reason == "THROTTLED"

    def test_urgent_never_throttled(self):
        living = FakeLiving()
        living._interoception_signals = type("Sig", (), {"throttle": True})()
        g = Gateway(living, FakeRouter(), config=None)
        result = g.accept(RawMessage(content="SOS", source="agent", channel="comms", urgent=True))
        assert isinstance(result, Accepted)

    def test_identity_resolution(self):
        living = FakeLiving()
        g = Gateway(living, FakeRouter(), config=None)
        g.set_identity_mgr(_FakeIdentityMgr())
        result = g.accept(RawMessage(content="hi", source="human", channel="cli", peer_id="libai"))
        assert isinstance(result, Accepted)
        assert result.living_message.user_display_name == "李白"

    def test_data_command_routed(self):
        living = FakeLiving()
        g = Gateway(living, FakeRouter(), config=None)
        g.set_agent_commands(_FakeCommandRegistry())
        result = g.accept(RawMessage(content="/db", source="human", channel="cli"))
        assert isinstance(result, Rejected)
        assert result.reason == "HANDLED"

    def test_comms_session_routed_to_comms(self):
        living = FakeLiving()
        g = Gateway(living, FakeRouter(), config=None)
        result = g.accept(RawMessage(
            content="hello from agent",
            source="agent", channel="comms",
            peer_id="other_agent", peer_type="agent",
        ))
        assert isinstance(result, Accepted)
        assert result.living_message.session_id.startswith("comms-")


class _FakeIdentityMgr:
    def resolve(self, id): return {"id": id, "name": "李白"}
    def get_display_name(self, id): return "李白"

class _FakeCommandRegistry:
    def execute(self, raw, user_id, session_id):
        return type("Result", (), {"output": "ok"})()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/iamlibai/workspace/claude-project/xiaomei-brain && source /home/iamlibai/workspace/python_env_common/bin/activate && PYTHONPATH=src python3 -m pytest tests/test_gateway_inbound.py -v
```

Expected: FAIL — module `gateway.inbound` not found

- [ ] **Step 3: Create `gateway/inbound.py` — types + Gateway class**

```python
# src/xiaomei_brain/gateway/inbound.py
"""Gateway — 统一入站门。所有外部消息的唯一入口。

Gateway = 感官/运动神经：接收信号 → 过滤噪声 → 送达意识层。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from xiaomei_brain.consciousness.living import LivingMessage

logger = logging.getLogger(__name__)


# ── Types ────────────────────────────────────────────────────

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
    session_id: str = ""          # 外部指定的 session_id，空则由 Gateway 分配


@dataclass
class Accepted:
    """消息通过 Gateway，准备入队。"""
    living_message: Any  # LivingMessage


@dataclass
class Rejected:
    """消息被 Gateway 拒绝。"""
    reason: str              # BUSY / THROTTLED / UNAUTHORIZED / HANDLED / EMPTY
    silent: bool = False     # True = 不通知发送方


AcceptResult = Accepted | Rejected


# ── Gateway ──────────────────────────────────────────────────

class Gateway:
    """统一入站门。

    所有外部消息的唯一入口。做机械层面的预处理（清洗、认证、限流、
    身份解析、会话路由、数据命令），然后将纯净消息送入 Living 队列。
    """

    def __init__(self, living, router, config=None):
        self._living = living
        self._router = router
        self._config = config
        self._identity_mgr = None
        self._agent_commands = None
        self._channels: dict[str, Any] = {}

    # ── Dependencies (set after init) ──────────────────────

    def set_identity_mgr(self, mgr) -> None:
        self._identity_mgr = mgr

    def set_agent_commands(self, commands) -> None:
        self._agent_commands = commands

    # ── Channel lifecycle ──────────────────────────────────

    def register_channel(self, name: str, adapter) -> None:
        """注册通道适配器。"""
        self._channels[name] = adapter
        logger.info("[Gateway] 注册通道: %s", name)

    def open_channels(self) -> None:
        """启动所有已注册通道。"""
        for name, adapter in self._channels.items():
            if hasattr(adapter, "setup"):
                try:
                    adapter.setup(living=self._living)
                    logger.info("[Gateway] 通道已启动: %s", name)
                except Exception as e:
                    logger.error("[Gateway] 通道启动失败: %s %s", name, e)

    def close_channels(self) -> None:
        """关闭所有通道。"""
        for name, adapter in self._channels.items():
            if hasattr(adapter, "shutdown"):
                try:
                    adapter.shutdown()
                    logger.info("[Gateway] 通道已关闭: %s", name)
                except Exception as e:
                    logger.warning("[Gateway] 关闭通道失败: %s %s", name, e)

    def is_open(self) -> bool:
        """通道是否全部开启（至少注册过）。"""
        return len(self._channels) > 0

    # ── Inbound ───────────────────────────────────────────

    def accept(self, raw: RawMessage) -> AcceptResult:
        """唯一入站入口。返回 Accepted 或 Rejected。"""
        # 1. Sanitize
        content = self._sanitize(raw.content)
        if content is None:
            return Rejected(reason="EMPTY", silent=True)

        # 2. Empty check
        if not content.strip():
            logger.debug("[Gateway] 忽略空消息")
            return Rejected(reason="EMPTY", silent=True)

        # 3. Busy check
        if getattr(self._living, '_chatting', False):
            logger.info("[Gateway] 聊天进行中，拒绝新消息: %s", content[:30])
            return Rejected(reason="BUSY", silent=False)

        # 4. Rate-limit check
        if raw.source != "human" and not raw.urgent:
            sig = getattr(self._living, '_interoception_signals', None)
            if sig and getattr(sig, 'throttle', False):
                logger.warning("[Gateway] 限流激活，丢弃非紧急消息: %.50s", content)
                return Rejected(reason="THROTTLED", silent=True)

        # 5. Identity resolution
        user_id = raw.peer_id if raw.peer_type == "human" else self._living.user_id
        user_display_name = self._resolve_identity(raw.peer_id)
        if not user_display_name:
            user_display_name = "这位用户"

        # 6. Session routing
        session_id = raw.session_id or self._route_session(raw)

        # 7. Data command handling (/db, /memory, /dag)
        if content.startswith("/"):
            handled = self._try_data_command(content, user_id, session_id)
            if handled:
                return Rejected(reason="HANDLED", silent=True)

        # 8. Enqueue to Living (passes display_name through)
        from xiaomei_brain.consciousness.living import LivingMessage
        msg = LivingMessage(
            content=content,
            user_id=user_id,
            session_id=session_id,
            source=raw.source,
            images=raw.images,
        )
        msg.user_display_name = user_display_name
        self._living.put_message(
            content=content,
            user_id=user_id,
            session_id=session_id,
            source=raw.source,
            images=raw.images,
            display_name=user_display_name,
        )
        return Accepted(living_message=msg)

    # ── Internal ───────────────────────────────────────────

    @staticmethod
    def _sanitize(text: str) -> str | None:
        """清洗输入。返回 None 表示消息应丢弃。"""
        if not isinstance(text, str):
            return None
        from xiaomei_brain.agent.message_utils import clean_input
        return clean_input(text)

    def _resolve_identity(self, peer_id: str) -> str:
        """解析用户身份，返回 display name。"""
        if not peer_id or not self._identity_mgr:
            return ""
        identity = self._identity_mgr.resolve(peer_id)
        if identity:
            return self._identity_mgr.get_display_name(peer_id)
        return ""

    def _route_session(self, raw: RawMessage) -> str:
        """确定会话 ID。"""
        # Agent comms → comms- prefix
        if raw.source == "agent" and raw.peer_type == "agent":
            return f"comms-{raw.peer_id}"
        # Use Router if rules exist
        from xiaomei_brain.gateway.router import InboundMsg
        routed = self._router.route(InboundMsg(
            content=raw.content,
            peer_type=raw.peer_type,
            peer_id=raw.peer_id,
            channel=raw.channel,
            images=raw.images,
        ))
        return routed.session_id

    def _try_data_command(self, content: str, user_id: str, session_id: str) -> bool:
        """处理数据查询命令 (/db /memory /dag)。返回 True 表示已处理。"""
        if not self._agent_commands:
            return False
        raw = content.strip()
        if raw.startswith("/"):
            raw = raw[1:].strip()
        cmd = raw.split(None, 1)[0].lower() if raw else ""
        # Only handle data commands here; /intask /inchat stay in Consciousness
        if cmd in ("db", "memory", "dag"):
            result = self._agent_commands.execute(raw, user_id=user_id, session_id=session_id)
            if result:
                print(f"\n{result.output}", flush=True)
                return True
        return False
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /home/iamlibai/workspace/claude-project/xiaomei-brain && source /home/iamlibai/workspace/python_env_common/bin/activate && PYTHONPATH=src python3 -m pytest tests/test_gateway_inbound.py -v
```

Expected: all 10 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/xiaomei_brain/gateway/inbound.py tests/test_gateway_inbound.py
git commit -m "feat: create Gateway class — unified inbound entry point

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 2: Export Gateway from gateway/__init__.py

**Files:**
- Modify: `src/xiaomei_brain/gateway/__init__.py`

- [ ] **Step 1: Update __init__.py exports**

```python
# src/xiaomei_brain/gateway/__init__.py
"""Gateway: 统一消息入口 + 路由 + 通道接口 + WS 服务器。

Agent 的统一对外界面，所有外界通信（人 / Agent）都从这里进出。

结构:
    inbound.py              # Gateway 类 — 入站统一入口
    server.py               # FastAPI WS 服务器（/ws, /health）
    connection.py           # WebSocket 连接管理
    protocol.py             # WS 消息协议
    router.py               # 消息路由（Router, InboundMsg, OutputRoute）
    channel_adapter.py      # ChannelAdapter ABC（频道接口定义）
"""

from .router import Router, InboundMsg, OutputRoute
from .channel_adapter import ChannelAdapter
from .inbound import Gateway, RawMessage, Accepted, Rejected

__all__ = [
    "Gateway",
    "RawMessage",
    "Accepted",
    "Rejected",
    "Router",
    "InboundMsg",
    "OutputRoute",
    "ChannelAdapter",
]
```

- [ ] **Step 2: Verify import works**

```bash
cd /home/iamlibai/workspace/claude-project/xiaomei-brain && source /home/iamlibai/workspace/python_env_common/bin/activate && PYTHONPATH=src python3 -c "from xiaomei_brain.gateway import Gateway, RawMessage, Accepted, Rejected; print('OK')"
```

Expected: prints "OK"

- [ ] **Step 3: Commit**

```bash
git add src/xiaomei_brain/gateway/__init__.py
git commit -m "feat: export Gateway types from gateway/__init__.py

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 3: Integrate Gateway into ConsciousLiving

**Files:**
- Modify: `src/xiaomei_brain/consciousness/conscious_living.py`

This task creates a Gateway instance in ConsciousLiving and wires channel lifecycle through it. External behavior is unchanged — Gateway is created but callers still use `living.put_message()` directly.

- [ ] **Step 1: Read current _setup_comms and _on_stop to identify exact edit points**

The key changes in `conscious_living.py`:

- In `__init__` or early setup: create `self._gateway_inbound = Gateway(living=self, router=self._router, config=self._config)`
- After `_boot_plugins()`: register channels from registry into gateway
- In `_setup_comms()`: replace the channel setup loop with `self._gateway_inbound.register_channel(...)` calls + `self._gateway_inbound.open_channels()`
- Wire `IdentityManager` and `CommandRegistry` to Gateway
- In `_on_stop()`: replace channel shutdown loop with `self._gateway_inbound.close_channels()`

- [ ] **Step 2: Apply changes**

Find in `_setup_comms` (around line 882):
```python
        # ── 各通道适配器 Post-load 初始化 ──────────────────
        for name in self._registry.list_channels():
            adapter = self._registry.get_channel(name)
            if adapter and hasattr(adapter, "setup"):
                try:
                    adapter.setup(living=self)
                except Exception as e:
                    logger.error("[ConsciousLiving] %s adapter setup 失败: %s", name, e)
```

Replace with:
```python
        # ── 各通道适配器 Post-load 初始化 ──────────────────
        for name in self._registry.list_channels():
            adapter = self._registry.get_channel(name)
            if adapter:
                self._gateway_inbound.register_channel(name, adapter)
        self._gateway_inbound.open_channels()
```

Find near end of `_setup_comms` or wherever Gateway dependencies are available:
```python
        # Wire Gateway dependencies
        if hasattr(self, '_identity_mgr'):
            self._gateway_inbound.set_identity_mgr(self._identity_mgr)
        if self.agent and self.agent.commands:
            self._gateway_inbound.set_agent_commands(self.agent.commands)
```

Find in `_on_stop()` (around line 1511):
```python
        # 停止所有通道
        for name in self._registry.list_channels():
            adapter = self._registry.get_channel(name)
            if adapter and hasattr(adapter, "shutdown"):
                try:
                    adapter.shutdown()
                except Exception as e:
                    logger.warning("[ConsciousLiving] 关闭 %s 失败: %s", name, e)
```

Replace with:
```python
        # 停止所有通道
        self._gateway_inbound.close_channels()
```

Also wire IdentityManager after its creation. Find (around line 437):
```python
        self._identity_mgr = IdentityManager(contacts_dir)
```
Add after:
```python
        if hasattr(self, '_gateway_inbound'):
            self._gateway_inbound.set_identity_mgr(self._identity_mgr)
```

And wire agent commands after agent is built. Find where agent is set and add:
```python
        if hasattr(self, '_gateway_inbound') and self.agent.commands:
            self._gateway_inbound.set_agent_commands(self.agent.commands)
```

- [ ] **Step 3: Run existing tests to verify no regression**

```bash
cd /home/iamlibai/workspace/claude-project/xiaomei-brain && source /home/iamlibai/workspace/python_env_common/bin/activate && PYTHONPATH=src python3 -m pytest tests/test_conscious_living.py tests/test_interoception.py -v -x
```

Expected: all existing tests PASS

- [ ] **Step 4: Commit**

```bash
git add src/xiaomei_brain/consciousness/conscious_living.py
git commit -m "feat: integrate Gateway into ConsciousLiving — channel lifecycle

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 4: Simplify Living.put_message() — remove sanitize + throttle

**Files:**
- Modify: `src/xiaomei_brain/consciousness/living.py:258-292`

- [ ] **Step 1: Apply the edit**

Replace the current `put_message()` body (lines 271-292):

```python
    def put_message(
        self,
        content: str,
        user_id: str | None = None,
        session_id: str | None = None,
        source: str = "",
        images: list[str] | None = None,
        urgent: bool = False,
        display_name: str | None = None,
    ) -> None:
        """Enqueue a message.

        Sanitization, throttle, and busy checks are handled by
        Gateway.accept() which calls this method after preprocessing.

        将消息放入队列。清洗、限流、busy 检查由 Gateway.accept() 处理。
        """
        msg = LivingMessage(
            content=content,
            user_id=user_id or self.user_id,
            session_id=session_id or self.session_id,
            source=source,
            images=images or [],
        )
        if display_name:
            msg.user_display_name = display_name
        self._queue.put_nowait(msg)
```

Keep the `_clean_input` static method on the class — it's now only used by Gateway (but keeping it avoids breaking any other callers).

- [ ] **Step 2: Run existing tests**

```bash
cd /home/iamlibai/workspace/claude-project/xiaomei-brain && source /home/iamlibai/workspace/python_env_common/bin/activate && PYTHONPATH=src python3 -m pytest tests/test_interoception.py -v -x
```

Expected: tests pass (they call put_message directly for testing, now simplified)

- [ ] **Step 3: Commit**

```bash
git add src/xiaomei_brain/consciousness/living.py
git commit -m "feat: simplify Living.put_message() — move sanitize/throttle to Gateway

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 5: Rewire WS Gateway (server_methods.py)

**Files:**
- Modify: `src/xiaomei_brain/gateway/server_methods.py:95-112`

- [ ] **Step 1: Edit _handle_chat_send**

Replace lines 102-111:
```python
    def _handle_chat_send(self, conn_id: str, req_id: str, params: dict) -> dict:
        try:
            p = ChatSendParams.model_validate(params)
        except Exception as e:
            return build_res(req_id, ok=False,
                             error=error_shape(ErrorCodes.INVALID_REQUEST, f"参数无效: {format_error(e)}"))

        content = p.content.strip()
        session_id = p.session_id or f"ws-{conn_id[:8]}"
        user_id = p.user_id or "ws-user"

        living = self._living
        if living is None:
            return build_res(req_id, ok=False,
                             error=error_shape(ErrorCodes.GATEWAY_NOT_READY, "Gateway 未就绪"))

        living.put_message(content, session_id=session_id, user_id=user_id)
        return build_res(req_id, ok=True, payload={"accepted": True, "session_id": session_id})
```

Replace with:
```python
    def _handle_chat_send(self, conn_id: str, req_id: str, params: dict) -> dict:
        try:
            p = ChatSendParams.model_validate(params)
        except Exception as e:
            return build_res(req_id, ok=False,
                             error=error_shape(ErrorCodes.INVALID_REQUEST, f"参数无效: {format_error(e)}"))

        content = p.content.strip()
        session_id = p.session_id or f"ws-{conn_id[:8]}"
        user_id = p.user_id or "ws-user"

        living = self._living
        if living is None:
            return build_res(req_id, ok=False,
                             error=error_shape(ErrorCodes.GATEWAY_NOT_READY, "Gateway 未就绪"))

        gw = getattr(living, '_gateway_inbound', None)
        if gw:
            from .inbound import RawMessage, Accepted
            result = gw.accept(RawMessage(
                content=content, source="human", channel="ws",
                peer_id=user_id, peer_type="human",
                session_id=session_id,
            ))
            accepted = isinstance(result, Accepted)
            return build_res(req_id, ok=accepted, payload={"accepted": accepted, "session_id": session_id})
        else:
            # Fallback: Gateway not yet initialized
            living.put_message(content, session_id=session_id, user_id=user_id)
            return build_res(req_id, ok=True, payload={"accepted": True, "session_id": session_id})
```

- [ ] **Step 2: Commit**

```bash
git add src/xiaomei_brain/gateway/server_methods.py
git commit -m "feat: rewire WS chat.send through Gateway.accept()

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 6: Rewire CLI input (cli/run.py)

**Files:**
- Modify: `src/xiaomei_brain/cli/run.py:270`

- [ ] **Step 1: Edit CLI message send**

Replace line 270:
```python
            living.put_message(msg, images=images, session_id=f"cli-{agent_id}")
```

With:
```python
            gw = getattr(living, '_gateway_inbound', None)
            if gw:
                from xiaomei_brain.gateway.inbound import RawMessage
                result = gw.accept(RawMessage(
                    content=msg, source="human", channel="cli",
                    images=images, session_id=f"cli-{agent_id}",
                ))
                if hasattr(result, 'reason'):
                    print(f"\n[Gateway] 消息被拒绝: {result.reason}", flush=True)
            else:
                living.put_message(msg, images=images, session_id=f"cli-{agent_id}")
```

- [ ] **Step 2: Commit**

```bash
git add src/xiaomei_brain/cli/run.py
git commit -m "feat: rewire CLI input through Gateway.accept()

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 7: Rewire Feishu adapter

**Files:**
- Modify: `src/xiaomei_brain/channels/feishu/adapter.py:78`

- [ ] **Step 1: Edit Feishu on_message callback**

Replace line 78:
```python
            living.put_message(text, source="human", session_id=session_id)
```

With:
```python
            gw = getattr(living, '_gateway_inbound', None)
            if gw:
                from xiaomei_brain.gateway.inbound import RawMessage
                gw.accept(RawMessage(
                    content=text, source="human", channel="feishu",
                    peer_id=sender, peer_type="human",
                    session_id=session_id,
                ))
            else:
                living.put_message(text, source="human", session_id=session_id)
```

Note: Remove `user_id` gap — `peer_id=sender` now flows through Gateway → identity resolution. This fixes the `user_id` missing issue for Feishu.

- [ ] **Step 2: Commit**

```bash
git add src/xiaomei_brain/channels/feishu/adapter.py
git commit -m "feat: rewire Feishu adapter through Gateway.accept(), fix user_id gap

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 8: Rewire DingTalk adapter

**Files:**
- Modify: `src/xiaomei_brain/channels/dingtalk/adapter.py:133`

- [ ] **Step 1: Edit DingTalk on_message callback**

Replace line 133-134:
```python
            living.put_message(text, source="human", session_id=session_id,
                              images=media_paths)
```

With:
```python
            gw = getattr(living, '_gateway_inbound', None)
            if gw:
                from xiaomei_brain.gateway.inbound import RawMessage
                gw.accept(RawMessage(
                    content=text, source="human", channel="dingtalk",
                    peer_id=sender, peer_type="human",
                    images=media_paths, session_id=session_id,
                ))
            else:
                living.put_message(text, source="human", session_id=session_id,
                                  images=media_paths)
```

Same fix as Feishu — `peer_id=sender` flows through Gateway identity resolution.

- [ ] **Step 2: Commit**

```bash
git add src/xiaomei_brain/channels/dingtalk/adapter.py
git commit -m "feat: rewire DingTalk adapter through Gateway.accept(), fix user_id gap

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 9: Rewire Agent Comms

**Files:**
- Modify: `src/xiaomei_brain/consciousness/agent_comms.py:64-68, 91-94`

- [ ] **Step 1: Edit check_inbox → put_message**

Lines 64-68, replace:
```python
            living.put_message(
                f"[来自 {msg.from_agent}] ({msg.type.value})\n{msg.content}",
                source="agent",
                session_id=session_id,
            )
```

With:
```python
            gw = getattr(living, '_gateway_inbound', None)
            content = f"[来自 {msg.from_agent}] ({msg.type.value})\n{msg.content}"
            if gw:
                from xiaomei_brain.gateway.inbound import RawMessage
                gw.accept(RawMessage(
                    content=content, source="agent", channel="comms",
                    peer_id=msg.from_agent, peer_type="agent",
                    session_id=session_id,
                ))
            else:
                living.put_message(content, source="agent", session_id=session_id)
```

- [ ] **Step 2: Edit on_receive → put_message**

Lines 91-94, replace:
```python
        living.put_message(
            f"[来自 {msg.from_agent}] ({msg.type.value})\n{msg.content}",
            source="agent", session_id=session_id,
        )
```

With:
```python
        gw = getattr(living, '_gateway_inbound', None)
        content = f"[来自 {msg.from_agent}] ({msg.type.value})\n{msg.content}"
        if gw:
            from xiaomei_brain.gateway.inbound import RawMessage
            gw.accept(RawMessage(
                content=content, source="agent", channel="comms",
                peer_id=msg.from_agent, peer_type="agent",
                session_id=session_id,
            ))
        else:
            living.put_message(content, source="agent", session_id=session_id)
```

- [ ] **Step 3: Commit**

```bash
git add src/xiaomei_brain/consciousness/agent_comms.py
git commit -m "feat: rewire Agent Comms through Gateway.accept()

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 10: Slim down MessageGateway — remove moved responsibilities

**Files:**
- Modify: `src/xiaomei_brain/consciousness/message_gateway.py`

- [ ] **Step 1: Remove empty check, busy check, identity, agent commands from handle()**

The `handle()` method currently has 12 steps. Remove: empty check (step 1), re-entry guard (step 2), identity resolution (step 4), agent commands from _try_handle_command (step 8). Keep: inter-agent routing (step 3), session switch (step 6), cancel reset (step 7), /intask /inchat + test commands (step 8 partial), meta-skill (step 9), drive (step 10), conversation driver (step 11), alarms (step 12).

Replace `handle()` with:

```python
    def handle(self, msg: LivingMessage, living: ConsciousLiving) -> None:
        """Preprocess message: comms routing, session switch, intent commands,
        meta-skill matching. Then delegate to ConversationDriver.

        Sanitization, empty check, busy check, and identity resolution are
        now handled by Gateway.accept() before the message reaches this point.

        预处理消息：comms 路由、会话切换、意图命令、元技能匹配，
        然后委托 ConversationDriver。
        """
        logger.debug("[MessageGateway] 收到消息: %s [session=%s]", msg.content[:50], msg.session_id)

        # 1. Inter-agent communication.
        if msg.session_id.startswith("comms-"):
            living._debug_log("living",
                f"{time.strftime('%H:%M:%S')} 收到 agent 消息 [{msg.session_id}]: {msg.content[:60]}"
            )
            living._handle_comms_message(msg)
            return

        # 2. Sync user identity to agent core for memory scoping.
        agent_core = living.agent._get_agent()
        agent_core.user_id = msg.user_id
        agent_core.user_display_name = getattr(msg, 'user_display_name', '这位用户')

        # 3. Session switch.
        living.session_id = msg.session_id
        if hasattr(living, '_attention') and living._attention:
            living._attention.switch_to(msg.session_id)

        # 4. Reset cancel flag.
        living._cancel_requested = False

        # 5. Intent commands (/intask, /inchat, test commands).
        if self._try_handle_intent_commands(msg, living):
            return

        # 6. Meta-skill pattern matching.
        if self._try_meta_skill(msg, living):
            return

        # 7. Drive activation.
        if living.drive:
            living.drive.on_user_active()

        # 8. Delegate to ConversationDriver.
        living.conversation_driver.handle_message(msg, living._get_consciousness_state())
        living._print_prompt()

        # 9. Round alarms.
        if living.cron_scheduler:
            living._check_round_alarms()
```

- [ ] **Step 2: Rename _try_handle_command → _try_handle_intent_commands and remove data commands**

In the renamed method, keep only:
- `/intask` / `/inchat` → GoalManager via ConversationDriver
- Bare `/` → list commands
- Test/debug commands via `_intent_commands`

Remove the agent commands block (`living.agent.commands.execute(...)`).

- [ ] **Step 3: Remove _resolve_identity static method**

It's moved to Gateway.

- [ ] **Step 4: Run tests to verify no regression**

```bash
cd /home/iamlibai/workspace/claude-project/xiaomei-brain && source /home/iamlibai/workspace/python_env_common/bin/activate && PYTHONPATH=src python3 -m pytest tests/ -x -q
```

Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/xiaomei_brain/consciousness/message_gateway.py
git commit -m "feat: slim MessageGateway — move empty/busy/identity/commands to Gateway

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 11: End-to-end verification

- [ ] **Step 1: Run all tests**

```bash
cd /home/iamlibai/workspace/claude-project/xiaomei-brain && source /home/iamlibai/workspace/python_env_common/bin/activate && PYTHONPATH=src python3 -m pytest tests/ -x -q
```

Expected: all tests PASS, no regressions

- [ ] **Step 2: Verify Gateway unit tests pass**

```bash
PYTHONPATH=src python3 -m pytest tests/test_gateway_inbound.py -v
```

Expected: all 10 tests PASS

- [ ] **Step 3: Verify imports work**

```bash
PYTHONPATH=src python3 -c "
from xiaomei_brain.gateway import Gateway, RawMessage, Accepted, Rejected
from xiaomei_brain.gateway.inbound import Gateway as GW
print('Gateway:', GW)
print('RawMessage:', RawMessage)
print('All imports OK')
"
```

Expected: prints import confirmation

- [ ] **Step 4: Commit verification results (if any tweaks were made)**

```bash
git add -A && git diff --cached --stat
```
