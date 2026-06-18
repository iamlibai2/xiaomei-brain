"""Gateway — 统一入站门。所有外部消息的唯一入口。

Gateway = 感官/运动神经：接收信号 → 过滤噪声 → 送达意识层。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    pass

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
        # Use Router if rules exist (returns default "main" if no match)
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
        raw_cmd = content.strip()
        if raw_cmd.startswith("/"):
            raw_cmd = raw_cmd[1:].strip()
        cmd = raw_cmd.split(None, 1)[0].lower() if raw_cmd else ""
        # Only handle data commands here; /intask /inchat stay in Consciousness
        if cmd in ("db", "memory", "dag"):
            result = self._agent_commands.execute(raw_cmd, user_id=user_id, session_id=session_id)
            if result:
                print(f"\n{result.output}", flush=True)
                return True
        return False
