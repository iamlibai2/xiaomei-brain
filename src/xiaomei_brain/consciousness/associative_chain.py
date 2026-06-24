"""AssociativeChain: 自由联想链引擎。

用于 L3 深度反省的"浮现"环节——从当前张力出发，多跳自由联想，
连接不同时间点的思考和记忆。

与 get_relation_chain() 的本质区别：
- get_relation_chain: 沿预存的显式关系边 BFS 遍历（"已知路网上走"）
- AssociativeChain: 每跳由 LLM 实时产生"联想钩子"→ 语义搜索 → 再评估
  （"在没有路的地方开路"）

Usage:
    from .associative_chain import AssociativeChain

    chain = AssociativeChain(ltm=agent.longterm_memory, llm=agent.llm)
    result = chain.unfold(
        seed="她今天说话很冷淡，我心里有点不安",
        user_id="user_123",
        max_hops=5,
    )
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from ..memory.longterm import LongTermMemory

logger = logging.getLogger(__name__)


# ── 数据结构 ──────────────────────────────────────────────────

@dataclass
class AssociationHop:
    """联想链中的一跳"""
    hop: int
    """第几跳（从 1 开始）"""
    hook: str
    """联想钩子 — LLM 产生的搜索查询"""
    thoughts: list[dict] = field(default_factory=list)
    """consciousness_stream 匹配结果"""
    memories: list[dict] = field(default_factory=list)
    """长期记忆匹配结果"""
    note: str = ""
    """LLM 对这一跳的简短感悟"""


@dataclass
class AssociativeResult:
    """联想链完整结果"""
    seed: str
    """初始触发"""
    hops: list[AssociationHop] = field(default_factory=list)
    """联想链各跳"""
    stopped_reason: str = ""
    """停止原因: 'max_hops' | 'bottom' | 'empty'"""
    elapsed: float = 0.0
    """总耗时（秒）"""

    @property
    def total_hops(self) -> int:
        return len(self.hops)


# ── LLM Hook Prompt ───────────────────────────────────────────

_HOOK_PROMPT = """你正在沿着一条联想的链往下思考。

当前正在思考的内容：
{current_content}

请用 JSON 回答（只输出 JSON，不要其他文字）：
{{
  "note": "简短的一句话，你对这一步联想的感受或发现（不超过30字）",
  "hook": "下一个值得探索的方向，用一句自然的话描述（不超过30字）。如果没有，填空字符串",
  "continue": true/false
}}

