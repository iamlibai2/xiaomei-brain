"""MessageGateway -- message entry preprocessing layer.

After Gateway.accept() has already handled sanitization, empty-filtering,
identity resolution, queue admission, and data commands (/db /memory /dag), this
layer handles:

- Inter-agent communication routing
- Session switching (AttentionLayer)
- Intent command dispatch (/intask, /inchat)
- Meta-skill pattern matching
- Drive activation

Finally delegates to ConversationDriver.handle_message().

MessageGateway -- 消息入口预处理层。

Gateway.accept() 已处理清洗、空消息过滤、身份解析、入队和数据命令后，
此层处理：

- Agent 间通讯路由
- 会话切换（AttentionLayer）
- 意图命令分发（/intask, /inchat）
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


def configure_agent_conversation_scope(
    agent_core,
    living,
    session_id: str,
    person_id: str,
    context_key: str = "",
) -> str:
    """Separate speaker identity from the current scene's memory boundary."""
    target_context = context_key
    if not target_context:
        people = getattr(living, "_people_service", None)
        session = people.store.get_session(session_id) if people else None
        if session is not None and session.scope_type == "conversation":
            target_context = f"conversation:{session.scope_id}"
        else:
            target_context = f"session:{session_id}"
    agent_core.memory_scope_id = person_id
    agent_core.shared_conversation = False
    if target_context.startswith("conversation:"):
        agent_core.memory_scope_id = target_context
        agent_core.shared_conversation = True
    return target_context


class MessageGateway:
    """Message entry: comms routing, intent commands, meta-skill matching,
    then delegate to ConversationDriver.

    消息入口：comms 路由、意图命令、元技能匹配，然后委托 ConversationDriver。
    """

    def handle(self, msg: LivingMessage, living: ConsciousLiving) -> None:
        """Preprocess message: comms routing, session switch, intent commands,
        meta-skill matching. Then delegate to ConversationDriver.

        Sanitization, empty check, queue admission, and identity resolution are
        now handled by Gateway.accept() before the message reaches this point.

        预处理消息：comms 路由、会话切换、意图命令、元技能匹配，
        然后委托 ConversationDriver。
        """
        logger.debug("[MessageGateway] 收到消息: %s [session=%s]", msg.content[:50], msg.session_id)

        # 1. Inter-agent communication.
        # 1. Agent 间通讯。
        if msg.session_id.startswith("comms-"):
            living._debug_log("living",
                f"{time.strftime('%H:%M:%S')} 收到 agent 消息 [{msg.session_id}]: {msg.content[:60]}"
            )
            living._handle_comms_message(msg)
            return

        # 2. Sync user identity to the underlying agent core for memory scoping.
        # 2. 同步用户身份到底层 agent core，用于记忆隔离。
        agent_core = living.agent._get_agent()
        agent_core.user_id = msg.user_id
        agent_core.user_display_name = getattr(msg, 'user_display_name', '这位用户')
        context_key = configure_agent_conversation_scope(
            agent_core,
            living,
            msg.session_id,
            msg.user_id,
            msg.context_key,
        )

        # 3. Context switch. session_id remains the persistence and routing key.
        # 3. 上下文切换。session_id 继续作为持久化与路由标识。
        living.session_id = msg.session_id
        if hasattr(living, '_attention') and living._attention:
            living._attention.switch_to(context_key)
        else:
            agent_core.context_key = context_key
        agent_core.session_id = msg.session_id

        # 4. Reset cancel flag.
        # 4. 重置取消标志。
        living._cancel_requested = False

        # 5. Meta-skill pattern matching.
        #    All commands handled upstream by Gateway.accept().
        # 5. 元技能模式匹配。
        #    所有命令由上游 Gateway.accept() 处理。
        if self._try_meta_skill(msg, living):
            return

        # The Agent and its channels stay online when the selected model is
        # unavailable. Reject through the normal message lifecycle before
        # building memory/context or making another provider request.
        model_error_getter = getattr(living, "current_model_service_error", None)
        model_error = model_error_getter() if callable(model_error_getter) else None
        if model_error:
            living.conversation_driver.reject_message(msg, model_error)
            return

        # 6. Drive activation.
        # 6. Drive 激活。
        if living.drive:
            living.drive.on_user_active()

        # 7. Delegate to ConversationDriver with full consciousness state.
        # 7. 委托 ConversationDriver，传入完整 consciousness state。
        living.conversation_driver.handle_message(msg, living._get_consciousness_state())

        # 8. Round alarms.
        # 8. 轮次闹钟。
        if living.cron_scheduler:
            living._check_round_alarms()

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
        living._command_done.set()
        return True
