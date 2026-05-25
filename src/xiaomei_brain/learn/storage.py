"""KnowledgeStorage: 知识持久化存储。

保存学习成果到 .md 文件 + 索引到 LongTermMemory + 建立知识图谱关联。
"""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path

logger = logging.getLogger(__name__)


class KnowledgeStorage:
    """知识存储：.md 文件 + LongTermMemory 索引 + 图谱关联。"""

    def __init__(self, agent_id: str, ltm, queue=None):
        """
        Args:
            agent_id: Agent ID，用于知识目录路径
            ltm: LongTermMemory 实例
            queue: LearningQueue 实例（用于 concept_expansion 入队）
        """
        self._agent_id = agent_id
        self._ltm = ltm
        self._queue = queue
        self._knowledge_dir = Path.home() / ".xiaomei-brain" / agent_id / "knowledge"
        self._knowledge_dir.mkdir(parents=True, exist_ok=True)

    # ── 保存 ──────────────────────────────────────────────

    def save(self, topic: str, content: str, source: str = "intent_driven_learning") -> str | None:
        """保存学习内容：写 .md 文件 + 索引 LongTermMemory + 建图关联。

        Returns:
            filepath 或 None
        """
        filepath = self._write_md(topic, content, source)
        memory_id = self._index_to_ltm(topic, content)

        if memory_id and self._ltm:
            self._build_relations(memory_id, content)

        return filepath

    # ── 内部 ──────────────────────────────────────────────

    def _write_md(self, topic: str, content: str, source: str) -> str | None:
        filename = topic.replace("/", "_").replace(" ", "_")
        filepath = self._knowledge_dir / f"{filename}.md"

        header = f"""---
topic: {topic}
learned_at: {time.strftime("%Y-%m-%d %H:%M")}
source: {source}
---

"""
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(header + content)
            logger.info("[KnowledgeStorage] 知识保存: %s", filepath)
            return str(filepath)
        except Exception as e:
            logger.warning("[KnowledgeStorage] 写文件失败: %s", e)
            return None

    def build_relations(self, memory_id: int, content: str) -> None:
        """解析知识内容的'## 关联'段落，建立图谱边 + concept_expansion 入队。"""
        self._build_relations(memory_id, content)

    def _index_to_ltm(self, topic: str, content: str) -> int | None:
        if not self._ltm:
            return None
        try:
            memory_id = self._ltm.store(
                content=content[:2000],
                source="learned",
                tags=[f"topic:{topic}", "knowledge"],
                importance=0.7,
                user_id="global",
                mem_type="knowledge",
            )
            logger.debug("[KnowledgeStorage] 知识已索引: #%d type=knowledge", memory_id)
            return memory_id
        except Exception as e:
            logger.warning("[KnowledgeStorage] 索引失败: %s", e)
            return None

    def _build_relations(self, memory_id: int, content: str) -> None:
        """解析'## 关联'段落，建图谱边 + concept_expansion 入队。"""
        lines_with_relations = []
        in_relations = False
        for line in content.split("\n"):
            if line.strip().startswith("### 关联") or line.strip().startswith("## 关联"):
                in_relations = True
                continue
            if in_relations and line.strip().startswith("→"):
                lines_with_relations.append(line.strip())
            elif in_relations and not line.strip().startswith("→") and line.strip():
                in_relations = False

        if not lines_with_relations:
            return

        relations_found: list[tuple[str, str]] = []  # [(target_type, name), ...]
        type_map = {"知识点": "knowledge", "相关技能": "skill", "相关经验": "experience"}
        for line in lines_with_relations:
            for label, ttype in type_map.items():
                if label in line:
                    names = re.findall(r'\[(.+?)\]', line)
                    for name in names:
                        name = name.strip()
                        if name:
                            relations_found.append((ttype, name))
                    break

        if not relations_found:
            return

        for target_type, name in relations_found:
            try:
                results = self._ltm.recall(name, top_k=1, user_id="global")
                if results:
                    target_id = results[0]["id"]
                    self._ltm.add_relation(
                        source_id=memory_id,
                        target_id=target_id,
                        relation_type="relates_to",
                        source_type="knowledge",
                        target_type=target_type,
                        context=name,
                    )
                    logger.debug("[KnowledgeStorage] 关联边: #%d → #%d (%s)", memory_id, target_id, name)
                elif self._queue:
                    # 关联的知识不存在 → 加入学习队列
                    self._queue.add(
                        topic=name,
                        reason="知识关联缺失",
                        priority=0.4,
                        source="concept_expansion",
                    )
            except Exception as e:
                logger.debug("[KnowledgeStorage] 关联边建立失败 (%s): %s", name, e)

        logger.info("[KnowledgeStorage] 已处理 %d 条知识关联", len(relations_found))
