"""Router: 消息路由 + 输出分发。

统一入口 + 统一出口。所有消息经过 Router 进出。

职责：
- 注册 Peer 映射：{peer_key} → {session_id, OutputRoute}
- 消息路由：InboundMsg → RoutedMsg（确定性规则匹配）
- 输出分发：RoutedMsg → ChannelAdapter.send()

LLM 不感知路由细节。路由是纯规则驱动的。
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


# ── Data Types ────────────────────────────────────────────────


@dataclass
class OutputRoute:
    """输出路由——回复应该发到哪个通道。"""
    type: str       # "cli" | "http_p2p" | "ws" | "feishu" | ...
    target: str     # "stdout" | agent_id | client_id | ...

    def __hash__(self) -> int:
        return hash((self.type, self.target))


@dataclass
class InboundMsg:
    """统一入站消息——从各 ChannelAdapter 到达。"""
    content: str
    peer_type: str = "human"     # "human" | "agent"
    peer_id: str = ""            # "libai" | "lingkong"
    channel: str = "cli"         # "cli" | "http_p2p" | "ws" | "feishu"
    images: list[str] = field(default_factory=list)
    raw_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RoutedMsg:
    """路由结果——映射到会话和输出路由。"""
    session_id: str
    content: str
    user_id: str = "global"
    images: list[str] = field(default_factory=list)
    output_route: OutputRoute = field(default_factory=lambda: OutputRoute("cli", "stdout"))
    source: str = ""


# ── Rule ──────────────────────────────────────────────────────


@dataclass
class PeerRule:
    """一条 Peer 匹配规则。"""
    peer_type: str      # "human" | "agent"
    peer_id: str        # "libai" | "lingkong" | "*" (wildcard)
    channel: str = "*"  # "cli" | "http_p2p" | "*" (wildcard)
    session_id: str = ""
    output_route: OutputRoute = field(default_factory=lambda: OutputRoute("cli", "stdout"))
    priority: int = 0   # 分数越高越优先


# ── Router ─────────────────────────────────────────────────────


class Router:
    """消息路由 + 输出分发。

    通过规则匹配将 InboundMsg 映射到 session + OutputRoute，
    通过 ChannelAdapter 将输出分发到正确的通道。
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._rules: list[PeerRule] = []
        self._adapters: dict[str, Any] = {}   # channel_type → ChannelAdapter
        self._default_route = OutputRoute("cli", "stdout")

    # ── Rules ──────────────────────────────────────────────

    def add_rule(self, rule: PeerRule) -> None:
        """添加一条路由规则。"""
        with self._lock:
            self._rules.append(rule)
            self._rules.sort(key=lambda r: r.priority, reverse=True)
        logger.info(
            "[Router] 添加规则: %s/%s → session=%s, route=%s/%s (priority=%d)",
            rule.peer_type, rule.peer_id, rule.session_id,
            rule.output_route.type, rule.output_route.target, rule.priority,
        )

    def remove_peer(self, peer_id: str) -> None:
        """移除指定 peer_id 的所有路由规则（用于连接断开时清理）。"""
        removed = 0
        with self._lock:
            before = len(self._rules)
            self._rules = [r for r in self._rules if r.peer_id != peer_id]
            removed = before - len(self._rules)
        if removed:
            logger.info("[Router] 移除规则: peer_id=%s (%d条)", peer_id, removed)

    def register_peer(
        self,
        peer_type: str,
        peer_id: str,
        channel: str = "*",
        session_id: str = "",
        output_type: str = "cli",
        output_target: str = "stdout",
        priority: int = 0,
    ) -> None:
        """便捷方法：注册一个 Peer 映射。"""
        self.add_rule(PeerRule(
            peer_type=peer_type,
            peer_id=peer_id,
            channel=channel,
            session_id=session_id or peer_id,
            output_route=OutputRoute(output_type, output_target),
            priority=priority,
        ))

    # ── Adapters ────────────────────────────────────────────

    def register_adapter(self, channel_type: str, adapter: Any) -> None:
        """注册一个 ChannelAdapter。"""
        self._adapters[channel_type] = adapter
        logger.info("[Router] 注册适配器: %s", channel_type)

    def get_adapter(self, channel_type: str) -> Any | None:
        return self._adapters.get(channel_type)

    # ── Routing ─────────────────────────────────────────────

    def route(self, msg: InboundMsg) -> RoutedMsg:
        """将入站消息路由到会话。按优先级匹配规则，无匹配则使用默认路由。"""
        with self._lock:
            best_score = -1
            best_rule: PeerRule | None = None

            for rule in self._rules:
                score = self._match_score(rule, msg)
                if score > best_score:
                    best_score = score
                    best_rule = rule

            if best_rule:
                return RoutedMsg(
                    session_id=best_rule.session_id,
                    content=msg.content,
                    user_id=msg.peer_id if msg.peer_type == "human" else "global",
                    images=msg.images,
                    output_route=best_rule.output_route,
                    source=msg.channel,
                )

        # 默认：cli session
        return RoutedMsg(
            session_id="main",
            content=msg.content,
            user_id=msg.peer_id or "global",
            images=msg.images,
            output_route=self._default_route,
            source=msg.channel,
        )

    def route_for_session(self, session_id: str) -> OutputRoute | None:
        """查询指定会话的输出路由。"""
        with self._lock:
            for rule in self._rules:
                if rule.session_id == session_id:
                    return rule.output_route
        return None

    # ── Delivery ────────────────────────────────────────────

    def check_route(self, route: OutputRoute) -> bool:
        """检查路由是否可达（不发送消息）。"""
        adapter = self._adapters.get(route.type)
        if adapter and hasattr(adapter, 'ping'):
            return adapter.ping(route.target)
        return True  # 无 ping 方法的 adapter 默认可达

    def deliver(self, text: str, route: OutputRoute, msg_type: str = "text") -> bool:
        """将文本分发到指定路由的通道。返回 True 表示成功。"""
        adapter = self._adapters.get(route.type)
        if adapter:
            try:
                adapter.send(route.target, text, msg_type=msg_type)
                return True
            except Exception as e:
                logger.warning("[Router] 分发失败 (%s/%s): %s", route.type, route.target, e)
                return False
        else:
            logger.debug("[Router] 无适配器: %s", route.type)
            return False

    # ── Internal ────────────────────────────────────────────

    @staticmethod
    def _match_score(rule: PeerRule, msg: InboundMsg) -> int:
        """计算规则匹配度。不匹配返回 -1。"""
        score = 0

        # peer_type 必须精确匹配
        if rule.peer_type != msg.peer_type:
            return -1
        score += 10

        # peer_id 匹配
        if rule.peer_id == "*":
            score += 0   # wildcard, no bonus
        elif rule.peer_id == msg.peer_id:
            score += 5
        else:
            return -1

        # channel 匹配
        if rule.channel == "*":
            score += 0
        elif rule.channel == msg.channel:
            score += 1
        else:
            return -1

        return score
