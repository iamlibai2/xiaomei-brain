"""WebSocket server — OpenClaw Gateway 协议兼容 + xiaomei-brain 内部协议"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from .connection import ConnectionManager
from .protocol import (
    MsgType, build_msg, build_req, build_res, build_event,
    generate_id, error_shape, ErrorCodes
)
from .protocol import parse_message
from xiaomei_brain.agent import AgentSession

logger = logging.getLogger(__name__)

# Global shared state (set by create_app)
_global_agent: Any = None
_global_tts: Any = None
_global_session_manager: Any = None
_global_agent_manager: Any = None
_global_config: Any = None
executor = ThreadPoolExecutor(max_workers=10)

# Connection manager singleton
cm = ConnectionManager()

app = FastAPI(title="xiaomei-brain WebSocket Gateway")

# 序列号计数器
_event_seq = 0

# Chat abort controllers: run_id -> asyncio.Event
_chat_abort_events: dict[str, asyncio.Event] = {}


def next_seq() -> int:
    global _event_seq
    _event_seq += 1
    return _event_seq


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "connections": cm.count}


# ── OpenClaw 协议方法处理 ────────────────────────────────────────────────────

async def _handle_openclaw_method(
    method: str,
    params: dict,
    req_id: str,
    send,
    client_session: Any,
    conn_id: str,
) -> Any:
    """处理 OpenClaw Gateway 协议方法"""
    from xiaomei_brain.base.config_provider import get_provider

    provider = get_provider()

    if method == "config.get":
        # 读取配置快照
        snapshot = provider.config
        # 移除敏感信息
        payload = {
            "config": _redact_config(snapshot),
            "hash": provider.hash,
            "path": provider.config_path,
        }
        await send(build_res(req_id, ok=True, payload=payload))

    elif method == "config.patch":
        base_hash = params.get("baseHash", "")
        raw = params.get("raw", "{}")

        if base_hash and base_hash != provider.hash:
            await send(build_res(req_id, ok=False, error=error_shape(
                ErrorCodes.INVALID_REQUEST,
                "config changed since last load; re-run config.get and retry"
            )))
            return

        try:
            patch = json.loads(raw) if isinstance(raw, str) else raw
            provider.patch(patch)
            await send(build_res(req_id, ok=True, payload={
                "ok": True,
                "hash": provider.hash,
            }))
        except Exception as e:
            await send(build_res(req_id, ok=False, error=error_shape(
                ErrorCodes.INVALID_REQUEST,
                str(e)
            )))

    elif method == "config.apply":
        base_hash = params.get("baseHash", "")
        raw = params.get("raw", "{}")

        if base_hash and base_hash != provider.hash:
            await send(build_res(req_id, ok=False, error=error_shape(
                ErrorCodes.INVALID_REQUEST,
                "config changed since last load; re-run config.get and retry"
            )))
            return

        try:
            new_config = json.loads(raw) if isinstance(raw, str) else raw
            provider.apply(new_config)
            await send(build_res(req_id, ok=True, payload={
                "ok": True,
                "hash": provider.hash,
            }))
        except Exception as e:
            await send(build_res(req_id, ok=False, error=error_shape(
                ErrorCodes.INVALID_REQUEST,
                str(e)
            )))

    elif method == "agents.list":
        # 返回 Agent 列表
        agents = _list_agents()
        await send(build_res(req_id, ok=True, payload={"agents": agents}))

    elif method == "agents.get":
        agent_id = params.get("agentId", "default")
        agent = _get_agent(agent_id)
        if agent:
            await send(build_res(req_id, ok=True, payload=agent))
        else:
            await send(build_res(req_id, ok=False, error=error_shape(
                ErrorCodes.NOT_FOUND,
                f"Agent '{agent_id}' not found"
            )))

    elif method == "chat.send":
        # OpenClaw 风格的聊天（支持流式事件）
        session_key = params.get("sessionKey", "main")
        content = params.get("message", "")
        run_id = params.get("runId") or str(uuid.uuid4())

        # 注册 abort event
        abort_event = asyncio.Event()
        _chat_abort_events[run_id] = abort_event

        try:
            # 发送 chat 事件 (start)
            await send(build_event("chat", {
                "sessionKey": session_key,
                "runId": run_id,
                "state": "start",
            }, seq=next_seq()))

            # 处理聊天
            await _do_openclaw_chat(content, session_key, run_id, req_id, send, client_session, conn_id, abort_event)
        finally:
            # 清理 abort event
            _chat_abort_events.pop(run_id, None)

    elif method == "chat.abort":
        session_key = params.get("sessionKey")
        run_id = params.get("runId")

        if not session_key:
            await send(build_res(req_id, ok=False, error=error_shape(
                ErrorCodes.INVALID_REQUEST,
                "sessionKey is required"
            )))
            return

        if not run_id:
            # 没有 runId → 中止该 sessionKey 下所有活跃的 abort events
            aborted_ids = []
            for rid, evt in list(_chat_abort_events.items()):
                # 注意：这里用 session_id 匹配，需要存储 rid -> session_id
                # 简化处理：如果没有 runId，返回未中止（因为没有 session 级别的追踪）
                pass
            await send(build_res(req_id, ok=True, payload={
                "ok": True,
                "aborted": False,
                "runIds": [],
                "reason": "session-wide abort not yet implemented, use runId",
            }))
            return

        # 有 runId → 中止指定的 run
        if run_id in _chat_abort_events:
            _chat_abort_events[run_id].set()
            await send(build_res(req_id, ok=True, payload={
                "ok": True,
                "aborted": True,
                "runIds": [run_id],
            }))
        else:
            # runId 未找到，说明已经结束或不存在
            await send(build_res(req_id, ok=True, payload={
                "ok": True,
                "aborted": False,
                "runIds": [],
            }))

    elif method == "chat.history":
        session_key = params.get("sessionKey", "main")
        limit = params.get("limit", 200)

        # OpenClaw 风格的消息结构
        messages = []
        if client_session:
            all_msgs = client_session.get_messages()
            for msg in all_msgs:
                # 转换消息格式以符合 OpenClaw 结构
                content = msg.get("content", "")
                role = msg.get("role", "user")
                timestamp = msg.get("timestamp", 0)

                # 如果是字符串 content，转换为 OpenClaw 格式
                if isinstance(content, str):
                    msg_entry = {
                        "role": role,
                        "content": [{"type": "text", "text": content}],
                        "timestamp": timestamp,
                    }
                else:
                    msg_entry = {
                        "role": role,
                        "content": content if isinstance(content, list) else [{"type": "text", "text": str(content)}],
                        "timestamp": timestamp,
                    }
                messages.append(msg_entry)

        # 限制数量
        hard_max = 1000
        max_limit = min(hard_max, limit if isinstance(limit, int) else 200)
        if len(messages) > max_limit:
            messages = messages[-max_limit:]

        # OpenClaw 返回格式
        await send(build_res(req_id, ok=True, payload={
            "sessionKey": session_key,
            "sessionId": client_session.id if client_session else None,
            "messages": messages,
        }))

    elif method == "sessions.list":
        # 返回会话列表
        sessions = _list_sessions()
        await send(build_res(req_id, ok=True, payload={"sessions": sessions}))

    elif method == "sessions.get":
        session_id = params.get("sessionId", "")
        session = _get_session(session_id)
        if session:
            await send(build_res(req_id, ok=True, payload=session))
        else:
            await send(build_res(req_id, ok=False, error=error_shape(
                ErrorCodes.NOT_FOUND,
                f"Session '{session_id}' not found"
            )))

    elif method == "ping":
        await send(build_res(req_id, ok=True, payload={"pong": True}))

    else:
        await send(build_res(req_id, ok=False, error=error_shape(
            ErrorCodes.INVALID_REQUEST,
            f"Unknown method: {method}"
        )))


async def _do_openclaw_chat(
    content: str,
    session_key: str,
    run_id: str,
    req_id: str,
    send,
    client_session: Any,
    conn_id: str,
    abort_event: asyncio.Event | None = None,
) -> None:
    """执行 OpenClaw 风格的聊天，返回流式事件，支持 abort"""
    if client_session is None:
        # 创建新会话
        session_id = f"ws-{uuid.uuid4().hex[:8]}"
        client_session = AgentSession(
            id=session_id,
            agent=_global_agent,
            session_manager=_global_session_manager,
        )
        cm.set_session(session_id, conn_id)

    client_session.add_message("user", content)

    try:
        def run_stream_sync():
            results = []
            for chunk in client_session.agent.stream(content):
                results.append(chunk)
            return results

        loop = asyncio.get_event_loop()
        all_chunks = await loop.run_in_executor(executor, run_stream_sync)

        full_content = "".join(all_chunks)
        sent_chunks = []

        # 发送每个 chunk 作为 chat 事件 (delta)
        for i, chunk in enumerate(all_chunks):
            # 检查是否被 abort
            if abort_event and abort_event.is_set():
                logger.info(f"[CHAT] Chat aborted for run_id={run_id}")
                await send(build_event("chat", {
                    "sessionKey": session_key,
                    "runId": run_id,
                    "state": "aborted",
                    "message": {"text": "".join(sent_chunks)},
                }, seq=next_seq()))
                return

            sent_chunks.append(chunk)
            await send(build_event("chat", {
                "sessionKey": session_key,
                "runId": run_id,
                "state": "delta",
                "message": {"text": chunk},
            }, seq=next_seq()))

        # 发送 chat 事件 (final)
        await send(build_event("chat", {
            "sessionKey": session_key,
            "runId": run_id,
            "state": "final",
            "message": {"text": full_content},
        }, seq=next_seq()))

        client_session.add_message("assistant", full_content)

    except Exception as e:
        logger.error("chat error: %s", e, exc_info=True)
        await send(build_event("chat", {
            "sessionKey": session_key,
            "runId": run_id,
            "state": "error",
            "errorMessage": str(e),
        }, seq=next_seq()))


def _redact_config(config: dict) -> dict:
    """移除配置中的敏感信息"""
    # 深拷贝避免修改原配置
    redacted = json.loads(json.dumps(config))
    # TODO: 实现敏感字段脱敏
    return redacted


def _list_agents() -> list[dict]:
    """列出所有 Agent"""
    if _global_agent_manager:
        try:
            return _global_agent_manager.list_agents()
        except:
            pass
    # 默认返回系统 Agent
    return [{
        "id": "default",
        "name": "小美",
        "description": "默认 AI 助手",
    }]


def _get_agent(agent_id: str) -> dict | None:
    """获取单个 Agent"""
    agents = _list_agents()
    for agent in agents:
        if agent["id"] == agent_id:
            return agent
    return None


def _list_sessions() -> list[dict]:
    """列出所有会话"""
    sessions = []
    for session_id, conn_id in cm._sessions.items():
        sessions.append({
            "id": session_id,
            "connectionId": conn_id,
        })
    return sessions


def _get_session(session_id: str) -> dict | None:
    """获取单个会话"""
    if session_id in cm._sessions:
        return {
            "id": session_id,
            "connectionId": cm._sessions[session_id],
        }
    return None


# ── 内部协议方法处理 ─────────────────────────────────────────────────────────

async def _handle_rpc(method: str, params: dict) -> dict:
    """Handle JSON-RPC config methods (xiaomei-brain 内部格式)"""
    from xiaomei_brain.base.config_provider import get_provider

    provider = get_provider()
    try:
        if method == "config.get":
            value = provider.get(params.get("path", ""))
            return {"value": value, "hash": provider.hash}
        elif method == "config.patch":
            raw = params.get("raw", "{}")
            partial = json.loads(raw)
            provider.patch(partial, params.get("baseHash", ""))
            return {"success": True, "hash": provider.hash}
        elif method == "config.apply":
            raw = params.get("raw", "{}")
            new_config = json.loads(raw)
            provider.apply(new_config, params.get("baseHash", ""))
            return {"success": True, "hash": provider.hash}
        elif method == "config.reload":
            provider.reload()
            return {"success": True, "hash": provider.hash}
        else:
            return {"error": {"code": -32601, "message": f"Method not found: {method}"}}
    except Exception as e:
        return {"error": {"code": -32603, "message": str(e)}}


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    """Main WebSocket endpoint - 支持 OpenClaw 协议和 xiaomei-brain 内部协议"""
    await ws.accept()
    conn_id = str(uuid.uuid4())
    cm.register(conn_id, ws)

    client_session: AgentSession | None = None

    async def send(msg: dict) -> None:
        try:
            await ws.send_json(msg)
        except Exception:
            pass

    async def handle_chat(msg: dict) -> None:
        """xiaomei-brain 内部协议聊天处理"""
        nonlocal client_session
        content = msg["content"]
        session_id = msg.get("session_id")

        message_id = str(uuid.uuid4())
        await send(build_msg(MsgType.CHAT_START, session_id=client_session.id if client_session else session_id, message_id=message_id))

        if client_session is None:
            session_id = session_id or f"ws-{uuid.uuid4().hex[:8]}"
            client_session = AgentSession(
                id=session_id,
                agent=_global_agent,
                session_manager=_global_session_manager,
            )
            cm.set_session(session_id, conn_id)

        client_session.add_message("user", content)

        try:
            def run_stream_sync():
                results = []
                for chunk in client_session.agent.stream(content):
                    results.append((chunk, False))
                results.append(("", True))
                return results

            logger.info("[WS] Starting agent.stream() for: %s", content[:50])
            loop = asyncio.get_event_loop()
            all_chunks = await loop.run_in_executor(executor, run_stream_sync)
            logger.info("[WS] agent.stream() returned %d chunks", len(all_chunks))

            full_chunks = []
            for chunk, is_final in all_chunks:
                if is_final:
                    break
                full_chunks.append(chunk)
                await send(build_msg(MsgType.TEXT_CHUNK, content=chunk))

            if _global_tts and full_chunks:
                text = "".join(full_chunks)
                await stream_tts(text, send)

            await send(build_msg(MsgType.TEXT_DONE, content="".join(full_chunks)))
            client_session.add_message("assistant", "".join(full_chunks))
        except Exception as e:
            logger.error("handle_chat error: %s", e, exc_info=True)
            await send(build_msg(MsgType.ERROR, message=str(e), code="CHAT_ERROR"))

    async def stream_tts(text: str, send_fn: Any) -> None:
        """Stream TTS audio chunks to client via WebSocket."""
        if not _global_tts:
            return

        audio_chunks = []
        def on_chunk(chunk: bytes) -> None:
            audio_chunks.append(chunk)

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            executor,
            lambda: _global_tts.speak_streaming(text, on_chunk),
        )

        for chunk in audio_chunks:
            try:
                await send_fn(build_msg(MsgType.AUDIO_CHUNK, data=base64.b64encode(chunk).decode()))
            except Exception:
                pass

        try:
            await send_fn(build_msg(MsgType.AUDIO_DONE))
        except Exception:
            pass

    try:
        while True:
            try:
                raw = await ws.receive_json()
            except Exception:
                break

            try:
                msg = parse_message(raw)
            except ValueError as e:
                await send(build_msg(MsgType.ERROR, message=str(e), code="PARSE_ERROR"))
                continue

            msg_type = msg.get("type", "")

            # ── OpenClaw Gateway 协议 ───────────────────────────────
            if msg_type == MsgType.REQ.value:
                # {"type": "req", "id": "...", "method": "...", "params": {...}}
                req_id = msg.get("id", generate_id())
                method = msg.get("method", "")
                params = msg.get("params", {})
                await _handle_openclaw_method(method, params, req_id, send, client_session, conn_id)
                continue

            if msg_type == MsgType.EVENT.value:
                # OpenClaw 事件（客户端发送的事件，如 config.subscribe）
                event = msg.get("event", "")
                payload = msg.get("payload", {})
                if event == "config.subscribe":
                    # 订阅配置变更
                    await send(build_event("config.subscribed", {"status": "ok"}, seq=next_seq()))
                continue

            # ── xiaomei-brain 内部协议 (JSON-RPC 兼容) ─────────────
            if msg_type == "" and "method" in msg:
                # JSON-RPC style
                jsonrpc = msg.get("jsonrpc", "2.0")
                method = msg.get("method", "")
                params = msg.get("params", {})
                id = msg.get("id")

                result = await _handle_rpc(method, params)
                response = {"jsonrpc": jsonrpc, "id": id}
                if "error" in result:
                    response["error"] = result["error"]
                else:
                    response["result"] = result
                await send(response)
                continue

            # ── xiaomei-brain 内部协议 (type 字段) ─────────────────
            if msg_type == MsgType.SESSION_START.value:
                session_id = msg.get("session_id")
                agent_id = msg.get("agent_id", "default")

                if client_session is None:
                    resolved_agent = _get_agent_for_request(agent_id)
                    if resolved_agent is None:
                        await send(build_msg(MsgType.ERROR, message=f"Agent '{agent_id}' not found", code="AGENT_NOT_FOUND"))
                        continue

                    if session_id:
                        client_session = AgentSession(
                            id=session_id,
                            agent=resolved_agent,
                            session_manager=_global_session_manager,
                        )
                        resumed = client_session.restore(session_id)
                    else:
                        session_id = f"ws-{uuid.uuid4().hex[:8]}"
                        client_session = AgentSession(
                            id=session_id,
                            agent=resolved_agent,
                            session_manager=_global_session_manager,
                        )
                        resumed = False
                    cm.set_session(session_id, conn_id)
                else:
                    resumed = False
                await send(build_msg(MsgType.SESSION_STARTED, session_id=client_session.id, resumed=resumed))

            elif msg_type == MsgType.SESSION_END.value:
                if client_session:
                    try:
                        client_session.save()
                    except Exception as e:
                        logger.error("Session save failed: %s", e)
                break

            elif msg_type == MsgType.CHAT.value:
                if client_session is None:
                    session_id = f"ws-{uuid.uuid4().hex[:8]}"
                    client_session = AgentSession(
                        id=session_id,
                        agent=_global_agent,
                        session_manager=_global_session_manager,
                    )
                    cm.set_session(session_id, conn_id)
                    await send(build_msg(MsgType.SESSION_STARTED, session_id=session_id, resumed=False))

                await handle_chat(msg)

            elif msg_type == MsgType.TOOL_CALL.value:
                name = msg.get("name", "")
                params = msg.get("params", {})
                call_id = str(uuid.uuid4())
                try:
                    loop = asyncio.get_event_loop()
                    result = await loop.run_in_executor(
                        executor,
                        lambda: (_global_agent or client_session.agent).tools.execute(name, **params),
                    )
                    await send(build_msg(MsgType.TOOL_CALL_RESULT, call_id=call_id, result=result, error=None))
                except Exception as e:
                    await send(build_msg(MsgType.TOOL_CALL_RESULT, call_id=call_id, result=None, error=str(e)))

            elif msg_type == MsgType.PING.value:
                await send(build_msg(MsgType.PONG))

            else:
                await send(build_msg(MsgType.ERROR, message=f"Unknown type: {msg_type}", code="UNKNOWN_MESSAGE"))

    except WebSocketDisconnect:
        pass
    finally:
        if client_session:
            try:
                client_session.save()
            except Exception as e:
                logger.error("Session save on disconnect failed: %s", e)
        cm.unregister(conn_id)


def _get_agent_for_request(agent_id: str | None) -> Any:
    """Resolve agent instance for a request."""
    if agent_id and _global_agent_manager:
        try:
            agent_instance = _global_agent_manager.build_agent(agent_id, _global_config)
            if agent_instance and agent_instance.llm:
                return _build_agent_from_instance(agent_instance)
        except ValueError:
            pass
    return _global_agent


def _build_agent_from_instance(agent_instance: Any) -> Any:
    """Build a full Agent object from an AgentInstance."""
    from xiaomei_brain import Agent
    from xiaomei_brain.memory import ConversationLogger
    from xiaomei_brain.memory.dream import DreamProcessor
    from xiaomei_brain.memory.scheduler import DreamScheduler
    from xiaomei_brain.agent.reminder import ReminderManager
    from xiaomei_brain.agent.context_extractor import ContextExtractor

    cfg = _global_config
    agent_dir = agent_instance.agent_dir()
    memory_dir = f"{agent_dir}/memory"

    memory = agent_instance.memory
    episodic = agent_instance.episodic_memory
    session_mgr = agent_instance.session_manager
    working_mem = agent_instance.working_memory

    conversation_logger = ConversationLogger(log_dir=f"{memory_dir}/conversations")
    dream_processor = DreamProcessor(
        llm=agent_instance.llm,
        memory=memory,
        conversation_logger=conversation_logger,
        episodic_memory=episodic,
    )
    dream_scheduler = DreamScheduler(dream_processor=dream_processor, idle_threshold=cfg.dream_idle_threshold)
    reminder_manager = ReminderManager(memory_dir=memory_dir, llm_client=agent_instance.llm)

    context_extractor = ContextExtractor(
        llm=agent_instance.llm,
        working_memory=working_mem,
        reminder_manager=reminder_manager,
        message_interval=5,
        time_interval=120,
    )

    system_prompt = agent_instance.get_system_prompt() or cfg.system_prompt
    agent = Agent(
        llm=agent_instance.llm,
        tools=agent_instance.tools,
        system_prompt=system_prompt,
        max_steps=cfg.max_steps,
        memory=memory,
        conversation_logger=conversation_logger,
        dream_scheduler=dream_scheduler,
        episodic_memory=episodic,
        reminder_manager=reminder_manager,
        context_max_tokens=cfg.context_max_tokens,
        context_recent_turns=cfg.context_recent_turns,
        context_extractor=context_extractor,
    )
    agent.working_memory = working_mem
    agent._dream_processor = dream_processor
    return agent


def create_app(agent: Any, tts: Any = None, session_manager: Any = None, agent_manager: Any = None, config: Any = None) -> FastAPI:
    """Create and configure the FastAPI app with shared agent and TTS."""
    global _global_agent, _global_tts, _global_session_manager, _global_agent_manager, _global_config
    _global_agent = agent
    _global_tts = tts
    _global_session_manager = session_manager
    _global_agent_manager = agent_manager
    _global_config = config

    return app
