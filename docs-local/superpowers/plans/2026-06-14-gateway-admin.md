# Gateway 加固 + Admin 管理门 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 Gateway 升级为 req/res/event RPC 协议，加固认证/错误/连接健康；新建 Admin 模块提供 REST 管理 API。

**Architecture:** Gateway（对话门）保持单一 WS 端点但协议升级为 req/res/event；Admin（管理门）是独立 FastAPI app，不同端口，Bearer token 认证。comms_server 不动。

**Tech Stack:** FastAPI, Pydantic, asyncio, uvicorn, websockets

---

### Task 1: 清理 protocol.py — 删旧格式，保留纯 req/res/event

**Files:**
- Modify: `src/xiaomei_brain/gateway/protocol.py`

- [ ] **Step 1: 重写 protocol.py**

```python
"""Gateway 协议：req/res/event 消息定义、错误码与构建工具。"""

from __future__ import annotations

import uuid
from enum import Enum
from typing import Any


PROTOCOL_VERSION = 1


class MsgType(str, Enum):
    REQ = "req"
    RES = "res"
    EVENT = "event"


def generate_id() -> str:
    return str(uuid.uuid4())


def build_req(method: str, params: dict | None = None, id: str | None = None) -> dict:
    return {
        "type": MsgType.REQ.value,
        "id": id or generate_id(),
        "method": method,
        "params": params or {},
    }


def build_res(id: str, ok: bool = True, payload: Any = None, error: dict | None = None) -> dict:
    msg: dict = {
        "type": MsgType.RES.value,
        "id": id,
        "ok": ok,
    }
    if ok:
        msg["payload"] = payload or {}
    else:
        msg["error"] = error or {"code": "INTERNAL_ERROR", "message": "Unknown error"}
    return msg


def build_event(event: str, payload: Any = None) -> dict:
    return {
        "type": MsgType.EVENT.value,
        "event": event,
        "payload": payload or {},
    }


# ── 错误码 ────────────────────────────────

class ErrorCodes:
    INVALID_REQUEST = "INVALID_REQUEST"
    NOT_FOUND = "NOT_FOUND"
    UNAUTHORIZED = "UNAUTHORIZED"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    PARSE_ERROR = "PARSE_ERROR"
    EMPTY_MESSAGE = "EMPTY_MESSAGE"
    GATEWAY_NOT_READY = "GATEWAY_NOT_READY"
    METHOD_NOT_FOUND = "METHOD_NOT_FOUND"


def error_shape(code: str, message: str, details: Any = None) -> dict:
    error: dict = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    return error
```

- [ ] **Step 2: 验证 import**

```bash
cd /home/iamlibai/workspace/claude-project/xiaomei-brain && source /home/iamlibai/workspace/python_env_common/bin/activate && PYTHONPATH=src python3 -c "
from xiaomei_brain.gateway.protocol import MsgType, PROTOCOL_VERSION, build_req, build_res, build_event, ErrorCodes, error_shape
print('PROTOCOL_VERSION:', PROTOCOL_VERSION)
print('REQ:', build_req('connect', {'token': 'x'}))
print('RES OK:', build_res('1', True, {'session_id': 's1'}))
print('RES ERR:', build_res('1', False, error=error_shape('UNAUTHORIZED', 'bad token')))
print('EVENT:', build_event('chat.chunk', {'text': 'hi'}))
print('OK')
"
```

### Task 2: 新建 gateway/schemas.py — Pydantic 消息 schema

**Files:**
- Create: `src/xiaomei_brain/gateway/schemas.py`

- [ ] **Step 1: 写 schemas.py**

```python
"""Gateway 消息 Pydantic schema 校验。"""

from __future__ import annotations

from pydantic import BaseModel, Field


# ── Connect ──────────────────────────────────

class ConnectParams(BaseModel):
    token: str = ""
    client: str = "unknown"


# ── Chat ─────────────────────────────────────

class ChatSendParams(BaseModel):
    content: str = Field(..., min_length=1)
    session_id: str = ""
    user_id: str = ""


class ChatAbortParams(BaseModel):
    session_id: str = ""


# ── Wire frames ──────────────────────────────

class ReqFrame(BaseModel):
    type: str = "req"
    id: str
    method: str
    params: dict = {}


class ResFrame(BaseModel):
    type: str = "res"
    id: str
    ok: bool
    payload: dict = {}
    error: dict | None = None


class EventFrame(BaseModel):
    type: str = "event"
    event: str
    payload: dict = {}
```

- [ ] **Step 2: 验证**

