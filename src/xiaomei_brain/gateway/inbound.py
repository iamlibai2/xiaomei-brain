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
        self._ws_server = None
        self._ws_thread = None

    # ── Dependencies (set after init) ──────────────────────

    def set_identity_mgr(self, mgr) -> None:
        self._identity_mgr = mgr

    def set_agent_commands(self, commands) -> None:
        self._agent_commands = commands

    def set_ws_server(self, server, thread) -> None:
        """注册 WS Gateway，由 Gateway 统一管理生命周期。"""
        self._ws_server = server
        self._ws_thread = thread

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
        """关闭所有通道（含 WS Gateway）。"""
        # 关闭 WS Gateway
        if self._ws_server is not None:
            try:
                self._ws_server.should_exit = True
                logger.info("[Gateway] WS Gateway 已请求关闭")
            except Exception as e:
                logger.warning("[Gateway] 关闭 WS Gateway 失败: %s", e)

        # 关闭所有插件通道适配器
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

        # 7. Command dispatch — all / commands handled here
        if content.startswith("/"):
            handled = self._dispatch_command(content, user_id, session_id)
            if handled:
                return Rejected(reason="HANDLED", silent=True)

        # 8. Enqueue to Living (passes display_name through)
        from xiaomei_brain.consciousness.living import LivingMessage
        msg = self._living.put_message(
            content=content,
            user_id=user_id,
            session_id=session_id,
            source=raw.source,
            images=raw.images,
            display_name=user_display_name,
        )
        # Lightweight test doubles and third-party Living implementations may
        # still return None. Preserve the accepted-message contract for them.
        if msg is None:
            msg = LivingMessage(
                content=content,
                user_id=user_id,
                session_id=session_id,
                source=raw.source,
                images=raw.images,
            )
            msg.user_display_name = user_display_name
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

    # ── Command dispatch ──────────────────────────────────────

    # Data commands routed to MemoryConsole.execute()
    _DATA_CMDS = frozenset({
        "db", "memory", "dag", "context", "clear", "new", "summarize",
        "expand", "periodic", "dream", "user-memories", "relationship", "learn",
        "self", "essence", "stream", "projects", "stats",
    })

    def _dispatch_command(self, content: str, user_id: str, session_id: str) -> bool:
        """统一命令入口。处理所有 / 命令。返回 True 表示已处理。

        顺序：裸 / → 数据命令 → 系统命令 → 未识别（入队当普通消息）
        """
        raw = content.strip()[1:].strip()  # 去掉 /
        living = self._living

        # Bare `/` → list all commands
        if not raw:
            self._list_all_commands()
            living._command_done.set()
            return True

        parts = raw.split(None, 1)
        cmd = parts[0].lower()
        cmd_args = parts[1] if len(parts) > 1 else ""

        # /help — show all commands (data + system)
        if cmd == "help":
            self._list_all_commands()
            living._command_done.set()
            return True

        # 1. Data commands: /db, /context, /dag, etc.
        if self._agent_commands and cmd in self._DATA_CMDS:
            result = self._agent_commands.execute(
                raw, user_id=user_id, session_id=session_id,
            )
            if result:
                print(f"\n{result.output}", flush=True)
                if result.user_id:
                    living.user_id = result.user_id
                    agent_core = living.agent._get_agent()
                    agent_core.user_id = result.user_id
                if result.session_id:
                    living.session_id = result.session_id
                    if hasattr(living, '_attention') and living._attention:
                        living._attention.switch_to(result.session_id)
                living._command_done.set()
                return True

        # 2. /intask /inchat — task/chat mode switch
        if cmd in ("intask", "inchat"):
            cd = getattr(living, 'conversation_driver', None)
            if cd and cd.handle_command(cmd, cmd_args):
                living._command_done.set()
            return True

        # 3. System/debug commands: /intent, /drive, /flame, etc.
        intent_cmds = getattr(living, '_intent_commands', {})
        if cmd in intent_cmds:
            logger.info("[Gateway] 执行系统命令: %s %s", cmd, cmd_args)
            intent_cmds[cmd](cmd_args)
            living._command_done.set()
            return True

        return False

    def _list_all_commands(self) -> None:
        """列出所有可用命令，按功能分组。"""
        living = self._living
        G, D, R = "\033[32m", "\033[38;5;73m", "\033[0m"
        C = "\033[36m"
        CW = 20  # 命令列宽度

        # ── 收集所有命令 → 描述映射 ────────────────────────────
        cmd_desc: dict[str, str] = {}

        # 数据命令
        data_cmds = [
            ("/user <name>",   "切换用户身份"),
            ("/db",            "查看数据库大小/表/行数"),
            ("/memory",        "查看最近长期记忆"),
            ("/stats",         "全局统计面板"),
            ("/stream <N>",    "查看最近经验流（默认20条）"),
            ("/context",       "查看完整上下文"),
            ("/user-memories", "查看用户记忆分布"),
            ("/dag <kw>",      "搜索DAG摘要"),
            ("/expand <kw>",   "展开DAG摘要原文"),
            ("/summarize",     "手动触发DAG压缩"),
            ("/periodic",      "手动触发定时记忆提取"),
            ("/dream",         "手动触发梦境深度提取"),
            ("/relationship",  "查看当前用户的关系数据"),
            ("/self",          "查看当前自我画像"),
            ("/essence",       "查看底色（性格基线）"),
            ("/projects",      "查看项目心智模型"),
            ("/learn",         "查看学习情况（队列 + 已学程序）"),
            ("/clear",         "清空当前会话上下文（数据保留）"),
            ("/new",           "新建会话"),
        ]
        for name, desc in data_cmds:
            cmd_desc[name] = desc

        # 系统命令（从 COMMAND_REGISTRY 取 docstring）
        from ..consciousness.living_commands import COMMAND_REGISTRY
        for name, (handler, _) in COMMAND_REGISTRY.items():
            full = f"/{name}"
            if full not in cmd_desc:  # 数据命令优先
                cmd_desc[full] = (handler.__doc__ or "").strip()

        # 模式切换
        cmd_desc["/intask"] = "进入任务模式"
        cmd_desc["/inchat"] = "退出任务模式"

        # ── 分组 ──────────────────────────────────────────────
        groups = [
            ("记忆与查询", [
                "/db", "/memory", "/stats", "/stream <N>", "/context",
                "/user-memories",
                "/dag <kw>", "/expand <kw>", "/summarize",
                "/periodic", "/dream",
            ]),
            ("会话", [
                "/user <name>", "/clear", "/new", "/sessions", "/switch <id>",
                "/export", "/intask", "/inchat",
            ]),
            ("自我认知", [
                "/self", "/essence", "/identity", "/flame", "/projects",
            ]),
            ("意识与驱动", [
                "/intent", "/fuel", "/tick", "/think",
                "/drive", "/purpose", "/pace-stats",
                "/relationship", "/learn",
            ]),
            ("身体与感官", [
                "/ears", "/eyes", "/hear", "/listen", "/look", "/see",
                "/register", "/touch",
            ]),
            ("系统", ["/model", "/mcp", "/plan", "/tool"]),
        ]

        # ── 渲染 ──────────────────────────────────────────────
        print()
        print(f"  {C}命令列表{R}")
        for group_name, cmd_names in groups:
            entries = [(n, cmd_desc.get(n, "")) for n in cmd_names if n in cmd_desc]
            if not entries:
                continue
            print(f"\n  {C}── {group_name} ──{R}")
            for name, desc in entries:
                print(f"  {G}{name:<{CW}}{R} {D}{desc}{R}", flush=True)
