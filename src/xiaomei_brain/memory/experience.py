"""Experience Memory — 情境→决策→结果 三元组经验记忆。

不是"记住 API 用法"，而是记录做项目过程中的：
- 情境：在做什么、什么技术栈、什么约束
- 决策：选了哪个方案
- 结果：好/坏/混合 + 具体发生了什么
- 教训：下次该怎么做

存储：复用 LongTermMemory 的 memories 表 + LanceDB 向量索引。
新增 experience_type 和 project_id 列（自动迁移，不影响现有数据）。

InnerVoice 识别到重要经验时触发提取，一次轻量 LLM 调用格式化。
每次 task 模式上下文组装时按语义召回。
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ── Experience 数据结构 ────────────────────────────────────────────────

@dataclass
class Experience:
    """一条经验记忆 — 情境→决策→结果→教训。"""

    id: str = ""
    context: str = ""             # 情境：在做什么、什么技术栈、什么约束
    decision: str = ""            # 决策：选了哪个方案
    outcome: str = ""             # 结果：好/坏/混合 + 具体发生了什么
    lesson: str = ""              # 教训：下次该怎么做
    outcome_type: str = "neutral" # "good" / "bad" / "mixed" / "neutral"
    project_id: str = ""          # 哪个项目（空 = 通用经验）
    tags: list[str] = field(default_factory=list)  # 标签：技术栈、问题类型
    created_at: float = field(default_factory=time.time)
    memory_id: int = 0            # 对应 memories 表的 ID

    # ── 格式化 ──────────────────────────────────────────────────

    def to_text(self) -> str:
        """格式化为可嵌入的文本（用于语义搜索）。"""
        parts = []
        if self.context:
            parts.append(f"情境：{self.context}")
        if self.project_id:
            parts.append(f"项目：{self.project_id}")
        if self.decision:
            parts.append(f"决策：{self.decision}")
        if self.outcome:
            parts.append(f"结果：{self.outcome}")
        if self.lesson:
            parts.append(f"教训：{self.lesson}")
        return "\n".join(parts)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "context": self.context,
            "decision": self.decision,
            "outcome": self.outcome,
            "lesson": self.lesson,
            "outcome_type": self.outcome_type,
            "project_id": self.project_id,
            "tags": self.tags,
            "created_at": self.created_at,
            "memory_id": self.memory_id,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Experience":
        return cls(
            id=data.get("id", ""),
            context=data.get("context", ""),
            decision=data.get("decision", ""),
            outcome=data.get("outcome", ""),
            lesson=data.get("lesson", ""),
            outcome_type=data.get("outcome_type", "neutral"),
            project_id=data.get("project_id", ""),
            tags=data.get("tags", []),
            created_at=data.get("created_at", time.time()),
            memory_id=data.get("memory_id", 0),
        )


# ── LLM 经验提取 Prompt ────────────────────────────────────────────────

_EXTRACT_PROMPT = """你刚经历了以下内心反省，请将其中值得记住的经验提取为结构化格式。

内心声音：{reflection}

请注意：
- 如果确实有值得记住的经验（"这个方法不行"、"这个坑记住了"、"下次..."），提取出来
- 如果没有实质经验，返回 null
- 情境 = 当时在做什么、什么约束
- 决策 = 你选择了什么方案/方法
- 结果 = 发生了什么（好/坏/混合）
- 教训 = 浓缩成一句话，下次该怎么做