```bash
cd /home/iamlibai/workspace/claude-project/xiaomei-brain && source /home/iamlibai/workspace/python_env_common/bin/activate && PYTHONPATH=src python3 -c "
from xiaomei_brain.gateway.schemas import ReqFrame, ResFrame, EventFrame, ConnectParams, ChatSendParams
r = ReqFrame(id='1', method='connect', params={'token':'x'})
print('ReqFrame:', r)
res = ResFrame(id='1', ok=True, payload={'session_id':'s1'})
print('ResFrame:', res)
ev = EventFrame(event='chat.chunk', payload={'text':'hi'})
print('EventFrame:', ev)
cp = ConnectParams(token='x', client='webchat-ui')
print('ConnectParams:', cp)
cs = ChatSendParams(content='hello')
print('ChatSendParams:', cs)
print('OK')
"
```

### Task 3: 新建 gateway/auth.py — WS 认证

**Files:**
- Create: `src/xiaomei_brain/gateway/auth.py`

- [ ] **Step 1: 写 auth.py**

```python
"""Gateway 对话门认证 — WS connect 握手 token 校验。"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def resolve_auth_mode(config) -> str:
    """从配置解析认证模式：'token' | 'none'"""
    if config is None:
        return "none"
    gateway_cfg = getattr(config, "gateway", None)
    if gateway_cfg is None:
        return "none"
    return getattr(gateway_cfg, "auth_mode", "none") or "none"


def get_configured_token(config) -> str:
    """从配置读取 gateway token。"""
    if config is None:
        return ""
    gateway_cfg = getattr(config, "gateway", None)
    if gateway_cfg is None:
        return ""
    return getattr(gateway_cfg, "token", "") or ""


def check_token(token: str, config) -> bool:
    """校验 connect 请求中的 token。

    Returns:
        True 如果认证通过。
    """
    mode = resolve_auth_mode(config)
    if mode == "none":
        logger.debug("[Gateway Auth] 免认证模式")
        return True

    configured = get_configured_token(config)
    if not configured:
        logger.warning("[Gateway Auth] token 模式但未配置 token，放行")
        return True

    if token == configured:
        return True

    logger.info("[Gateway Auth] token 不匹配: got=%s...", token[:4] if token else "(empty)")
    return False
```

- [ ] **Step 2: 验证 import**

```bash
cd /home/iamlibai/workspace/claude-project/xiaomei-brain && source /home/iamlibai/workspace/python_env_common/bin/activate && PYTHONPATH=src python3 -c "
from xiaomei_brain.gateway.auth import resolve_auth_mode, check_token, get_configured_token
# None config → none mode
assert resolve_auth_mode(None) == 'none'
assert check_token('any', None) == True
print('OK')
"
```

### Task 4: 新建 gateway/server_methods.py — RPC handler

**Files:**
- Create: `src/xiaomei_brain/gateway/server_methods.py`

- [ ] **Step 1: 写 server_methods.py**

