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
                  AND strength < 0.7
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

class ExtractJob:
    """对话提取 job — 从 conversation_db 读当天消息，LLM 深度提取记忆。"""

    DREAM_EXTRACT_PROMPT = """你是一个记忆提取器。从以下对话记录中，提取关于**用户**的值得长期记住的信息。

提取规则：
- 只提取关于用户的信息：用户的事实、偏好、重要决定、个人经历
- 不要提取关于AI助手自身的信息
- 用第三人称"用户"来描述，明确信息主体是用户
- 忽略寒暄、情绪表达、无实质内容的对话
- 每条记忆用以下格式输出：
  ADD: 记忆内容（以"用户"开头）
- 如果没有值得记住的信息，只回复 EMPTY
- 多条记忆之间用 --- 分隔

已有记忆：
{recent_memories}

对话记录：
{messages}"""

    def __init__(
        self,
        extractor: "MemoryExtractor",
        user_id: str = "global",
    ) -> None:
        self.extractor = extractor
        self.user_id = user_id

    def run(self) -> DreamResult:
        """从今日对话提取新记忆。"""
        if not self.extractor.llm or not self.extractor.ltm or not self.extractor.db:
            return DreamResult(job="extract", errors=1, details="missing dependencies")

        today_start = datetime.now().replace(
            hour=0, minute=0, second=0, microsecond=0,
        ).timestamp()

        messages = self.extractor.db.query(since=today_start, limit=500)
        if len(messages) < 3:
            return DreamResult(job="extract", saved=0, details="<3 messages, skip")

        formatted = self._format_messages(messages)

        recent_memories = ""
        existing = self.extractor.ltm.get_recent(10, user_id=self.user_id)
        if existing:
            recent_memories = "\n".join(f"- {m['content']}" for m in existing)

        prompt = self.DREAM_EXTRACT_PROMPT.format(
            messages=formatted,
            recent_memories=recent_memories or "（无已有记忆）",
        )

        try:
            result = self.extractor.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                tools=None,
            )
            text = result.content or ""
        except Exception as e:
            logger.error("[ExtractJob] LLM call failed: %s", e)
            return DreamResult(job="extract", errors=1, details=str(e))

        if text.strip() == "EMPTY":
            return DreamResult(job="extract", saved=0, details="EMPTY response")

        saved = self._execute_adds(text)
        return DreamResult(job="extract", saved=saved)

    def _format_messages(self, messages: list[dict]) -> str:
        lines = []
        for m in messages:
            role = m.get("role", "user")
            content = m.get("content", "")[:500]
            lines.append(f"[{role}] {content}")
        return "\n".join(lines)

    def _execute_adds(self, text: str) -> int:
        ltm = self.extractor.ltm
        user_id = self.user_id
        saved = 0

        for line in text.split("\n"):
            line = line.strip()
            if not line.upper().startswith("ADD:"):
                continue
            content = line[4:].strip()
            if not content:
                continue
            content = re.sub(r"^[-*]\s*", "", content).strip()
            if not content or len(content) < 5:
                continue
            try:
                mid = ltm.store(
                    content=content,
                    source="dream",
                    importance=0.8,
                    user_id=user_id,
                )
                if mid:
                    saved += 1
                    logger.debug("[ExtractJob] stored #%d: %.50s", mid, content)
            except Exception as e:
                logger.warning("[ExtractJob] store failed: %s", e)

        return saved
