"""MessageGateway: 消息入口预处理层。

在消息进入 ConversationDriver 之前，完成：
- 空消息/重入过滤
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
    """消息入口：命令检测、身份解析、会话切换，然后委托 ConversationDriver。"""

    def handle(self, msg: LivingMessage, living: ConsciousLiving) -> None:
        # 1. 忽略空消息
        if not msg.content or not msg.content.strip():
            logger.debug("[MessageGateway] 忽略空消息")
            return

        # 2. 防重入
        if living._chatting:
            living._debug_log("living", f"{time.strftime('%H:%M:%S')} 消息 (忽略，chatting): {msg.content[:30]}")
            logger.info("[MessageGateway] 聊天进行中，忽略新消息: %s", msg.content[:30])
            return

        logger.debug("[MessageGateway] 收到消息: %s [session=%s]", msg.content[:50], msg.session_id)

        # 3. Agent 间通讯
        if msg.session_id.startswith("comms-"):
            living._debug_log("living",
                f"{time.strftime('%H:%M:%S')} 收到 agent 消息 [{msg.session_id}]: {msg.content[:60]}"
            )
            living._handle_comms_message(msg)
            return

        # 4. 身份解析
        self._resolve_identity(msg, living)

        # 5. 设置 agent_core 用户信息
        agent_core = living.agent._get_agent()
        agent_core.user_id = msg.user_id
        agent_core.user_display_name = getattr(msg, 'user_display_name', '这位用户')

        # 6. 会话切换
        if hasattr(living, '_attention') and living._attention:
            living._attention.switch_to(msg.session_id)

        # 7. 重置取消标志
        living._cancel_requested = False

        # 8. 命令检测
        if self._try_handle_command(msg, living):
            return

        # 9. 元技能模式匹配
        if self._try_meta_skill(msg, living):
            return

        # 10. Drive 激活
        if living.drive:
            living.drive.on_user_active()

        # 11. 委托 ConversationDriver
        living.conversation_driver.handle_message(msg, living._get_consciousness_state())
        living._print_prompt()

        # 12. 轮次闹钟
        if living.cron_scheduler:
            living._check_round_alarms()

    # ── Identity ──────────────────────────────────────────────────

    @staticmethod
    def _resolve_identity(msg: LivingMessage, living: ConsciousLiving) -> None:
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

    # ── Commands ──────────────────────────────────────────────────

    @staticmethod
    def _try_handle_command(msg: LivingMessage, living: ConsciousLiving) -> bool:
        """检测并处理命令。返回 True 表示已处理（调用方应 return）。"""
        raw = msg.content.strip()
        if raw.startswith("/"):
            raw = raw[1:].strip()
        parts = raw.split(None, 1)
        cmd = parts[0].lower() if parts else ""
        cmd_args = parts[1] if len(parts) > 1 else ""

        # /intask /inchat → ConversationDriver/GoalManager
        if cmd in ("intask", "inchat"):
            if living.conversation_driver.handle_command(cmd, cmd_args):
                living._print_prompt()
                living._command_done.set()
            return True

        # 裸 `/` → 列出所有命令
        if not cmd:
            living._list_commands()
            living._command_done.set()
            return True

        # 测试/调试命令
        if cmd in living._intent_commands:
            logger.info("[MessageGateway] 执行测试命令: %s %s", cmd, cmd_args)
            handler = living._intent_commands[cmd]
            handler(cmd_args)
            living._command_done.set()
            return True

        # Agent 命令（/db, /memory, /dag）
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

    # ── Meta Skill ────────────────────────────────────────────────

    @staticmethod
    def _try_meta_skill(msg: LivingMessage, living: ConsciousLiving) -> bool:
        """元技能模式匹配："去学 XX 技能" / "帮我找 XX skill"。返回 True 表示已处理。"""
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
