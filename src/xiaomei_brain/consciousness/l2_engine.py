"""L2Engine: L2 轻度加柴引擎（DMN — 内心独白）。

从 Consciousness 中抽取，独立管理 L2 的两次 LLM 调用流程：
- 调用 1：意图决策（ReAct + 工具）
- 调用 2：意识涌现（内心独白 + DOUBT）

Social cognition（EVENTS/PERCEPTION/SIGNAL）已拆到 metacognition/social_cognition.py。
Narrative Memory（NARR）已拆到 RoundScheduler._invoke_narrative_learn()。

输入：SelfImage 状态 + 触发 context
输出：Intent + 内心独白
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime
from typing import TYPE_CHECKING, Any

from .intent import Intent, IntentType, create_wait_intent, create_greet_intent, create_reflect_intent, create_dream_intent, create_care_intent, create_sleep_intent
from xiaomei_brain.consciousness.context_pipeline import build_simple_context
from xiaomei_brain.prompts import L2_EMERGENCE_PROMPT, L2_EMERGENCE_FORMAT_APPENDIX

if TYPE_CHECKING:
    from .core import Consciousness, ConsciousnessReport

logger = logging.getLogger(__name__)


class L2Engine:
    """L2 轻度加柴引擎（DMN — 内心独白）。

    持有 Consciousness 引用，负责 L2 的完整生命周期：
    intent_react → parse → emergence_react → split_doubt → store

    Social cognition（EVENTS/PERCEPTION/SIGNAL → Drive）已拆到 SocialCognition。

    拥有独立的 Agent 实例（_l2_agent），与 Layer 1 的 Agent 隔离：
    - 独立的 messages / session_id / tool_call_buffer
    - 只注册探索类工具（dag_expand / dag_search / web_search / thought_search / being）
    - 不写 ConversationDB，不触发记忆提取
    """

    # 探索类工具白名单
    EXPLORE_TOOL_NAMES: set[str] = {"dag_expand", "dag_search", "web_search", "thought_search", "being", "check_inbox"}

    # 欲望饥渴 → 对应意图类型
    _DESIRE_INTENT_TYPE = {
        "belonging": IntentType.GREET,
        "cognition": IntentType.LEARN,
        "achievement": IntentType.PROGRESS,
        "expression": IntentType.EXPRESS,
    }

    def __init__(self, consciousness: Consciousness) -> None:
        self._c = consciousness
        self._l2_agent: Any = None  # 独立 Agent 实例（懒加载）
        self._learn_queue = None  # LearningQueue（由 ConsciousLiving 注入）
        self._wild_observer: Any = None  # WildObserver（懒加载）

    # ── WildObserver ──────────────────────────────────────

    def _observe(
        self, context: str, drive_snapshot: dict, intent: Any,
        emergence_text: str, doubts: list[dict],
    ) -> None:
        """被动记录一次 L2 观测数据。不改变任何逻辑。"""
        try:
            if self._wild_observer is None:
                from .wild_observer import WildObserver
                self._wild_observer = WildObserver(self._c._agent_id)

            agent_core = self._c.agent._get_agent()
            user_name = getattr(agent_core, 'user_display_name', '')

            self._wild_observer.observe_l2(
                context=context,
                drive_snapshot=drive_snapshot,
                intent=intent,
                emergence_text=emergence_text,
                doubts=doubts,
                user_name=user_name,
            )
        except Exception as e:
            logger.debug("[L2Engine] WildObserver failed: %s", e)

    # ── L2 独立 Agent ───────────────────────────────────────

    def _get_l2_agent(self) -> Any:
        """懒加载 L2 专用 Agent 实例。

        与 Layer 1 的 Agent 完全隔离：
        - 独立的 messages / session_id / tool_call_buffer
        - 只注册探索类工具
        - 共享 LLM 客户端（线程安全，只做 HTTP 请求）
        """
        if self._l2_agent is not None:
            return self._l2_agent

        from ..agent.core import Agent
        from ..tools.registry import ToolRegistry

        c = self._c
        agent_instance = c.agent  # AgentInstance
        main_agent = agent_instance._get_agent()  # core Agent

        # 创建探索类工具专用 ToolRegistry
        l2_tools = ToolRegistry()
        agent_tools = getattr(agent_instance, "tools", None)
        if agent_tools:
            for name in self.EXPLORE_TOOL_NAMES:
                tool = agent_tools.get(name)
                if tool:
                    l2_tools.register(tool)
                    logger.debug("[L2Engine] 注册工具: %s", name)

        # 创建独立 Agent
        self._l2_agent = Agent(
            llm=main_agent.llm,
            tools=l2_tools,
            system_prompt="",
            max_steps=12,
        )
        self._l2_agent.session_id = "l2-internal"
        self._l2_agent.user_id = c._agent_id

        logger.info(
            "[L2Engine] 独立 Agent 已创建: session=%s, tools=%d",
            self._l2_agent.session_id,
            len(l2_tools.list_tools()),
        )
        return self._l2_agent

    # ── 公共入口 ─────────────────────────────────────────────

    def tick(self, context: str) -> ConsciousnessReport:
        """[已废弃] 执行一次 L2 tick（意图决策 + 内心独白合体）。

        全代码库零调用。实际流程中 Layer2 拆分调用：
        - tick_intent(): 只做意图决策
        - tick_emergence(): 只做内心独白

        调用 1：意图决策 — inject_consciousness() + 意图指令
        调用 2：意识涌现 — inject_consciousness() + 自由表达 + DOUBT
        """
        c = self._c
        c._last_intent_time = time.time()
        c._last_emerge_time = time.time()

        # 刷新意识记忆窗口
        c._refresh_memory_window()

        # ── 观测：捕获 L2 前的 Drive 快照（不干预，只记录）──
        drive_snapshot = {}
        if c.self_image:
            bo = c.self_image.body
            drive_snapshot = {
                "energy": bo.energy,
                "emotion": bo.mood,
                "emotion_intensity": bo.emotion_intensity,
                "belonging": bo.desire_belonging,
                "cognition": bo.desire_cognition,
                "achievement": bo.desire_achievement,
                "expression": bo.desire_expression,
            }

        llm = getattr(c.agent, "llm", None)
        emergence_text = ""
        intent = None
        doubts: list[dict] = []

        if llm:
            try:
                # ── 调用 1：意图决策（ReAct + 工具）──────────────
                intent_response = self._call_intent_react(context)
                intent = self._parse_intent_response(intent_response)
                logger.debug("[Consciousness L2] 意图决策: %s", intent_response[:200])

                if c.drive:
                    c.drive.consume_energy(0.01)

                # 欲望饥渴时，强制意图匹配对应欲望
                if intent and context.startswith("desire_starvation_"):
                    desire_type = context.replace("desire_starvation_", "")
                    expected = self._DESIRE_INTENT_TYPE.get(desire_type)
                    c.intent_slot.urgent_intents.add((expected or intent.type).value)
                    if expected and intent.type != expected:
                        logger.info("[Consciousness L2] 意图修正: %s → %s（异常=%s）",
                                    intent.type.value, expected.value, context)
                        intent = Intent(type=expected, priority=intent.priority, content=intent.content)

                # ── 调用 2：意识涌现（带探索工具）────────────
                agent_core = self._c.agent._get_agent()
                user_name = getattr(agent_core, 'user_display_name', '这位用户')

                # ── 欲望冲突检测：多欲望高 + 能量低 → 内在张力 ──
                conflict_desc = ""
                if c.self_image:
                    bo = c.self_image.body
                    desires = [
                        ("归属欲", bo.desire_belonging),
                        ("认知欲", bo.desire_cognition),
                        ("成就欲", bo.desire_achievement),
                        ("表达欲", bo.desire_expression),
                    ]
                    high = [(n, v) for n, v in desires if v > 0.65]
                    if len(high) >= 2 and bo.energy < 0.4:
                        names = "、".join(f"{n}({v:.0%})" for n, v in high)
                        conflict_desc = (
                            f"你的{names}都很高，但能量只有{bo.energy:.0%}。"
                            f"这种矛盾让你感到内在的拉扯——想要多个方向同时前进，但力不从心。"
                        )

                emergence_prompt = self._build_l2_prompt(
                    context, user_name=user_name, conflict=conflict_desc,
                )
                emergence_text = self._call_emergence_react(llm, emergence_prompt)

                if c.drive:
                    c.drive.consume_energy(0.02)

                # 分离自我不确定感
                emergence_text, doubts = self._split_doubt(emergence_text)
                if doubts:
                    c.self_image.contribute_self_doubts(doubts)
                    logger.info("[Consciousness L2] 自我不确定: %d 条", len(doubts))

                # 终端展示自由表达
                if emergence_text:
                    from .internal_display import C_FREE, RESET, print_section
                    print_section("自由表达", icon="✨")
                    print(f"{C_FREE}{emergence_text}{RESET}", flush=True)

                # 清空累积变化
                c._state_buffer.clear()
                c.history.last_llm_fuel_time = time.time()

                # 清空 PACE 反射缓冲
                if c.self_image.mind.pace_reflections:
                    consumed = len(c.self_image.mind.pace_reflections)
                    c.self_image.mind.pace_reflections = []
                    logger.info("[Consciousness L2] 已消费 %d 条 PACE 反射", consumed)
            except Exception as e:
                logger.warning("[Consciousness L2] LLM调用失败: %s", e)

        # 如果LLM失败，用规则生成意图
        if not intent:
            intent = self._fallback_intent(context)
            if intent and context.startswith("desire_starvation_"):
                c.intent_slot.urgent_intents.add(intent.type.value)

        # 存入意图缓冲
        if intent and intent.is_actionable():
            if c.self_image is not None:
                c.self_image.contribute_intent(intent.to_dict())
            # LEARN 意图的 TOPIC 也加入学习队列（持久化，不依赖立即触发）
            if intent.type == IntentType.LEARN:
                learn_topic = (intent.params or {}).get("learn_topic", "")
                if learn_topic and self._learn_queue is not None:
                    ok = self._learn_queue.add(
                        topic=learn_topic,
                        reason=intent.content or "L2 意图决策",
                        priority=0.7,
                        source="user_need",
                    )
                    if ok:
                        logger.info("[Consciousness L2] LEARN TOPIC 入队: %s", learn_topic)

        # 生成报告
        report = self._build_report(context, emergence_text, intent)
        c._last_report = report

        # 存储
        if c._storage:
            c._storage.save(report)

        # 写入意识涌现 → inner_thought + consciousness_stream
        self._store_emergence(emergence_text)

        # Narrative Memory 已拆到 RoundScheduler._invoke_narrative_learn()
        # via ConversationDriver，不再从 L2 emergence 生成 NARR 块

        # ── Desk: 把 L2 的分析扔上桌面 ─────────────────
        self._drop_to_desk(context, intent, emergence_text)

        # ── Experience Stream: 记录内部思考 ───────────
        self._log_to_experience_stream(context, intent, emergence_text)

        # ── WildObserver: 被动记录，不干预 ─────────────
        self._observe(context, drive_snapshot, intent, emergence_text, doubts)

        return report

    def tick_intent(self, context: str) -> Intent | None:
        """只做意图决策，不跑内心独白。用于 anomaly 等只需决策的场景。"""
        c = self._c
        c._last_intent_time = time.time()
        c._refresh_memory_window()

        # 观测快照
        drive_snapshot = {}
        if c.self_image:
            bo = c.self_image.body
            drive_snapshot = {
                "energy": bo.energy,
                "emotion": bo.mood,
                "emotion_intensity": bo.emotion_intensity,
                "belonging": bo.desire_belonging,
                "cognition": bo.desire_cognition,
                "achievement": bo.desire_achievement,
                "expression": bo.desire_expression,
            }

        llm = getattr(c.agent, "llm", None)
        intent = None

        if llm:
            try:
                intent_response = self._call_intent_react(context)
                intent = self._parse_intent_response(intent_response)
                logger.debug("[Consciousness L2] 意图决策: %s", intent_response[:200])

                if c.drive:
                    c.drive.consume_energy(0.01)

                # 欲望饥渴 force-correction
                if intent and context.startswith("desire_starvation_"):
                    desire_type = context.replace("desire_starvation_", "")
                    expected = self._DESIRE_INTENT_TYPE.get(desire_type)
                    c.intent_slot.urgent_intents.add(
                        (expected or intent.type).value
                    )
                    if expected and intent.type != expected:
                        logger.info("[Consciousness L2] 意图修正: %s → %s（异常=%s）",
                                    intent.type.value, expected.value, context)
                        intent = Intent(type=expected, priority=intent.priority, content=intent.content)
            except Exception as e:
                logger.warning("[Consciousness L2] 意图决策失败: %s", e)

        # fallback intent
        if not intent:
            intent = self._fallback_intent(context)
            if intent and context.startswith("desire_starvation_"):
                c.intent_slot.urgent_intents.add(intent.type.value)

        # 存入意图缓冲
        if intent and intent.is_actionable():
            if c.self_image is not None:
                c.self_image.contribute_intent(intent.to_dict())
            if intent.type == IntentType.LEARN:
                learn_topic = (intent.params or {}).get("learn_topic", "")
                if learn_topic and self._learn_queue is not None:
                    self._learn_queue.add(
                        topic=learn_topic,
                        reason=intent.content or "L2 意图决策",
                        priority=0.7,
                        source="user_need",
                    )

        # 后处理
        self._drop_to_desk(context, intent, "")
        self._log_to_experience_stream(context, intent, "")

        report = self._build_report(context, "", intent)
        c._last_report = report
        if c._storage:
            c._storage.save(report)

        self._observe(context, drive_snapshot, intent, "", [])

        return intent

    def tick_emergence(self, context: str) -> str:
        """只做内心独白，不跑意图决策。用于 periodic 等需要自我表达的场景。"""
        c = self._c
        c._last_emerge_time = time.time()
        c._refresh_memory_window()

        drive_snapshot = {}
        if c.self_image:
            bo = c.self_image.body
            drive_snapshot = {
                "energy": bo.energy,
                "emotion": bo.mood,
                "emotion_intensity": bo.emotion_intensity,
                "belonging": bo.desire_belonging,
                "cognition": bo.desire_cognition,
                "achievement": bo.desire_achievement,
                "expression": bo.desire_expression,
            }

        llm = getattr(c.agent, "llm", None)
        emergence_text = ""
        doubts: list[dict] = []

        if llm:
            try:
                agent_core = c.agent._get_agent()
                user_name = getattr(agent_core, 'user_display_name', '这位用户')

                conflict_desc = ""
                if c.self_image:
                    bo = c.self_image.body
                    desires = [
                        ("归属欲", bo.desire_belonging),
                        ("认知欲", bo.desire_cognition),
                        ("成就欲", bo.desire_achievement),
                        ("表达欲", bo.desire_expression),
                    ]
                    high = [(n, v) for n, v in desires if v > 0.65]
                    if len(high) >= 2 and bo.energy < 0.4:
                        names = "、".join(f"{n}({v:.0%})" for n, v in high)
                        conflict_desc = (
                            f"你的{names}都很高，但能量只有{bo.energy:.0%}。"
                            f"这种矛盾让你感到内在的拉扯——想要多个方向同时前进，但力不从心。"
                        )

                emergence_prompt = self._build_l2_prompt(context, user_name=user_name, conflict=conflict_desc)
                emergence_text = self._call_emergence_react(llm, emergence_prompt)

                if c.drive:
                    c.drive.consume_energy(0.02)

                # 分离自我不确定感
                emergence_text, doubts = self._split_doubt(emergence_text)
                if doubts:
                    c.self_image.contribute_self_doubts(doubts)
                    logger.info("[Consciousness L2] 自我不确定: %d 条", len(doubts))

                if emergence_text:
                    from .internal_display import C_FREE, RESET, print_section
                    print_section("自由表达", icon="✨")
                    print(f"{C_FREE}{emergence_text}{RESET}", flush=True)

                c._state_buffer.clear()
                c.history.last_llm_fuel_time = time.time()

                if c.self_image.mind.pace_reflections:
                    consumed = len(c.self_image.mind.pace_reflections)
                    c.self_image.mind.pace_reflections = []
                    logger.info("[Consciousness L2] 已消费 %d 条 PACE 反射", consumed)
            except Exception as e:
                logger.warning("[Consciousness L2] 内心独白失败: %s", e)

        # 后处理
        self._store_emergence(emergence_text)
        narr_count = self._store_narr_blocks(emergence_text)
        c._last_emergence_stored = 1 if emergence_text else 0
        c._last_emergence_narr = narr_count
        c._last_emergence_doubt = len(doubts)

        self._drop_to_desk(context, None, emergence_text)
        self._log_to_experience_stream(context, None, emergence_text)

        report = self._build_report(context, emergence_text, None)
        c._last_report = report
        if c._storage:
            c._storage.save(report)

        self._observe(context, drive_snapshot, None, emergence_text, doubts)

        return emergence_text

    # ── 调用 1：意图决策 ─────────────────────────────────────

    def _call_intent_react(self, context: str) -> str:
        """通过 L2 独立 Agent 的 ReAct 循环进行意图决策（探索类工具，静默）。"""
        c = self._c
        l2_agent = self._get_l2_agent()

        system_prompt = build_simple_context(c, mode="internal")
        has_goal = c.purpose and c.purpose.get_current() is not None

        # 查询目标 tag 的记忆
        goal_memories = []
        longterm = getattr(c.agent, "longterm_memory", None)
        if longterm:
            try:
                conn = longterm._get_conn()
                rows = conn.execute(
                    """SELECT m.content, m.created_at FROM memories m
                       JOIN memory_tags mt ON m.id = mt.memory_id
                       WHERE m.user_id = ? AND m.status != 'EXTINCT'
                       AND mt.tag IN ('目标', '任务')
                       ORDER BY m.created_at DESC LIMIT 10""",
                    (c._agent_id,),
                ).fetchall()
                for r in rows:
                    goal_memories.append({
                        "content": r["content"],
                        "created_at": r["created_at"],
                    })
            except Exception as e:
                logger.warning("查询目标相关记忆失败: %s", e)

        question = self._build_intent_prompt(context, has_goal=has_goal, goal_memories=goal_memories)

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": question},
        ]

        logger.info("[Consciousness] ReAct 意图决策开始, sys_len=%d, q_len=%d",
                    len(system_prompt), len(question))

        # 提示用户意图决策开始（silent 模式下 react_nodb 不打印 header）
        from .internal_display import print_section
        print_section("意图决策", icon="🧠")

        t0 = time.time()
        try:
            result = l2_agent.react_nodb(messages=messages, max_steps=12, label="intent", silent=True)
            elapsed = time.time() - t0
            logger.info("[Consciousness] ReAct 意图决策完成, elapsed=%.1fs, result_len=%d",
                        elapsed, len(result))
            # 展示思考部分，过滤 ---INTENT--- 结构块
            self._print_intent_display(result)
            return result
        except Exception as e:
            from xiaomei_brain.llm.client import LLMError
            if isinstance(e, LLMError) and e.retryable:
                logger.warning("[Consciousness] ReAct 意图决策: 网络异常，跳过本次")
            else:
                logger.error("[Consciousness] ReAct 意图决策失败: %s", e, exc_info=True)
            return ""

    def _build_intent_prompt(self, context: str, has_goal: bool = False, goal_memories: list[dict] | None = None) -> str:
        """构建意图决策问题 prompt。"""
        context_note = ""
        if context:
            context_map = {
                "user_idle_long": "触发原因：对方较长时间没说话，你可能想确认他是否还在。",
                "user_idle_critical": "触发原因：对方很久没说话了，你可能想主动联系他。",
                "goal_deviation": "触发原因：目标进展出现偏离，可能需要反省。",
                "memory_loss": "触发原因：记忆数量减少，可能需要关注。",
                "energy_low": "触发原因：能量偏低，可能需要休息或进入梦境。",
                "agent_state_reset": "触发原因：状态意外重置，需要重新确认自身存在。",
                "consciousness_restart": "触发原因：意识刚重新启动。",
                "emotion_spike": "触发原因：情绪剧烈波动，需要表达或处理。",
            }
            if context.startswith("desire_starvation_"):
                desire_type = context.replace("desire_starvation_", "")
                desire_map = {
                    "belonging": "归属欲", "cognition": "认知欲",
                    "achievement": "成就欲", "expression": "表达欲",
                }
                dn = desire_map.get(desire_type, desire_type)
                context_note = f"触发原因：{dn}长期未被满足，已处于饥渴状态。"
            else:
                context_note = context_map.get(context, f"触发原因：{context}")

        intents = "wait / greet / care / learn / express / work / talk / talk_agent"
        if has_goal:
            intents += " / progress"
        intents += " / reflect / sleep"
        prompt = (
            "基于你的自我认知，请判断你此刻应该做什么。你可以使用工具来辅助判断（如搜索、读文件等）。\n\n"
            + "意图说明：\n"
            + "- talk：想和用户进行更深入的对话交流（区别于 greet 的简短问候）\n"
            + "- talk_agent：想和其他 agent 聊天交流\n"
            + "- sleep：能量已经很困了，或者手头确实无事可做，主动进入休眠节省资源\n"
            + f"可选意图：{intents}\n"
        )
        # 有未完成目标时，优先推进
        if has_goal:
            prompt += (
                "\n**重要**：你有未完成的目标。当前用户不在，这是你推进目标的最佳时机。"
                "如果没有更紧急的事，应该优先选择 progress 意图来执行目标。\n"
            )
        if goal_memories:
            lines = []
            for i, m in enumerate(goal_memories, 1):
                created_raw = m.get("created_at")
                created = ""
                if created_raw:
                    try:
                        if isinstance(created_raw, (int, float)):
                            created = datetime.fromtimestamp(created_raw).strftime("%m-%d")
                        else:
                            created = str(created_raw)[:10]
                    except Exception:
                        created = ""
                time_tag = f"（{created}）" if created else ""
                lines.append(f"  {i}. {m.get('content', '')[:120]}{time_tag}")
            prompt += f"\n待办事项：\n" + "\n".join(lines) + "\n"
            prompt += "如果你判断应该推进工作，选择 work 意图。"
        if context_note:
            prompt += f"\n{context_note}\n"

        # periodic/idle 触发时，注入当前欲望水平让 LLM 注意到
        # 注释原因：系统提示词 _render_body() 已包含欲望水平，先观察 LLM 是否能自行注意到
        # if context in ("periodic", "user_idle_long", "accumulated_changes", "unknown"):
        #     bo = c.self_image.body
        #     desire_hints = []
        #     if bo.desire_belonging > 0.6:
        #         desire_hints.append(f"你的归属欲较高（{bo.desire_belonging:.0%}），可以考虑 talk 或 talk_agent")
        #     if bo.desire_cognition > 0.6:
        #         desire_hints.append(f"你的认知欲较高（{bo.desire_cognition:.0%}），可以考虑 learn")
        #     if bo.desire_achievement > 0.6:
        #         desire_hints.append(f"你的成就欲较高（{bo.desire_achievement:.0%}），可以考虑 progress")
        #     if bo.desire_expression > 0.6:
        #         desire_hints.append(f"你的表达欲较高（{bo.desire_expression:.0%}），可以考虑 express")
        #     if desire_hints:
        #         prompt += "\n".join(desire_hints) + "\n"

        # 注入情境相关模式（注入点2）
        try:
            ltm_ref = getattr(self._c, 'agent', None)
            ltm_ref = getattr(ltm_ref, 'longterm_memory', None) if ltm_ref else None
            if ltm_ref:
                from ..memory.pattern import PatternStorage, PatternInjector
                storage = PatternStorage(ltm_ref)
                injector = PatternInjector(storage, ltm_ref)
                pattern_line = injector.inject_l2_intent(context)
                if pattern_line:
                    prompt += f"\n{pattern_line}\n"
        except Exception as e:
            logger.debug("Pattern 注入 L2 intent 失败（将跳过）: %s", e)

        prompt += ("\n先自由思考，分析你此刻的状态、能量、欲望水平、对方的情况，"
                   "说明你为什么做出这个选择——不要直接给结论，要让读的人理解你的推理过程。"
                   "然后在 ---INTENT--- 分隔符后输出结构化结果：\n"
                   "---INTENT---\n"
                   "INTENT: <意图类型>\n"
                   "REASON: <理由，一句话>\n"
                   "TARGET_USER: <目标用户ID>（greet/care/express/talk 等主动消息必填，其他意图填 \"-\"）\n"
                   "TOPIC: <学习主题>（仅 LEARN 意图时需要，其他意图不输出此行）")
        return prompt

    @staticmethod
    def _strip_block(text: str, marker: str) -> str:
        """去除结构化块（---INTENT--- 等），只保留思考文本。"""
        if marker in text:
            text = text.split(marker, 1)[0]
        return text.strip()

    def _print_intent_display(self, response: str) -> None:
        """展示意图决策的思考过程，过滤掉 ---INTENT--- 结构块。"""
        thinking = self._strip_block(response, "---INTENT---")
        if thinking:
            from .internal_display import C_FREE, RESET
            print(f"{C_FREE}{thinking}{RESET}", flush=True)

    def _parse_intent_response(self, response: str) -> Intent | None:
        """解析 LLM 返回的意图。优先从 ---INTENT--- 块提取，兼容旧格式。"""
        # 优先从 ---INTENT--- 块提取
        block_content = response
        if "---INTENT---" in response:
            parts = response.split("---INTENT---", 1)
            block_content = parts[1] if len(parts) > 1 else response

        match = re.search(r"INTENT:\s*(\w+)", block_content, re.IGNORECASE)
        if not match:
            # 兼容：整个 response 中搜索
            match = re.search(r"INTENT:\s*(\w+)", response, re.IGNORECASE)
            if not match:
                return None

        intent_type_str = match.group(1).upper()

        try:
            intent_type = IntentType(intent_type_str.lower())
        except ValueError:
            return None

        reason_match = re.search(r"REASON:\s*(.+)", block_content)
        reason = reason_match.group(1).strip() if reason_match else ""

        # 解析 TARGET_USER
        target_match = re.search(r"TARGET_USER:\s*(.+)", block_content)
        target_user = target_match.group(1).strip() if target_match else ""
        if target_user in ("-", "null", "none", ""):
            target_user = ""

        # 解析 LEARN 意图的 TOPIC 字段
        topic_match = re.search(r"TOPIC:\s*(.+)", block_content)
        learn_topic = topic_match.group(1).strip() if topic_match else ""

        if intent_type == IntentType.LEARN and learn_topic:
            logger.info("[Consciousness L2] 意图: LEARN → %s", learn_topic)

        priority_map = {
            IntentType.WAIT: 10,
            IntentType.GREET: 70,
            IntentType.CARE: 75,
            IntentType.REFLECT: 50,
            IntentType.DREAM: 40,
            IntentType.LEARN: 60,
            IntentType.EXPRESS: 60,
            IntentType.PROGRESS: 60,
            IntentType.WORK: 55,
            IntentType.SLEEP: 80,
        }

        params = {"learn_topic": learn_topic} if learn_topic else {}
        if target_user:
            params["user_id"] = target_user

        return Intent(
            type=intent_type,
            priority=priority_map.get(intent_type, 50),
            content=reason,
            params=params,
        )

    def _fallback_intent(self, context: str) -> Intent:
        """规则生成意图（LLM 失败时）。"""
        si = self._c.self_image

        if context == "user_idle_long":
            return create_greet_intent("对方长时间没说话，想问候")
        elif context == "user_idle_critical":
            return create_greet_intent("对方很久没说话，想问候", priority=85)
        elif context == "goal_deviation":
            return create_reflect_intent("目标进展连续下降")
        elif context == "memory_loss":
            return create_reflect_intent("记忆数量减少")
        elif context == "energy_low":
            return create_dream_intent(priority=60)
        elif context == "agent_state_reset":
            return create_greet_intent("状态意外重置，重新确认存在", priority=70)
        elif context == "consciousness_restart":
            if si.history.last_dream_summary:
                return create_greet_intent(si.history.last_dream_summary[:50], priority=80)
            else:
                return create_greet_intent("我醒了", priority=70)
        elif context.startswith("desire_starvation_"):
            desire_type = context.replace("desire_starvation_", "")
            if desire_type == "belonging":
                return create_greet_intent("归属欲长期未被满足，想联系对方", priority=75)
            elif desire_type == "cognition":
                return Intent(type=IntentType.LEARN, priority=70, content="认知欲饥渴，想学习新知识")
            elif desire_type == "achievement":
                return Intent(type=IntentType.PROGRESS, priority=70, content="成就欲饥渴，想推进目标")
            elif desire_type == "expression":
                return Intent(type=IntentType.EXPRESS, priority=70, content="表达欲饥渴，想分享想法")
            else:
                return create_wait_intent()
        elif context == "emotion_spike":
            return create_care_intent("情绪剧烈波动，想表达感受", priority=80)
        else:
            return create_wait_intent()

    # ── 调用 2：意识涌现 ─────────────────────────────────────

    def _build_l2_prompt(self, context: str, user_name: str = "对方", conflict: str = "") -> str:
        """构建 L2 加柴 prompt — 使用 inject_consciousness 作为状态头。"""
        consciousness_context = build_simple_context(self._c, mode="internal")

        conflict_hint = ""
        if conflict:
            conflict_hint = (
                f"\n（注意：{conflict}"
                f"在下面的思考中，请自然地表达你的不确定和矛盾感。）\n"
            )

        return L2_EMERGENCE_PROMPT.format(
            consciousness_context=consciousness_context,
            conflict_hint=conflict_hint,
            format_appendix=L2_EMERGENCE_FORMAT_APPENDIX,
        )

    def _call_emergence_react(self, llm, prompt: str, exclude_tools: set[str] | None = None) -> str:
        """意识涌现 ReAct 循环（带探索工具），最多 2 轮工具调用。"""
        from ..tools.registry import ToolRegistry

        # 从 L2 独立 Agent 获取探索类工具
        l2_agent = self._get_l2_agent()
        l2_tools = getattr(l2_agent, "tools", None)
        explore_tool_names = set(self.EXPLORE_TOOL_NAMES)
        if exclude_tools:
            explore_tool_names -= exclude_tools
        explore_tools: list = []
        if l2_tools:
            for name in explore_tool_names:
                tool = l2_tools.get(name)
                if tool:
                    explore_tools.append(tool)

        if not explore_tools:
            resp = llm.chat(
                messages=[{"role": "user", "content": prompt}],
                tools=None,
            )
            return resp.content or ""

        tmp_registry = ToolRegistry()
        for t in explore_tools:
            tmp_registry.register(t)

        openai_tools = tmp_registry.to_openai_tools()
        messages: list[dict] = [{"role": "user", "content": prompt}]

        max_rounds = 2
        for _round in range(max_rounds):
            resp = llm.chat(messages=messages, tools=openai_tools)

            if resp.tool_calls:
                assistant_msg = {
                    "role": "assistant",
                    "content": resp.content or "",
                    "tool_calls": [
                        {"id": tc.id, "type": "function",
                         "function": {"name": tc.name, "arguments": json.dumps(tc.arguments, ensure_ascii=False)}}
                        for tc in resp.tool_calls
                    ],
                }
                messages.append(assistant_msg)

                for tc in resp.tool_calls:
                    try:
                        result = tmp_registry.execute(tc.name, **tc.arguments)
                    except Exception as e:
                        result = f"工具执行失败: {e}"
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result[:2000],
                    })

                logger.info(
                    "[Consciousness] 涌现探索 round=%d, tool_calls=%s",
                    _round + 1, [tc.name for tc in resp.tool_calls],
                )
            else:
                return resp.content or ""

        resp = llm.chat(
            messages=messages + [{"role": "user", "content": "请基于以上探索，输出你的内心独白。" + L2_EMERGENCE_FORMAT_APPENDIX}],
            tools=None,
        )
        return resp.content or ""

    # ── 后处理 ──────────────────────────────────────────────

    @staticmethod
    def _split_consciousness_events(response: str) -> tuple[str, str]:
        """分离意识涌现文本和驱动事件 JSON。"""
        if "---EVENTS---" in response:
            parts = response.split("---EVENTS---", 1)
            consciousness = parts[0].strip()
            events = parts[1].strip() if len(parts) > 1 else ""
            return consciousness, events
        return response, ""

    @staticmethod
    def _split_signal(text: str) -> tuple[str, str]:
        """分离 ---SIGNAL--- JSON（深度感知判断）。"""
        if "---SIGNAL---" not in text:
            return text, ""

        idx = text.index("---SIGNAL---")
        signal_content = text[idx + len("---SIGNAL---"):].strip()
        clean_text = text[:idx].strip()
        return clean_text, signal_content

    @staticmethod
    def _split_perception(text: str) -> tuple[str, list[dict]]:
        """分离感知检查块（第四问产出）。"""
        if "---PERCEPTION---" not in text:
            return text, []

        idx = text.index("---PERCEPTION---")
        after_marker = text[idx + len("---PERCEPTION---"):]

        next_pos = None
        for sep in ["---EVENTS---", "---NARR---"]:
            pos = after_marker.find(sep)
            if pos != -1 and (next_pos is None or pos < next_pos):
                next_pos = pos

        perception_content = after_marker[:next_pos] if next_pos is not None else after_marker

        perceptions = []
        for line in perception_content.split("\n"):
            line = line.strip()
            if line.startswith("- ") or line.startswith("• "):
                content = line[2:].strip()
                if content:
                    perceptions.append({
                        "content": content,
                        "time": time.time(),
                    })

        if next_pos is not None:
            clean_text = text[:idx] + after_marker[next_pos:]
        else:
            clean_text = text[:idx]

        return clean_text.strip(), perceptions

    @staticmethod
    def _split_doubt(text: str) -> tuple[str, list[dict]]:
        """分离 ---DOUBT--- 块（自我不确定感）。"""
        if "---DOUBT---" not in text:
            return text, []

        idx = text.index("---DOUBT---")
        after_marker = text[idx + len("---DOUBT---"):]

        next_pos = None
        for sep in ["---EVENTS---", "---NARR---", "---PERCEPTION---", "---SIGNAL---"]:
            pos = after_marker.find(sep)
            if pos != -1 and (next_pos is None or pos < next_pos):
                next_pos = pos

        doubt_content = after_marker[:next_pos] if next_pos is not None else after_marker

        doubts = []
        for line in doubt_content.split("\n"):
            line = line.strip()
            if line.startswith("- ") or line.startswith("• "):
                content = line[2:].strip()
                if content:
                    doubts.append({
                        "content": content,
                        "time": time.time(),
                    })

        if next_pos is not None:
            clean_text = text[:idx] + after_marker[next_pos:]
        else:
            clean_text = text[:idx].strip()

        return clean_text, doubts

    # ── 存储 ─────────────────────────────────────────────────

    def _build_report(self, context: str, emergence_text: str, intent: Intent | None) -> ConsciousnessReport:
        """生成 ConsciousnessReport。"""
        from .core import ConsciousnessReport

        c = self._c
        try:
            si_snapshot = c.self_image.to_dict()
        except Exception:
            si_snapshot = {}

        return ConsciousnessReport(
            trigger="tick_L2",
            depth="light",
            summary=f"LLM加柴：{emergence_text[:50] if emergence_text else context}",
            full_report=emergence_text,
            self_image_snapshot=si_snapshot,
            intent_snapshot=intent.to_dict() if intent else None,
            anomaly=context,
        )

    def _store_emergence(self, emergence_text: str) -> None:
        """写入意识涌现 → inner_thought + consciousness_stream。"""
        if not emergence_text:
            return
        c = self._c

        logger.info("[Consciousness L2] 自由表达已存储 (%d 字)", len(emergence_text))
        if c.agent and hasattr(c.agent, "longterm_memory") and c.agent.longterm_memory and emergence_text:
            c.agent.longterm_memory.store_narrative(
                content=emergence_text,
                trigger='L2_light',
                energy_level=c.body.energy if c.self_image else None,
                user_idle_duration=c.perception.user_idle_duration if c.self_image else None,
                conversation_summary=c._get_recent_conversation()[:100] if hasattr(c, '_get_recent_conversation') else None,
                user_id=getattr(c.agent, "user_id", "global"),
            )

    def _store_narr_blocks(self, emergence_text: str) -> int:
        """解析并存储 NARR 块，返回成功存储数量。"""
        from ..memory.narrative import parse_narr_block

        c = self._c
        ltm = c.agent.longterm_memory
        narr_blocks = parse_narr_block(emergence_text)
        stored = 0
        for nb in narr_blocks:
            try:
                nm_id = ltm.store_narrative_memory(
                    category=nb.get("category", "自我定义"),
                    content=nb.get("content", ""),
                    scene_tags=nb.get("scene_tags", []),
                    feels_like=nb.get("feels_like", ""),
                    changed_me=nb.get("changed_me", ""),
                    weight=nb.get("weight", 0.8),
                    related_narrative_id=None,
                    source="L2",
                    timestamp=nb.get("timestamp"),
                    user_id=getattr(c.agent, "user_id", "global"),
                )
                logger.info("\033[91m[NARR]\033[0m tick_L2 stored: %s", nm_id)
                stored += 1
                if c.drive:
                    c.drive.on_insight(0.1)
            except Exception as e:
                logger.warning("\033[91m[NARR]\033[0m store failed: %s", e)
        return stored

    def _drop_to_desk(self, context: str, intent: Intent | None, emergence_text: str) -> None:
        """把 L2 的分析结果扔到桌面，供 Action/Chat 取用。"""
        c = self._c
        si = c.self_image
        if not si or not hasattr(si, "desk"):
            return

        desk = si.desk

        # 1. 意图决策
        # SLEEP intent 不放 desk：它是纯状态切换信号，只有 IDLE 循环消费，
        # 不需要让 ActionDispatcher / chat 上下文渲染等看到。
        if intent and intent.is_actionable() and intent.type != IntentType.SLEEP:
            intent_type = intent.type.value
            intent_content = getattr(intent, "content", "")
            desk.drop(
                content=f"L2 意图决策：{intent_type} — {intent_content}",
                source="L2",
                intent=intent_type,
                confidence=0.8,
            )

        # 2. 意识涌现摘要（取前 300 字作为上下文）
        if emergence_text and len(emergence_text) > 20:
            desk.drop(
                content=f"L2 内心独白：{emergence_text[:300]}",
                source="L2",
                intent="reflect",
                confidence=0.6,
            )

        logger.info("[L2 Desk] 已投放 %d 条到桌面", (1 if intent else 0) + (1 if emergence_text else 0))

    def _log_to_experience_stream(self, context: str, intent: Intent | None, emergence_text: str) -> None:
        """把 L2 的思考写入经验流。"""
        c = self._c
        es = getattr(c.agent, "exp_stream", None)
        if not es:
            return

        # 意图决策
        if intent and intent.is_actionable():
            intent_type = intent.type.value
            intent_reason = getattr(intent, "content", "")
            try:
                es.log(
                    type="internal_thought",
                    content=f"L2 意图决策：{intent_type} — {intent_reason}",
                    importance=0.6,
                )
            except Exception as e:
                logger.debug("[L2 ExpStream] intent write failed: %s", e)

        # 意识涌现摘要
        if emergence_text and len(emergence_text) > 20:
            try:
                es.log(
                    type="internal_thought",
                    content=f"内心独白：{emergence_text}",
                    importance=0.6,
                )
            except Exception as e:
                logger.debug("[L2 ExpStream] emergence write failed: %s", e)
