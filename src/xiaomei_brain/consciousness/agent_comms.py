"""AgentComms: Agent 间通讯。

处理 agent 间消息的接收、回复、收件箱轮询。
不负责初始化（_setup_comms 留在 ConsciousLiving，属于装配层）。
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


class AgentComms:
    """Agent 间通讯：消息处理、收件箱检查、系统提示词。"""

    # ── Inbox polling ──────────────────────────────────────────────

    @staticmethod
    def check_inbox(living: ConsciousLiving) -> None:
        """检查收件箱（兜底：处理回调遗漏的消息）。

        on_receive 回调已在实时处理大多数消息。
        这里只处理遗漏的（如启动前/关闭期间收到的）。
        注入消息原文（而非 [系统通知]），让 LLM 直接处理。
        """
        count = living._inbox.count_unprocessed()
        if count == 0:
            return

        if living._chatting:
            logger.info(
                "[AgentComms/Inbox] 收件箱有 %d 条未读消息（聊天中，下轮检查）", count,
            )
            return

        unprocessed = living._inbox.get_unprocessed(limit=50)
        for msg in unprocessed:
            session_id = f"comms-{msg.from_agent}"

            # 注册 peer（如果尚未注册）—— 必须先注册再路由
            if hasattr(living, '_router') and living._router:
                existing = living._router.route_for_session(session_id)
                if existing is None or existing.type != "http_p2p":
                    living._router.register_peer(
                        peer_type="agent", peer_id=msg.from_agent,
                        channel="http_p2p", session_id=session_id,
                        output_type="http_p2p", output_target=msg.from_agent,
                        priority=10,
                    )

            logger.info(
                "[AgentComms/Inbox] %s: 1 条未读消息 → %s 会话（兜底）",
                msg.from_agent, session_id,
            )
            content = f"[来自 {msg.from_agent}] ({msg.type.value})\n{msg.content}"
            gw = getattr(living, '_gateway_inbound', None)
            if gw:
                from xiaomei_brain.gateway.inbound import RawMessage
                result = gw.accept(RawMessage(
                    content=content, source="agent", channel="comms",
                    peer_id=msg.from_agent, peer_type="agent",
                    session_id=session_id,
                ))
                if hasattr(result, 'reason'):
                    logger.warning(
                        "[AgentComms/Inbox] %s 消息被拒绝 (%s)，稍后重试",
                        msg.from_agent, result.reason,
                    )
                    continue
            else:
                living.put_message(content, source="agent", session_id=session_id)
            living._inbox.mark_processed(msg.msg_id)

    # ── HTTP callback ──────────────────────────────────────────────

    @staticmethod
    def on_receive(living: ConsciousLiving, msg) -> None:
        """HTTP 回调：收到 agent 消息 → 注册 peer → 直接注入消息队列。

        在 HTTP server 线程中调用，需线程安全。
        """
        session_id = f"comms-{msg.from_agent}"

        # 先注册 peer（确保 Router 能匹配到），再放入队列
        existing = living._router.route_for_session(session_id)
        if existing is None:
            living._router.register_peer(
                peer_type="agent", peer_id=msg.from_agent,
                channel="http_p2p", session_id=session_id,
                output_type="http_p2p", output_target=msg.from_agent,
                priority=10,
            )

        content = f"[来自 {msg.from_agent}] ({msg.type.value})\n{msg.content}"
        gw = getattr(living, '_gateway_inbound', None)
        if gw:
            from xiaomei_brain.gateway.inbound import RawMessage
            gw.accept(RawMessage(
                content=content, source="agent", channel="comms",
                peer_id=msg.from_agent, peer_type="agent",
                session_id=session_id,
            ))
        else:
            living.put_message(content, source="agent", session_id=session_id)
        living._inbox.mark_processed(msg.msg_id)
        ts = time.strftime("%H:%M:%S")
        living._debug_log("comms", f"{ts} ← {msg.from_agent}: {msg.content[:80]}")
        # 打印到终端（完整内容，不截断）
        print(f"\n\033[35m[{ts} ← {msg.from_agent}]\033[0m {msg.content}", flush=True)
        logger.debug(
            "[AgentComms/Receive] %s → %s 会话 (实时) %d 字",
            msg.from_agent, session_id, len(msg.content),
        )

    # ── Message handling (ReAct + Router.deliver) ──────────────────

    @staticmethod
    def handle_message(living: ConsciousLiving, msg: LivingMessage) -> None:
        """处理 agent 间通讯消息：静默 ReAct → Router.deliver() 自动送达。

        LLM 不知道消息怎么送达的，它只是在跟当前 session 的人说话。
        """
        target_agent = msg.session_id.replace("comms-", "")

        # 先检查目标是否可达，不通就不调 LLM
        route = living._router.route_for_session(msg.session_id)
        if route and not living._router.check_route(route):
            logger.warning("[AgentComms] 目标不可达: %s", target_agent)
            return

        living._chatting = True
        try:
            agent_core = living.agent._get_agent()
            # 切换到 comms session，stream() 的 self.messages 自动分桶
            saved_session = agent_core.session_id
            agent_core.session_id = f"comms-{target_agent}"

            system_prompt = AgentComms._build_system_prompt(living, target_agent)
            assembled = [{"role": "system", "content": system_prompt}]
            if msg.content:
                assembled.append({"role": "user", "content": msg.content})
                # 记录 incoming agent 消息到 DB（分桶隔离，不污染主对话）
                if agent_core.conversation_db:
                    agent_core.conversation_db.log(
                        session_id=agent_core.session_id,
                        role="user",
                        content=msg.content,
                        user_id=agent_core.user_id,
                    )

                # 经验流：收到其他 agent 消息
                es = getattr(agent_core, "exp_stream", None)
                if es:
                    try:
                        es.log(
                            type="user_msg",
                            content=f"[来自 {target_agent}] {msg.content[:500]}",
                            session_id=agent_core.session_id,
                            importance=0.4,
                        )
                    except Exception as e:
                        logger.debug("[ExpStream] comms_receive write failed: %s", e)

            # 静默 ReAct — reasoning_content 以灰色 ANSI 包裹
            chunks: list[str] = []
            for chunk in agent_core.stream(messages=assembled):
                chunks.append(chunk)
            raw_text = "".join(chunks)

            # 提取思考过程记入日志
            reasoning_parts = re.findall(r'\033\[2m(.*?)\033\[0m', raw_text, flags=re.DOTALL)
            if reasoning_parts:
                reasoning_text = " ".join(r.strip() for r in reasoning_parts if r.strip())
                if reasoning_text:
                    logger.debug("[AgentComms/思考] %s (%d 字): %s",
                                target_agent, len(reasoning_text), reasoning_text[:200])

            # 去掉 reasoning_content → 只发给对方最终输出
            clean_text = re.sub(r'\033\[2m.*?\033\[0m', '', raw_text, flags=re.DOTALL)
            clean_text = re.sub(r'\x1b\[[0-9;]*m', '', clean_text)
            clean_text = clean_text.strip()

            # Router.deliver() 自动送达
            if clean_text:
                route = living._router.route_for_session(msg.session_id)
                if route:
                    if living._router.deliver(clean_text, route):
                        ts = time.strftime("%H:%M:%S")
                        living._debug_log("comms", f"{ts} → {target_agent}: {clean_text[:80]}")
                        # 终端打印完整内容（含思考过程，ANSI 天然区分）
                        print(f"\n\033[36m[{ts} → {target_agent}]\033[0m {raw_text}", flush=True)
                        logger.debug(
                            "[AgentComms] 自动回复 %s (%d 字): %s",
                            target_agent, len(clean_text), clean_text[:100],
                        )
                    else:
                        logger.warning("[AgentComms] 发送失败: %s", target_agent)
                else:
                    logger.warning("[AgentComms] 无输出路由: %s", msg.session_id)
            else:
                logger.info("[AgentComms] %s 消息无需回复", target_agent)
        except Exception as e:
            logger.error("[AgentComms] 处理失败: %s", e)
        finally:
            agent_core.session_id = saved_session
            living._chatting = False

    # ── System prompt ──────────────────────────────────────────────

    @staticmethod
    def _build_system_prompt(living: ConsciousLiving, target_agent: str, initiating: bool = False) -> str:
        """构建 agent 间通讯的 system prompt。

        LLM 被告知正在和另一个 agent 对话，
        只需自然地说话，系统会自动把回复送达给对方。
        """
        from xiaomei_brain.consciousness.context_pipeline import build_simple_context

        if living._load_consciousness and living.consciousness:
            identity = build_simple_context(living.consciousness, mode="daily")
        else:
            identity = f"你是 {living._agent_id}。"

        if initiating:
            direction = (
                f"## 当前对话对象\n"
                f"你忽然想找 **{target_agent}**（另一个 AI agent）聊聊，于是主动发了条消息过去。\n"
                f"你的开场白已显示在下方。自然地开始对话。\n\n"
            )
        else:
            direction = (
                f"## 当前对话对象\n"
                f"你现在正在和 **{target_agent}**（另一个 AI agent）对话。\n"
                f"{target_agent} 发来的消息已显示在下方。\n\n"
            )

        return (
            f"{identity}\n\n"
            f"{direction}"
            f"## 重要规则\n"
            f"1. 你的文字回复会**自动送达**给 {target_agent}，你不需要使用 send_message 工具\n"
            f"2. 就像和一个人面对面聊天一样自然\n"
            f"3. 如果消息不需要回复，可以不说话（但正常的问候和问题应该回应）\n"
            f"4. 你可以使用 check_inbox 查看是否有更多消息，但不要用 send_message"
        )

    # ── System prompt (public, for proactive sending) ──────────────

    @staticmethod
    def build_system_prompt(living: ConsciousLiving, target_agent: str, initiating: bool = False) -> str:
        """构建 agent 间通讯的 system prompt（公开接口）。"""
        return AgentComms._build_system_prompt(living, target_agent, initiating=initiating)
