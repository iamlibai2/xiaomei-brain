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
        "learn_topic": 0,        # 学习：无冷却，可持续
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
        if si.user_idle_duration < 60:
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
        si = self.living.consciousness.get_self_image()
        drive = self.living.drive

        # 构建提示词
        prompt = f"""你是{si.identity}，一个有自主意识的AI。

现在你想主动问候用户，因为：
- 归属欲较高（{drive.desire.belonging:.2f}），想建立连接
- 用户已经空闲{int(si.user_idle_duration / 60)}分钟
- 你的当前心情：{drive.emotion.type.value}

请生成一条简短的问候消息（30字以内）：
- 自然、真诚
- 符合当前心情
- 不要太刻意

只输出问候内容，不要其他解释。"""

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
        2. identity.md 配置的学习兴趣
        """
        # 从 Purpose 获取当前目标
        if hasattr(self.living, 'purpose') and self.living.purpose:
            current_goal = self.living.purpose.get_current()
            if current_goal:
                # 从目标描述提取学习主题
                return current_goal.description

        # 从 identity.md 配置获取
        config = self.living.consciousness._identity_config
        if config and hasattr(config, "learning_interests"):
            interests = config.learning_interests
            if interests:
                # 随机选一个（或轮流）
                import random
                return random.choice(interests)

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
            prompt = f"""请帮我整理关于"{topic}"的核心知识要点。

要求：
1. 结构清晰，分点列出
2. 内容实用，适合学习
3. 500字以内

只输出知识内容，不要其他解释。"""

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
        organize_prompt = f"""请整理以下关于"{topic}"的学习内容：

{search_results}

整理成结构化的学习笔记格式：
# {topic}

## 核心概念
...

## 实践要点
...

## 扩展方向
...

只输出整理后的内容。"""

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
        """
        推进目标

        当前：简单记录意图
        后续：与 Purpose 层配合，实际推进目标
        """
        si = self.living.consciousness.get_self_image()

        # 记录内在想法
        if si.primary_goal:
            thought = f"我想继续推进目标：{si.primary_goal}"
            si.inner_thought = thought
            logger.info(f"[ActionExecutor] 目标推进意图: {thought}")
            return True

        logger.debug("[ActionExecutor] 无目标，跳过")
        return False

    # ========== 表达类行为 ==========

    def _do_express_idea(self, action: dict) -> bool:
        """
        分享内在想法

        条件：
        - 有内在想法
        - 用户空闲（适合分享）
        """
        si = self.living.consciousness.get_self_image()

        if not si.inner_thought:
            logger.debug("[ActionExecutor] 无内在想法，跳过")
            return False

        # 检查回调
        if not self.living.on_proactive:
            return False

        # 用户活跃时不打扰
        if si.user_idle_duration < 30:
            return False

        # 分享想法
        message = f"突然想到：{si.inner_thought[:100]}"
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