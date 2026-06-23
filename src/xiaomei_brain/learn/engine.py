"""LearningEngine: 学习主循环。

协调 queue → topic selection → ReAct → storage 的完整学习流程。
"""

from __future__ import annotations

import logging
import random
import time

from ..prompts import LEARN_REACT_PROMPT
from .queue import LearningQueue
from .storage import KnowledgeStorage
from .meta_skill import MetaSkillPuller
from ..consciousness.context_pipeline import build_simple_context

logger = logging.getLogger(__name__)

LEARN_COOLDOWN = 60  # 同一主题的学习冷却（秒）


class LearningEngine:
    """学习引擎 — 学习主循环的编排者。

    使用方式：
        engine = LearningEngine(cl, queue, storage, meta_skill)
        success = engine.learn()  # 由 ActionExecutor._do_learn_topic 调用
    """

    def __init__(
        self,
        conscious_living,
        queue: LearningQueue,
        storage: KnowledgeStorage,
        meta_skill: MetaSkillPuller,
    ) -> None:
        self._cl = conscious_living
        self._queue = queue
        self._storage = storage
        self._meta_skill = meta_skill
        self._last_topic: str = ""
        self._last_preview: str = ""
        self._last_word_count: int = 0
        self._last_db_id: int = 0
        self._last_md_path: str = ""

    # ── 主入口 ────────────────────────────────────────────

    def learn(self) -> bool:
        """执行一次完整的学习循环：选题 → ReAct → 保存。

        Returns:
            True 表示学习成功
        """
        topic = self._select_topic()
        if not topic:
            logger.debug("[LearningEngine] 无学习主题")
            return False

        knowledge = self._react_learn(topic)
        if not knowledge:
            logger.warning("[LearningEngine] 学习失败: %s", topic)
            return False

        memory_id = self._storage.save(topic, knowledge)

        if self._cl.drive:
            self._cl.drive.on_desire_satisfied("cognition", 0.1)

        # 取第一段非标题文本作为摘要
        lines = [l for l in knowledge.split("\n") if l.strip() and not l.startswith("#")]
        preview = " ".join(lines[:2])[:120] if lines else knowledge[:120]

        # 记录以供 ActionDispatcher 展示
        filename = KnowledgeStorage._clean_filename(topic)
        self._last_topic = topic
        self._last_preview = preview
        self._last_word_count = len(knowledge)
        self._last_db_id = memory_id or 0
        self._last_md_path = str(self._storage._knowledge_dir / f"{filename}.md")

        # 经验流：学到了什么
        try:
            agent_core = self._cl.agent._get_agent()
            es = getattr(agent_core, "exp_stream", None)
            if es:
                es.log(
                    type="internal_action",
                    content=f"学习完成「{topic}」: {preview}",
                    importance=0.6,
                )
        except Exception as e:
            logger.debug("[ExpStream] learn write failed: %s", e)

        logger.info("[LearningEngine] 学习完成: %s (%d 字)", topic, len(knowledge))
        return True

    def pull_meta_skill(self, skill_domain: str) -> bool:
        """拉取元技能。"""
        return self._meta_skill.pull(skill_domain)

    # ── 主题选择 ──────────────────────────────────────────

    def _select_topic(self) -> str | None:
        """选择学习主题。优先级：队列 → LEARN intent TOPIC → Purpose → 兴趣 → 已有知识轮换 → 兜底"""
        # 1. 学习队列（优先）
        if self._queue:
            item = self._queue.pop()
            if item:
                return item["topic"]

        # 2. L2 LEARN intent 的 TOPIC 字段
        si = self._cl.consciousness.get_self_image() if self._cl.consciousness else None
        if si and hasattr(si.intent, "intent_buffer"):
            for intent_dict in si.intent.intent_buffer:
                if intent_dict.get("type", "").upper() == "LEARN":
                    topic = (intent_dict.get("params", {}) or {}).get("learn_topic", "")
                    if topic:
                        logger.info("[LearningEngine] 从 LEARN intent 提取主题: %s", topic)
                        return topic

        # 3. Purpose 当前目标
        if hasattr(self._cl, 'purpose') and self._cl.purpose:
            current_goal = self._cl.purpose.get_current()
            if current_goal:
                return current_goal.description

        # 4. SelfImage 学习兴趣（跳过冷却期内已学过的）
        if si and si.being.learning_interests:
            interests = si.being.learning_interests
            now = time.time()
            fresh = [i for i in interests
                     if (now - self._storage.get_last_learned_time(i)) >= LEARN_COOLDOWN]
            if fresh:
                # 模式加权：topic_cluster 模式给候选主题加分
                if len(fresh) > 1:
                    try:
                        from ..memory.pattern import PatternStorage, PatternInjector
                        ltm_ref = getattr(self._storage, '_ltm', None)
                        if ltm_ref:
                            storage = PatternStorage(ltm_ref)
                            injector = PatternInjector(storage, ltm_ref)
                            boosts = injector.boost_learning_topics(fresh)
                            if boosts:
                                fresh.sort(key=lambda t: boosts.get(t, 0), reverse=True)
                                logger.info("[LearningEngine] 模式加权前3: %s",
                                            str([f"{t}={boosts.get(t, 0):.2f}" for t in fresh[:3]]))
                    except Exception as e:
                        logger.warning("[LearningEngine] 模式加权失败: %s", e)
                return random.choice(fresh)
            logger.debug("[LearningEngine] 所有学习兴趣都在冷却中")

        # 5. 已有知识主题轮换（基于 LTM）
        now = time.time()
        all_topics = self._get_stored_topics()
        if all_topics:
            fresh = [t for t in all_topics
                     if (now - self._storage.get_last_learned_time(t)) >= LEARN_COOLDOWN]
            if fresh:
                return random.choice(fresh)
            logger.debug("[LearningEngine] 所有知识主题都在冷却中，跳过学习")
            return None

        # 6. 兜底
        return "AI技术发展"

    def _get_stored_topics(self) -> list[str]:
        """从 LTM 获取已存储的知识主题列表。"""
        try:
            results = self._storage._ltm.search_by_tags(
                ["knowledge"], user_id="global",
            )
            topics = set()
            for r in results:
                for tag in r.get("tags", []):
                    if tag.startswith("topic:"):
                        topics.add(tag[6:])
            return list(topics)
        except Exception:
            return []

    # ── ReAct 学习 ────────────────────────────────────────

    def _react_learn(self, topic: str) -> str | None:
        """ReAct 自主学习：websearch → 读网页 → 关联记忆 → 综合输出"""
        agent = self._cl.agent if hasattr(self._cl, "agent") else None
        if not agent:
            return None

        agent_core = agent._get_agent()
        es = getattr(agent_core, "exp_stream", None)
        consciousness = self._cl.consciousness
        if not consciousness:
            return None

        system_prompt = build_simple_context(consciousness, mode="task")
        agent_id = getattr(agent, "id", "")
        safe_topic = topic.replace("/", "_").replace(" ", "_")

        user_msg = LEARN_REACT_PROMPT.format(
            topic=topic,
            agent_id=agent_id,
            safe_topic=safe_topic,
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_msg},
        ]

        logger.info("[LearningEngine] ReAct 学习开始: %s", topic)

        try:
            result = agent_core.react_nodb(messages=messages, max_steps=15, label="work",
                                           exp_stream=es, summarize=True)
            return result.strip() if result else None
        except Exception as e:
            logger.warning("[LearningEngine] ReAct 学习失败: %s", e)
            return None