```python
"""Gateway RPC 方法处理 — req → handler → res/event。"""

from __future__ import annotations

import logging
from typing import Any

from .protocol import build_res, build_event, error_shape, ErrorCodes
from .auth import check_token

logger = logging.getLogger(__name__)


class MethodRouter:
    """将 RPC method 名路由到处理函数。"""

    def __init__(self, living: Any = None, config: Any = None) -> None:
        self._living = living
        self._config = config
        self._handlers: dict[str, callable] = {
            "connect": self._handle_connect,
            "chat.send": self._handle_chat_send,
            "chat.abort": self._handle_chat_abort,
        }
        # 已认证的 session
        self._auth_sessions: set[str] = set()

    def dispatch(self, conn_id: str, req_id: str, method: str, params: dict) -> dict:
        """分发 RPC 请求到对应 handler。

        Returns:
            res 帧 dict。
        """
        # 非 connect 方法需要先认证
        if method != "connect" and conn_id not in self._auth_sessions:
            return build_res(req_id, ok=False,
                             error=error_shape(ErrorCodes.UNAUTHORIZED, "请先 connect"))

        handler = self._handlers.get(method)
        if handler is None:
            return build_res(req_id, ok=False,
                             error=error_shape(ErrorCodes.METHOD_NOT_FOUND,
                                               f"未知方法: {method}"))

        try:
            return handler(conn_id, req_id, params)
        except Exception as e:
            logger.error("[MethodRouter] %s 处理失败: %s", method, e)
            return build_res(req_id, ok=False,
                             error=error_shape(ErrorCodes.INTERNAL_ERROR, str(e)))

    # ── Handlers ──────────────────────────────

    def _handle_connect(self, conn_id: str, req_id: str, params: dict) -> dict:
        token = params.get("token", "")
        client = params.get("client", "unknown")

        if not check_token(token, self._config):
            return build_res(req_id, ok=False,
                             error=error_shape(ErrorCodes.UNAUTHORIZED, "Token 无效"))

        self._auth_sessions.add(conn_id)
        logger.info("[Gateway] 客户端已认证: conn=%s client=%s", conn_id[:8], client)

        session_id = f"ws-{conn_id[:8]}"
        return build_res(req_id, ok=True, payload={
            "session_id": session_id,
            "protocol_version": 1,
        })

    def _handle_chat_send(self, conn_id: str, req_id: str, params: dict) -> dict:
        content = params.get("content", "").strip()
        if not content:
            return build_res(req_id, ok=False,
                             error=error_shape(ErrorCodes.EMPTY_MESSAGE, "空消息"))

        session_id = params.get("session_id") or f"ws-{conn_id[:8]}"
        user_id = params.get("user_id", "") or "ws-user"

        living = self._living
        if living is None:
            return build_res(req_id, ok=False,
                             error=error_shape(ErrorCodes.GATEWAY_NOT_READY, "Gateway 未就绪"))

        living.put_message(content, session_id=session_id, user_id=user_id)
        return build_res(req_id, ok=True, payload={"accepted": True, "session_id": session_id})

    def _handle_chat_abort(self, conn_id: str, req_id: str, params: dict) -> dict:
        living = self._living
        if living is None:
            return build_res(req_id, ok=False,
                             error=error_shape(ErrorCodes.GATEWAY_NOT_READY, "Gateway 未就绪"))
        try:
            living.abort_chat()
            return build_res(req_id, ok=True, payload={"aborted": True})
        except Exception as e:
            return build_res(req_id, ok=False,
                             error=error_shape(ErrorCodes.INTERNAL_ERROR, str(e)))

    def drop_session(self, conn_id: str) -> None:
        """断开连接时清除认证状态。"""
        self._auth_sessions.discard(conn_id)
```

- [ ] **Step 2: 验证 import**

```bash
cd /home/iamlibai/workspace/claude-project/xiaomei-brain && source /home/iamlibai/workspace/python_env_common/bin/activate && PYTHONPATH=src python3 -c "
from xiaomei_brain.gateway.server_methods import MethodRouter
# 无 living 时 connect 应该失败（除非免认证）
mr = MethodRouter(living=None, config=None)
# connect without auth
res = mr.dispatch('c1', '1', 'connect', {})
print('Connect res:', res)
# connect 通过后 chat.send 失败（无 living）
res2 = mr.dispatch('c1', '2', 'chat.send', {'content': 'hi'})
print('Chat send res:', res2)
print('OK')
"
```

### Task 5: 重写 gateway/server.py — 纯 req/res/event WS 端点

**Files:**
- Modify: `src/xiaomei_brain/gateway/server.py`

**Note:** 完全替换当前 server.py 内容。

- [ ] **Step 1: 重写 server.py**

```python
"""WebSocket server — Gateway 对话门。

FastAPI + WebSocket，req/res/event 协议。
所有消息经 MethodRouter → Living，输出经 WSAdapter 推回客户端。
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from .connection import ConnectionManager, cm
from .protocol import (
    MsgType, build_res, build_event, error_shape, ErrorCodes,
)
from .server_methods import MethodRouter
from .auth import resolve_auth_mode

logger = logging.getLogger(__name__)

_global_config: Any = None
_global_router: Any = None
_method_router: MethodRouter | None = None

app = FastAPI(title="xiaomei-brain Gateway")

PING_TIMEOUT = 30  # 秒


@app.on_event("startup")
async def _capture_loop() -> None:
    from .ws_adapter import WSAdapter
    WSAdapter.set_loop(asyncio.get_running_loop())


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "connections": cm.count}


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    conn_id = str(uuid.uuid4())
    cm.register(conn_id, ws)

    if _global_router:
        session_id = f"ws-{conn_id[:8]}"
        _global_router.register_peer(
            peer_type="human", peer_id=conn_id,
            channel="ws", session_id=session_id,
            output_type="ws", output_target=session_id,
        )
        cm.set_session(session_id, conn_id)

    async def send_frame(frame: dict) -> None:
        try:
            await ws.send_json(frame)
        except Exception as e:
            logger.debug("WS send_json failed: %s", e)

    try:
        while True:
            try:
                raw = await asyncio.wait_for(ws.receive_json(), timeout=PING_TIMEOUT)
            except asyncio.TimeoutError:
                logger.debug("WS ping 超时: conn=%s", conn_id[:8])
                break
            except Exception:
                break

            msg_type = raw.get("type", "")

            if msg_type == MsgType.REQ.value:
                req_id = raw.get("id", "")
                method = raw.get("method", "")
                params = raw.get("params", {})

                if not req_id or not method:
                    await send_frame(build_res(
                        req_id or "?", ok=False,
                        error=error_shape(ErrorCodes.INVALID_REQUEST, "缺少 id 或 method"),
                    ))
                    continue

                if _method_router:
                    res = _method_router.dispatch(conn_id, req_id, method, params)
                    await send_frame(res)
                else:
                    await send_frame(build_res(
                        req_id, ok=False,
                        error=error_shape(ErrorCodes.GATEWAY_NOT_READY, "Gateway 未就绪"),
                    ))

            elif msg_type == "ping":
                await send_frame({"type": "pong"})

            else:
                await send_frame(build_res(
                    raw.get("id", "?"), ok=False,
                    error=error_shape(ErrorCodes.INVALID_REQUEST, f"未知消息类型: {msg_type}"),
                ))

    except WebSocketDisconnect:
        pass
    finally:
        if _method_router:
            _method_router.drop_session(conn_id)
        cm.unregister(conn_id)


def create_app(
    router: Any = None,
    living: Any = None,
    tts: Any = None,
    agent_manager: Any = None,
    config: Any = None,
) -> FastAPI:
    global _global_router, _global_config, _method_router
    _global_router = router
    _global_config = config
    _method_router = MethodRouter(living=living, config=config)

    if router:
        from .ws_adapter import WSAdapter
        router.register_adapter("ws", WSAdapter(cm))

    auth_mode = resolve_auth_mode(config)
    logger.info("[Gateway] 对话门已创建 (auth=%s)", auth_mode)
    return app
```