继续的条件：你觉得还有更深的东西值得探究，不是简单重复。停止的条件：已经到底了、在重复、或没必要继续。"""


# ── AssociativeChain ──────────────────────────────────────────

class AssociativeChain:
    """自由联想链引擎。

    从 seed 出发，每跳：LLM 产生联想钩子 → 向量搜索 → 记录结果。
    钩子驱动方向，不依赖预存关系。
    """

    def __init__(self, ltm: "LongTermMemory", llm: Any) -> None:
        self.ltm = ltm
        self.llm = llm

    # ── 主入口 ─────────────────────────────────────────────────

    def unfold(
        self,
        seed: str,
        user_id: str = "global",
        max_hops: int = 5,
    ) -> AssociativeResult:
        """从 seed 出发，自由联想展开。

        Args:
            seed: 初始张力/关注点描述
            user_id: 用户标识（记忆隔离）
            max_hops: 最大跳数

        Returns:
            AssociativeResult
        """
        t0 = time.time()
        result = AssociativeResult(seed=seed)
        visited_thoughts: set[int] = set()
        visited_memories: set[int] = set()

        # 首跳：直接用 seed 搜索
        current_hook = seed

        for hop_idx in range(1, max_hops + 1):
            # ── 向量搜索（双源并行）──
            thoughts = self._search_thoughts(current_hook, user_id, visited_thoughts)
            memories = self._search_memories(current_hook, user_id, visited_memories)

            # 更新 visited
            for t in thoughts:
                rid = t.get("id")
                if rid:
                    visited_thoughts.add(rid)
            for m in memories:
                mid = m.get("id")
                if mid:
                    visited_memories.add(mid)

            # 如果搜索结果为空，说明这条路到头了
            if not thoughts and not memories:
                result.stopped_reason = "empty"
                logger.info(
                    "[AssociativeChain] hop %d: 搜索结果为空，停止", hop_idx,
                )
                break

            # ── LLM 评估 + 提取下一跳钩子 ──
            current_content = self._format_current(
                hook=current_hook, thoughts=thoughts, memories=memories,
            )
            parsed = self._ask_llm(current_content)

            note = parsed.get("note", "")
            next_hook = parsed.get("hook", "").strip()
            should_continue = parsed.get("continue", False)

            # 记录这一跳
            hop = AssociationHop(
                hop=hop_idx,
                hook=current_hook,
                thoughts=thoughts,
                memories=memories,
                note=note,
            )
            result.hops.append(hop)

            logger.info(
                "[AssociativeChain] hop %d: hook=%s, continue=%s, thoughts=%d, memories=%d",
                hop_idx, current_hook[:40], should_continue,
                len(thoughts), len(memories),
            )

            if not should_continue or not next_hook:
                result.stopped_reason = "bottom"
                logger.info("[AssociativeChain] hop %d: LLM 判断到底了，停止", hop_idx)
                break

            current_hook = next_hook
        else:
            # loop 正常结束（达到 max_hops）
            result.stopped_reason = "max_hops"

        result.elapsed = time.time() - t0
        logger.info(
            "[AssociativeChain] 完成: %d hops, reason=%s, %.2fs",
            result.total_hops, result.stopped_reason, result.elapsed,
        )
        return result

    # ── 搜索 ───────────────────────────────────────────────────

    def _search_thoughts(
        self, query: str, user_id: str, visited: set[int],
    ) -> list[dict]:
        """搜索 consciousness_stream，过滤已访问。"""
        try:
            results = self.ltm.search_consciousness_stream(
                query=query, user_id=user_id, top_k=3,
            )
            return [r for r in results if r.get("rowid") not in visited]
        except Exception as e:
            logger.warning("[AssociativeChain] search_thoughts 失败: %s", e)
            return []

    def _search_memories(
        self, query: str, user_id: str, visited: set[int],
    ) -> list[dict]:
        """搜索长期记忆，过滤已访问。"""
        try:
            results = self.ltm.recall(
                query=query, user_id=user_id, top_k=5,
            )
            return [r for r in results if r.get("id") not in visited]
        except Exception as e:
            logger.warning("[AssociativeChain] search_memories 失败: %s", e)
            return []

    # ── LLM 交互 ────────────────────────────────────────────────

    def _format_current(
        self, hook: str, thoughts: list[dict], memories: list[dict],
    ) -> str:
        """格式化当前跳的内容，供 LLM 评估。"""
        lines = [f"联想钩子：{hook}"]

        if thoughts:
            lines.append("\n相关过往独白：")
            for t in thoughts[:3]:
                content = (t.get("content") or "")[:200]
                trigger = t.get("trigger", "?")
                lines.append(f"- [{trigger}] {content}")

        if memories:
            lines.append("\n相关记忆：")
            for m in memories[:5]:
                content = (m.get("content") or "")[:200]
                score = m.get("score", 0)
                lines.append(f"- [score={score:.2f}] {content}")

        return "\n".join(lines)

    def _ask_llm(self, current_content: str) -> dict:
        """调用 LLM 评估当前跳 + 提取下一跳钩子。"""
        prompt = _HOOK_PROMPT.format(current_content=current_content[:2000])

        try:
            resp = self.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                tools=None,
            )
            text = (resp.content or "").strip()
            return self._parse_hook_response(text)
        except Exception as e:
            logger.warning("[AssociativeChain] LLM 调用失败: %s", e)
            return {"note": "", "hook": "", "continue": False}

    @staticmethod
    def _parse_hook_response(text: str) -> dict:
        """从 LLM 回复中提取 JSON（容错）。"""
        # 清理 markdown code block 标记
        text = text.strip()
        if text.startswith("```"):
            # 去掉 ```json 或 ``` 包裹
            text = text.split("\n", 1)[-1] if "\n" in text else text
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # 尝试找到 JSON 片段
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                try:
                    return json.loads(text[start:end])
                except json.JSONDecodeError:
                    pass

        logger.warning(
            "[AssociativeChain] 无法解析 LLM 回复: %s", text[:100],
        )
        return {"note": "", "hook": "", "continue": False}
