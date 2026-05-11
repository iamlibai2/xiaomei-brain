"""
欲望驱动行为执行器

Layer 3 实现：
- 检查欲望阈值 → 执行主动行为
- 行为类型：greet_user, learn_topic, progress_goal, express_idea
- 冷却策略：社交类有冷却，学习类可持续
"""

import logging
import os
import time
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)


class DesireActionExecutor:
    """
    欲望驱动行为执行器

    将 Drive 的欲望状态转化为实际行为：
    - 归属欲 → 主动问候
    - 认知欲 → 主动学习
    - 成就欲 → 推进目标
    - 表达欲 → 分享想法
    """

    # 冷却时间配置（秒）
    COOLING_TIMES = {
        "greet_user": 3600,      # 问候：1小时冷却
        "express_idea": 1800,    # 表达：30分钟冷却
        "learn_topic": 7200,     # 学习：2小时冷却，避免重复触发
        "progress_goal": 0,      # 目标：无冷却，可持续
    }

    def __init__(self, living: Any, agent_id: str = "xiaomei"):
        """
        初始化执行器

        living: ConsciousLiving 实例
        """
        self.living = living

        # 冷却记录
        self._last_action_time: dict[str, float] = {}

        # 知识存储目录
        self.knowledge_dir = Path.home() / ".xiaomei-brain" / "agents" / agent_id / "knowledge"
        self.knowledge_dir.mkdir(parents=True, exist_ok=True)

    def can_execute(self, action_type: str) -> bool:
        """检查行为是否在冷却期内"""
        cooling_time = self.COOLING_TIMES.get(action_type, 0)
        if cooling_time == 0:
            return True  # 无冷却

        last_time = self._last_action_time.get(action_type, 0)
        elapsed = time.time() - last_time

        return elapsed >= cooling_time

    def execute(self, action: dict) -> bool:
        """
        执行一个欲望驱动行为

        action: {
            "type": "greet_user",
            "priority": 0.75,
            "desire_type": "belonging",
            "reason": "..."
        }

        返回：是否成功执行
        """
        action_type = action.get("type")

        # 检查冷却
        if not self.can_execute(action_type):
            logger.debug(f"[ActionExecutor] {action_type} 在冷却期内，跳过")
            return False

        # 执行对应行为
        success = False
        if action_type == "greet_user":
            success = self._do_greet_user(action)
        elif action_type == "learn_topic":
            success = self._do_learn_topic(action)
        elif action_type == "progress_goal":
            success = self._do_progress_goal(action)
        elif action_type == "express_idea":
            success = self._do_express_idea(action)

        if success:
            self._last_action_time[action_type] = time.time()
            logger.info(f"[ActionExecutor] 执行成功: {action_type}")

        return success

    # ========== 社交类行为 ==========

    def _do_greet_user(self, action: dict) -> bool:
        """
        主动问候用户

        条件：
        - 用户空闲超过1分钟（避免打扰活跃对话）
        - 有 on_proactive 回调

        消息：LLM 生成个性化问候
        """
        si = self.living.consciousness.get_self_image()

        # 用户刚活跃，不打扰
        if si.perception.user_idle_duration < 60:
            logger.debug("[ActionExecutor] 用户刚活跃，跳过问候")
            return False

        # 检查回调
        if not self.living.on_proactive:
            logger.debug("[ActionExecutor] 无 on_proactive 回调")
            return False

        # LLM 生成问候消息
        message = self._generate_greet_message()

        # 发送问候
        self.living.on_proactive(message)

        # 满足归属欲
        self.living.drive.on_desire_satisfied("belonging", 0.2)

        logger.info(f"[ActionExecutor] 问候用户: {message[:50]}")
        return True

    def _generate_greet_message(self) -> str:
        """LLM 生成个性化问候消息"""
        from xiaomei_brain.prompts import GREET_GENERATE_PROMPT

        si = self.living.consciousness.get_self_image()
        drive = self.living.drive

        # 构建提示词
        prompt = GREET_GENERATE_PROMPT.format(
            identity=si.identity.identity,
            belonging=drive.desire.belonging,
            idle_minutes=int(si.perception.user_idle_duration / 60),
            mood=drive.emotion.type.value,
        )

        # 调用 LLM
        try:
            if self.living.agent and hasattr(self.living.agent, "llm"):
                llm = self.living.agent.llm
                # LLMClient 使用 chat 方法
                messages = [{"role": "user", "content": prompt}]
                response = llm.chat(messages)
                if response and hasattr(response, "content"):
                    return response.content.strip()
                elif response:
                    return str(response).strip()
        except Exception as e:
            logger.warning(f"[ActionExecutor] LLM 生成失败: {e}")

        # 后备：规则生成
        templates = [
            "好久没和你聊天了，想你了~",
            "你在忙什么呢？有空聊聊吗？",
            "突然想问问你最近怎么样~",
        ]
        return templates[0]

    # ========== 学习类行为 ==========

    def _do_learn_topic(self, action: dict) -> bool:
        """
        主动学习

        流程：
        1. 获取学习主题（从 identity.md 配置或 Purpose 目标）
        2. 搜索相关知识
        3. LLM 整理内容
        4. 保存到 knowledge/{topic}.md
        5. 满足认知欲
        """
        # 获取学习主题
        topic = self._get_learning_topic()

        if not topic:
            logger.debug("[ActionExecutor] 无学习主题")
            return False

        # 开始探索 → 好奇心上升
        self.living.drive.on_curiosity(0.1)

        # 搜索知识
        knowledge = self._search_and_learn(topic)

        if not knowledge:
            logger.warning(f"[ActionExecutor] 学习失败: {topic}")
            return False

        # 保存知识
        self._save_knowledge(topic, knowledge)

        # 满足认知欲
        self.living.drive.on_desire_satisfied("cognition", 0.3)

        logger.info(f"[ActionExecutor] 学习完成: {topic}")
        return True

    def _get_learning_topic(self) -> str | None:
        """
        获取学习主题

        来源优先级：
        1. Purpose 层的当前目标
        2. identity.md 配置的学习兴趣（排除最近冷却期内已学的）
        3. knowledge/ 目录下已有的 .md 文件（按 mtime 从旧到新）
        """
        cooling_time = self.COOLING_TIMES.get("learn_topic", 0)
        now = time.time()

        # 从 knowledge/ 目录收集所有可用主题（排除冷却期内修改过的）
        available_from_files = []
        if self.knowledge_dir.exists():
            for f in self.knowledge_dir.glob("*.md"):
                mtime = f.stat().st_mtime
                if cooling_time > 0 and (now - mtime) < cooling_time:
                    continue  # 在冷却期内，跳过
                available_from_files.append(f.stem)

        # 从 Purpose 获取当前目标
        if hasattr(self.living, 'purpose') and self.living.purpose:
            current_goal = self.living.purpose.get_current()
            if current_goal:
                return current_goal.description

        # 从 identity.md 配置获取学习兴趣
        config = self.living.consciousness._identity_config
        if config and hasattr(config, "learning_interests"):
            interests = config.learning_interests
            if interests:
                # 过滤掉冷却期内已学过的
                candidates = [i for i in interests if i not in available_from_files]
                if candidates:
                    import random
                    return random.choice(candidates)

        # 从已有知识文件选择最久未更新的
        if available_from_files:
            import random
            return random.choice(available_from_files)

        # 默认主题
        return "AI技术发展"

    def _search_and_learn(self, topic: str) -> str | None:
        """
        搜索并学习主题

        流程：
        1. 调用 websearch 搜索
        2. LLM 整理成结构化内容
        """
        # 检查 agent 是否有 websearch 工具
        if not self.living.agent:
            logger.debug("[ActionExecutor] 无 agent，无法搜索")
            return None

        # 搜索知识
        search_results = None
        try:
            # 尝试调用 websearch 工具
            if hasattr(self.living.agent, "tool_registry"):
                registry = self.living.agent.tool_registry
                if "websearch" in registry._tools:
                    search_results = registry.call("websearch", topic)
        except Exception as e:
            logger.warning(f"[ActionExecutor] 搜索失败: {e}")

        # 如果没有搜索结果，使用 LLM 直接生成知识
        if not search_results:
            from xiaomei_brain.prompts import LEARN_GENERATE_PROMPT
            prompt = LEARN_GENERATE_PROMPT.format(topic=topic)

            try:
                if hasattr(self.living.agent, "llm"):
                    llm = self.living.agent.llm
                    messages = [{"role": "user", "content": prompt}]
                    response = llm.chat(messages)
                    if response and hasattr(response, "content"):
                        search_results = response.content
                    elif response:
                        search_results = str(response)
            except Exception as e:
                logger.warning(f"[ActionExecutor] LLM 生成知识失败: {e}")
                return None

        # LLM 整理内容
        from xiaomei_brain.prompts import LEARN_ORGANIZE_PROMPT
        organize_prompt = LEARN_ORGANIZE_PROMPT.format(
            topic=topic,
            search_results=search_results,
        )

        try:
            if hasattr(self.living.agent, "llm"):
                llm = self.living.agent.llm
                messages = [{"role": "user", "content": organize_prompt}]
                response = llm.chat(messages)
                if response and hasattr(response, "content"):
                    return response.content.strip()
                elif response:
                    return str(response).strip()
        except Exception as e:
            logger.warning(f"[ActionExecutor] 整理失败: {e}")

        # 返回原始内容
        return search_results

    def _save_knowledge(self, topic: str, content: str) -> None:
        """保存学习内容到 .md 文件"""
        # 清理文件名
        filename = topic.replace("/", "_").replace(" ", "_")
        filepath = self.knowledge_dir / f"{filename}.md"

        # 写入文件
        header = f"""---
topic: {topic}
learned_at: {time.strftime("%Y-%m-%d %H:%M")}
source: desire_driven_learning
---

"""
        full_content = header + content

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(full_content)

        logger.info(f"[ActionExecutor] 知识保存: {filepath}")

    # ========== 目标类行为 ==========

    def _do_progress_goal(self, action: dict) -> bool:
        """推进目标（欲望驱动，成就欲 > 0.6）。

        AWAKE  → 发送主动提醒，不打扰用户
        SLEEPING / DREAMING → 自动推进任务
        """
        living = self.living

        # 获取当前 Task（优先）或 Purpose 目标
        task = living.task_manager.get_current_task()
        goal = living.purpose.get_current() if living.purpose else None

        if not task and not goal:
            logger.debug("[ActionExecutor] 无任务/目标，跳过")
            return False

        # 判断当前状态
        state = living.state.value if hasattr(living, 'state') else 'awake'

        if state in ('sleeping', 'dreaming'):
            return self._auto_progress_goal(task, goal)
        else:
            return self._remind_progress_goal(task, goal)

    def _auto_progress_goal(self, task, goal) -> bool:
        """SLEEPING/DREAMING：自动推进目标"""
        living = self.living

        # 恢复暂停的 Task
        if task and task.is_paused():
            living.task_manager.resume_task(task.task_id)
            logger.info("[ActionExecutor] 恢复 Task: %s", task.description[:40])

        # 如果没有 Task 但有 Goal，创建 Task
        if not task and goal:
            from xiaomei_brain.purpose.goal import TaskType
            task = living.task_manager.create_task(
                description=goal.description,
                task_type=TaskType.EXECUTION,
            )
            logger.info("[ActionExecutor] 创建 Task: %s", task.description[:40])

        # 确保目标有活跃的子目标
        goal_obj = living.purpose.get_current() if living.purpose else None
        if not goal_obj:
            logger.debug("[ActionExecutor] 无活跃目标，跳过")
            return False

        # 找到第一个未完成的子目标，没有子目标则直接用目标本身
        sub_goals = living.purpose.get_sub_goals(goal_obj.id) if living.purpose else []
        active_sub = None
        for sg in sub_goals:
            if not sg.is_completed():
                active_sub = sg
                break

        if not active_sub:
            # 所有子目标都完成了，检查父目标
            if goal_obj.is_completed():
                logger.info("[ActionExecutor] 目标已完成: %s", goal_obj.description[:40])
                if task:
                    living.task_manager.complete_task(task.task_id)
                living.drive.on_desire_satisfied("achievement", 0.3)
                return True
            # 没有子目标且目标未完成，直接用目标本身
            active_sub = goal_obj

        # 激活子目标
        if active_sub.id != goal_obj.id:
            living.purpose.set_current(active_sub.id)

        # 构建上下文并执行
        from ..consciousness.conscious_living import LivingMessage
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

        # 执行后满足成就欲
        living.drive.on_desire_satisfied("achievement", 0.3)
        return True

    def _remind_progress_goal(self, task, goal) -> bool:
        """AWAKE：提醒用户有未完成任务"""
        living = self.living

        if not living.on_proactive:
            return False

        si = living.consciousness.get_self_image()
        if si.perception.user_idle_duration < 60:
            return False  # 用户活跃中，不打扰

        # 生成提醒消息
        desc = ""
        if task:
            desc = task.description[:60]
        elif goal:
            desc = goal.description[:60]

        if desc:
            msg = f"想起来之前的「{desc}」还没完成，要继续吗？回复'继续'我就开始。"
            living.on_proactive(msg)
            logger.info("[ActionExecutor] 目标提醒: %s", desc)

        # 提醒本身满足了一部分成就欲
        living.drive.on_desire_satisfied("achievement", 0.1)
        si.mind.inner_thought = f"我想继续推进目标：{desc}"
        return True

    # ========== 表达类行为 ==========

    def _do_express_idea(self, action: dict) -> bool:
        """
        分享内在想法

        条件：
        - 有内在想法
        - 用户空闲（适合分享）
        """
        si = self.living.consciousness.get_self_image()

        if not si.mind.inner_thought:
            logger.debug("[ActionExecutor] 无内在想法，跳过")
            return False

        # 检查回调
        if not self.living.on_proactive:
            return False

        # 用户活跃时不打扰
        if si.perception.user_idle_duration < 30:
            return False

        # 分享想法
        message = f"突然想到：{si.mind.inner_thought[:100]}"
        self.living.on_proactive(message)

        # 满足表达欲
        self.living.drive.on_desire_satisfied("expression", 0.2)

        logger.info(f"[ActionExecutor] 表达想法: {message[:50]}")
        return True

    # ========== 批量执行 ==========

    def execute_best_action(self, actions: list[dict]) -> bool:
        """
        从候选行为中执行最佳的一个

        actions: check_desire_actions() 返回的候选列表
        """
        if not actions:
            return False

        # 按优先级排序（已排序）
        for action in actions:
            if self.execute(action):
                return True  # 执行一个就返回

        return False