- [ ] **Step 2: 验证 import**

```bash
cd /home/iamlibai/workspace/claude-project/xiaomei-brain && source /home/iamlibai/workspace/python_env_common/bin/activate && PYTHONPATH=src python3 -c "
from xiaomei_brain.gateway.server import create_app, app
print('create_app:', create_app)
print('OK')
"
```

### Task 6: 更新 ws_adapter.py — 输出 event 格式

**Files:**
- Modify: `src/xiaomei_brain/gateway/ws_adapter.py`

- [ ] **Step 1: 修改 send() 输出 event 帧**

把当前 `send()` 方法中的消息格式从 `{"type": msg_type, "text": text}` 改为 `{"type": "event", "event": "...", "payload": {"text": "..."}}`：

```python
"""WSAdapter — WebSocket 通道适配器。

收/发合并在 gateway/ 下：与 server.py 协同构成 WS 完整通道。
"""

from __future__ import annotations

import asyncio
import logging

from .channel_adapter import ChannelAdapter
from .connection import ConnectionManager
from .protocol import build_event

logger = logging.getLogger(__name__)


class WSAdapter(ChannelAdapter):
    """WebSocket 通道适配器：向已连接的 WebSocket 客户端发送消息。

    收（入站）由 gateway/server.py 的 /ws 端点处理。
    发（出站）由本适配器的 send() 处理。
    """

    _loop = None

    def __init__(self, conn_manager: ConnectionManager) -> None:
        self._conn_manager = conn_manager

    @classmethod
    def set_loop(cls, loop) -> None:
        cls._loop = loop

    @property
    def channel_type(self) -> str:
        return "ws"

    def send(self, target: str, text: str, msg_type: str = "text") -> None:
        """推送文本到指定 WebSocket 连接。

        target: session_id
        msg_type: "text" 完整消息 → event:"session.message"
                  "text_chunk" 流式块 → event:"chat.chunk"
        """
        conn_id = self._conn_manager.get_conn_id(target)
        if conn_id is None:
            logger.debug("[WSAdapter] 无连接: session=%s", target)
            return

        loop = self._loop
        if loop is None:
            logger.debug("[WSAdapter] 事件循环未设置: session=%s", target)
            return

        if msg_type == "text_chunk":
            event_name = "chat.chunk"
        else:
            event_name = "session.message"

        frame = build_event(event_name, {"text": text})
        asyncio.run_coroutine_threadsafe(
            self._conn_manager.send(conn_id, frame),
            loop,
        )
```

- [ ] **Step 2: 验证 import**

```bash
cd /home/iamlibai/workspace/claude-project/xiaomei-brain && source /home/iamlibai/workspace/python_env_common/bin/activate && PYTHONPATH=src python3 -c "
from xiaomei_brain.gateway.ws_adapter import WSAdapter
from xiaomei_brain.gateway.connection import ConnectionManager
adapter = WSAdapter(ConnectionManager())
print('channel_type:', adapter.channel_type)
print('OK')
"
```

