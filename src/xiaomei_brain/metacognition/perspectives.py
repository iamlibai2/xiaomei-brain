"""统一多视角审视 — LLM 自主选择视角，三阶段运行。

不是静态角色扮演——是让 LLM 自己判断：要不要审视？从什么角度？要几个？
三阶段：元视角生成 → 并行审视 → 综合建议。

断点位置由代码固定，触发由 LLM 决定。

Usage:
    from .perspectives import broaden_perspective

    result = broaden_perspective(
        target="当前计划", stage="design",
        context=plan_text, pmm_context=pmm.get_context(),
        llm=agent.llm,
    )
    # result 为综合调整建议，或 None（LLM 决定跳过 / 调用失败）
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

logger = logging.getLogger(__name__)

# ── 阶段信息 ─────────────────────────────────────────────────────────

_STAGE_INFO: dict[str, tuple[str, str]] = {
    "understand": ("需求理解", "理解这个任务真正要解决什么问题，谁会被影响"),
    "design":     ("分解计划", "审视当前子目标拆分——有没有遗漏、有没有多余、顺序对吗"),
    "execute":    ("当前方法", "审视执行路径，找盲区或替代方案"),
    "review":     ("单步产出", "审视刚才这一步的产出质量——有没有隐患、边界情况漏了吗"),
    "retrospect": ("整体交付", "审视完整交付——从用户/维护者/质量标准角度看，真的算'完成'了吗"),
}


# ── Phase 1: 元视角生成 ──────────────────────────────────────────────

_PHASE1_PROMPT = """你正在{stage_hint}。

当前{target}：
{context}
{pmm_section}
你可以选择做一次多视角审视——跳出当前思路，从不同角度看这件事。

思考：谁会被这个{target}影响？他们关心什么？有什么容易被忽略的角度？

如果当前{target}清晰完整、方向明确，回复 **跳过**。
如果需要审视，列出 1-3 个具体视角——不要用笼统的"架构师""用户"，用具体角色。
每个视角一行，格式：
视角: 角色名 | 一句话说明关注点"""


def _generate_perspectives(
    llm: Any, target: str, stage_name: str, stage_hint: str,
    context: str, pmm_context: str, timeout: float,
) -> list[dict[str, str]] | None:
    """Phase 1: LLM 决定是否审视 + 生成视角列表。

    Returns:
        视角列表 [{"name": ..., "focus": ...}]，或 None（跳过/失败）。
    """
    pmm_section = f"\n项目背景：\n{pmm_context}" if pmm_context else ""
    prompt = _PHASE1_PROMPT.format(
        stage_hint=stage_hint, target=target,
        context=context[:1500], pmm_section=pmm_section[:500],
    )

    try:
        response = llm.chat([{"role": "user", "content": prompt}])
        text = (response.content or "").strip() if hasattr(response, "content") else ""
    except Exception as e:
        logger.warning("[broaden] Phase1 LLM 调用失败: %s", e)
        return None

    if not text or "跳过" in text[:20]:
        logger.debug("[broaden] Phase1: LLM 决定跳过审视 (stage=%s)", stage_name)
        return None

    perspectives = []
    for line in text.split("\n"):
        line = line.strip()
        if line.startswith("视角:") or line.startswith("视角："):
            # 格式: "视角: 角色名 | 关注点"
            content = line.split(":", 1)[-1].strip().lstrip("：").strip()
            if "|" in content:
                name, focus = content.split("|", 1)
                name = name.strip()
                focus = focus.strip()
                if name and focus:
                    perspectives.append({"name": name, "focus": focus})

    if not perspectives:
        logger.debug("[broaden] Phase1: 未解析到有效视角")
        return None

    return perspectives[:3]


# ── Phase 2: 并行视角审视 ─────────────────────────────────────────────

_PHASE2_PROMPT = """你是「{name}」。你关注：{focus}

