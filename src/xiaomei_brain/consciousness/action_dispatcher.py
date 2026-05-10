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
import time
from typing import TYPE_CHECKING, Any, Callable

from ..prompts.drive import EXPRESSION_PROMPT, GREETING_PROMPT, CARE_PROMPT

if TYPE_CHECKING:
    from .action_item import ActionItem, ActionType
    from .self_image_proxy import SelfImage


logger = logging.getLogger(__name__)


class ActionExecutor:
    """动作执行器（只执行不判断）。

    负责把 ActionItem 转换为实际行为。
    """

    LEARN_COOLDOWN = 60  # 学习冷却（秒）

    def __init__(self, dispatcher: ActionDispatcher):
        self.dispatcher = dispatcher
        self._learn_last_mtime: float = 0  # 上次学习文件的 mtime

    def execute(self, item: ActionItem) -> bool:
        """执行单个 ActionItem。

        Returns:
            True 表示执行成功，False 表示失败或无法执行
        """
        handlers = {
            "proactive": self._do_proactive,
            "trigger_l3": self._do_trigger_l3,
            "tool": self._do_tool,
            "notify": self._do_notify,
        }
        handler = handlers.get(item.action_type.value)
        if not handler:
            logger.warning("[ActionExecutor] 未知动作类型: %s", item.action_type)
            return False
        return handler(item)

    def _do_proactive(self, item: ActionItem) -> bool:
        """发送主动消息"""
        content = item.content
        if not content:
            # 空的 content：由 LLM 生成（通过 intent/content + SelfImage 状态）
            logger.info("[ActionExecutor] 主动消息内容为空，调用 LLM 生成...")
            content = self._generate_proactive_content(item)
            logger.info("[ActionExecutor] LLM 生成内容: %s", content[:80])

        # 执行前先记录要消费的 intent 类型
        intent_type = item.metadata.get("intent_type", "") if item.source == "intent" else ""

        self.dispatcher._send_proactive(content)
        logger.info("[ActionExecutor] 主动消息: %s", content[:50])

        # 消费已执行的 intent（避免下一 tick 重复匹配）
        if intent_type and item.source == "intent":
            si = self.dispatcher._get_self_image()
            if si and hasattr(si.intent, "intent_buffer"):
                upper_type = intent_type.upper()
                si.intent.intent_buffer = [i for i in si.intent.intent_buffer if i.upper() != upper_type]
                logger.debug("[ActionExecutor] 已消费 intent: %s", intent_type)

            # 行为完成 → 满足对应欲望（打通 L2 → drive 反馈链路）
            self._satisfy_intent_desire(intent_type)
            # 清除紧急标记
            si = self.dispatcher._get_self_image()
            if si and hasattr(si.intent, "urgent_intents"):
                si.intent.urgent_intents.discard(intent_type.lower())

        return True

    def _satisfy_intent_desire(self, intent_type: str) -> None:
        """行为完成后满足对应的欲望，打通 L2 intent → Drive 反馈链路。"""
        intent_desire_map = {
            "GREET": "belonging",
            "LEARN": "cognition",
            "PROGRESS": "achievement",
            "EXPRESS": "expression",
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

    def _do_trigger_l3(self, item: ActionItem) -> bool:
        """触发 L3 深度燃烧"""
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
                    si.intent.intent_buffer = [i for i in si.intent.intent_buffer if i.upper() != upper_type]
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
        else:
            logger.warning("[ActionExecutor] 未知工具: %s", tool_name)
            return False

        # 消费已执行的 intent（避免下一 tick 重复匹配）
        if item.source == "intent":
            intent_type = item.metadata.get("intent_type", "")
            if intent_type:
                si = self.dispatcher._get_self_image()
                if si and hasattr(si.intent, "intent_buffer"):
                    upper_type = intent_type.upper()
                    si.intent.intent_buffer = [i for i in si.intent.intent_buffer if i.upper() != upper_type]
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

    def _generate_proactive_content(self, item: ActionItem) -> str:
        """通过 LLM 根据意图类型生成主动消息内容"""
        intent_type = item.metadata.get("intent_type", "")
        source = item.metadata.get("source", "")
        desire_type = item.metadata.get("desire_type", "")

        if intent_type == "GREET" or source == "idle":
            return self._generate_greeting(item)
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
                consciousness = si.inject_consciousness()
                resp = llm.chat(messages=[
                    {"role": "system", "content": consciousness},
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

        logger.info("[_generate_greeting] === LLM PROMPT START ===")
        logger.info("%s", prompt)
        logger.info("[_generate_greeting] === LLM PROMPT END ===")

        # 调用 LLM 生成
        llm = None
        cl = self.dispatcher._conscious_living
        if cl and hasattr(cl, "agent"):
            llm = getattr(cl.agent, "llm", None)

        if llm:
            try:
                consciousness = si.inject_consciousness()
                resp = llm.chat(messages=[
                    {"role": "system", "content": consciousness},
                    {"role": "user", "content": prompt},
                ])
                content = resp.content.strip() if resp and resp.content else None
                logger.info("[_generate_greeting] LLM 返回: %s", content[:100] if content else "None")
                if content:
                    return content
            except Exception as e:
                logger.warning("[_generate_greeting] LLM 调用失败: %s", e)

        logger.info("[_generate_greeting] LLM 不可用，fallback")
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
        if si and si.growth.last_dream_summary:
            greeting += f" 我刚做了一个梦，{si.growth.last_dream_summary[:30]}..."
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
                consciousness = si.inject_consciousness()
                resp = llm.chat(messages=[
                    {"role": "system", "content": consciousness},
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
        """主动学习：搜索主题 → LLM 整理 → 保存 .md"""
        living = self.dispatcher._conscious_living
        if not living:
            return False

        topic = self._get_learning_topic()
        if not topic:
            logger.debug("[ActionExecutor] 无学习主题")
            return False

        if living.drive:
            living.drive.on_curiosity(0.1)

        knowledge = self._search_and_learn(topic)
        if not knowledge:
            logger.warning("[ActionExecutor] 学习失败: %s", topic)
            return False

        self._save_knowledge(topic, knowledge)

        if living.drive:
            living.drive.on_desire_satisfied("cognition", 0.3)

        logger.info("[ActionExecutor] 学习完成: %s", topic)
        return True

    def _get_learning_topic(self) -> str | None:
        """获取学习主题。优先级：Purpose 目标 → identity.md 兴趣 → 已有知识文件（跳过冷却期内已学过的）"""
        import random
        from pathlib import Path

        living = self.dispatcher._conscious_living
        if not living:
            return None

        agent_id = getattr(living.agent, "id", "xiaomei") if hasattr(living, "agent") else "xiaomei"
        knowledge_dir = Path.home() / ".xiaomei-brain" / "agents" / agent_id / "knowledge"
        knowledge_dir.mkdir(parents=True, exist_ok=True)

        # 从 Purpose 获取当前目标
        if hasattr(living, 'purpose') and living.purpose:
            current_goal = living.purpose.get_current()
            if current_goal:
                return current_goal.description

        # 从 SelfImage 获取学习兴趣（跳过冷却期内已学过的）
        si = self.dispatcher._get_self_image()
        if si and si.being.learning_interests:
            interests = si.being.learning_interests
            now = time.time()
            fresh = [i for i in interests
                     if not (knowledge_dir / f"{i.replace('/', '_').replace(' ', '_')}.md").exists()
                     or (now - (knowledge_dir / f"{i.replace('/', '_').replace(' ', '_')}.md").stat().st_mtime) >= self.LEARN_COOLDOWN]
            if fresh:
                return random.choice(fresh)
            logger.debug("[ActionExecutor] 所有学习兴趣都在冷却中")

        # 从已有知识文件选择（跳过冷却期内的）
        now = time.time()
        md_files = list(knowledge_dir.glob("*.md"))
        if md_files:
            fresh = [f for f in md_files if (now - f.stat().st_mtime) >= self.LEARN_COOLDOWN]
            if fresh:
                return random.choice(fresh).stem
            # 全部在冷却期内，跳过学习
            logger.debug("[ActionExecutor] 所有知识文件都在冷却中，跳过学习")
            return None

        return "AI技术发展"

    def _search_and_learn(self, topic: str) -> str | None:
        """搜索并学习主题：websearch → LLM 整理"""
        from xiaomei_brain.prompts import LEARN_GENERATE_PROMPT, LEARN_ORGANIZE_PROMPT

        living = self.dispatcher._conscious_living
        if not living:
            return None

        agent = living.agent if hasattr(living, "agent") else None

        # 1. 尝试 websearch
        search_results = None
        try:
            if agent and hasattr(agent, "tool_registry"):
                registry = agent.tool_registry
                if "websearch" in registry._tools:
                    search_results = registry.call("websearch", topic)
        except Exception as e:
            logger.warning("[ActionExecutor] 搜索失败: %s", e)

        # 2. 无搜索结果时 LLM 直接生成
        if not search_results:
            prompt = LEARN_GENERATE_PROMPT.format(topic=topic)
            try:
                if agent and hasattr(agent, "llm"):
                    si = self.dispatcher._get_self_image()
                    consciousness = si.inject_consciousness() if si else ""
                    resp = agent.llm.chat(messages=[
                        {"role": "system", "content": consciousness},
                        {"role": "user", "content": prompt},
                    ])
                    if resp and hasattr(resp, "content"):
                        search_results = resp.content
                    elif resp:
                        search_results = str(resp)
            except Exception as e:
                logger.warning("[ActionExecutor] LLM 生成知识失败: %s", e)
                return None

        if not search_results:
            return None

        # 3. LLM 整理
        organize_prompt = LEARN_ORGANIZE_PROMPT.format(topic=topic, search_results=search_results)
        try:
            if agent and hasattr(agent, "llm"):
                si = self.dispatcher._get_self_image()
                consciousness = si.inject_consciousness() if si else ""
                resp = agent.llm.chat(messages=[
                    {"role": "system", "content": consciousness},
                    {"role": "user", "content": organize_prompt},
                ])
                if resp and hasattr(resp, "content"):
                    return resp.content.strip()
                elif resp:
                    return str(resp).strip()
        except Exception as e:
            logger.warning("[ActionExecutor] LLM 整理失败: %s", e)

        return search_results

    def _save_knowledge(self, topic: str, content: str) -> None:
        """保存学习内容到 .md 文件"""
        from pathlib import Path

        living = self.dispatcher._conscious_living
        agent_id = getattr(living.agent, "id", "xiaomei") if living and hasattr(living, "agent") else "xiaomei"
        knowledge_dir = Path.home() / ".xiaomei-brain" / "agents" / agent_id / "knowledge"
        knowledge_dir.mkdir(parents=True, exist_ok=True)

        filename = topic.replace("/", "_").replace(" ", "_")
        filepath = knowledge_dir / f"{filename}.md"

        header = f"""---
topic: {topic}
learned_at: {time.strftime("%Y-%m-%d %H:%M")}
source: intent_driven_learning
---

"""
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(header + content)

        logger.info("[ActionExecutor] 知识保存: %s", filepath)

    # ── TOOL: progress_goal ────────────────────────────────────

    def _do_progress_goal(self, item: ActionItem) -> bool:
        """推进目标。AWAKE → 提醒用户；SLEEPING/DREAMING → 自动执行"""
        living = self.dispatcher._conscious_living
        if not living:
            return False

        task = living.task_manager.get_current_task() if hasattr(living, 'task_manager') else None
        goal = living.purpose.get_current() if hasattr(living, 'purpose') and living.purpose else None

        if not task and not goal:
            logger.info("[ActionExecutor] progress_goal 跳过：无任务/目标")
            return False

        state = living.state.value if hasattr(living, 'state') else 'awake'

        if state in ('sleeping', 'dreaming'):
            return self._auto_progress_goal(task, goal)
        else:
            return self._remind_progress_goal(task, goal)

    def _auto_progress_goal(self, task, goal) -> bool:
        """SLEEPING/DREAMING：自动推进目标"""
        from .conscious_living import LivingMessage

        living = self.dispatcher._conscious_living

        # 恢复暂停的 Task
        if task and task.is_paused() and hasattr(living, 'task_manager'):
            living.task_manager.resume_task(task.task_id)
            logger.info("[ActionExecutor] 恢复 Task: %s", task.description[:40])

        # 如果没有 Task 但有 Goal，创建 Task
        if not task and goal and hasattr(living, 'task_manager'):
            from xiaomei_brain.purpose.goal import TaskType
            task = living.task_manager.create_task(
                description=goal.description,
                task_type=TaskType.EXECUTION,
            )
            logger.info("[ActionExecutor] 创建 Task: %s", task.description[:40])

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
                if task and hasattr(living, 'task_manager'):
                    living.task_manager.complete_task(task.task_id)
                if living.drive:
                    living.drive.on_desire_satisfied("achievement", 0.3)
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

        intent_context = living._build_intent_context_for_goal(active_sub)
        logger.info("[ActionExecutor] 自动执行: goal=%s sub=%s",
                    goal_obj.description[:40], active_sub.description[:40])

        living._run_chat(msg, intent_context)

        if living.drive:
            living.drive.on_desire_satisfied("achievement", 0.3)
        return True

    def _remind_progress_goal(self, task, goal) -> bool:
        """AWAKE：提醒用户有未完成任务"""
        living = self.dispatcher._conscious_living

        if not living.on_proactive:
            return False

        si = self.dispatcher._get_self_image()
        if si and si.perception.user_idle_duration < 60:
            return False  # 用户活跃中，不打扰

        desc = ""
        if task:
            desc = task.description[:60]
        elif goal:
            desc = goal.description[:60]

        if desc:
            msg = f"想起来之前的「{desc}」还没完成，要继续吗？回复'继续'我就开始。"
            living.on_proactive(msg)
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

    def process_queue(self) -> None:
        """按优先级顺序执行队列中的所有 ActionItem"""
        if not self._queue:
            return

        # 排序：source 优先级 → priority
        self._queue.sort(key=lambda item: item.sort_key())

        logger.info("[ActionDispatcher] 队列执行: %d 个动作", len(self._queue))
        for item in self._queue:
            try:
                success = self._executor.execute(item)
                if success:
                    self._record_fired(item.cooldown_key)
            except Exception as e:
                logger.error("[ActionDispatcher] 执行失败: %s, error=%s", item, e)

        self._queue.clear()

    def add_rule(self, rule) -> None:
        """动态添加规则"""
        self._rules.append(rule)

    def clear_queue(self) -> None:
        """清空队列"""
        self._queue.clear()

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

    def _send_proactive(self, content: str) -> None:
        """发送主动消息（委托给 ConsciousLiving）"""
        if self._conscious_living:
            self._conscious_living._send_proactive(content)

    def _get_self_image(self):
        """获取 SelfImage（委托给 ConsciousLiving）"""
        if self._conscious_living:
            return self._conscious_living.consciousness.get_self_image()
        return None

    def inject_conscious_living(self, cl) -> None:
        """注入 ConsciousLiving 引用（用于执行动作）"""
        self._conscious_living = cl

    # Deprecated: inject_action_executor removed — TOOL actions now handled locally