### Task 7: 更新 ws_cli.py — 使用 req/res/event 协议

**Files:**
- Modify: `examples/ws_cli.py`

**Note:** 改动集中在消息收发逻辑：`_login()`、`_recv_loop()`、`_send_and_wait()`。

- [ ] **Step 1: 修改 _login() — 用 req/res/event**

将 `_login()` 中的 `list_identities` 和 `session_start` 改为 connect + chat.send 流程。由于协议变了，不再走旧的 `list_identities` 和 `session_start`：

```python
async def _login(ws) -> tuple[str, str]:
    """通过 WS connect 握手，获取 agent 信息。

    Returns:
        (user_id, agent_name)
    """
    import os

    token = os.environ.get("GATEWAY_TOKEN", "")
    connect_req = {
        "type": "req",
        "id": "connect-1",
        "method": "connect",
        "params": {"token": token, "client": "ws-cli"},
    }
    await ws.send(json.dumps(connect_req, ensure_ascii=False))

    agent_name = ""
    try:
        raw = await asyncio.wait_for(ws.recv(), timeout=5)
        data = json.loads(raw)
        if data.get("type") == "res" and data.get("ok"):
            payload = data.get("payload", {})
            session_id = payload.get("session_id", "")
            agent_name = payload.get("agent_name", "")
            _cprint(f"\n{_DIM}已连接，session: {session_id}{_RST}")
        else:
            err = data.get("error", {})
            _cprint(f"\n\033[91m认证失败: {err.get('message', '未知错误')}\033[0m")
            return "", ""
    except asyncio.TimeoutError:
        _cprint(f"\n\033[91m连接超时\033[0m")
        return "", ""

    # 交互式输入 user_id
    uid = ""
    while not uid:
        try:
            inp = input("login: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return "", agent_name

        if not inp:
            continue
        uid = inp

    _cprint(f"\n{_DIM}身份: {uid}{_RST}")
    return uid, agent_name
```

- [ ] **Step 2: 修改 _recv_loop() — 处理 res/event 帧**

替换 `_recv_loop()` 中的消息处理逻辑：

```python
async def _recv_loop(ws, app: Application) -> None:
    """WebSocket 接收循环。

    收到 event:"chat.chunk" → 流式渲染
    收到 event:"session.message" → 完整渲染
    收到 res (ok=false) → 错误渲染
    """
    try:
        while _state.running:
            try:
                raw = await ws.recv()
            except websockets.ConnectionClosed:
                break
            except Exception:
                break

            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue

            mt = data.get("type", "")

            if mt == "event":
                event_name = data.get("event", "")
                payload = data.get("payload", {})
                text = payload.get("text", "")

                if event_name == "chat.chunk":
                    _on_text_chunk(text)
                elif event_name == "session.message":
                    _state.msg_count += 1
                    _on_text(text)
                    app.invalidate()

            elif mt == "res":
                if not data.get("ok"):
                    err = data.get("error", {})
                    _on_error(err.get("code", ""), err.get("message", ""))
                    app.invalidate()

            elif mt == "pong":
                pass

    finally:
        pass
```

注意：删除 `_ping_loop` 相关代码，`_recv_loop` 不再管理 ping（协议层面 server 处理超时）。

- [ ] **Step 3: 修改 handle_enter 中的 _send_and_wait() — 用 req 帧**

替换消息发送部分：

```python
        # 原来的 msg = {"type": "chat", ...}
        # 改为:
        msg = {
            "type": "req",
            "id": f"msg-{_state.msg_count + 1}",
            "method": "chat.send",
            "params": {
                "content": text,
                "user_id": _state.user_id,
            },
        }
```

- [ ] **Step 4: 验证 ws_cli import**

```bash
cd /home/iamlibai/workspace/claude-project/xiaomei-brain && source /home/iamlibai/workspace/python_env_common/bin/activate && PYTHONPATH=src python3 -c "
# Check ws_cli can be parsed (syntax check)
import py_compile
py_compile.compile('examples/ws_cli.py', doraise=True)
print('OK')
"
```

### Task 8: 新建 admin/auth.py — Bearer token 认证

**Files:**
- Create: `src/xiaomei_brain/admin/__init__.py`
- Create: `src/xiaomei_brain/admin/auth.py`

- [ ] **Step 1: 写 __init__.py**

```python
"""Admin 管理门 — 独立的管理 API 服务。"""
```

- [ ] **Step 2: 写 admin/auth.py**

