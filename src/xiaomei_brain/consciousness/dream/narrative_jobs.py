"""NarrativeConsolidationJob: 梦境层叙事记忆整合。

职责：
- 归档低 weight 叙事记忆
- 合并同 scene_tag 的多条 active 叙事
- 将高 weight 叙事中的 changed_me 提炼到 SelfModel growth_log
"""

import logging
import time
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("xiaomei_brain.narrative")
_P_LOG = "\033[91m[NARR-Dream]\033[0m"


@dataclass
class NarrativeConsolidationResult:
    archived: int = 0
    """归档了多少条"""
    consolidated: int = 0
    """合并了多少组"""
    growth_entries: int = 0
    """写入了多少条 growth_log"""
    errors: int = 0


class NarrativeConsolidationJob:
    def __init__(self, ltm: Any) -> None:
        self.ltm = ltm

    def run(self) -> NarrativeConsolidationResult:
        result = NarrativeConsolidationResult()
        if not self.ltm:
            return result

        try:
            self._archive_low_weight(result)
        except Exception as e:
            logger.warning("%s archive failed: %s", _P_LOG, e)
            result.errors += 1

        try:
            self._consolidate_by_scene_tag(result)
        except Exception as e:
            logger.warning("%s consolidate failed: %s", _P_LOG, e)
            result.errors += 1

        logger.info("%s Done: archived=%d consolidated=%d growth=%d",
                    _P_LOG, result.archived, result.consolidated, result.growth_entries)
        return result

    def _archive_low_weight(self, result: NarrativeConsolidationResult) -> None:
        """归档 weight < 0.4 或长期未引用的叙事记忆"""
        conn = self.ltm._get_conn()
        now = time.time()
        # 超过 30 天 weight < 0.4，或超过 60 天未引用
        cursor = conn.execute(
            """SELECT id, weight, created_at FROM narrative_memories
               WHERE status = 'active'
               AND (weight < 0.4 OR (created_at < ? AND weight < 0.6))""",
            (now - 30 * 86400,),
        )
        rows = cursor.fetchall()
        for r in rows:
            self.ltm.archive_narrative_memory(r[0])
            result.archived += 1
            logger.info("%s Archived low-weight: %s (weight=%.2f)", _P_LOG, r[0], r[1])

    def _consolidate_by_scene_tag(self, result: NarrativeConsolidationResult) -> None:
        """合并同 scene_tag 的多条 active 叙事"""
        conn = self.ltm._get_conn()
        # 找出现有 active scene_tags
        rows = conn.execute(
            """SELECT scene_tags FROM narrative_memories
               WHERE status = 'active'""",
        ).fetchall()

        import json
        all_tags: set[str] = set()
        for (tags_json,) in rows:
            try:
                tags = json.loads(tags_json or "[]")
                all_tags.update(tags)
            except Exception:
                pass

        for scene_tag in all_tags:
            # 查找该 scene_tag 下的所有 active 记录
            tag_rows = conn.execute(
                """SELECT id, content, changed_me, weight, category
                   FROM narrative_memories
                   WHERE status = 'active' AND scene_tags LIKE ?""",
                (f'%"{scene_tag}"%',),
            ).fetchall()

            if len(tag_rows) < 2:
                continue  # 不足2条不合并

            # 生成合并内容：取 weight 最高的 3 条的 content 摘要
            sorted_rows = sorted(tag_rows, key=lambda r: r[3], reverse=True)[:3]
            merged_content_parts = [f"- {row[1][:80]}" for row in sorted_rows]
            merged_content = "合并摘要：\n" + "\n".join(merged_content_parts)

            # changed_me 取最新一条
            latest_changed = sorted_rows[0][2] or ""
            avg_weight = sum(r[3] for r in tag_rows) / len(tag_rows)

            # 写入合并记录
            self.ltm.consolidate_narrative_memories(
                scene_tag=scene_tag,
                merged_content=merged_content,
                merged_changed_me=latest_changed,
            )
            result.consolidated += 1
            logger.info("%s Consolidated %d NARRs with tag '%s'",
                        _P_LOG, len(tag_rows), scene_tag)
