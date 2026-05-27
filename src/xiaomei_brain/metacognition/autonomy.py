"""自主推进与多模型审查 — Layer 4 & 5。

自主推进（Layer 4）：
    "可逆的操作自主，不可逆的确认。"
    不是 LLM 判断——是规则计算。在 PACE 的 _pre_check() 中调用。

多模型审查（Layer 5）：
    方向级决策、架构级改动时触发审查。
    pro 执行，另一个 prompt 审视。
    触发条件：创建新模块、修改架构、子目标完成、InnerVoice 发出信号。
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


# ── 多模型审查 ─────────────────────────────────────────────────────────

# 审查触发条件
_REVIEW_TRIGGER_PATTERNS = [
    "创建", "新建", "新增模块", "新文件",
    "架构", "重构", "config", "router", "路由",
    "数据模型", "schema", "migration",
]


def should_review(
    description: str,
    files_changed: list[str] | None = None,
    operation_type: str = "",
    sub_goal_completed: bool = False,
    inner_voice_signal: str = "",
) -> bool:
    """判断是否需要触发多模型审查。

    触发条件：
    - 创建新模块/新文件
    - 修改架构相关代码（config、router、数据模型）
    - 子目标完成时的最终检查
    - InnerVoice 发出"不太对劲"信号时

    Args:
        description: 操作描述
        files_changed: 修改的文件列表
        operation_type: 操作类型
        sub_goal_completed: 是否子目标完成
        inner_voice_signal: InnerVoice 信号文本

    Returns:
        是否需要审查
    """
    # InnerVoice 发出信号
    if inner_voice_signal:
        import re
        if re.search(r"(不太对|不对劲|有问题|要注意|确认一下)", inner_voice_signal):
            return True

    # 子目标完成
    if sub_goal_completed:
        return True

    # 创建新模块/文件
    if operation_type == "create":
        return True

    # 修改架构文件
    if files_changed:
        architecture_files = {
            "config", "router", "route", "schema", "model",
            "__init__", "settings", "middleware", "migration",
        }
        for f in files_changed:
            parts = f.lower().replace(".py", "").replace(".ts", "").replace(".js", "").split("/")
            for part in parts:
                if part in architecture_files:
                    return True

    # 描述包含触发词
    desc_lower = description.lower()
    if any(pattern in desc_lower for pattern in _REVIEW_TRIGGER_PATTERNS):
        return True

    return False


# ── 审查 Prompt ────────────────────────────────────────────────────────

_REVIEW_SYSTEM_PROMPT = """你是一个代码审查者。你的角色是从不同角度审视一个决策或改动。

你不是在挑剔——你是在帮助发现盲区。请从以下角度思考：

1. 有没有更简单的方案？
   - 这个改动是不是过度设计了？
   - 有没有更直接的方式达到同样效果？

2. 和项目整体风格一致吗？
   - 命名、结构、模式是否和现有代码协调？
   - 会不会引入不一致性？

3. 有什么可能出问题的地方？
   - 边界情况、错误处理、性能影响
   - 对其他模块的副作用

请简洁地给出审查意见。如果一切合理，就说"审查通过，没有问题"。"""

_REVIEW_USER_PROMPT = """请审视以下决策/改动：

操作：{description}

涉及文件：
{files}

上下文：
{context}

请给出你的审查意见。"""


def review(
    description: str,
    files_changed: list[str],
    llm: Any,
    context: str = "",
) -> str | None:
    """执行多模型审查。

    使用不同于执行 prompt 的角色 prompt 来审视决策。
    同一模型 + 不同角色也能发现盲区。

    Args:
        description: 操作描述
        files_changed: 涉及文件
        llm: LLM 客户端（和主执行用同一个模型，不同 system prompt）
        context: 额外上下文

    Returns:
        审查意见文本，或 None（审查失败）
    """
    if not llm:
        return None

    files_text = "\n".join(f"- {f}" for f in files_changed[:10]) or "无"

    messages = [
        {"role": "system", "content": _REVIEW_SYSTEM_PROMPT},
        {"role": "user", "content": _REVIEW_USER_PROMPT.format(
            description=description[:500],
            files=files_text,
            context=context[:500] if context else "无",
        )},
    ]

    try:
        response = llm.chat(messages)
        if response and hasattr(response, "content"):
            result = (response.content or "").strip()
            logger.info("[Review] 审查完成: %s", result[:80])
            return result
    except Exception as e:
        logger.warning("[Review] 审查失败: %s", e)

    return None
