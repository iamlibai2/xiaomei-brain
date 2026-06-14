"""HTTPP2PAdapter: Agent 间 HTTP P2P 通道适配器。"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from ...gateway.channel_adapter import ChannelAdapter

if TYPE_CHECKING:
    from .directory import AgentDirectory

logger = logging.getLogger(__name__)


def register(ctx):
    """插件入口：注册 HTTP P2P 频道。"""
    ctx.register_channel("http_p2p", HTTPP2PAdapter(ctx.agent_id))


class HTTPP2PAdapter(ChannelAdapter):
    """Agent 间 HTTP P2P 通道适配器。

    通过 comms HTTP 客户端向其他 agent 发送消息。
    封装 AgentMessage 创建和 HTTP POST 调用。
    """

    def __init__(self, agent_id: str, directory: AgentDirectory | None = None) -> None:
        self._agent_id = agent_id
        self._directory = directory
        self._server = None  # setup() 时赋值

    def set_directory(self, directory: AgentDirectory) -> None:
        """注入通讯录。"""
        self._directory = directory

    def setup(self, living=None) -> None:
        """启动 P2P 通讯：收件箱 + 通讯录 + HTTP 服务器。"""
        if living is None:
            return

        db_path = getattr(living.agent, "db_path", None) or os.path.expanduser(
            f"~/.xiaomei-brain/{living._agent_id}/memory/brain.db"
        )
        from .inbox import AgentInbox
        from .directory import AgentDirectory

        # 收件箱
        living._inbox = AgentInbox(db_path)

        # 通讯录
        living._directory = getattr(living.agent, "_directory", None) or AgentDirectory()
        self._directory = living._directory

        # HTTP 服务器
        comms_port = living._config.living.comms_port
        if comms_port < 0:
            logger.info("[HTTPP2PAdapter] P2P 通讯已禁用 (comms_port=%d)", comms_port)
            return

        host = "0.0.0.0"
        if comms_port > 0:
            ports_to_try = [comms_port]
        else:
            # 按 agent_id 确定性分配固定端口，避免 agent 间端口碰撞
            import hashlib
            base = 18765 + (int(hashlib.md5(self._agent_id.encode()).hexdigest(), 16) % 100)
            ports_to_try = [base]
        from ...gateway.comms_server import start_comms_server_in_thread

        for port in ports_to_try:
            try:
                thread, server = start_comms_server_in_thread(
                    inbox=living._inbox,
                    agent_id=self._agent_id,
                    host=host,
                    port=port,
                    on_receive=living._on_comms_receive,
                )
                living._comms_thread = thread
                living._comms_server = server
                self._server = server
                living._directory.register(self._agent_id, f"{host}:{port}")
                logger.info("[HTTPP2PAdapter] P2P 通讯服务已启动: %s:%d", host, port)
                break
            except OSError:
                logger.debug("[HTTPP2PAdapter] 端口 %d 被占用，尝试下一个", port)
                continue
        else:
            logger.warning("[HTTPP2PAdapter] P2P 通讯服务启动失败（所有端口被占用）")

    def ping(self, target: str) -> bool:
        """检查目标 agent 是否可达（不发送消息）。"""
        if not self._directory:
            return False
        address = self._directory.resolve(target)
        if not address:
            return False
        import urllib.request
        try:
            req = urllib.request.Request(
                f"http://{address}/health",
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=3) as resp:
                return 200 <= resp.status < 300
        except Exception:
            return False

    def send(self, target: str, text: str, msg_type: str = "text") -> None:
        """向目标 agent 发送 HTTP 消息。

        Args:
            target: 目标 agent_id
            text: 消息内容（默认作为 chat 类型发送）
        """
        if not self._directory:
            logger.warning("[HTTPP2PAdapter] 通讯录未设置，无法发送到 %s", target)
            return

        from .protocol import AgentMessage, MsgType
        from .client import send_message as _send

        msg = AgentMessage(
            type=MsgType.CHAT,
            from_agent=self._agent_id,
            to_agent=target,
            content=text,
        )

        ok, detail = _send(msg, directory=self._directory)
        if ok:
            logger.debug("[HTTPP2PAdapter] -> %s OK [%s]", target, msg.msg_id)
        else:
            logger.warning("[HTTPP2PAdapter] -> %s 失败: %s", target, detail)

    def shutdown(self) -> None:
        """关闭 P2P HTTP 服务器。"""
        if self._server is not None:
            try:
                self._server.shutdown()
                logger.info("[HTTPP2PAdapter] P2P 通讯服务已关闭")
            except Exception as e:
                logger.warning("[HTTPP2PAdapter] 关闭 P2P 通讯服务失败: %s", e)

    @property
    def channel_type(self) -> str:
        return "http_p2p"
