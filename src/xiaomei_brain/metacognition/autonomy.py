"""自主推进判断 — Layer 4。

"可逆的操作自主，不可逆的确认。"
不是 LLM 判断——是规则计算。在 PACE 的 _pre_check() 中调用。

多模型审查（原 Layer 5）已合并到 perspectives.broaden_perspective()——统一多视角审视。
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ── 不可逆操作关键词 ──────────────────────────────────────────────────

_IRREVERSIBLE_PATTERNS = [
    # Git 危险操作
    "force push", "git push --force", "push -f",
    "git reset --hard", "git clean -f",
    # 数据删除
    "DROP TABLE", "DROP DATABASE", "DELETE FROM", "TRUNCATE",
    "rm -rf", "rm -r", "shred",
    # 权限/安全
    "chmod 777", "chown", "sudo rm",
    # 生产环境
    "deploy to production", "deploy prod",
    # 破坏性迁移
    "DROP COLUMN", "irreversible migration",
]


def is_irreversible(goal_description: str) -> bool:
    """检查目标描述是否包含不可逆操作。"""
    desc_lower = goal_description.lower()
    return any(pattern.lower() in desc_lower for pattern in _IRREVERSIBLE_PATTERNS)


# ── 自主推进判断 ───────────────────────────────────────────────────────

def can_autonomy(
    goal_description: str,
    blocked_by: list[str] | None = None,
    similar_experiences: list | None = None,
    capability_weaknesses: dict[str, float] | None = None,
) -> tuple[bool, str]:
    """判断是否可以自主推进（不需要用户确认）。

    五道检查：
    1. 不可逆操作检查
    2. 依赖检查
    3. 经验匹配
    4. 能力匹配
    5. 模糊度检查

    Args:
        goal_description: 目标描述
        blocked_by: 被哪些目标阻塞（空列表或 None 表示无阻塞）
        similar_experiences: 类似经验列表（Experience 对象）
        capability_weaknesses: 能力弱点 {domain: weakness_score 0.0-1.0}

    Returns:
        (can_autonomy, reason)
    """
    blocked_by = blocked_by or []
    similar_experiences = similar_experiences or []
    capability_weaknesses = capability_weaknesses or {}

    # 1. 不可逆操作检查
    if is_irreversible(goal_description):
        return False, "包含不可逆操作，需要用户确认"

    # 2. 依赖检查
    if blocked_by:
        return False, f"被 {len(blocked_by)} 个前置目标阻塞，无法执行"

    # 3. 经验匹配
    if similar_experiences:
        good = sum(
            1 for e in similar_experiences
            if getattr(e, "outcome_type", "") in ("good", "mixed")
        )
        total = len(similar_experiences)
        success_rate = good / total if total > 0 else 0
        if success_rate < 0.5:
            return False, f"类似任务成功率仅 {success_rate:.0%}（< 50%），建议确认"

    # 4. 能力匹配
    domain = _classify_domain(goal_description)
    if domain and capability_weaknesses.get(domain, 0) > 0.5:
        return False, f"在 {domain} 领域能力较弱，建议确认"

    # 5. 模糊度检查
    if _is_ambiguous(goal_description):
        return False, "目标描述不够清晰，需要确认后再执行"

    return True, "可以自主推进"


def _classify_domain(description: str) -> str:
    """从目标描述中推断技术领域。"""
    desc = description.lower()

    domain_keywords = {
        "前端": ["react", "vue", "angular", "css", "html", "ui", "组件", "页面", "前端"],
        "后端": ["api", "server", "数据库", "sql", "orm", "后端", "接口", "rest"],
        "运维": ["docker", "k8s", "kubernetes", "deploy", "ci/cd", "nginx", "部署", "运维"],
        "数据": ["数据", "etl", "pipeline", "分析", "统计", "报表", "ml", "机器学习"],
        "安全": ["安全", "auth", "oauth", "加密", "权限", "xss", "csrf"],
    }

    for domain, keywords in domain_keywords.items():
        if any(kw in desc for kw in keywords):
            return domain

    return ""


def _is_ambiguous(description: str) -> bool:
    """检查目标描述是否过于模糊。"""
    desc = description.strip()

    # 太短 → 模糊
    if len(desc) < 5:
        return True

    # 全是模糊词
    vague_words = {"改一下", "优化", "改进", "弄一下", "处理", "调整", "做个东西"}
    if desc in vague_words or all(w in vague_words for w in desc.split()):
        return True

    # 只有"做X"但没有具体说明
    if desc.startswith("做") and len(desc) < 10:
        return True

    return False


