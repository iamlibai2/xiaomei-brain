"""显著性权重自学习 — 检测 LLM 回复中引用了哪些 section，自适应调整评分权重。

核心理念：
- LLM 的回复本身就告诉你哪些 section 是有用的
- 引用 → +0.02（缓慢上升），未引用 → -0.005（极慢衰减）
- 纯规则检测，零成本、零延迟
- 跨会话持久化，每个 agent 一份

Usage:
    from .salience_profile import SalienceProfile, _detect_section_references
    profile = SalienceProfile.load(path)
    boost = profile.get_boost("memory")  # 0.0 ~ 0.3
    profile.feedback("memory", True)     # LLM 引用了 memory
    profile.save(path)
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ── 引用检测规则 ────────────────────────────────────────

# section_name → 在 LLM 回复中匹配这些关键词
_REFERENCE_PATTERNS: dict[str, list[str]] = {
    "memory": [
        "之前", "上次", "记得", "你说过", "聊过", "那次",
        "当时我们", "历史", "记录", "以前",
    ],
    "body": [
        "能量", "心情", "疲惫", "状态不", "精神", "累了",
        "开心", "紧张", "兴奋", "沮丧", "情绪",
    ],
    "being": [
        "朋友", "关系", "初识", "亲密", "信任",
    ],
    "mind": [
        "目标", "进展", "计划", "你的目标是", "下一步",
    ],
    "inner_voice": [
        "我在想", "刚才在想", "内心", "直觉",
    ],
    "experience": [
        "之前的方法", "以前做过", "踩过坑", "上次用",
        "上回", "经验", "教训",
    ],
    "pace": [
        "卡住", "方向", "换方法", "调整策略", "换个思路",
    ],
    "intent": [
        "意图", "想做", "打算做",
    ],
    "milestones": [
        "里程碑", "达成", "完成了",
    ],
}


def _detect_section_references(response_text: str) -> set[str]:
    """检测 LLM 回复中引用了哪些 section 的数据。

    纯规则，不需要 LLM。检测不完全但一致 — 多轮平均后权重会收敛。
    """
    referenced: set[str] = set()
    if not response_text:
        return referenced

    for section_name, keywords in _REFERENCE_PATTERNS.items():
        if any(k in response_text for k in keywords):
            referenced.add(section_name)

    return referenced


# ── SalienceProfile ─────────────────────────────────────

class SalienceProfile:
    """每个 section 的自适应权重，跨会话持久化。

    权重范围: -0.3 ~ +0.3
    学习率: 引用 +0.02, 未引用 -0.005（衰减慢 4 倍）
    """

    MAX_BOOST = 0.3
    MIN_BOOST = -0.3
    REWARD = 0.02
    DECAY = 0.005

    def __init__(self) -> None:
        self.weights: dict[str, float] = {}
        self._hit_count: dict[str, int] = {}
        self._miss_count: dict[str, int] = {}

    # ── 核心 API ───────────────────────────────────

    def feedback(self, section_name: str, was_referenced: bool) -> None:
        """一次反馈：LLM 发起的本轮对话中，这个 section 是否被引用。"""
        if was_referenced:
            self._hit_count[section_name] = self._hit_count.get(section_name, 0) + 1
            new_weight = min(self.MAX_BOOST,
                             self.weights.get(section_name, 0.0) + self.REWARD)
            self.weights[section_name] = new_weight
        else:
            self._miss_count[section_name] = self._miss_count.get(section_name, 0) + 1
            # 只在有足够命中数后才衰减（防止初始化时的噪声惩罚）
            if self._hit_count.get(section_name, 0) >= 3:
                new_weight = max(self.MIN_BOOST,
                                 self.weights.get(section_name, 0.0) - self.DECAY)
                self.weights[section_name] = new_weight

    def get_boost(self, section_name: str) -> float:
        """获取该 section 的学习权重。未经学习的 section 返回 0.0。"""
        return self.weights.get(section_name, 0.0)

    # ── 持久化 ─────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        return {
            "weights": self.weights,
            "hits": self._hit_count,
            "misses": self._miss_count,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SalienceProfile:
        p = cls()
        p.weights = data.get("weights", {})
        p._hit_count = data.get("hits", {})
        p._miss_count = data.get("misses", {})
        return p

    def save(self, path: str | Path) -> None:
        """保存到 JSON 文件。"""
        try:
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2))
        except Exception as e:
            logger.debug("[SalienceProfile] 保存失败: %s", e)

    @classmethod
    def load(cls, path: str | Path) -> SalienceProfile:
        """从 JSON 文件加载，文件不存在则返回空 profile。"""
        p = Path(path)
        if not p.exists():
            return cls()
        try:
            data = json.loads(p.read_text())
            return cls.from_dict(data)
        except (json.JSONDecodeError, ValueError) as e:
            logger.debug("[SalienceProfile] 加载失败，使用空 profile: %s", e)
            return cls()
