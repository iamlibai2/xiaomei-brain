"""MetaSkillPuller: Hub 技能拉取。

搜索 → 拉取 SKILL.md → 存入 LongTermMemory(type=skill)。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ..prompts import META_SKILL_PROMPT
from ..consciousness.context_pipeline import build_simple_context

if TYPE_CHECKING:
    from .storage import KnowledgeStorage

logger = logging.getLogger(__name__)


class MetaSkillPuller:
    """从 Hub 拉取技能。

    依赖外部注入 agent / consciousness / storage / send_proactive。
    """

    def __init__(self, storage: "KnowledgeStorage") -> None:
        self._storage = storage
        self._agent = None          # 由引擎注入
        self._consciousness = None  # 由引擎注入
        self._send_proactive = None # 由引擎注入: (msg) -> None

    def pull(self, skill_domain: str) -> bool:
        """搜索 Hub → 拉取 SKILL.md → 存入 LTM。

        Returns:
            True 表示成功拉取或已有高可信度技能
        """
        if not self._agent or not self._consciousness:
            logger.warning("[MetaSkillPuller] 未注入 agent/consciousness")
            return False

        ltm = getattr(self._agent, "longterm_memory", None)

        # 检查是否已有高可信度技能
        if ltm:
            existing = ltm.recall(f"技能 {skill_domain}", top_k=3, user_id="global")
            high_conf = [m for m in existing if m.get("type") == "skill" and m.get("confidence", 0) > 0.5]
            if high_conf:
                logger.info("[MetaSkillPuller] 已有高可信度技能，跳过")
                if self._send_proactive:
                    self._send_proactive(f"我已经会 {skill_domain} 相关的技能了。")
                return True

        agent_core = self._agent._get_agent()
        es = getattr(agent_core, "exp_stream", None)
        system_prompt = build_simple_context(self._consciousness, mode="daily")
        prompt = META_SKILL_PROMPT.format(skill_domain=skill_domain)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ]

        logger.info("[MetaSkillPuller] 拉取技能: %s", skill_domain)

        try:
            result = agent_core.react_nodb(messages=messages, max_steps=15, label="work",
                                           exp_stream=es, summarize=True)
        except Exception as e:
            logger.warning("[MetaSkillPuller] ReAct 失败: %s", e)
            return False

        if not result:
            return False

        # 提取技能名称
        skill_name = skill_domain
        for line in result.split("\n"):
            if line.startswith("## ") and "type:" not in line:
                skill_name = line[3:].strip()
                break

        # 存入 LongTermMemory
        if ltm:
            try:
                memory_id = ltm.store(
                    content=result[:2000],
                    source="hub",
                    tags=[f"domain:{skill_domain}", "skill"],
                    importance=0.6,
                    user_id="global",
                    mem_type="skill",
                    confidence=0.5,
                    skill_domain=skill_domain,
                )
                logger.info("[MetaSkillPuller] 已存入 #%d (%s)", memory_id, skill_name)

                # 解析关联建边
                self._storage.build_relations(memory_id, result)

                if self._send_proactive:
                    self._send_proactive(f"我学会了 {skill_name} 技能（来自 Hub）")
                return True
            except Exception as e:
                logger.warning("[MetaSkillPuller] 存储失败: %s", e)

        return False
