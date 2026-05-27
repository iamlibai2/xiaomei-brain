"""PerspectiveEngine: 多视角并行 LLM 调用，突破单执行者视角僵化。

触发时机：PACE 子目标执行卡住时（InnerVoice "方向不对" 或重试 ≥ 1 次）。
每个视角用极简上下文（只有子目标描述，不加载失败历史），产出方向感。

Usage:
    engine = PerspectiveEngine()
    direction = engine.run(llm, goal_description)
    # direction 作为执行者 context 前缀注入
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

logger = logging.getLogger(__name__)

# ── 视角定义 ──────────────────────────────────────────────

DEFAULT_PERSPECTIVES: list[dict[str, str]] = [
    {
        "name": "架构师",
        "prompt": (
            "你是一位资深系统架构师。执行者在做一个子目标时卡住了。"
            "从架构的层面看——和整体设计一致吗？有没有设计层面的问题被忽略了？"
            "不用给方案，给1-2句直觉式的方向感。"
        ),
    },
    {
        "name": "极简主义",
        "prompt": (
            "你的信条是'最简单的方案往往是对的'。执行者在一个子目标上反复尝试但做不成。"
            "有没有更简单的做法？甚至——这一步真的必须做吗？"
            "不用给方案，给1-2句直觉式的方向感。"
        ),
    },
    {
        "name": "用户",
        "prompt": (
            "你从这个软件的使用者角度看问题。执行者卡在某个子目标上。"
            "从使用者的角度——他们真正关心的是什么？当前的做法是在解决真实问题，"
            "还是在解决技术本身？不用给方案，给1-2句直觉式的方向感。"
        ),
    },
    {
        "name": "反面",
        "prompt": (
            "你的任务是找漏洞。执行者卡在了一个子目标上。"
            "当前方案最可能出问题的地方在哪？最坏情况下会怎样？"
            "不用给方案，给1-2句直觉式的方向感。"
        ),
    },
]


class PerspectiveEngine:
    """多视角并行调用引擎。

    用 ThreadPoolExecutor 并行调用 LLM，每个视角极简上下文。
    聚合结果作为"方向感"注入执行者 context。
    """

    def __init__(self, perspectives: list[dict[str, str]] | None = None) -> None:
        self._perspectives = perspectives or DEFAULT_PERSPECTIVES
        self._timeout: float = 30.0

    def run(self, llm: Any, goal_description: str) -> str:
        """并行调用所有视角，返回聚合的方向感文本。

        Args:
            llm: LLM 客户端（需要 chat(messages) -> response.content 接口）
            goal_description: 当前子目标描述

        Returns:
            聚合的方向感文本。如果所有视角失败返回空字符串。
        """
        results: list[str] = []

        with ThreadPoolExecutor(max_workers=len(self._perspectives)) as executor:
            futures = {
                executor.submit(
                    self._call_perspective, llm, p["name"], p["prompt"], goal_description,
                ): p["name"]
                for p in self._perspectives
            }

            for future in as_completed(futures, timeout=self._timeout):
                name = futures[future]
                try:
                    result = future.result(timeout=self._timeout)
                    if result:
                        results.append(f"【{name}视角】{result}")
                except Exception as e:
                    logger.warning("[PerspectiveEngine] 视角 %s 调用失败: %s", name, e)

        if not results:
            return ""

        logger.info(
            "[PerspectiveEngine] %d/%d 视角成功产出方向感",
            len(results), len(self._perspectives),
        )
        return "\n\n".join(results)

    @staticmethod
    def _call_perspective(
        llm: Any, name: str, system_prompt: str, goal_description: str,
    ) -> str | None:
        """单个视角的 LLM 调用。"""
        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": (
                    f"当前子目标：{goal_description[:300]}\n\n"
                    "执行者卡住了。从你的视角看，问题可能出在哪？不用给方案，给1-2句直觉。"
                ),
            },
        ]

        try:
            response = llm.chat(messages)
            if response and hasattr(response, "content"):
                text = (response.content or "").strip()
                if text:
                    # 截断，只要方向感
                    return text[:200]
        except Exception as e:
            logger.warning("[PerspectiveEngine] %s LLM 调用异常: %s", name, e)

        return None