当前{target}：
{context}
{pmm_section}
从你的视角看，这个{target}有什么盲区、问题或改进点？1-2 句话。直接说重点，不要客套。"""


def _parallel_review(
    llm: Any, perspectives: list[dict[str, str]],
    target: str, context: str, pmm_context: str, timeout: float,
) -> list[str]:
    """Phase 2: 并行调用每个视角。

    Returns:
        各视角的观察文本列表。
    """
    pmm_section = f"\n项目背景：\n{pmm_context}" if pmm_context else ""
    results: list[str] = []

    with ThreadPoolExecutor(max_workers=len(perspectives)) as executor:
        futures = {}
        for p in perspectives:
            prompt = _PHASE2_PROMPT.format(
                name=p["name"], focus=p["focus"],
                target=target, context=context[:1000],
                pmm_section=pmm_section[:300],
            )
            futures[
                executor.submit(
                    _call_single, llm, p["name"], prompt, timeout,
                )
            ] = p["name"]

        for future in as_completed(futures, timeout=timeout):
            name = futures[future]
            try:
                result = future.result(timeout=timeout)
                if result:
                    results.append(f"【{name}】{result}")
            except Exception as e:
                logger.warning("[broaden] 视角 %s 调用失败: %s", name, e)

    if results:
        logger.info(
            "[broaden] Phase2: %d/%d 视角产出观察",
            len(results), len(perspectives),
        )
    return results


def _call_single(llm: Any, name: str, prompt: str, timeout: float) -> str | None:
    """单个视角的 LLM 调用。"""
    try:
        response = llm.chat([{"role": "user", "content": prompt}])
        if response and hasattr(response, "content"):
            text = (response.content or "").strip()
            if text:
                return text[:200]
    except Exception as e:
        logger.warning("[broaden] %s LLM 异常: %s", name, e)
    return None


# ── Phase 3: 综合 ────────────────────────────────────────────────────

_PHASE3_PROMPT = """以下是从不同视角对当前{target}的观察：

{observations}

请综合这些观察，给出对当前{target}的调整建议。2-3 条，具体可操作。
如果各视角都觉得没问题，回复"各视角无异议，继续执行"。直接给建议，不要客套。"""


def _synthesize(
    llm: Any, observations: list[str],
    target: str, context: str, pmm_context: str, timeout: float,
) -> str | None:
    """Phase 3: 综合各视角产出，给出调整建议。"""
    observations_text = "\n\n".join(observations)
    prompt = _PHASE3_PROMPT.format(target=target, observations=observations_text)

    try:
        response = llm.chat([{"role": "user", "content": prompt}])
        if response and hasattr(response, "content"):
            text = (response.content or "").strip()
            if text:
                return text[:500]
    except Exception as e:
        logger.warning("[broaden] Phase3 LLM 调用失败: %s", e)

    return None


# ── 主入口 ────────────────────────────────────────────────────────────

def broaden_perspective(
    target: str = "",
    stage: str = "",
    context: str = "",
    pmm_context: str = "",
    llm: Any = None,
    timeout: float = 30.0,
) -> str | None:
    """统一多视角审视。

    三阶段：元视角生成 → 并行审视 → 综合建议。
    代码决定断点位置，LLM 决定是否审视、要什么视角。

    Args:
        target: 审视对象（"当前计划""当前方法""单步产出""整体交付"）
        stage: 阶段标签 (understand/design/execute/review/retrospect)
        context: 当前上下文
        pmm_context: PMM 项目认知地图文本
        llm: LLM 客户端
        timeout: 单个视角 LLM 调用超时

    Returns:
        综合调整建议文本，或 None（跳过/失败）。
    """
    if not llm:
        return None

    stage_info = _STAGE_INFO.get(stage)
    if not stage_info:
        logger.warning("[broaden_perspective] 未知阶段: %s", stage)
        return None
    stage_name, stage_hint = stage_info

    # Phase 1: 元视角生成
    perspectives = _generate_perspectives(
        llm, target, stage_name, stage_hint, context, pmm_context, timeout,
    )
    if not perspectives:
        return None

    logger.info(
        "[broaden_perspective] stage=%s → %d 视角: %s",
        stage, len(perspectives), [p["name"] for p in perspectives],
    )

    # Phase 2: 并行审视
    observations = _parallel_review(
        llm, perspectives, target, context, pmm_context, timeout,
    )
    if not observations:
        return None

    # Phase 3: 综合
    result = _synthesize(llm, observations, target, context, pmm_context, timeout)
    if result:
        logger.info("[broaden_perspective] 综合完成: %s", result[:80])

    return result
