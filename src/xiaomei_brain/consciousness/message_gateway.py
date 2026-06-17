"""MessageGateway -- message entry preprocessing layer.

Before the message enters ConversationDriver, performs:
- Empty message / re-entry filtering
- Inter-agent communication routing
- Identity resolution (IdentityManager)
- Session switching (AttentionLayer)
- Command detection and dispatch (/intent, /fuel, /db, etc.)
- Meta-skill pattern matching
- Drive activation

Finally delegates to ConversationDriver.handle_message().

MessageGateway -- 消息入口预处理层。

在消息进入 ConversationDriver 之前，完成：
- 空消息 / 重入过滤
- Agent 间通讯路由
- 身份解析（IdentityManager）
- 会话切换（AttentionLayer）
- 命令检测与分发（/intent, /fuel, /db 等）
- 元技能模式匹配
- Drive 激活

最后委托给 ConversationDriver.handle_message()。
"""

from __future__ import annotations

import logging
import re
import time
from typing import TYPE_CHECKING

from .living import LivingMessage

if TYPE_CHECKING:
    from .conscious_living import ConsciousLiving

logger = logging.getLogger(__name__)


class MessageGateway:
    """Message entry: command detection, identity resolution, session switching,
    then delegate to ConversationDriver.

    消息入口：命令检测、身份解析、会话切换，然后委托 ConversationDriver。
    """

    def handle(self, msg: LivingMessage, living: ConsciousLiving) -> None:
        # 1. Ignore empty messages.
        # 1. 忽略空消息。
        if not msg.content or not msg.content.strip():
            logger.debug("[MessageGateway] 忽略空消息")
            return

        # 2. Re-entry guard.
        # 2. 防重入。
        if living._chatting:
            living._debug_log("living", f"{time.strftime('%H:%M:%S')} 消息 (忽略，chatting): {msg.content[:30]}")
            logger.info("[MessageGateway] 聊天进行中，忽略新消息: %s", msg.content[:30])
            return

        logger.debug("[MessageGateway] 收到消息: %s [session=%s]", msg.content[:50], msg.session_id)

        # 3. Inter-agent communication.
        # 3. Agent 间通讯。
        if msg.session_id.startswith("comms-"):
            living._debug_log("living",
                f"{time.strftime('%H:%M:%S')} 收到 agent 消息 [{msg.session_id}]: {msg.content[:60]}"
            )
            living._handle_comms_message(msg)
            return

        # 4. Identity resolution.
        # 4. 身份解析。
        self._resolve_identity(msg, living)

        # 5. Sync user identity to the underlying agent core for memory scoping.
        # 5. 同步用户身份到底层 agent core，用于记忆隔离。
        agent_core = living.agent._get_agent()
        agent_core.user_id = msg.user_id
        agent_core.user_display_name = getattr(msg, 'user_display_name', '这位用户')

        # 6. Session switch.
        # 6. 会话切换。
        # Update current session ID for output routing.
        # 更新当前会话 ID（用于输出路由）。
        living.session_id = msg.session_id
        if hasattr(living, '_attention') and living._attention:
            living._attention.switch_to(msg.session_id)

        # 7. Reset cancel flag.
        # 7. 重置取消标志。
        living._cancel_requested = False

        # 8. Command detection.
        # 8. 命令检测。
        if self._try_handle_command(msg, living):
            return

        # 9. Meta-skill pattern matching.
        # 9. 元技能模式匹配。
        if self._try_meta_skill(msg, living):
            return

        # 10. Drive activation.
        # 10. Drive 激活。
        if living.drive:
            living.drive.on_user_active()

        # 11. Delegate to ConversationDriver with full consciousness state.
        # 11. 委托 ConversationDriver，传入完整 consciousness state。
        living.conversation_driver.handle_message(msg, living._get_consciousness_state())
        living._print_prompt()

        # 12. Round alarms.
        # 12. 轮次闹钟。
        if living.cron_scheduler:
            living._check_round_alarms()

    #---------------------------------------------------------------------------
    #   Identity
    #   身份解析
    #---------------------------------------------------------------------------

    @staticmethod
    def _resolve_identity(msg: LivingMessage, living: ConsciousLiving) -> None:
        # Resolve user identity via IdentityManager and set display name on msg.
        # 通过 IdentityManager 解析用户身份，设置 msg 上的 display name。
        identity_mgr = getattr(living, '_identity_mgr', None)
        if identity_mgr:
            identity = identity_mgr.resolve(msg.user_id) if msg.user_id else None
            if identity:
                msg.user_display_name = identity_mgr.get_display_name(msg.user_id)
                logger.debug("[MessageGateway] 身份已确认: id=%s", msg.user_id)
            else:
                msg.user_display_name = getattr(msg, 'user_display_name', None) or "这位用户"
                logger.debug("[MessageGateway] 身份未确认: sender=%s", msg.session_id)
        else:
            msg.user_display_name = "这位用户"

    #---------------------------------------------------------------------------
    #   Commands
    #   命令处理
    #---------------------------------------------------------------------------

    @staticmethod
    def _try_handle_command(msg: LivingMessage, living: ConsciousLiving) -> bool:
        """Detect and handle commands.

        Returns True if handled (caller should return).

        检测并处理命令。返回 True 表示已处理（调用方应 return）。
        """
        raw = msg.content.strip()
        if raw.startswith("/"):
            raw = raw[1:].strip()
        parts = raw.split(None, 1)
        cmd = parts[0].lower() if parts else ""
        cmd_args = parts[1] if len(parts) > 1 else ""

        # /intask /inchat -- handled by GoalManager via ConversationDriver.
        # /intask /inchat -- 由 GoalManager 处理（通过 ConversationDriver）。
        if cmd in ("intask", "inchat"):
            if living.conversation_driver.handle_command(cmd, cmd_args):
                living._print_prompt()
                living._command_done.set()
            return True

        # Bare `/` -> list all commands.
        # 裸 `/` -> 列出所有命令。
        if not cmd:
            living._list_commands()
            living._command_done.set()
            return True

        # Test / debug commands.
        # 测试/调试命令。
        if cmd in living._intent_commands:
            logger.info("[MessageGateway] 执行测试命令: %s %s", cmd, cmd_args)
            handler = living._intent_commands[cmd]
            handler(cmd_args)
            living._command_done.set()
            return True

        # Agent commands (/db, /memory, /dag).
        # Agent 命令（/db, /memory, /dag）。
        if living.agent.commands:
            result = living.agent.commands.execute(
                raw,
                user_id=msg.user_id,
                session_id=msg.session_id,
            )
            if result:
                logger.info("[MessageGateway] Agent 命令: %s", raw)
                print(f"\n{result.output}", flush=True)
                living._print_prompt()
                living._command_done.set()
                return True

        return False

    #---------------------------------------------------------------------------
    #   Meta Skill
    #   元技能
    #---------------------------------------------------------------------------

    @staticmethod
    def _try_meta_skill(msg: LivingMessage, living: ConsciousLiving) -> bool:
        """Meta-skill pattern matching.

        Matches patterns like "去学 XX 技能" / "帮我找 XX skill" / "搜索 XX 技能".
        Enqueues an ActionItem for the dispatcher to pull the skill from remote.
        Returns True if handled.

        元技能模式匹配："去学 XX 技能" / "帮我找 XX skill" / "搜索 XX 技能"。
        将 ActionItem 放入 dispatcher 队列，由 dispatcher 远程拉取 skill。
        返回 True 表示已处理。
        """
        raw = msg.content.strip()
        meta_skill_pattern = re.compile(r'(去学|帮我找|搜索|找一个?).*(技能|skill)', re.IGNORECASE)
        if not meta_skill_pattern.search(raw):
            return False

        domain = re.sub(r'(去学|帮我找|搜索|找一个?|技能|skill|一下|一个|的)', '', raw).strip()
        if not domain:
            return False

        from .action_item import ActionItem, ActionType
        action_item = ActionItem(
            action_type=ActionType.TOOL,
            content="meta_skill_pull",
            reason=f"对方要求学习技能: {domain}",
            priority=0.85,
            source="intent",
            cooldown_key=f"meta_skill_pull_{domain}",
            metadata={"skill_domain": domain},
        )
        living._dispatcher._queue.append(action_item)
        living._dispatcher.process_queue()
        living._print_prompt()
        living._command_done.set()
        return True