返回 JSON（不要其他内容）：
{{"has_experience": true/false, "context": "...", "decision": "...", "outcome": "...", "outcome_type": "good/bad/mixed", "lesson": "..."}}
如果没有经验：{{"has_experience": false}}"""


# ── ExperienceMemory 存储引擎 ──────────────────────────────────────────

class ExperienceMemory:
    """经验记忆存储和检索。

    复用 LongTermMemory 的：
    - memories 表：存储格式化文本 + 元数据
    - LanceDB 向量索引：语义搜索
    - tags 系统：按技术栈/问题类型过滤

    额外：
    - experience_type 列：标记经验类型（决策/模式/踩坑）
    - project_id 列：关联项目
    """

    def __init__(self, ltm: Any) -> None:
        """
        Args:
            ltm: LongTermMemory 实例
        """
        self._ltm = ltm

    # ── 存储 ──────────────────────────────────────────────────────

    def store_experience(self, exp: Experience) -> int:
        """存储一条经验记忆。

        Returns:
            memories 表的 ID
        """
        # 用 source="experience" 区分，格式化文本用于语义搜索
        text = exp.to_text()
        tags = list(exp.tags)
        if exp.project_id:
            tags.append(f"project:{exp.project_id}")
        if exp.outcome_type:
            tags.append(f"outcome:{exp.outcome_type}")

        memory_id = self._ltm.store(
            content=text,
            source="experience",
            tags=tags,
            importance=self._calc_importance(exp),
        )

        # 写入 experience 专用字段
        conn = self._ltm._get_conn()
        conn.execute(
            "UPDATE memories SET experience_type=?, project_id=? WHERE id=?",
            (exp.outcome_type, exp.project_id, memory_id),
        )
        conn.commit()

        exp.memory_id = memory_id
        logger.info(
            "[Experience] 存储 #%d [%s] [%s]: %s",
            memory_id, exp.outcome_type, exp.project_id or "通用",
            exp.lesson[:60],
        )
        return memory_id

    def _calc_importance(self, exp: Experience) -> float:
        """根据 outcome 计算经验重要性。"""
        base = {
            "bad": 0.7,     # 踩坑经验最重要
            "mixed": 0.6,
            "good": 0.5,
            "neutral": 0.4,
        }.get(exp.outcome_type, 0.5)
        # 有明确教训的加分
        if exp.lesson:
            base = min(1.0, base + 0.1)
        return base

    # ── 召回 ──────────────────────────────────────────────────────

    def recall(
        self,
        query: str = "",
        project_id: str = "",
        tags: list[str] | None = None,
        outcome_type: str = "",
        top_k: int = 5,
        min_success_rate: float | None = None,
    ) -> list[Experience]:
        """语义召回经验记忆。

        Args:
            query: 语义搜索查询（当前情境描述）
            project_id: 按项目过滤（空 = 不过滤）
            tags: 按标签过滤（技术栈、问题类型等）
            outcome_type: 按结果类型过滤（"good"/"bad"/"mixed"）
            top_k: 返回数量
            min_success_rate: 最小成功率阈值（0.0-1.0），过滤掉以 bad 为主的经验

        Returns:
            经验列表，按语义相似度排序
        """
        # 用向量搜索获取候选
        results = self._ltm.recall(
            query=query or "经验 教训 决策",
            top_k=top_k * 2,  # 多取一些，后面再过滤
            sources=["experience"],
        )

        # 转换为 Experience 对象并过滤
        experiences: list[Experience] = []
        for r in results:
            exp = self._row_to_experience(r)

            # 按项目过滤
            if project_id and exp.project_id and exp.project_id != project_id:
                continue

            # 按 outcome 过滤
            if outcome_type and exp.outcome_type != outcome_type:
                continue

            # 按标签过滤
            if tags:
                exp_tag_set = set(exp.tags)
                if not any(t in exp_tag_set for t in tags):
                    continue

            experiences.append(exp)

        # 成功率过滤
        if min_success_rate is not None and experiences:
            similar_ids = [e.id for e in experiences if e.id]
            if similar_ids:
                good_count = sum(
                    1 for e in experiences
                    if e.outcome_type in ("good", "mixed")
                )
                success_rate = good_count / len(experiences) if experiences else 0
                if success_rate < min_success_rate:
                    logger.info(
                        "[Experience] 类似经验成功率 %.0f%% < %.0f%%，建议谨慎",
                        success_rate * 100, min_success_rate * 100,
                    )

        return experiences[:top_k]

    def _row_to_experience(self, row: dict) -> Experience:
        """将 memories 表行转为 Experience 对象。"""
        content = row.get("content", "")
        exp = Experience(
            id=str(row.get("id", "")),
            memory_id=row.get("id", 0),
            outcome_type=row.get("experience_type", "neutral"),
            project_id=row.get("project_id", ""),
            tags=self._parse_tags(row.get("tags", "")),
            created_at=row.get("created_at", time.time()),
        )

        # 尝试从 content 解析结构化字段
        if content:
            exp = self._parse_content_fields(content, exp)

        return exp

    def _parse_content_fields(self, content: str, exp: Experience) -> Experience:
        """从格式化文本中解析结构化字段。"""
        for line in content.split("\n"):
            line = line.strip()
            if line.startswith("情境："):
                exp.context = line[3:]
            elif line.startswith("决策："):
                exp.decision = line[3:]
            elif line.startswith("结果："):
                exp.outcome = line[3:]
            elif line.startswith("教训："):
                exp.lesson = line[3:]
            elif line.startswith("项目："):
                if not exp.project_id:
                    exp.project_id = line[3:]
        return exp

    @staticmethod
    def _parse_tags(tags_val) -> list[str]:
        """解析 tags 值（可能是 JSON 字符串或列表）。"""
        if isinstance(tags_val, list):
            return tags_val
        if isinstance(tags_val, str):
            try:
                return json.loads(tags_val)
            except (json.JSONDecodeError, TypeError):
                return [t.strip() for t in tags_val.split(",") if t.strip()]
        return []

    # ── 查询 ──────────────────────────────────────────────────────

    def get_by_project(self, project_id: str, limit: int = 20) -> list[Experience]:
        """获取项目的所有经验。"""
        conn = self._ltm._get_conn()
        rows = conn.execute(
            """SELECT id, content, experience_type, project_id, created_at
               FROM memories WHERE source='experience' AND project_id=?
               ORDER BY created_at DESC LIMIT ?""",
            (project_id, limit),
        ).fetchall()

        experiences = []
        for r in rows:
            d = dict(r)
            # 加载 tags
            tag_rows = conn.execute(
                "SELECT tag FROM memory_tags WHERE memory_id=?",
                (d["id"],),
            ).fetchall()
            d["tags"] = [tr[0] for tr in tag_rows]
            experiences.append(self._row_to_experience(d))

        return experiences

    def get_statistics(self, project_id: str = "") -> dict:
        """获取经验统计信息。"""
        conn = self._ltm._get_conn()
        where = "source='experience'"
        params: list = []
        if project_id:
            where += " AND project_id=?"
            params.append(project_id)

        rows = conn.execute(
            f"SELECT experience_type, COUNT(*) as cnt FROM memories WHERE {where} GROUP BY experience_type",
            params,
        ).fetchall()

        total = sum(r[1] for r in rows)
        stats = {"total": total, "good": 0, "bad": 0, "mixed": 0, "neutral": 0}
        for r in rows:
            key = r[0] if r[0] in stats else "neutral"
            stats[key] = r[1]

        return stats

    # ── LLM 提取 ──────────────────────────────────────────────────

    def extract_from_reflection(
        self,
        reflection_text: str,
        llm: Any,
        project_id: str = "",
    ) -> Experience | None:
        """从 InnerVoice 反省文本中提取经验。

        Args:
            reflection_text: InnerVoice 反省文本（自然语言）
            llm: LLM 客户端
            project_id: 当前项目 ID

        Returns:
            Experience 或 None（如果无实质经验）
        """
        if not llm:
            return None

        try:
            prompt = _EXTRACT_PROMPT.format(reflection=reflection_text)
            messages = [{"role": "user", "content": prompt}]
            response = llm.chat(messages)
            text = response.content if hasattr(response, "content") else str(response)

            # 解析 JSON
            # 提取 JSON 块
            json_match = __import__("re").search(r"\{[\s\S]*\}", text)
            if not json_match:
                return None

            data = json.loads(json_match.group())
            if not data.get("has_experience"):
                return None

            exp = Experience(
                id="",
                context=data.get("context", "")[:500],
                decision=data.get("decision", "")[:500],
                outcome=data.get("outcome", "")[:500],
                lesson=data.get("lesson", "")[:300],
                outcome_type=data.get("outcome_type", "neutral"),
                project_id=project_id,
            )

            # 存储
            self.store_experience(exp)
            return exp

        except Exception as e:
            logger.warning("[Experience] 提取失败: %s", e)
            return None
