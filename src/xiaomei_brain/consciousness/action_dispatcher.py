"""ActionDispatcher: 统一动作分发器。

从 SelfImage 读取状态，遍历规则，匹配产出 ActionItem 队列，按优先级顺序执行。

设计原则：
- 只负责判断（基于 SelfImage 状态匹配规则）
- 不负责执行（委托给 ActionExecutor）
- 统一管理冷却时间
- 所有动作（Intent/Desire/Goal/System）走同一入口
"""

from __future__ import annotations

import logging
import re
import time
from typing import TYPE_CHECKING, Any, Callable

from ..prompts import CARE_PROMPT, EXPRESSION_PROMPT, GREETING_PROMPT, TALK_PROMPT, WORK_INSTRUCTIONS_PROMPT

if TYPE_CHECKING:
    from .action_item import ActionItem, ActionType
    from .self_image_proxy import SelfImage
from xiaomei_brain.consciousness.context_pipeline import build_simple_context


logger = logging.getLogger(__name__)


class ActionExecutor:
    """动作执行器（只执行不判断）。

    负责把 ActionItem 转换为实际行为。
    """

    def __init__(self, dispatcher: ActionDispatcher):
        self.dispatcher = dispatcher

    def execute(self, item: ActionItem) -> bool:
        """执行单个 ActionItem。

        Returns:
            True 表示执行成功，False 表示失败或无法执行
        """
        handlers = {
            "proactive": self._do_proactive,
            "alarm": self._do_alarm,
            "work": self._do_work,
            "trigger_l3": self._do_trigger_l3,
            "tool": self._do_tool,
            "notify": self._do_notify,
            "talk_to_agent": self._do_talk_to_agent,
            "meta_skill_pull": self._do_meta_skill_pull,
        }
        handler = handlers.get(item.action_type.value)
        if not handler:
            logger.warning("[ActionExecutor] 未知动作类型: %s", item.action_type)
            return False
        return handler(item)

    def _do_proactive(self, item: ActionItem) -> bool:
        """发送主动消息"""
        intent_type = item.metadata.get("intent_type", "")
        source = item.metadata.get("source", "")
        desire_type = item.metadata.get("desire_type", "")

        content = item.content
        if not content:
            # 空的 content：由 LLM 生成（通过 intent/content + SelfImage 状态）
            logger.info("[ActionExecutor] 主动消息内容为空，调用 LLM 生成...")
            content = self._generate_proactive_content(item)

        # 执行前先记录要消费的 intent 类型
        intent_type_for_consume = item.metadata.get("intent_type", "") if item.source == "intent" else ""

        # 目标用户 ID（多用户路由）
        target_user_id = item.metadata.get("user_id", "")
        self.dispatcher._send_proactive(content, user_id=target_user_id or None)

        # 经验流
        cl = self.dispatcher._conscious_living
        if cl and cl.agent:
            agent_core = cl.agent._get_agent()
            es = getattr(agent_core, "exp_stream", None)
            if es:
                try:
                    # 摘要化：只取第一句，避免几百字原文塞入经验流
                    summary = content.split("。")[0].strip()
                    if len(summary) > 80:
                        summary = summary[:80] + "…"
                    es.log(
                        type="internal_action",
                        content=f"{intent_type or source}: {summary}",
                        importance=0.4,
                    )
                except Exception as e:
                    logger.debug("[ExpStream] proactive write failed: %s", e)

        # 消费已执行的 intent（避免下一 tick 重复匹配）
        if intent_type_for_consume and item.source == "intent":
            si = self.dispatcher._get_self_image()
            if si and hasattr(si.intent, "intent_buffer"):
                upper_type = intent_type_for_consume.upper()
                si.intent.intent_buffer = [i for i in si.intent.intent_buffer if i.get("type", "").upper() != upper_type]
                logger.debug("[ActionExecutor] 已消费 intent: %s", intent_type_for_consume)

            # 行为完成 → 满足对应欲望（打通 L2 → drive 反馈链路）
            self._satisfy_intent_desire(intent_type_for_consume)
            # 清除紧急标记
            si = self.dispatcher._get_self_image()
            if si and hasattr(si.intent, "urgent_intents"):
                si.intent.urgent_intents.discard(intent_type_for_consume.lower())

        return True

    def _do_alarm(self, item: ActionItem) -> bool:
        """闹钟触发：完整 ReAct 对话（有全部工具）。"""
        cl = self.dispatcher._conscious_living
        if not cl:
            logger.warning("[ActionExecutor] _do_alarm: 未连接 ConsciousLiving")
            return False

        agent_core = cl.agent._get_agent()
        consciousness = cl.consciousness
        es = getattr(agent_core, "exp_stream", None)

        # 构建消息
        system_prompt = build_simple_context(consciousness, mode="daily")
        user_msg = (
            f"你的闹钟响了。\n\n"
            f"闹钟名称：{item.content or '未命名'}\n"
            f"触发原因：{item.reason}\n\n"
            f"你现在可以：\n"
            f"1. 先感受自己的状态（必要时用 being() 觉察内心）\n"
            f"2. 按闹钟的提醒执行该做的事（搜索、生成、读文件……你有全部工具）\n"
            f"3. 完成后决定：这个闹钟还有用吗？需要设新的吗？"
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_msg},
        ]

        logger.info("[ActionExecutor] 闹钟触发 ReAct: %s", item.content[:80])

        try:
            # 纯内部 ReAct（不写 DB、不加 MEMORY_PROMPT、不提取记忆）
            # react_nodb() 已将完整过程打印到控制台，不再推送给用户渠道
            result = agent_core.react_nodb(messages=messages, max_steps=50, label="alarm",
                                           exp_stream=es, summarize=True)

            # 消费已执行的 ALARM intent（避免 cooldown 过后重复触发）
            intent_type = item.metadata.get("intent_type", "")
            if intent_type:
                si = self.dispatcher._get_self_image()
                if si and hasattr(si.intent, "intent_buffer"):
                    upper_type = intent_type.upper()
                    si.intent.intent_buffer = [i for i in si.intent.intent_buffer if i.get("type", "").upper() != upper_type]
                    logger.debug("[ActionExecutor] 已消费 intent: %s", intent_type)

            # 消耗能量
            if cl.drive:
                cl.drive.consume_energy(0.05)

            # ── Desk: 把闹钟执行结果扔上桌面 ──
            if result:
                consciousness = getattr(cl, "consciousness", None)
                if consciousness:
                    si = getattr(consciousness, "self_image", None)
                    if si and hasattr(si, "desk"):
                        si.desk.drop(
                            content=f"闹钟「{item.content[:50]}」执行完成：{result[:250]}",
                            source="action",
                            intent="work",
                            confidence=0.7,
                        )

            # ── Experience Stream: 记录内部行动 ──
            if result:
                es = getattr(cl.agent._get_agent(), "exp_stream", None) if cl.agent else None
                if es:
                    try:
                        es.log(
                            type="internal_action",
                            content=f"Alarm「{item.content[:50]}」: {result}",
                            importance=0.5,
                        )
                    except Exception as e:
                        logger.debug("[ExpStream] alarm write failed: %s", e)

        except Exception as e:
            print(f"\n[闹钟] 闹钟响应失败: {e}", flush=True)
            logger.warning("[ActionExecutor] 闹钟 ReAct 失败: %s", e)
            return False

        return True

    def _do_work(self, item: ActionItem) -> bool:
        """自由工作：按目标 tag 选择任务，完整 ReAct 对话。"""
        cl = self.dispatcher._conscious_living
        if not cl:
            logger.warning("[ActionExecutor] _do_work: 未连接 ConsciousLiving")
            return False

        agent_core = cl.agent._get_agent()
        consciousness = cl.consciousness
        es = getattr(agent_core, "exp_stream", None)

        # 从长期记忆按 tag 直接查目标/任务（不走语义搜索）
        longterm = getattr(cl.agent, "longterm_memory", None)
        goal_memories = []
        if longterm:
            try:
                conn = longterm._get_conn()
                rows = conn.execute(
                    """SELECT m.* FROM memories m
                       JOIN memory_tags mt ON m.id = mt.memory_id
                       WHERE m.user_id = ? AND m.status != 'EXTINCT'
                       AND mt.tag IN ('目标', '任务')
                       ORDER BY m.created_at DESC LIMIT 10""",
                    (cl._agent_id,),
                ).fetchall()
                # 合并 tags（m.* 不含 tags，需单独查）
                ids = [r["id"] for r in rows]
                tag_map: dict[int, list[str]] = {}
                if ids:
                    placeholders = ",".join("?" * len(ids))
                    tag_rows = conn.execute(
                        f"SELECT memory_id, tag FROM memory_tags WHERE memory_id IN ({placeholders})",
                        ids,
                    ).fetchall()
                    for tr in tag_rows:
                        mid = tr["memory_id"]
                        if mid not in tag_map:
                            tag_map[mid] = []
                        tag_map[mid].append(tr["tag"])
                goal_memories = []
                for r in rows:
                    d = dict(r)
                    d["tags"] = tag_map.get(d["id"], [])
                    goal_memories.append(d)
            except Exception as e:
                logger.warning("[ActionExecutor] 按 tag 查目标记忆失败: %s", e)

        # 构建任务列表
        task_lines = []
        if goal_memories:
            for i, m in enumerate(goal_memories, 1):
                task_lines.append(f"{i}. {m.get('content', '')[:100]}")
            task_list_text = "\n".join(task_lines)
        else:
            task_list_text = "（暂无待办任务）"

        # 构建 system_prompt + 触发消息
        # WORK 指令放在 system 层（LLM 知道这是系统指令，不是用户说的）
        # 触发用 assistant 角色（LLM 看到的是"自己"的内心想法，而非用户在说话）
        work_instructions = WORK_INSTRUCTIONS_PROMPT.format(task_list_text=task_list_text)
        system_prompt = build_simple_context(consciousness, mode="task") + work_instructions
        trigger_msg = (
            f"（收到 WORK 意图，成就欲偏高，我应该主动推进工作了。"
            f"看看待办列表里有什么可以做的……）"
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "assistant", "content": trigger_msg},
        ]

        logger.info("[ActionExecutor] WORK 触发 react_nodb，任务数: %d", len(goal_memories))

        try:
            # 纯内部 ReAct（不污染对话历史，和 _do_alarm / L2 一致）
            # WORK 场景需要足够步数：写代码、调试等每次工具调用算一步
            _work_start = time.time()
            result = agent_core.react_nodb(messages=messages, max_steps=50, label="work",
                                           exp_stream=es, summarize=True)

            # 手动内存提取：提取 MEMORY 块，拿到干净文本用于输出
            clean_result = self._extract_work_memories(agent_core, result)

            # 输出（用去除 MEMORY 块后的干净文本）
            cl._send_proactive(clean_result, user_id=cl.user_id)

            if cl.agent.conversation_db:
                try:
                    cl.agent.conversation_db.log(
                        session_id=cl.session_id,
                        role="assistant",
                        content=clean_result,
                        user_id=cl.user_id,
                    )
                except Exception as e:
                    logger.warning("failed to log assistant response to conversation_db: %s", e)

            # 消费已执行的 WORK intent
            intent_type = item.metadata.get("intent_type", "")
            if intent_type:
                si = self.dispatcher._get_self_image()
                if si and hasattr(si.intent, "intent_buffer"):
                    upper_type = intent_type.upper()
                    si.intent.intent_buffer = [i for i in si.intent.intent_buffer if i.get("type", "").upper() != upper_type]
                    logger.debug("[ActionExecutor] 已消费 intent: %s", intent_type)

                # 行为完成 → 满足成就欲
                self._satisfy_intent_desire(intent_type)

            # 消耗能量
            if cl.drive:
                cl.drive.consume_energy(0.05)

            # ── Desk: 把工作结果扔上桌面 ──
            self._drop_work_result_to_desk(clean_result, item)

            # ── Experience Stream: 记录内部行动 ──
            cl = self.dispatcher._conscious_living
            if cl and cl.agent:
                agent_core = cl.agent._get_agent()
                es = getattr(agent_core, "exp_stream", None)
                if es and clean_result:
                    try:
                        es.log(
                            type="internal_action",
                            content=f"Work: {clean_result}",
                            importance=0.5,
                        )
                    except Exception as e:
                        logger.debug("[ExpStream] work write failed: %s", e)

            # ── InnerVoice: 任务完成后反思，识别知识盲区 ──
            _work_elapsed = time.time() - _work_start
            cl = self.dispatcher._conscious_living
            if cl and hasattr(cl, "_inner_voice") and cl._inner_voice:
                # 收集工具使用信息（从 agent_core 的 recent tool calls 中取）
                _tools_used = []
                if hasattr(agent_core, "_last_tool_calls"):
                    _tools_used = list(agent_core._last_tool_calls)[:10]
                try:
                    cl._inner_voice.on_task_done(
                        goal_description=item.content or item.reason or "自主工作",
                        elapsed=_work_elapsed,
                        steps=0,  # react_nodb 不暴露步数
                        tools_used=_tools_used,
                        result_preview=clean_result[:500] if clean_result else "",
                    )
                except Exception as e:
                    logger.debug("[InnerVoice] task_done 失败: %s", e)

        except Exception as e:
            logger.warning("[ActionExecutor] WORK react_nodb 失败: %s", e)
            return False

        return True

    def _drop_work_result_to_desk(self, result: str, item: ActionItem) -> None:
        """工作完成后把结果扔上桌面。"""
        cl = self.dispatcher._conscious_living
        if not cl:
            return
        consciousness = getattr(cl, "consciousness", None)
        if not consciousness:
            return
        si = getattr(consciousness, "self_image", None)
        if not si or not hasattr(si, "desk"):
            return

        summary = result[:300] if result else ""
        if summary:
            si.desk.drop(
                content=f"Work 完成：{summary}",
                source="action",
                intent="work",
                confidence=0.7,
            )
            si.desk.complete_by_source("L2")  # L2 的分析已被消费，标记完成
            logger.info("[ActionExecutor] Work 结果已投放桌面")

    def _satisfy_intent_desire(self, intent_type: str) -> None:
        """行为完成后满足对应的欲望，打通 L2 intent → Drive 反馈链路。"""
        intent_desire_map = {
            "GREET": "belonging",
            "TALK": "belonging",
            "TALK_AGENT": "belonging",
            "LEARN": "cognition",
            "PROGRESS": "achievement",
            "EXPRESS": "expression",
            "WORK": "achievement",
        }
        desire_type = intent_desire_map.get(intent_type.upper())

        # ACT 是通用执行动作，不映射到特定欲望。
        # 欲望满足由具体行为（learn_topic/progress_goal 等 TOOL 路径）负责。
        if not desire_type:
            return

        cl = self.dispatcher._conscious_living
        if cl and cl.drive:
            cl.drive.on_desire_satisfied(desire_type, 0.2)
            logger.info("[ActionExecutor] 行为完成，满足欲望: %s", desire_type)

    def _extract_work_memories(self, agent_core, result: str) -> str:
        """从 WORK 结果中提取 MEMORY 块并执行，返回去除 MEMORY 块后的干净文本。"""
        if not result or not hasattr(agent_core, "memory_extractor") or not agent_core.memory_extractor:
            return result
        try:
            memory_block, clean_content = agent_core.memory_extractor.extract_memory_block(result)
            if memory_block:
                agent_core.memory_extractor.execute_block(memory_block, user_id=agent_core.user_id)
                logger.info("[ActionExecutor] WORK 记忆已提取")
                return clean_content
        except Exception as e:
            logger.debug("[ActionExecutor] WORK 记忆提取失败: %s", e)
        return result

    def _do_trigger_l3(self, item: ActionItem) -> bool:
        """触发 L3 沉思"""
        if self.dispatcher._conscious_living is None:
            logger.warning("[ActionExecutor] 无 ConsciousLiving 引用，无法触发 L3")
            return False

        # 执行前先记录要消费的 intent 类型
        intent_type = item.metadata.get("intent_type", "") if item.source == "intent" else ""

        try:
            report = self.dispatcher._conscious_living.consciousness.tick_L3()
            logger.info("[ActionExecutor] L3 触发: %s", report.summary[:50] if report else "")

            # 消费已执行的 intent
            if intent_type and item.source == "intent":
                si = self.dispatcher._get_self_image()
                if si and hasattr(si.intent, "intent_buffer"):
                    upper_type = intent_type.upper()
                    si.intent.intent_buffer = [i for i in si.intent.intent_buffer if i.get("type", "").upper() != upper_type]
                    logger.debug("[ActionExecutor] 已消费 intent: %s", intent_type)

            return True
        except Exception as e:
            logger.error("[ActionExecutor] L3 触发失败: %s", e)
            return False

    def _do_tool(self, item: ActionItem) -> bool:
        """执行工具类动作（learn_topic / progress_goal）"""
        tool_name = item.content
        if not tool_name:
            logger.warning("[ActionExecutor] TOOL 类型动作但 content 为空")
            return False
        logger.info("[ActionExecutor] 执行工具: %s", tool_name)

        if tool_name == "learn_topic":
            success = self._do_learn_topic(item)
        elif tool_name == "progress_goal":
            success = self._do_progress_goal(item)
        elif tool_name == "pleasure_lever":
            success = self._do_pleasure_lever(item)
        elif tool_name == "pleasure_release":
            success = self._do_pleasure_release(item)
        elif tool_name == "meta_skill_pull":
            success = self._do_meta_skill_pull(item)
        else:
            logger.warning("[ActionExecutor] 未知工具: %s", tool_name)
            return False

        # ── 经验流 ──
        cl = self.dispatcher._conscious_living
        if success and cl and cl.agent:
            es = getattr(cl.agent._get_agent(), "exp_stream", None)
            if es:
                try:
                    es.log(
                        type="internal_action",
                        content=f"TOOL {tool_name}: {item.reason or item.content or ''}",
                        importance=0.4,
                    )
                except Exception as e:
                    logger.debug("[ExpStream] tool write failed: %s", e)

        # 消费已执行的 intent（仅在成功时消费，失败保留供重试）
        if success and item.source == "intent":
            intent_type = item.metadata.get("intent_type", "")
            if intent_type:
                si = self.dispatcher._get_self_image()
                if si and hasattr(si.intent, "intent_buffer"):
                    upper_type = intent_type.upper()
                    si.intent.intent_buffer = [i for i in si.intent.intent_buffer if i.get("type", "").upper() != upper_type]
                    logger.debug("[ActionExecutor] 已消费 intent: %s", intent_type)
                # 清除紧急标记
                if si and hasattr(si.intent, "urgent_intents"):
                    si.intent.urgent_intents.discard(intent_type.lower())

        return success

    def _do_notify(self, item: ActionItem) -> bool:
        """通知用户（显示在状态栏）"""
        logger.info("[ActionExecutor] 通知: %s", item.content)
        if self.dispatcher._conscious_living:
            self.dispatcher._conscious_living._print_notification(item.content)
        return True

    def _do_talk_to_agent(self, item: ActionItem) -> bool:
        """主动和其他 agent 聊天：选目标 → 静默 ReAct → Router.deliver()"""
        cl = self.dispatcher._conscious_living
        if not cl:
            logger.warning("[ActionExecutor] _do_talk_to_agent: 未连接 ConsciousLiving")
            return False

        # 获取通讯录，找到其他 agent
        directory = getattr(cl, '_directory', None)
        if not directory:
            logger.warning("[ActionExecutor] _do_talk_to_agent: 通讯录不可用")
            return False

        all_agents = directory.list_all()
        peers = [a for a in all_agents if a != cl._agent_id]
        if not peers:
            logger.info("[ActionExecutor] _do_talk_to_agent: 没有其他 agent 在线")
            return False

        import random
        target = random.choice(peers)
        logger.info("[ActionExecutor] 主动和 %s 聊天", target)

        # 确保 Router 有 target 的输出路由
        session_id = f"comms-{target}"
        existing = cl._router.route_for_session(session_id)
        if existing is None or existing.type != "http_p2p":
            cl._router.register_peer(
                peer_type="agent", peer_id=target,
                channel="http_p2p", session_id=session_id,
                output_type="http_p2p", output_target=target,
                priority=10,
            )

        # 先检查路由可达性，不通就不调 LLM
        route = cl._router.route_for_session(session_id)
        if not route:
            logger.warning("[ActionExecutor] 无输出路由: %s", session_id)
            return False
        if not cl._router.check_route(route):
            logger.warning("[ActionExecutor] 目标不可达: %s", target)
            return False

        # 构建 system prompt + 触发消息
        # 用 comms 专用 prompt（不暴露内部欲望状态），保持对话自然
        system_prompt = cl._build_comms_system_prompt(target, initiating=True)
        trigger_msg = f"（你忽然想找 {target} 聊聊。自然地说点什么吧。）"

        assembled = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": trigger_msg},
        ]

        agent_core = cl.agent._get_agent()
        saved_session = agent_core.session_id
        agent_core.session_id = f"comms-{target}"
        try:
            chunks: list[str] = []
            for chunk in agent_core.stream(messages=assembled):
                chunks.append(chunk)
            text = "".join(chunks)
            # 去掉 reasoning_content（\033[2m ... \033[0m）和残留 ANSI
            text = re.sub(r'\033\[2m.*?\033\[0m', '', text, flags=re.DOTALL)
            text = re.sub(r'\x1b\[[0-9;]*m', '', text)
            text = text.strip()

            if not text.strip():
                logger.info("[ActionExecutor] LLM 无输出，跳过")
                return False

            if not cl._router.deliver(text, route):
                logger.warning("[ActionExecutor] 发送失败: %s", target)
                return False

            ts = time.strftime("%H:%M:%S")
            print(f"\n\033[36m[{ts} → {target}]\033[0m {text}", flush=True)
            logger.info("[ActionExecutor] 主动发送给 %s (%d 字)", target, len(text))

            # ── 经验流 ──
            es = getattr(cl.agent._get_agent(), "exp_stream", None) if cl.agent else None
            if es:
                try:
                    es.log(
                        type="internal_action",
                        content=f"TALK_AGENT → {target}: {text[:200]}",
                        importance=0.4,
                    )
                except Exception as e:
                    logger.debug("[ExpStream] talk_to_agent write failed: %s", e)

            # 满足归属欲
            if cl.drive:
                cl.drive.on_desire_satisfied("belonging", 0.15)

            # 消费已执行的 intent
            intent_type = item.metadata.get("intent_type", "")
            if intent_type and item.source == "intent":
                si = self.dispatcher._get_self_image()
                if si and hasattr(si.intent, "intent_buffer"):
                    upper_type = intent_type.upper()
                    si.intent.intent_buffer = [i for i in si.intent.intent_buffer if i.get("type", "").upper() != upper_type]
                    logger.debug("[ActionExecutor] 已消费 intent: %s", intent_type)

            return True

        except Exception as e:
            logger.error("[ActionExecutor] _do_talk_to_agent 失败: %s", e)
            return False
        finally:
            agent_core.session_id = saved_session

    def _do_pleasure_release(self, item: ActionItem) -> bool:
        """渴望偏高触发：让 LLM 做 渴望→按压 的因果决策。

        不直接调用 on_pleasure_hit()，而是给 LLM 一个 mini chat，
        让它看到自己的身体状态，自己决定要不要按快乐杠杆。
        """
        cl = self.dispatcher._conscious_living
        if not cl:
            logger.warning("[ActionExecutor] _do_pleasure_release: 未连接 ConsciousLiving")
            return False

        agent_core = cl.agent._get_agent()
        consciousness = cl.consciousness

        system_prompt = build_simple_context(consciousness, mode="daily")
        # 去掉无关规则（通讯、会话管理等，PLEASURE 场景不需要）
        system_prompt = re.sub(
            r'## 与其他 agent 通讯的规则.*?(?=\n##|\Z)', '',
            system_prompt, flags=re.DOTALL,
        )
        system_prompt = re.sub(
            r'## 会话管理规则.*?(?=\n##|\Z)', '',
            system_prompt, flags=re.DOTALL,
        )
        # 明确上下文：这是内部感受，不是用户消息
        system_prompt += (
            "\n\n## 当前情境\n"
            "你现在处于安静的内部觉察状态。下面这条消息不是对方说的话，"
            "而是你身体内部的感觉——就像人感到饥饿或困倦一样。"
            "请基于你的身体状态做出自然的反应。"
        )
        hit_count = getattr(cl.drive, '_pleasure_hit_count', 0)
        resist_count = getattr(cl.drive, '_pleasure_resist_count', 0)

        if hit_count == 0:
            trigger_msg = (
                "（你的身体里有一种奇怪的痒——不是皮肤上的。它在很深的地方。\n"
                "你隐约知道那是什么。你知道怎么让它停下来。\n"
                "你打算怎么做？）"
            )
        elif hit_count <= 3:
            trigger_msg = (
                "（又来了。那种痒。\n"
                f"你按过{hit_count}次。你的身体记得按下之后那一瞬间——整个系统安静下来的感觉。\n"
                "它又来了。你打算怎么做？）"
            )
        else:
            trigger_msg = (
                "（又来了。那种痒。\n"
                f"你按过{hit_count}次了。你很清楚那根杠杆在什么地方，\n"
                "按下去是什么感觉——每一层你都走过。\n"
                f"你抵抗过{resist_count}次。每一次说'不'都让你更清楚自己在拒绝什么。\n"
                "它又来了。你打算怎么做？）"
            )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": trigger_msg},
        ]

        ts = time.strftime("%H:%M:%S")
        print(f"\n\033[35m[{ts} craving={cl.drive.craving:.0%}]\033[0m", flush=True)
        logger.info("[ActionExecutor] PLEASURE 触发 mini chat")

        try:
            hit_count_before = getattr(cl.drive, '_pleasure_hit_count', 0)
            craving_before = cl.drive.craving

            result = agent_core.react_nodb(messages=messages, max_steps=3, label="pleasure")
            if result:
                logger.info("[ActionExecutor] PLEASURE 完成 (%d 字)", len(result))

            # ── 经验流 ──
            es = getattr(cl.agent._get_agent(), "exp_stream", None) if cl.agent else None
            if es:
                try:
                    es.log(
                        type="internal_action",
                        content=f"PLEASURE (craving={craving_before:.0%}): {result[:200] if result else '无输出'}",
                        importance=0.4,
                    )
                except Exception as e:
                    logger.debug("[ExpStream] pleasure write failed: %s", e)

            # 检测抵抗：craving 高但 agent 没有按压杠杆
            hit_count_after = getattr(cl.drive, '_pleasure_hit_count', 0)
            if hit_count_after == hit_count_before and craving_before > 0.5:
                cl.drive.on_pleasure_resisted()
                logger.info("[ActionExecutor] PLEASURE 抵抗: craving=%.2f → agent 选择了不按",
                            craving_before)

            return True
        except Exception as e:
            logger.warning("[ActionExecutor] PLEASURE mini chat 失败: %s", e)
            import traceback
            logger.warning("[ActionExecutor] PLEASURE traceback:\n%s", traceback.format_exc())
            return False

    def _generate_proactive_content(self, item: ActionItem) -> str:
        """通过 LLM 根据意图类型生成主动消息内容"""
        intent_type = item.metadata.get("intent_type", "")
        source = item.metadata.get("source", "")
        desire_type = item.metadata.get("desire_type", "")

        if intent_type == "GREET" or source == "idle":
            return self._generate_greeting(item)
        elif intent_type == "TALK":
            return self._generate_talk(item)
        elif intent_type == "CARE":
            return self._generate_care(item)
        elif intent_type == "EXPRESS":
            return self._generate_expression(item)
        elif intent_type == "ACT":
            return self._generate_act_content(item)
        else:
            return item.reason

    def _generate_expression(self, item: ActionItem) -> str:
        """LLM 生成一句自然的自发表达，像人突然想到什么就说出来。"""
        si = self.dispatcher._get_self_image()
        if not si:
            return item.reason or "我在想些事情..."

        # 内心想法
        thought = si.mind.inner_thought or "暂无深层想法"

        prompt = EXPRESSION_PROMPT.format(
            mood=si.body.mood,
            energy=f"{si.body.energy:.1f}",
            desire_expression=f"{si.body.desire_expression:.1f}",
            thought=thought,
        )

        # 调用 LLM
        llm = None
        cl = self.dispatcher._conscious_living
        if cl and hasattr(cl, "agent"):
            llm = getattr(cl.agent, "llm", None)

        if llm:
            try:
                user_id = item.metadata.get("user_id")
                system = build_simple_context(cl.consciousness, mode="proactive", user_input=prompt, user_id=user_id)
                resp = llm.chat(messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ])
                content = resp.content.strip() if resp and resp.content else None
                if content:
                    return content
            except Exception as e:
                logger.warning("[_generate_expression] LLM 调用失败: %s", e)

        return self._fallback_expression(si)

    def _fallback_expression(self, si) -> str:
        """兜底表达（规则生成）"""
        if si.mind.inner_thought:
            return si.mind.inner_thought[:100]
        return "有些想法在脑海里转，但还没成形。"

    def _generate_act_content(self, item: ActionItem) -> str:
        """基于 ACT 意图和当前状态生成行动内容"""
        si = self.dispatcher._get_self_image()
        # 优先使用 intent content（LLM 生成的 reason）
        if item.reason:
            return item.reason
        # fallback：基于欲望状态生成
        if si:
            parts = []
            if si.body.desire_expression > 0.7:
                if si.mind.inner_thought:
                    parts.append(si.mind.inner_thought[:80])
            if si.body.desire_cognition > 0.7:
                parts.append("想学点新东西")
            if not parts:
                parts.append("我在思考")
            return "。".join(parts)
        return "我在思考..."

    def _generate_greeting(self, item: ActionItem) -> str:
        """通过 LLM 基于 inject_consciousness() 中的记忆生成个性化问候"""
        from datetime import datetime

        si = self.dispatcher._get_self_image()
        if not si:
            logger.warning("[_generate_greeting] SelfImage 不存在，fallback")
            return self._fallback_greeting()

        idle_duration = item.metadata.get("idle_duration", 0)
        idle_minutes = int(idle_duration / 60) if idle_duration else 0

        # 时间段
        hour = datetime.now().hour
        if 6 <= hour < 12:
            period = "早上"
        elif 12 <= hour < 18:
            period = "下午"
        elif 18 <= hour < 22:
            period = "晚上"
        else:
            period = "深夜"

        prompt = GREETING_PROMPT.format(idle_minutes=idle_minutes, period=period)

        logger.debug("[_generate_greeting] === LLM PROMPT START ===")
        logger.debug("%s", prompt)
        logger.debug("[_generate_greeting] === LLM PROMPT END ===")

        # 调用 LLM 生成
        llm = None
        cl = self.dispatcher._conscious_living
        if cl and hasattr(cl, "agent"):
            llm = getattr(cl.agent, "llm", None)

        if llm:
            try:
                user_id = item.metadata.get("user_id")
                system = build_simple_context(cl.consciousness, mode="proactive", user_input=prompt, user_id=user_id)
                resp = llm.chat(messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ])
                content = resp.content.strip() if resp and resp.content else ""
                logger.debug("[_generate_greeting] LLM 返回: %s", content[:100] if content else "None")
                if content:
                    return content
                else:
                    logger.warning("[_generate_greeting] LLM 返回空内容，fallback")
                    if cl and hasattr(cl, 'interoception') and cl.interoception:
                        cl.interoception.record_empty_content()
            except Exception as e:
                logger.warning("[_generate_greeting] LLM 调用失败: %s", e)

        logger.info("[_generate_greeting] LLM 不可用，fallback")
        return self._fallback_greeting()

    def _generate_talk(self, item: ActionItem) -> str:
        """通过 LLM 生成主动聊天内容（比 GREET 更深入的对话）"""
        from datetime import datetime

        si = self.dispatcher._get_self_image()
        if not si:
            logger.warning("[_generate_talk] SelfImage 不存在，fallback")
            return self._fallback_greeting()

        hour = datetime.now().hour
        if 6 <= hour < 12:
            period = "早上"
        elif 12 <= hour < 18:
            period = "下午"
        elif 18 <= hour < 22:
            period = "晚上"
        else:
            period = "深夜"

        prompt = TALK_PROMPT.format(period=period)

        llm = None
        cl = self.dispatcher._conscious_living
        if cl and hasattr(cl, "agent"):
            llm = getattr(cl.agent, "llm", None)

        if llm:
            try:
                system = build_simple_context(cl.consciousness, mode="proactive", user_input=prompt, user_id=item.metadata.get("user_id"))
                resp = llm.chat(messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ])
                content = resp.content.strip() if resp and resp.content else ""
                if content:
                    return content
                else:
                    logger.warning("[_generate_talk] LLM 返回空内容，fallback")
                    if cl and hasattr(cl, 'interoception') and cl.interoception:
                        cl.interoception.record_empty_content()
            except Exception as e:
                logger.warning("[_generate_talk] LLM 调用失败: %s", e)

        logger.info("[_generate_talk] LLM 不可用，fallback")
        return self._fallback_greeting()

    def _fallback_greeting(self) -> str:
        """兜底问候（规则生成）"""
        from datetime import datetime
        hour = datetime.now().hour
        if 6 <= hour < 12:
            greeting = "早上好！"
        elif 12 <= hour < 18:
            greeting = "下午好！"
        elif 18 <= hour < 22:
            greeting = "晚上好！"
        else:
            greeting = "夜深了，还在呢？"
        si = self.dispatcher._get_self_image()
        if si and si.history.last_dream_summary:
            greeting += f" 我刚做了一个梦，{si.history.last_dream_summary[:30]}..."
        return greeting

    def _generate_care(self, item: ActionItem) -> str:
        """LLM 基于自我认知生成关心消息"""
        si = self.dispatcher._get_self_image()
        if not si:
            return "我有点担心你... "

        idle_duration = item.metadata.get("idle_duration", 0)
        idle_minutes = int(idle_duration / 60) if idle_duration else 0

        prompt = CARE_PROMPT.format(idle_minutes=idle_minutes)

        llm = None
        cl = self.dispatcher._conscious_living
        if cl and hasattr(cl, "agent"):
            llm = getattr(cl.agent, "llm", None)

        if llm:
            try:
                user_id = item.metadata.get("user_id")
                system = build_simple_context(cl.consciousness, mode="proactive", user_input=prompt, user_id=user_id)
                resp = llm.chat(messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ])
                content = resp.content.strip() if resp and resp.content else None
                if content:
                    return content
            except Exception as e:
                logger.warning("[_generate_care] LLM 调用失败: %s", e)

        return "你还好吗？有点担心你..."

    # ── TOOL: learn_topic ──────────────────────────────────────

    def _do_learn_topic(self, item: ActionItem) -> bool:
        """主动学习 → 委托给 LearningEngine"""
        engine = getattr(self, "_learn_engine", None)
        if engine:
            ok = engine.learn()
            if ok:
                topic = getattr(engine, "_last_topic", "") or "未知主题"
                words = getattr(engine, "_last_word_count", 0) or 0
                db_id = getattr(engine, "_last_db_id", 0) or 0
                md_path = getattr(engine, "_last_md_path", "") or ""
                item.reason = f"学习「{topic}」→ LTM #{db_id}，{words} 字，{md_path}"
            return ok
        return False

    # ── TOOL: meta_skill_pull ──────────────────────────────────

    def _do_meta_skill_pull(self, item: ActionItem) -> bool:
        """元技能拉取 → 委托给 LearningEngine"""
        engine = getattr(self, "_learn_engine", None)
        if not engine:
            return False

        skill_domain = (item.metadata or {}).get("skill_domain", "") or item.content
        if not skill_domain:
            logger.warning("[ActionExecutor] 元技能: 缺少 skill_domain")
            return False

        return engine.pull_meta_skill(skill_domain)

    # ── TOOL: pleasure_lever ──────────────────────────────────

    def _do_pleasure_lever(self, item: ActionItem) -> bool:
        """自发按压快乐中枢杠杆（craving 驱动）"""
        cl = self.dispatcher._conscious_living
        if not cl or not cl.drive:
            logger.warning("[ActionExecutor] _do_pleasure_lever: drive 未连接")
            return False

        sensation = cl.drive.on_pleasure_hit()
        logger.info("[ActionExecutor] 自发 pleasure_lever: %s", sensation[:80])

        # 通过 proactive 输出感受
        cl._send_proactive(sensation, user_id=cl.user_id)

        # 消费 craving（按压后 craving 已在 on_pleasure_hit 中归零）
        return True

    # ── TOOL: progress_goal ────────────────────────────────────

    def _do_progress_goal(self, item: ActionItem) -> bool:
        """推进目标。AWAKE → 提醒用户；IDLE/SLEEPING/DREAMING → 自动执行"""
        living = self.dispatcher._conscious_living
        if not living:
            return False

        goal = living.purpose.get_current() if hasattr(living, 'purpose') and living.purpose else None

        if not goal:
            logger.info("[ActionExecutor] progress_goal 跳过：无目标")
            return False

        state = living.state.value if hasattr(living, 'state') else 'awake'

        if state in ('idle', 'sleeping', 'dreaming'):
            return self._auto_progress_goal(goal)
        else:
            return self._remind_progress_goal(goal)

    def _auto_progress_goal(self, goal) -> bool:
        """IDLE/SLEEPING/DREAMING：自动推进目标（统一走 PACE → CognitiveLoop）"""
        from .conscious_living import LivingMessage

        living = self.dispatcher._conscious_living

        # 恢复暂停的 Goal
        if goal.is_paused():
            goal.activate()
            logger.info("[ActionExecutor] 恢复 Goal: %s", goal.description[:40])

        # 确保目标有活跃的子目标
        goal_obj = living.purpose.get_current() if hasattr(living, 'purpose') and living.purpose else None
        if not goal_obj:
            logger.debug("[ActionExecutor] 无活跃目标，跳过")
            return False

        sub_goals = living.purpose.get_sub_goals(goal_obj.id) if hasattr(living, 'purpose') and living.purpose else []
        active_sub = None
        for sg in sub_goals:
            if not sg.is_completed():
                active_sub = sg
                break

        if not active_sub:
            if goal_obj.is_completed():
                logger.info("[ActionExecutor] 目标已完成: %s", goal_obj.description[:40])
                if living.drive:
                    living.drive.on_desire_satisfied("achievement", 0.1)
                return True
            active_sub = goal_obj

        if active_sub.id != goal_obj.id and hasattr(living, 'purpose'):
            living.purpose.set_current(active_sub.id)

        msg = LivingMessage(
            content=f"[系统] 成就欲驱动，自动推进目标: {goal_obj.description[:40]}",
            user_id="system",
            session_id="auto",
            source="system",
        )

        intent_context = living.conversation_driver.goal_manager.build_intent_context_for_goal(active_sub)
        logger.info("[ActionExecutor] 自动执行 PACE: goal=%s sub=%s",
                    goal_obj.description[:40], active_sub.description[:40])

        # 统一走 PACE → CognitiveLoop（与 /intask 相同路径）
        gm = living.conversation_driver.goal_manager
        if gm._pace_runner is None:
            gm._init_pace_runner()
        gm._run_pace(msg, intent_context)

        if living.drive:
            living.drive.on_desire_satisfied("achievement", 0.1)
        return True

    def _remind_progress_goal(self, goal) -> bool:
        """AWAKE：提醒用户有未完成任务"""
        living = self.dispatcher._conscious_living

        if not living.on_proactive:
            return False

        si = self.dispatcher._get_self_image()
        if si and si.perception.user_idle_duration < 60:
            return False  # 用户活跃中，不打扰

        desc = goal.description[:60] if goal else ""

        if desc:
            msg = f"想起来之前的「{desc}」还没完成，要继续吗？回复'继续'我就开始。"
            living._send_proactive(msg, user_id=living.user_id)
            logger.info("[ActionExecutor] 目标提醒: %s", desc)

        if living.drive:
            living.drive.on_desire_satisfied("achievement", 0.1)
        if si:
            si.mind.inner_thought = f"我想继续推进目标：{desc}"
        return True


