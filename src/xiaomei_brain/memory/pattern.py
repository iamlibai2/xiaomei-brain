"""Pattern Memory — 模式记忆：跨时间统计规律的提取、存储和注入。

从 ExperienceStream 提取统计规律，存入 LTM type="pattern"，通过注入点影响决策。

Classes:
    Pattern: 一条模式记忆的数据结构
    PatternStorage: 存取 LTM type="pattern" 记录
    PatternExtractor: 在梦境中查询数据 → 构建 prompt → 调 LLM → 解析输出
    PatternInjector: 五个注入点的检索 + 格式化
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ── Pattern 数据结构 ─────────────────────────────────────

@dataclass
class Pattern:
    """一条模式记忆"""

    content: str = ""
    category: str = "user_behavior"
    subcategory: str = "temporal_rhythm"
    confidence: float = 0.5
    evidence: str = ""
    scene_tags: list[str] = field(default_factory=list)
    memory_id: int = 0

    VALID_CATEGORIES = {"user_behavior", "self_efficacy", "interaction"}
    VALID_SUBCATEGORIES = {
        "temporal_rhythm", "topic_cluster", "mood_trend",
        "error_pattern", "strategy", "learning",
        "depth_pattern", "transition",
    }

    def to_dict(self) -> dict:
        return {
            "content": self.content,
            "category": self.category,
            "subcategory": self.subcategory,
            "confidence": self.confidence,
            "evidence": self.evidence,
            "scene_tags": self.scene_tags,
            "memory_id": self.memory_id,
        }

    @classmethod
    def from_ltm_record(cls, record: dict) -> "Pattern":
        tags = record.get("tags", [])
        scene_tags = record.get("scene_tags", [])
        category = "user_behavior"
        subcategory = "temporal_rhythm"
        for tag in tags:
            if tag in cls.VALID_CATEGORIES:
                category = tag
            elif tag in cls.VALID_SUBCATEGORIES:
                subcategory = tag
        return cls(
            content=record.get("content", ""),
            category=category,
            subcategory=subcategory,
            confidence=record.get("confidence", 0.5) or 0.5,
            evidence=record.get("evidence", "") or "",
            scene_tags=list(scene_tags) if scene_tags else [],
            memory_id=record.get("id", 0),
        )


# ── PatternStorage ───────────────────────────────────────

class PatternStorage:
    """模式记忆的持久化存储，复用 LTM memories 表 type="pattern"。"""

    def __init__(self, ltm) -> None:
        self._ltm = ltm

    def store(self, pattern: Pattern) -> int | None:
        """存储一条模式到 LTM。返回 memory_id 或 None。"""
        if not self._ltm:
            return None
        try:
            memory_id = self._ltm.store(
                content=pattern.content,
                source="dream",
                tags=[
                    "pattern",
                    pattern.category,
                    pattern.subcategory,
                ],
                importance=pattern.confidence,
                user_id="global",
                mem_type="pattern",
                scene_tags=pattern.scene_tags,
                confidence=pattern.confidence,
            )
            pattern.memory_id = memory_id
            logger.info(
                "[PatternStorage] 存储: #%d cat=%s conf=%.2f: %s",
                memory_id, pattern.category, pattern.confidence, pattern.content,
            )
            return memory_id
        except Exception as e:
            logger.warning("[PatternStorage] 存储失败: %s", e)
            return None

    def update_confidence(self, memory_id: int, new_confidence: float) -> bool:
        """更新已有模式的置信度。"""
        if not self._ltm:
            return False
        try:
            conn = self._ltm._get_conn()
            conn.execute(
                "UPDATE memories SET confidence = ?, importance = ? WHERE id = ?",
                (new_confidence, new_confidence, memory_id),
            )
            conn.commit()
            logger.info(
                "[PatternStorage] 更新置信度: #%d → %.2f", memory_id, new_confidence,
            )
            return True
        except Exception as e:
            logger.warning("[PatternStorage] 更新置信度失败: %s", e)
            return False

    def get_all(self) -> list[dict]:
        """获取所有模式（用于梦境对比）。"""
        if not self._ltm:
            return []
        try:
            return self._ltm.search_by_tags(["pattern"], user_id="global")
        except Exception:
            return []

    def get_top(self, top_k: int = 3) -> list[dict]:
        """获取置信度最高的 N 条模式（用于系统提示词注入）。"""
        patterns = self.get_all()
        patterns.sort(key=lambda p: p.get("confidence", 0) or 0, reverse=True)
        return patterns[:top_k]

    def search_by_tags(self, tags: list[str]) -> list[dict]:
        """按标签检索模式。"""
        if not self._ltm:
            return []
        try:
            return self._ltm.search_by_tags(tags, user_id="global")
        except Exception:
            return []

    def decay_unobserved(self, observed_ids: set[int]) -> int:
        """衰减未被本次观察到的模式。返回衰减数量。"""
        all_patterns = self.get_all()
        decayed = 0
        for p in all_patterns:
            pid = p.get("id", 0)
            if pid not in observed_ids:
                old_conf = p.get("confidence", 0.5) or 0.5
                new_conf = round(old_conf * 0.9, 2)
                if new_conf < 0.1:
                    new_conf = 0.05
                self.update_confidence(pid, new_conf)
                decayed += 1
                logger.debug(
                    "[PatternStorage] 衰减: #%d %.2f→%.2f", pid, old_conf, new_conf,
                )
        return decayed


# ── PatternExtractor ─────────────────────────────────────

class PatternExtractor:
    """在梦境中提取模式：查询数据 → 构建 prompt → 调 LLM → 解析 → 存储。"""

    def __init__(
        self,
        storage: PatternStorage,
        exp_stream,
        conversation_db,
        ltm,
    ) -> None:
        self._storage = storage
        self._exp_stream = exp_stream
        self._conversation_db = conversation_db
        self._ltm = ltm

    def extract(self, llm, time_window: float = 86400.0) -> list[Pattern]:
        """执行一次模式提取。

        Args:
            llm: LLM 客户端（需要 .chat() 方法）
            time_window: 回顾时间窗口（秒），默认 24h

        Returns:
            提取到的 Pattern 列表
        """
        # 1. 收集数据
        experience_data = self._gather_experience(time_window)
        existing_patterns = self._gather_existing_patterns()
        social_signals = self._gather_social_signals(time_window)

        # 2. 构建 prompt
        from ..prompts import PATTERN_EXTRACT_PROMPT

        prompt = PATTERN_EXTRACT_PROMPT.format(
            experience_data=experience_data or "（本时段无活动记录）",
            existing_patterns=existing_patterns or "（暂无已有模式）",
            social_signals=social_signals or "（无社交信号记录）",
        )

        # 3. 调 LLM
        try:
            resp = llm.chat(
                messages=[{"role": "user", "content": prompt}],
                tools=None,
            )
            raw = resp.content or ""
            logger.info("[PatternExtractor] LLM 返回 %d 字", len(raw))
        except Exception as e:
            logger.error("[PatternExtractor] LLM 调用失败: %s", e)
            return []

        # 4. 解析输出
        patterns = self._parse_response(raw)

        # 5. 存储
        stored_ids: set[int] = set()
        for p in patterns:
            if p.memory_id > 0:
                # UPDATE 已有模式
                self._storage.update_confidence(p.memory_id, p.confidence)
                stored_ids.add(p.memory_id)
            else:
                # ADD 新模式
                mid = self._storage.store(p)
                if mid:
                    stored_ids.add(mid)

        # 6. 衰减未观察到的已有模式
        decayed = self._storage.decay_unobserved(stored_ids)
        logger.info(
            "[PatternExtractor] 提取完成: new+updated=%d, decayed=%d",
            len(stored_ids), decayed,
        )

        return patterns

    def _gather_experience(self, time_window: float) -> str:
        """从 ExperienceStream 收集最近时段的数据。"""
        if not self._exp_stream:
            return ""
        since = time.time() - time_window
        try:
            events = self._exp_stream.get_recent(limit=200)
            if not events:
                return ""
            filtered = [e for e in events if e.get("created_at", 0) >= since]
            lines = []
            for e in filtered[-100:]:
                etype = e.get("type", "?")
                content = e.get("content", "")[:150]
                lines.append(f"[{etype}] {content}")
            return "\n".join(lines)
        except Exception as e:
            logger.warning("[PatternExtractor] 收集经验失败: %s", e)
            return ""

    def _gather_existing_patterns(self) -> str:
        """获取已有模式列表（供 LLM 对比）。"""
        patterns = self._storage.get_all()
        if not patterns:
            return ""
        lines = []
        for p in patterns[-30:]:
            lines.append(
                f"#{p.get('id', '?')} [{p.get('confidence', 0):.2f}] "
                f"{p.get('content', '')}"
            )
        return "\n".join(lines)

    def _gather_social_signals(self, time_window: float) -> str:
        """从 ExperienceStream 收集社交感知相关事件。"""
        if not self._exp_stream:
            return ""
        since = time.time() - time_window
        try:
            events = self._exp_stream.get_recent(limit=200)
            if not events:
                return ""
            # 过滤 internal_reflection 类型（InnerVoice/SocialPerception 写入）
            filtered = [
                e for e in events
                if e.get("type") == "internal_reflection"
                and e.get("created_at", 0) >= since
            ]
            lines = []
            for e in filtered[-20:]:
                content = e.get("content", "")[:120]
                lines.append(f"[{e.get('created_at', 0)}] {content}")
            return "\n".join(lines)
        except Exception:
            return ""

    def _parse_response(self, raw: str) -> list[Pattern]:
        """解析 LLM 返回的 JSON。"""
        try:
            # 尝试提取 JSON 块
            json_str = raw
            if "```json" in raw:
                json_str = raw.split("```json")[1].split("```")[0]
            elif "```" in raw:
                json_str = raw.split("```")[1].split("```")[0]
            data = json.loads(json_str.strip())
            pattern_list = data.get("patterns", [])
        except json.JSONDecodeError:
            logger.warning("[PatternExtractor] JSON 解析失败: %.100s", raw)
            return []

        patterns = []
        for item in pattern_list:
            action = item.get("action", "ADD").upper()
            content = item.get("content", "").strip()
            if not content:
                continue

            category = item.get("category", "user_behavior")
            if category not in Pattern.VALID_CATEGORIES:
                category = "user_behavior"

            subcategory = item.get("subcategory", "temporal_rhythm")
            if subcategory not in Pattern.VALID_SUBCATEGORIES:
                subcategory = "temporal_rhythm"

            confidence = max(0.05, min(0.95, float(item.get("confidence", 0.5))))

            memory_id = 0
            if action == "UPDATE":
                memory_id = int(item.get("existing_pattern_id", 0) or 0)
            elif action == "MERGE":
                memory_id = 0  # 新建合并后的模式

            p = Pattern(
                content=content,
                category=category,
                subcategory=subcategory,
                confidence=confidence,
                evidence=item.get("evidence", "").strip(),
                scene_tags=item.get("scene_tags", []) or [],
                memory_id=memory_id,
            )
            patterns.append(p)
            logger.info(
                "[PatternExtractor] %s: %.2f %s/%s: %s",
                action, confidence, category, subcategory, content,
            )

        return patterns


# ── PatternInjector ──────────────────────────────────────

class PatternInjector:
    """模式注入：五个注入点的检索 + 格式化。

    注入点：
    1. 系统提示词 — top-3 高置信度模式
    2. L2 intent  — 语义匹配当前情境
    3. 对话上下文 — 语义匹配用户消息
    4. 学习选题   — topic_cluster 加成
    5. 梦境提取   — 全部已有模式（由 PatternExtractor._gather_existing_patterns 处理）
    """

    def __init__(self, storage: PatternStorage, ltm) -> None:
        self._storage = storage
        self._ltm = ltm

    # ── 注入点 1: 系统提示词 ─────────────────────────────

    def render_system_prompt(self) -> str:
        """渲染系统提示词中的模式片段。"""
        top = self._storage.get_top(top_k=3)
        if not top:
            return ""
        lines = ["我注意到："]
        for p in top:
            content = p.get("content", "")
            if content:
                lines.append(f"· {content}")
        return "\n".join(lines)

    # ── 注入点 2: L2 intent 决策 ──────────────────────────

    def inject_l2_intent(self, context_description: str) -> str:
        """为 L2 intent 决策注入情境相关模式（仅1条最相关）。"""
        if not self._ltm or not context_description:
            return ""
        try:
            results = self._ltm.recall(
                context_description, top_k=2, user_id="global",
            )
            pattern_results = [
                r for r in results
                if "pattern" in (r.get("tags", []) or [])
            ]
            if not pattern_results:
                return ""
            content = pattern_results[0].get("content", "")[:80]
            logger.info(
                "[PatternInjector] L2 intent 注入: %s", content,
            )
            return f"当前情境相关模式：{content}"
        except Exception:
            return ""

    # ── 注入点 3: 对话上下文 ──────────────────────────────

    def inject_context(self, user_message: str) -> str:
        """为用户消息注入话题相关模式（仅1条最相关）。"""
        if not self._ltm or not user_message:
            return ""
        try:
            results = self._ltm.recall(
                user_message, top_k=2, user_id="global",
            )
            pattern_results = [
                r for r in results
                if "pattern" in (r.get("tags", []) or [])
            ]
            if not pattern_results:
                return ""
            content = pattern_results[0].get("content", "")[:80]
            logger.info(
                "[PatternInjector] 对话上下文注入: %s", content,
            )
            return f"\n[话题趋势] {content}"
        except Exception:
            return ""

    # ── 注入点 4: 学习选题加权 ────────────────────────────

    def boost_learning_topics(self, candidates: list[str]) -> dict[str, float]:
        """根据 topic_cluster 模式给候选主题加权。返回 {topic: boost}。"""
        if not candidates:
            return {}
        try:
            cluster_patterns = self._storage.search_by_tags(
                ["pattern", "topic_cluster"],
            )
            boosts: dict[str, float] = {}
            for candidate in candidates:
                boost = 0.0
                for p in cluster_patterns:
                    content = p.get("content", "")
                    confidence = p.get("confidence", 0.5) or 0.5
                    if candidate in content or any(
                        keyword in content
                        for keyword in candidate.split()
                    ):
                        boost += confidence * 0.2
                if boost > 0:
                    boosts[candidate] = min(boost, 0.5)
            return boosts
        except Exception:
            return {}