```python
"""Admin 管理门认证 — Bearer token 校验。"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import Header, HTTPException, Depends

logger = logging.getLogger(__name__)

_CONFIG: Any = None


def set_admin_config(config: Any) -> None:
    """注入配置引用。"""
    global _CONFIG
    _CONFIG = config


def _get_admin_token() -> str:
    """从配置读取 admin token。"""
    if _CONFIG is None:
        return ""
    admin_cfg = getattr(_CONFIG, "admin", None)
    if admin_cfg is None:
        return ""
    return getattr(admin_cfg, "token", "") or ""


def verify_admin(authorization: str = Header(default="")) -> str:
    """FastAPI 依赖：校验 Bearer token。

    Returns:
        token 如果有效，否则 raise 401。
    """
    token = _get_admin_token()
    if not token:
        # 未配置 admin token → 禁止访问
        raise HTTPException(status_code=403, detail="Admin token 未配置")

    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="缺少 Bearer token")

    provided = authorization[len("Bearer "):]
    if provided != token:
        raise HTTPException(status_code=401, detail="Admin token 无效")

    return provided
```

- [ ] **Step 3: 验证 import**

```bash
cd /home/iamlibai/workspace/claude-project/xiaomei-brain && source /home/iamlibai/workspace/python_env_common/bin/activate && PYTHONPATH=src python3 -c "
from xiaomei_brain.admin.auth import verify_admin, set_admin_config
print('OK')
"
```

### Task 9: 新建 admin/routes/ — 四个路由模块

**Files:**
- Create: `src/xiaomei_brain/admin/routes/__init__.py`
- Create: `src/xiaomei_brain/admin/routes/status.py`
- Create: `src/xiaomei_brain/admin/routes/config.py`
- Create: `src/xiaomei_brain/admin/routes/agents.py`
- Create: `src/xiaomei_brain/admin/routes/sessions.py`

- [ ] **Step 1: routes/__init__.py**

```python
"""Admin 管理门路由。"""
```

- [ ] **Step 2: routes/status.py**

```python
"""GET /api/status — 系统状态。"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends

from ..auth import verify_admin

router = APIRouter()

_LIVING: Any = None
_START_TIME = time.time()


def set_living(living: Any) -> None:
    global _LIVING
    _LIVING = living


@router.get("/api/status", dependencies=[Depends(verify_admin)])
def get_status() -> dict:
    living = _LIVING
    status = {
        "uptime_seconds": round(time.time() - _START_TIME),
        "agent_state": None,
        "drive": None,
    }
    if living:
        status["agent_state"] = str(getattr(living, 'state', None))
        drive = getattr(living, 'drive', None)
        if drive:
            ds = {}
            for name in ("desire", "emotion", "hormone", "motivation"):
                obj = getattr(drive, name, None)
                if obj:
                    ds[name] = {
                        k: v for k, v in vars(obj).items() if not k.startswith("_") and isinstance(v, (int, float))
                    }
            status["drive"] = ds
    return status
```

- [ ] **Step 3: routes/config.py**

```python
"""GET/PATCH /api/config — 配置读写。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ..auth import verify_admin

router = APIRouter()

_CONFIG: Any = None


def set_config(config: Any) -> None:
    global _CONFIG
    _CONFIG = config


@router.get("/api/config", dependencies=[Depends(verify_admin)])
def get_config() -> dict:
    if _CONFIG is None:
        raise HTTPException(status_code=503, detail="配置未加载")
    cfg = getattr(_CONFIG, "data", None)
    if cfg:
        return {"config": dict(cfg)}
    result = {}
    for attr in dir(_CONFIG):
        if not attr.startswith("_"):
            v = getattr(_CONFIG, attr)
            if isinstance(v, (str, int, float, bool, list, dict, type(None))):
                result[attr] = v
    return {"config": result}


@router.patch("/api/config", dependencies=[Depends(verify_admin)])
def patch_config(patch: dict) -> dict:
    if _CONFIG is None:
        raise HTTPException(status_code=503, detail="配置未加载")
    applied = []
    for key, value in patch.items():
        if hasattr(_CONFIG, key):
            setattr(_CONFIG, key, value)
            applied.append(key)
    return {"applied": applied}
```

- [ ] **Step 4: routes/agents.py**

