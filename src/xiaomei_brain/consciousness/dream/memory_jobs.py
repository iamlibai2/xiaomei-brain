"""Memory jobs: 梦境记忆处理任务。

移自 memory/dream.py，DreamProcessor 类已废弃删除。
保留 ReinforceJob 和 ExtractJob。

Job types:
- ReinforceJob:  低 strength 记忆强化 + extinct 处理
- ExtractJob:     LLM 从今日对话提取新记忆
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...memory.longterm import LongTermMemory
    from ...memory.extractor import MemoryExtractor
    from ...memory.conversation_db import ConversationDB

logger = logging.getLogger(__name__)


# ── Constants ─────────────────────────────────────────────────

STRENGTH_DECAY_BASE = 0.9995
STRENGTH_L4 = 0.2
MEMORY_REINFORCE_BOOST = 0.1
MEMORY_EXTINCT_DAYS = 30
STATUS_ACTIVE = "active"
STATUS_EXTINCT = "extinct"


# ── DreamResult ─────────────────────────────────────────────

@dataclass
class DreamResult:
    """Job 执行结果"""
    job: str
    saved: int = 0
    reinforced: int = 0
    extinct: int = 0
    errors: int = 0
    details: str = ""


# ── ReinforceJob ────────────────────────────────────────────

class ReinforceJob:
    """记忆强化 job — 扫描低 strength 记忆，强化 + extinct 处理。"""

    def __init__(
        self,
        ltm: "LongTermMemory",
        user_id: str | None = None,
        boost: float = MEMORY_REINFORCE_BOOST,
        batch_size: int = 50,
    ) -> None:
        self.ltm = ltm
        self.user_id = user_id
        self.boost = boost
        self.batch_size = batch_size

    def run(self) -> DreamResult:
        """执行强化扫描。"""
        conn = self.ltm._get_conn()
        now = time.time()
        reinforce_cutoff = now - 24 * 3600

        if self.user_id:
            safe_uid = self.ltm._safe_user_id(self.user_id)
            where_user = f"AND user_id = '{safe_uid}'"
        else:
            where_user = ""

        rows = conn.execute(
            f"""SELECT * FROM memories
                WHERE status = ?
                  AND strength < 1.0
                  AND last_strengthen < ?
                  {where_user}
                ORDER BY strength ASC
                LIMIT ?""",
            (STATUS_ACTIVE, reinforce_cutoff, self.batch_size),
        ).fetchall()

        reinforced = 0
        extinct = 0
        errors = 0

        for row in rows:
            mid = row["id"]
            try:
                current_strength = row["strength"]
                last_accessed = row["last_accessed"]
                content = row["content"]
                row_user_id = row["user_id"]
                last_strengthen = row["last_strengthen"]

                elapsed_hours = (now - last_strengthen) / 3600.0
                effective = current_strength * (STRENGTH_DECAY_BASE ** elapsed_hours)

                if effective < STRENGTH_L4:
                    new_strength = current_strength + self.boost * (1.0 - current_strength)
                    new_strength = min(0.95, new_strength)

                    conn.execute(
                        "UPDATE memories SET strength = ?, last_strengthen = ? WHERE id = ?",
                        (new_strength, now, mid),
                    )
                    self.ltm._update_lance(mid, content, row_user_id)
                    reinforced += 1

                    if new_strength < STRENGTH_L4 and (now - last_accessed) > MEMORY_EXTINCT_DAYS * 86400:
                        conn.execute(
                            "UPDATE memories SET status = ? WHERE id = ?",
                            (STATUS_EXTINCT, mid),
                        )
                        self.ltm._delete_from_lance(mid)
                        extinct += 1
                        logger.info(
                            "[ReinforceJob] Memory #%d extinct (strength=%.3f, last_accessed=%dd ago)",
                            mid, new_strength, int((now - last_accessed) / 86400),
                        )
                else:
                    new_strength = current_strength + self.boost * (1.0 - current_strength)
                    new_strength = min(0.95, new_strength)
                    conn.execute(
                        "UPDATE memories SET strength = ?, last_strengthen = ? WHERE id = ?",
                        (new_strength, now, mid),
                    )
                    reinforced += 1

            except Exception as e:
                logger.warning("[ReinforceJob] Failed to reinforce #%d: %s", mid, e)
                errors += 1

        conn.commit()

        logger.info(
            "[ReinforceJob] reinforced=%d extinct=%d errors=%d",
            reinforced, extinct, errors,
        )
        return DreamResult(
            job="reinforce",
            reinforced=reinforced,
            extinct=extinct,
            errors=errors,
            details=f"reinforced={reinforced} extinct={extinct}",
        )


# ── ExtractJob ──────────────────────────────────────────────

from ...prompts import DREAM_USER_EXTRACT_PROMPT

# 每批处理的消息数
EXTRACT_BATCH_SIZE = 100
# 单次梦境最多处理的消息数（防止首次运行处理过多）
EXTRACT_MAX_MESSAGES = 1000


class ExtractJob:
    """对话提取 job — 分批从 conversation_db 读当天消息，LLM 深度提取记忆。

    V2 改进：
    - 分批处理（每 ~100 条消息一批），每批独立 LLM 调用
    - 前一批结果作为"已有记忆"传给下一批，自然去重
    - 扩大提取范围：事实/关系/经历/情感/承诺/洞察/自我收获
    """

    PROMPT = DREAM_USER_EXTRACT_PROMPT
    BATCH_SIZE = EXTRACT_BATCH_SIZE

    def __init__(
        self,
        extractor: "MemoryExtractor",
        user_id: str = "global",
    ) -> None:
        self.extractor = extractor
        self.user_id = user_id

    # ── Run ────────────────────────────────────────────────────

    def run(self) -> DreamResult:
        """按用户分组、分批从今日对话提取新记忆。

        先按 user_id 将消息分组，每组内再分批处理。
        这样每条记忆都能正确关联到对话所属的用户，而非全部归 global。
        """
        if not self.extractor.llm or not self.extractor.ltm or not self.extractor.db:
            return DreamResult(job="extract", errors=1, details="missing dependencies")

        # 查询今日所有消息
        today_start = datetime.now().replace(
            hour=0, minute=0, second=0, microsecond=0,
        ).timestamp()

        messages = self.extractor.db.query(since=today_start, limit=EXTRACT_MAX_MESSAGES)
        if len(messages) < 3:
            return DreamResult(job="extract", saved=0, details=f"<3 messages, skip")

        logger.info("[ExtractJob] Processing %d messages", len(messages))

        # 按 user_id 分组
        user_groups: dict[str, list[dict]] = {}
        for m in messages:
            uid = m.get("user_id") or "global"
            user_groups.setdefault(uid, []).append(m)

        logger.info("[ExtractJob] %d user groups: %s", len(user_groups),
                    {u: len(msgs) for u, msgs in user_groups.items()})

        cumulative: list[str] = []       # 累积的记忆内容（给下一批做上下文）
        batch_count = 0
        total_saved = 0

        for group_user_id, group_msgs in user_groups.items():
            if len(group_msgs) < 3:
                continue

            # 按用户分组内分批
            user_batches = [
                group_msgs[i:i + self.BATCH_SIZE]
                for i in range(0, len(group_msgs), self.BATCH_SIZE)
            ]

            for batch_idx, batch in enumerate(user_batches):
                formatted = self._format_messages(batch)

                # 构建"已有记忆"上下文（来自前面批次的结果）
                context = self._build_context(cumulative)

                prompt = self.PROMPT.format(
                    messages=formatted,
                    recent_memories=context,
                )

                try:
                    result = self.extractor.llm.chat(
                        messages=[{"role": "user", "content": prompt}],
                        tools=None,
                    )
                    text = result.content or ""
                except Exception as e:
                    logger.error(
                        "[ExtractJob] LLM call failed for user=%s batch %d/%d: %s",
                        group_user_id, batch_idx + 1, len(user_batches), e,
                    )
                    continue

                batch_count += 1
                text = text.strip()

                if text == "EMPTY":
                    logger.debug("[ExtractJob] user=%s batch %d/%d: EMPTY",
                                 group_user_id, batch_idx + 1, len(user_batches))
                    continue

                # 记忆直接归属到本组用户
                batch_saved = self._execute_adds(text, user_id=group_user_id)
                total_saved += batch_saved

                # 解析本批 ADD 行的内容，加入累积上下文
                batch_contents = self._extract_add_contents(text)
                cumulative.extend(batch_contents)

                logger.info(
                    "[ExtractJob] user=%s batch %d/%d: %d messages → %d memories stored (total=%d)",
                    group_user_id, batch_idx + 1, len(user_batches),
                    len(batch), batch_saved, total_saved,
                )

        if batch_count == 0:
            return DreamResult(
                job="extract", saved=0,
                details=f"<3 messages, skip",
            )

        return DreamResult(
            job="extract", saved=total_saved,
            details=f"{len(messages)} msgs in {batch_count} batches across {len(user_groups)} users, cumulative={len(cumulative)} items",
        )

    # ── Helpers ────────────────────────────────────────────────

    def _build_context(self, cumulative: list[str]) -> str:
        """构建"已有记忆"上下文文本。"""
        if not cumulative:
            return "（无已有记忆）"
        # 限制上下文长度，最新的放在前面（最近批次的更相关）
        items = cumulative[-50:]  # 最多 50 条
        return "\n".join(f"- {c}" for c in reversed(items))

    def _extract_add_contents(self, text: str) -> list[str]:
        """从 LLM 输出中提取 ADD 行的纯内容（去掉 scenes 标签）。"""
        contents = []
        for line in text.split("\n"):
            line = line.strip()
            if not line.upper().startswith("ADD:"):
                continue
            content = line[4:].strip()
            content = re.sub(r"^[-*]\s*", "", content).strip()
            if not content or len(content) < 5:
                continue
            # 去掉 [我] 前缀（只影响存储路由，不影响内容展示）
            if content.startswith("[我]"):
                content = content[3:].strip()
            # 去掉 | scenes: 部分，只保留内容
            if " | " in content:
                content = content.rsplit(" | ", 1)[0].strip()
            contents.append(content)
        return contents

    def _format_messages(self, messages: list[dict]) -> str:
        lines = []
        for m in messages:
            role = m.get("role", "user")
            if role == "assistant":
                label = "我"
            else:
                label = m.get("user_id") or m.get("user_display_name") or "对方"
            content = m.get("content", "")[:500]
            lines.append(f"[{label}] {content}")
        return "\n".join(lines)

    def _execute_adds(self, text: str, user_id: str | None = None) -> int:
        ltm = self.extractor.ltm
        if user_id is None:
            user_id = self.user_id
        saved = 0

        # Parse all ADD lines and their optional scene tags
        add_lines: list[tuple[str, list[str]]] = []  # (content, scene_tags)
        rel_lines: list[str] = []

        for line in text.split("\n"):
            line = line.strip()
            if not line:
                continue
            if line.upper().startswith("ADD:"):
                content = line[4:].strip()
                content = re.sub(r"^[-*]\s*", "", content).strip()
                if not content or len(content) < 5:
                    continue
                # Parse optional | scenes: tag
                scene_tags: list[str] = []
                if " | " in content:
                    parts = content.rsplit(" | ", 1)
                    content = parts[0].strip()
                    tag_part = parts[1].strip()
                    if tag_part.startswith("scenes:"):
                        tag_str = tag_part[7:].strip()
                        if tag_str and tag_str != "无":
                            scene_tags = [t.strip() for t in tag_str.split(",") if t.strip()]
                add_lines.append((content, scene_tags))
            elif line.upper().startswith("RELATES:"):
                rel_lines.append(line)

        # Store memories (first pass to get IDs)
        content_to_id: dict[str, int] = {}
        for content, scene_tags in add_lines:
            # [我] 前缀 → 涉及自己，存 global
            mem_user_id = user_id
            if content.startswith("[我]"):
                mem_user_id = "global"
                content = content[3:].strip()
                logger.debug("[ExtractJob] '[我]' prefix → user_id=global")

            try:
                # Dedup: recall first, UPDATE if similar memory already exists
                is_dup = False
                try:
                    existing = ltm.recall(content, user_id=mem_user_id, top_k=3)
                    if existing and existing[0].get("score", 0) > 0.85:
                        old = existing[0]
                        logger.info(
                            "[ExtractJob DEDUP] #%d score=%.2f -> UPDATE instead of ADD: %.50s",
                            old["id"], existing[0]["score"], content,
                        )
                        clean = self.extractor._simple_update(old["content"], content)
                        ltm.save_history(old["id"], old["content"], "UPDATE")
                        ltm.update_content(old["id"], clean)
                        content_to_id[content[:30]] = old["id"]
                        saved += 1
                        is_dup = True
                except Exception as e:
                    logger.debug("[ExtractJob DEDUP] recall failed, will ADD: %s", e)

                if not is_dup:
                    mid = ltm.store(
                        content=content,
                        source="dream",
                        importance=0.8,
                        user_id=mem_user_id,
                        scene_tags=scene_tags if scene_tags else None,
                        mem_type="common",
                    )
                    if mid:
                        saved += 1
                        content_to_id[content[:30]] = mid
                        logger.debug("[ExtractJob] stored #%d: %.50s scenes=%s", mid, content, scene_tags)
            except Exception as e:
                logger.warning("[ExtractJob] store failed: %s", e)

        # Process RELATES lines (second pass)
        for rel_line in rel_lines:
            self._execute_relates(rel_line, content_to_id, user_id)

        return saved

    def _execute_relates(self, rel_line: str, content_to_id: dict[str, int], user_id: str) -> None:
        """Parse and execute a RELATES line to create memory relations."""
        ltm = self.extractor.ltm

        # Format: RELATES: 记忆1|--<type>-->|记忆2
        m = re.match(r'^RELATES:\s*(.+?)\s*\|--([a-zA-Z_]+)-->+\s*\|(.+)$', rel_line, re.IGNORECASE)
        if not m:
            m = re.match(r'^RELATES:\s*(.+?)\s*\|<--([a-zA-Z_]+)-->\s*\|(.+)$', rel_line, re.IGNORECASE)
        if not m:
            return

        from_content = m.group(1).strip()
        relation_type = m.group(2).strip().lower()
        to_content = m.group(3).strip()

        if relation_type not in ltm.VALID_RELATION_TYPES:
            return

        from_id = None
        for snippet, mid in content_to_id.items():
            if from_content[:30] in snippet:
                from_id = mid
                break
        if from_id is None:
            similar = ltm.recall(from_content, user_id=user_id, top_k=1)
            if similar:
                from_id = similar[0]["id"]

        to_id = None
        similar_to = ltm.recall(to_content, user_id=user_id, top_k=1)
        if similar_to:
            to_id = similar_to[0]["id"]

        if from_id and to_id:
            ltm.add_relation(
                source_id=from_id,
                target_id=to_id,
                relation_type=relation_type,
                source_type="experience",
                target_type="experience",
            )


# ── RelationReinforceJob ────────────────────────────────────────────────────

@dataclass
class RelationReinforceResult:
    """关系强化结果"""
    reinforced: int = 0
    created: int = 0
    decayed: int = 0
    dormant: int = 0
    scene_clustered: int = 0
    errors: int = 0
    details: str = ""


class RelationReinforceJob:
    """关系强化 job — 共现→关系加固 + 权重衰减 + 场景聚类。

    在 DREAMING 阶段执行，维护记忆关系的健康度。
    """

    def __init__(
        self,
        ltm: "LongTermMemory",
        user_id: str | None = None,
    ) -> None:
        self.ltm = ltm
        self.user_id = user_id

    def run(self) -> RelationReinforceResult:
        """执行关系强化。"""
        result = RelationReinforceResult()

        try:
            co_result = self._reinforce_from_co_occurrence()
            result.reinforced = co_result.get("reinforced", 0)
            result.created = co_result.get("created", 0)

            decay_result = self.ltm.decay_relation_weights(decay_days=7, decay_factor=0.95)
            result.decayed = decay_result.get("decayed", 0)
            result.dormant = decay_result.get("dormant", 0)

            result.details = (
                f"加固{result.reinforced}条(新建{result.created}条), "
                f"衰减{result.decayed}条(休眠{result.dormant}条)"
            )
        except Exception as e:
            logger.error("[RelationReinforceJob] 失败: %s", e)
            result.errors = 1
            result.details = str(e)

        return result

    def _reinforce_from_co_occurrence(self) -> dict:
        """从共现记录强化关系权重。"""
        conn = self.ltm._get_conn()
        now = time.time()
        cutoff = now - 7 * 86400

        if self.user_id:
            rows = conn.execute("""
                SELECT co.memory_a_id, co.memory_b_id, co.co_count,
                       rel.id as rel_id, rel.weight as rel_weight, rel.relation_type
                FROM memory_co_occurrence co
                JOIN memories m ON m.id = co.memory_a_id
                LEFT JOIN memory_relations rel
                    ON rel.from_memory_id = co.memory_a_id
                   AND rel.to_memory_id = co.memory_b_id
                WHERE co.last_seen > ?
                  AND (m.user_id = ? OR m.user_id = 'global')
                ORDER BY co.co_count DESC
                LIMIT 50
            """, (cutoff, self.user_id)).fetchall()
        else:
            rows = conn.execute("""
                SELECT co.memory_a_id, co.memory_b_id, co.co_count,
                       rel.id as rel_id, rel.weight as rel_weight, rel.relation_type
                FROM memory_co_occurrence co
                LEFT JOIN memory_relations rel
                    ON rel.from_memory_id = co.memory_a_id
                   AND rel.to_memory_id = co.memory_b_id
                WHERE co.last_seen > ?
                ORDER BY co.co_count DESC
                LIMIT 50
            """, (cutoff,)).fetchall()

        reinforced = 0
        created = 0

        for row in rows:
            m_a, m_b = row["memory_a_id"], row["memory_b_id"]
            co_count = row["co_count"]
            rel_id = row["rel_id"]
            rel_weight = row["rel_weight"] if row["rel_weight"] is not None else 0.5

            if rel_id:
                new_weight = min(0.95, rel_weight + 0.1 * (1 - rel_weight))
                conn.execute(
                    "UPDATE memory_relations SET weight = ?, last_reinforced = ? WHERE id = ?",
                    (new_weight, now, rel_id),
                )
                reinforced += 1
            elif co_count >= 3:
                conn.execute(
                    """INSERT OR IGNORE INTO memory_relations
                       (from_memory_id, to_memory_id, relation_type, context, created_at, weight, last_reinforced)
                       VALUES (?, ?, 'co_occurrence', 'from:co_occurrence', ?, 0.2, ?)""",
                    (m_a, m_b, now, now),
                )
                created += 1

        conn.commit()
        return {"reinforced": reinforced, "created": created}