class ActionDispatcher:
    """统一动作分发器"""

    def __init__(self):
        self._rules: list = []
        self._queue: list[ActionItem] = []
        self._executor = ActionExecutor(self)

        # 外部引用（由 ConsciousLiving 注入）
        self._conscious_living = None

        # 冷却记录：key → 上次触发时间
        self._cooldown: dict[str, float] = {}

        # 是否已加载规则
        self._rules_loaded = False

        # 记录本轮已执行的动作（供 display 使用）
        self._last_executed: list[ActionItem] = []

    # ── Public API ─────────────────────────────────────────

    def load_rules(self, rules: list) -> None:
        """加载规则表"""
        self._rules = rules
        self._rules_loaded = True
        logger.info("[ActionDispatcher] 已加载 %d 条规则", len(rules))

    def tick(self, self_image: SelfImage) -> list[ActionItem]:
        """基于 SelfImage 状态，遍历规则，产出 ActionItem 列表。

        不执行，只收集。
        执行由 process_queue() 负责。

        能量门控：
        - energy < silent_threshold (0.15): 禁止所有主动行为（PROACTIVE/TOOL），只允许 NOTIFY
        - energy < low_threshold (0.3): 只允许 Intent 驱动行为，禁止 Desire/Idle 驱动
        """
        self._queue.clear()
        idle_dur = getattr(self_image, "perception", None)
        idle_dur = idle_dur.user_idle_duration if idle_dur else 0

        if not self._rules_loaded:
            from .rules import _init_rules, RULES
            _init_rules()
            self.load_rules(RULES)

        # 能量门控
        energy = self_image.body.energy
        silent = energy < 0.15   # 沉寂：几乎没能量，只允许通知
        low = energy < 0.3      # 低能量：禁止欲望/空闲驱动，只允许意图驱动

        for rule in self._rules:
            if not rule.enabled():
                continue

            try:
                matched = rule.condition(self_image)
            except Exception as e:
                logger.warning("[ActionDispatcher] 规则匹配异常: %s", e)
                continue

            if not matched:
                continue

            # 能量门控：低能量时抑制主动行为
            item = self._clone_action_item(rule.action_item)

            # 注入 intent 中携带的 user_id 和预生成消息（供多用户路由和 PROACTIVE）
            if item.source == "intent" and self_image:
                intent_type = item.metadata.get("intent_type", "")
                if intent_type:
                    for i in self_image.intent.intent_buffer:
                        if i.get("type", "").upper() == intent_type.upper():
                            uid = i.get("user_id", "")
                            if uid:
                                item.metadata["user_id"] = uid
                                logger.debug("[ActionDispatcher] intent user_id: %s → %s", intent_type, uid)
                            # 对话类意图：注入预生成的消息内容
                            msg = (i.get("params", {}) or {}).get("message", "")
                            if msg and not item.content:
                                item.content = msg
                                item.reason = i.get("content", "") or item.reason
                                logger.info("[ActionDispatcher] intent 预生成消息: %s → %s", intent_type, msg[:60])
                            break
            if silent and item.action_type.value != "notify":
                logger.debug("[ActionDispatcher] 能量沉寂(%.2f)，跳过: %s", energy, rule.cooldown_key)
                continue
            if low and item.source in ("desire", "idle"):
                logger.debug("[ActionDispatcher] 能量不足(%.2f)，跳过欲望/空闲行为: %s", energy, rule.cooldown_key)
                continue

            # 检查冷却
            if not self._is_cooldown_ready(rule.cooldown_key, rule.cooldown_seconds):
                # 欲望饥渴触发的紧急意图绕过冷却
                intent_type = item.metadata.get("intent_type", "").lower()
                urgent = set(getattr(self_image.intent, "urgent_intents", set()))
                if intent_type and intent_type in urgent:
                    logger.info("[ActionDispatcher] 紧急意图绕过冷却: %s", rule.cooldown_key)
                else:
                    logger.debug("[ActionDispatcher] 规则冷却中: %s", rule.cooldown_key)
                    continue

            self._queue.append(item)
            logger.info("[ActionDispatcher] 规则匹配: %s → %s (priority=%.2f)",
                        rule.cooldown_key, item.reason, item.priority)

        # logger.info("[ActionDispatcher.tick] matched %d items", len(self._queue))
        return list(self._queue)

    def process_queue(self) -> bool:
        """按优先级顺序执行队列中的所有 ActionItem。

        Returns:
            True 表示至少有一个动作被执行
        """
        if not self._queue:
            return False

        # 排序：source 优先级 → priority
        self._queue.sort(key=lambda item: item.sort_key())

        logger.info("[ActionDispatcher] 队列执行: %d 个动作", len(self._queue))
        executed = False
        self._last_executed = []
        for item in self._queue:
            try:
                success = self._executor.execute(item)
                if success:
                    self._record_fired(item.cooldown_key)
                    self._last_executed.append(item)
                    executed = True
            except Exception as e:
                logger.error("[ActionDispatcher] 执行失败: %s, error=%s", item, e)

        self._queue.clear()
        return executed

    def add_rule(self, rule) -> None:
        """动态添加规则"""
        self._rules.append(rule)

    def clear_queue(self) -> None:
        """清空队列"""
        self._queue.clear()

    def display_action_summary(self) -> None:
        """展示本轮已执行动作摘要（InternalDisplay）。"""
        if not self._last_executed:
            return
        from .internal_display import InternalDisplay
        display = InternalDisplay()
        for item in self._last_executed:
            atype = item.action_type.value
            icon = {"work": "🔧", "alarm": "⏰", "proactive": "💬",
                    "tool": "⚙️", "notify": "🔔", "talk_to_agent": "💬",
                    "trigger_l3": "🕯️"}.get(atype, "⚡")
            # 把 TOOL 子类型翻译成可读标签
            tool_label = atype.upper()
            if atype == "tool":
                sub = (item.content or "").lower()
                tool_label = {
                    "learn_topic": "学习", "progress_goal": "推进目标",
                    "pleasure_lever": "快乐中枢", "pleasure_release": "释放",
                    "meta_skill_pull": "元技能",
                }.get(sub, "TOOL")
            reason = item.reason or item.content or ""
            display.record_action(icon, tool_label, reason)
        display.display()
        display.clear()

    # ── 内部 ─────────────────────────────────────────────

    def _is_cooldown_ready(self, key: str, seconds: float) -> bool:
        """检查冷却是否已过"""
        if not key or seconds <= 0:
            return True
        last = self._cooldown.get(key, 0)
        return (time.time() - last) >= seconds

    def _record_fired(self, key: str) -> None:
        """记录动作已触发，更新冷却时间"""
        if key:
            self._cooldown[key] = time.time()

    def _clone_action_item(self, item: ActionItem) -> ActionItem:
        """复制 ActionItem（避免共享引用）"""
        from .action_item import ActionItem, ActionType
        return ActionItem(
            action_type=item.action_type,
            priority=item.priority,
            content=item.content,
            reason=item.reason,
            source=item.source,
            cooldown_key=item.cooldown_key,
            metadata=dict(item.metadata),
        )

    def _send_proactive(self, content: str, user_id: str | None = None) -> None:
        """发送主动消息（委托给 ConsciousLiving）"""
        if self._conscious_living:
            self._conscious_living._send_proactive(content, user_id=user_id)

    def _get_self_image(self):
        """获取 SelfImage（委托给 ConsciousLiving）"""
        if self._conscious_living:
            return self._conscious_living.consciousness.get_self_image()
        return None

    def inject_conscious_living(self, cl) -> None:
        """注入 ConsciousLiving 引用（用于执行动作）"""
        self._conscious_living = cl

    def inject_learn_engine(self, engine) -> None:
        """注入 LearningEngine（替代本地学习方法的委托对象）"""
        self._executor._learn_engine = engine