```python
"""GET/POST /api/agents — Agent 管理。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ..auth import verify_admin

router = APIRouter()

_AGENT_MANAGER: Any = None


def set_agent_manager(mgr: Any) -> None:
    global _AGENT_MANAGER
    _AGENT_MANAGER = mgr


@router.get("/api/agents", dependencies=[Depends(verify_admin)])
def list_agents() -> dict:
    if _AGENT_MANAGER is None:
        raise HTTPException(status_code=503, detail="AgentManager 未就绪")
    agents = _AGENT_MANAGER.list_agents() if hasattr(_AGENT_MANAGER, "list_agents") else []
    return {"agents": agents}


@router.get("/api/agents/{agent_id}", dependencies=[Depends(verify_admin)])
def get_agent(agent_id: str) -> dict:
    if _AGENT_MANAGER is None:
        raise HTTPException(status_code=503, detail="AgentManager 未就绪")
    info = _AGENT_MANAGER.get_agent_info(agent_id) if hasattr(_AGENT_MANAGER, "get_agent_info") else None
    if info is None:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' 不存在")
    return {"agent": info}


@router.post("/api/agents", dependencies=[Depends(verify_admin)])
def create_agent(data: dict) -> dict:
    if _AGENT_MANAGER is None:
        raise HTTPException(status_code=503, detail="AgentManager 未就绪")
    name = data.get("name", "")
    copy_from = data.get("copy_from")
    if not name:
        raise HTTPException(status_code=400, detail="缺少 name")
    result = _AGENT_MANAGER.create_agent(name, copy_from=copy_from)
    return {"agent": result}
```

- [ ] **Step 5: routes/sessions.py**

```python
"""GET /api/sessions — 会话列表。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ..auth import verify_admin

router = APIRouter()

_LIVING: Any = None


def set_living(living: Any) -> None:
    global _LIVING
    _LIVING = living


@router.get("/api/sessions", dependencies=[Depends(verify_admin)])
def list_sessions() -> dict:
    living = _LIVING
    if living is None:
        raise HTTPException(status_code=503, detail="Living 未就绪")
    sessions = getattr(living, '_sessions', {})
    return {
        "sessions": [
            {"id": k, "user_id": getattr(v, "user_id", ""), "agent_id": getattr(v, "agent_id", "")}
            for k, v in sessions.items()
        ]
    }
```

- [ ] **Step 6: 验证所有路由 import**

```bash
cd /home/iamlibai/workspace/claude-project/xiaomei-brain && source /home/iamlibai/workspace/python_env_common/bin/activate && PYTHONPATH=src python3 -c "
from xiaomei_brain.admin.routes.status import router as r1
from xiaomei_brain.admin.routes.config import router as r2
from xiaomei_brain.admin.routes.agents import router as r3
from xiaomei_brain.admin.routes.sessions import router as r4
print('All routes OK')
"
```

### Task 10: 新建 admin/server.py — Admin FastAPI app

**Files:**
- Create: `src/xiaomei_brain/admin/server.py`

- [ ] **Step 1: 写 admin/server.py**

```python
"""Admin 管理门 — 独立 FastAPI app，不同端口。"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI

from .auth import set_admin_config, verify_admin
from .routes.status import router as status_router, set_living as set_status_living
from .routes.config import router as config_router, set_config
from .routes.agents import router as agents_router, set_agent_manager
from .routes.sessions import router as sessions_router, set_living as set_sessions_living

logger = logging.getLogger(__name__)

admin_app = FastAPI(title="xiaomei-brain Admin")


@admin_app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


def create_admin_app(
    living: Any = None,
    agent_manager: Any = None,
    config: Any = None,
) -> FastAPI:
    """创建 Admin 管理门 FastAPI app。

    Args:
        living: ConsciousLiving 实例
        agent_manager: AgentManager 实例
        config: 配置对象
    """
    set_admin_config(config)
    set_status_living(living)
    set_sessions_living(living)
    set_config(config)
    set_agent_manager(agent_manager)

    admin_app.include_router(status_router)
    admin_app.include_router(config_router)
    admin_app.include_router(agents_router)
    admin_app.include_router(sessions_router)

    logger.info("[Admin] 管理门已创建")
    return admin_app
```

- [ ] **Step 2: 验证 import**

```bash
cd /home/iamlibai/workspace/claude-project/xiaomei-brain && source /home/iamlibai/workspace/python_env_common/bin/activate && PYTHONPATH=src python3 -c "
from xiaomei_brain.admin.server import create_admin_app, admin_app
print('create_admin_app:', create_admin_app)
print('OK')
"
```

### Task 11: 连线 conscious_living.py — 启动 Admin server

**Files:**
- Modify: `src/xiaomei_brain/consciousness/conscious_living.py`

- [ ] **Step 1: 在 WS Gateway 启动后添加 Admin 启动**

在 `conscious_living.py` 中，找到 WS Gateway 启动代码块（约 898-918 行，`ws_port` 相关），在其后添加 Admin server 启动：

