"""KnowledgeStorage: 知识持久化存储。

主存储路径：LongTermMemory（数据库 + 向量索引）
附加产物：.md 文件（人类可读）
"""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# 安全文件名字符（保留中文、英文、数字、下划线、连字符）
_SAFE_FILENAME_RE = re.compile(r"[^\w\u4e00-\u9fff\-]")


class KnowledgeStorage:
    """知识存储：LongTermMemory 主存储 + .md 附加产物 + 图谱关联。"""

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

    def save(self, topic: str, content: str, source: str = "intent_driven_learning") -> int | None:
        """保存学习内容：LongTermMemory 主路径 → .md 附加产物 → 建图关联。

        LTM 是主存储路径，失败则整体失败。.md 是附加产物，失败不阻塞。

        Returns:
            memory_id 或 None
        """
        # 1. LTM 主路径（必须成功）
        memory_id = self._index_to_ltm(topic, content)
        if not memory_id:
            logger.warning("[KnowledgeStorage] LTM 索引失败，知识未保存: %s", topic)
            return None

        logger.info("[KnowledgeStorage] 知识已保存到 LTM: #%d topic=%s", memory_id, topic)

        # 2. .md 附加产物（失败不阻塞）
        self._write_md(topic, content, source)

        # 3. 图谱关联
        self._build_relations(memory_id, content)

        return memory_id

    # ── 查询 ──────────────────────────────────────────────

    def get_last_learned_time(self, topic: str) -> float:
        """查询某主题上次学习时间（基于 LTM）。

        Returns:
            Unix timestamp，未学过返回 0
        """
        if not self._ltm:
            return 0.0
        try:
            results = self._ltm.recall(
                f"topic:{topic}", top_k=1, user_id="global",
            )
            if results:
                return float(results[0].get("created_at", 0) or 0)
        except Exception:
            pass

        # 回退：按标签搜索
        try:
            results = self._ltm.search_by_tags(
                [f"topic:{topic}"], user_id="global",
            )
            if results:
                return float(results[0].get("created_at", 0) or 0)
        except Exception:
            pass

        return 0.0

    # ── 内部 ──────────────────────────────────────────────

    @staticmethod
    def _clean_filename(topic: str, max_len: int = 100) -> str:
        """清洗 topic 为安全文件名。

        移除 markdown 标记（**、#、[] 等），保留中文、英文、数字、
        下划线、连字符，其他字符替换为下划线。
        """
        # 去掉 markdown 标记
        cleaned = topic
        for char in ["**", "__", "*", "#", "[", "]", "`", "~~"]:
            cleaned = cleaned.replace(char, "")
        # 替换不安全字符为下划线
        cleaned = _SAFE_FILENAME_RE.sub("_", cleaned)
        # 合并连续下划线
        cleaned = re.sub(r"_+", "_", cleaned)
        # 去掉首尾下划线
        cleaned = cleaned.strip("_")
        # 限制长度
        if len(cleaned) > max_len:
            cleaned = cleaned[:max_len].rstrip("_")
        return cleaned or "unknown"

    def _write_md(self, topic: str, content: str, source: str) -> str | None:
        filename = self._clean_filename(topic)
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
            logger.info("[KnowledgeStorage] .md 附加产物: %s", filepath)
            return str(filepath)
        except Exception as e:
            logger.warning("[KnowledgeStorage] .md 写入失败（不影响主路径）: %s", e)
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
                    ok = self._queue.add(
                        topic=name,
                        reason="知识关联缺失",
                        priority=0.4,
                        source="concept_expansion",
                    )
                    if ok:
                        logger.info("[KnowledgeStorage] 概念扩展入队: %s", name)
            except Exception as e:
                logger.debug("[KnowledgeStorage] 关联边建立失败 (%s): %s", name, e)

        logger.info("[KnowledgeStorage] 已处理 %d 条知识关联", len(relations_found))