```python
        # ── Admin 管理门（独立端口，强制认证）────────────────────
        admin_port = getattr(self._config, 'admin_port', 0)
        if admin_port <= 0:
            # 尝试从 living config 读取
            lc = getattr(self._config, 'living', None)
            if lc:
                admin_port = getattr(lc, 'admin_port', 0)
        if admin_port <= 0:
            admin_port = ws_port + 1 if ws_port > 0 else 0

        if admin_port > 0:
            from ..admin.server import create_admin_app
            import uvicorn
            admin_app = create_admin_app(
                living=self,
                agent_manager=self._agent_manager,
                config=self._config,
            )
            admin_config = uvicorn.Config(admin_app, host=host, port=admin_port, log_level="warning")
            self._admin_server = uvicorn.Server(admin_config)
            self._admin_thread = threading.Thread(
                target=self._admin_server.run,
                daemon=True,
                name="admin-gateway",
            )
            self._admin_thread.start()
            logger.info("[ConsciousLiving] Admin 管理门已启动: http://%s:%d (auth=Bearer token)", host, admin_port)
```

- [ ] **Step 2: 在 `__init__` 中初始化 admin 相关属性**

在 `ConsciousLiving.__init__()` 中找到 `self._ws_thread = None` 附近，添加：

```python
        self._admin_thread = None
        self._admin_server = None
```

- [ ] **Step 3: 验证 import**

```bash
cd /home/iamlibai/workspace/claude-project/xiaomei-brain && source /home/iamlibai/workspace/python_env_common/bin/activate && PYTHONPATH=src python3 -c "
# Ensure conscious_living can be imported (checks syntax and imports)
import xiaomei_brain.consciousness.conscious_living
print('OK')
"
```

### Task 12: 端到端验证

- [ ] **Step 1: 检查所有 gateway 模块 import**

```bash
cd /home/iamlibai/workspace/claude-project/xiaomei-brain && source /home/iamlibai/workspace/python_env_common/bin/activate && PYTHONPATH=src python3 -c "
from xiaomei_brain.gateway import Router, InboundMsg, OutputRoute, ChannelAdapter
from xiaomei_brain.gateway.protocol import MsgType, PROTOCOL_VERSION, build_req, build_res, build_event, ErrorCodes, error_shape
from xiaomei_brain.gateway.schemas import ReqFrame, ResFrame, EventFrame, ConnectParams, ChatSendParams
from xiaomei_brain.gateway.auth import resolve_auth_mode, check_token
from xiaomei_brain.gateway.server_methods import MethodRouter
from xiaomei_brain.gateway.server import create_app
from xiaomei_brain.gateway.ws_adapter import WSAdapter
print('ALL GATEWAY IMPORTS OK')
"
```

- [ ] **Step 2: 检查所有 admin 模块 import**

```bash
cd /home/iamlibai/workspace/claude-project/xiaomei-brain && source /home/iamlibai/workspace/python_env_common/bin/activate && PYTHONPATH=src python3 -c "
from xiaomei_brain.admin.server import create_admin_app
from xiaomei_brain.admin.auth import verify_admin
print('ALL ADMIN IMPORTS OK')
"
```

- [ ] **Step 3: FastAPI app 可创建**

```bash
cd /home/iamlibai/workspace/claude-project/xiaomei-brain && source /home/iamlibai/workspace/python_env_common/bin/activate && PYTHONPATH=src python3 -c "
from xiaomei_brain.gateway.server import create_app
from xiaomei_brain.gateway.router import Router
router = Router()
app = create_app(router=router, living=None, config=None)
# 检查路由
routes = [r.path for r in app.routes]
assert '/health' in routes, f'Missing /health: {routes}'
assert '/ws' in routes, f'Missing /ws: {routes}'
print('Gateway routes:', routes)
print('OK')

from xiaomei_brain.admin.server import create_admin_app
admin_app = create_admin_app(living=None, agent_manager=None, config=None)
admin_routes = [r.path for r in admin_app.routes]
assert '/health' in admin_routes, f'Missing /health: {admin_routes}'
assert '/api/status' in admin_routes, f'Missing /api/status: {admin_routes}'
assert '/api/config' in admin_routes, f'Missing /api/config: {admin_routes}'
assert '/api/agents' in admin_routes, f'Missing /api/agents: {admin_routes}'
assert '/api/agents/{agent_id}' in admin_routes, f'Missing /api/agents/{{agent_id}}: {admin_routes}'
assert '/api/sessions' in admin_routes, f'Missing /api/sessions: {admin_routes}'
print('Admin routes:', admin_routes)
print('ALL OK')
"
```

- [ ] **Step 4: 提交**

```bash
git add src/xiaomei_brain/gateway/ src/xiaomei_brain/admin/ examples/ws_cli.py src/xiaomei_brain/consciousness/conscious_living.py
git commit -m "feat: gateway req/res/event protocol + admin management API"
```
