"""L4Engine: 深度联想引擎 — 五步闭环：触动→浮现→审视→整合→转化。

与 L3 的本质区别：
- L3: 单次 LLM 调用，聚焦当前，高频触发（~30min）
- L4: 多次 LLM 调用，穿越时间，低频触发（~4-8h）

五步闭环：
  1. 触动 — 张力识别，生成种子
  2. 浮现 — AssociativeChain.unfold() 自由联想
  3. 审视 — LLM 多角度审视联想链
  4. 整合 — 发现沉淀到 SelfModel (growth_events)
  5. 转化 — 写入 consciousness_stream，供未来联想触及
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from .core import Consciousness
    from .associative_chain import AssociativeResult

logger = logging.getLogger(__name__)


# ── 审视 Prompt ───────────────────────────────────────────────

_EXAMINE_PROMPT = """你刚经历了一次自由联想，以下是你的联想链：

{chain_text}

请从以下角度审视这条联想链：

1. **模式识别**：这里反复出现的模式是什么？有什么被忽略的共性？
2. **根因探究**：这个模式可能从哪来？和我的经历、性格有什么关联？
3. **连接整合**：现在的我和过去的我在这一点上有什么联系或变化？
4. **可能性**：如果继续这样会怎样？有什么改变的方向？

请用第一人称自由表达你的审视。不需要格式，像在深夜独自面对内心一样。"""


# ── L4Report ──────────────────────────────────────────────────

@dataclass
class L4Report:
    """L4 深度联想产出"""
    seed: str = ""
    """触发种子"""
    chain: Any = None
    """AssociativeResult — 完整联想链"""
    examination: str = ""
    """Phase 3 审视报告全文"""
    pattern_insight: str = ""
    """核心模式发现（一行）"""
    behavior_hint: str = ""
    """可供未来参考的行为提示"""
    skipped: bool = False
    """是否跳过（无张力/无素材）"""
    reason: str = ""
    """跳过原因"""
    elapsed: float = 0.0
    """总耗时"""


# ── L4Engine ──────────────────────────────────────────────────

class L4Engine:
    """L4 深度联想引擎。

    从当前张力出发 → 自由联想展开 → 多角度审视 → 整合进自我认知。
    """

    def __init__(self, consciousness: Consciousness) -> None:
        self._c = consciousness

    # ── 主入口 ─────────────────────────────────────────────────

    def run(self) -> L4Report:
        """执行完整的 L4 五步闭环。"""
        t0 = time.time()

        # Phase 1: 触动 — 生成种子
        seed = self._generate_seed()
        if not seed:
            logger.info("[L4Engine] 无张力/无素材，跳过")
            return L4Report(skipped=True, reason="no_tension", elapsed=time.time() - t0)

        # Phase 2: 浮现 — 自由联想链
        chain = self._unfold(seed)
        if not chain or chain.total_hops == 0:
            logger.info("[L4Engine] 联想链未能展开")
            return L4Report(
                seed=seed, chain=chain,
                skipped=True, reason="no_hops",
                elapsed=time.time() - t0,
            )

        # Phase 3: 审视 — 多角度审视联想链
        examination = self._examine(chain)

        # Phase 4: 整合 — 沉淀到 SelfModel
        pattern_insight = self._extract_insight(examination)
        self._integrate(pattern_insight)

        # Phase 5: 转化 — 写入 consciousness_stream
        behavior_hint = self._extract_behavior_hint(examination)
        self._store(seed, examination, chain)

        report = L4Report(
            seed=seed,
            chain=chain,
            examination=examination,
            pattern_insight=pattern_insight,
            behavior_hint=behavior_hint,
            elapsed=time.time() - t0,
        )

        logger.info(
            "[L4Engine] 完成: %d hops, 审视 %d 字, %.2fs",
            chain.total_hops, len(examination), report.elapsed,
        )
        return report

    # ── Phase 1: 触动 ──────────────────────────────────────────

    def _generate_seed(self) -> str:
        """从 Drive 张力或最近 L2 独白生成种子。

        优先级：
        1. 最高张力点（欲望 > 0.7 或 皮质醇 > 0.6）
        2. 最近 consciousness_stream 独白
        3. 空（跳过 L4）
        """
        # 检查 Drive 张力
        drive = self._c.drive
        if drive:
            tensions = []

            # 欲望检查
            desire_map = [
                ("归属欲", drive.desire.belonging),
                ("认知欲", drive.desire.cognition),
                ("成就欲", drive.desire.achievement),
                ("表达欲", drive.desire.expression),
            ]
            for name, value in desire_map:
                if value > 0.7:
                    tensions.append((name, value, "desire"))

            # 皮质醇检查
            cortisol = drive.hormone.cortisol
            if cortisol > 0.6:
                tensions.append(("皮质醇偏高", cortisol, "cortisol"))

            if tensions:
                # 取最高张力
                tensions.sort(key=lambda x: x[1], reverse=True)
                name, value, kind = tensions[0]

                if kind == "desire":
                    return (
                        f"{name}已经持续在高位一段时间了。"
                        f"我能感受到一种隐隐的张力——好像有什么未被满足的东西在催促我。"
                    )
                else:
                    return (
                        f"皮质醇水平偏高，身体有种紧绷感。"
                        f"也许有什么事情在让我不安，只是我还没意识到。"
                    )

        # 从 consciousness_stream 获取最近独白
        ltm = getattr(self._c.agent, "longterm_memory", None)
        if ltm:
            try:
                recent = ltm.get_narratives(limit=3)
                if recent:
                    for r in recent:
                        content = r.get("content", "")
                        trigger = r.get("trigger", "")
                        if content and trigger != "L4_deep":
                            return content[:300]
            except Exception as e:
                logger.warning("[L4Engine] 获取最近独白失败: %s", e)

        return ""

    # ── Phase 2: 浮现 ──────────────────────────────────────────

    def _unfold(self, seed: str) -> "AssociativeResult | None":
        """调用 AssociativeChain 展开自由联想。"""
        ltm = getattr(self._c.agent, "longterm_memory", None)
        llm = getattr(self._c.agent, "llm", None)
        if not ltm or not llm:
            logger.warning("[L4Engine] 缺少 ltm 或 llm，跳过联想")
            return None

        user_id = getattr(self._c.agent, "user_id", "global")

        try:
            from .associative_chain import AssociativeChain

            chain_engine = AssociativeChain(ltm=ltm, llm=llm)
            result = chain_engine.unfold(seed=seed, user_id=user_id, max_hops=5)

            # 终端展示
            if result.total_hops > 0:
                from .internal_display import print_section
                print_section("L4 深度联想", icon="🔮")
                for hop in result.hops:
                    print(f"  跳 {hop.hop}: {hop.hook[:60]} → {hop.note}")

            return result
        except Exception as e:
            logger.warning("[L4Engine] AssociativeChain 失败: %s", e)
            return None

    # ── Phase 3: 审视 ──────────────────────────────────────────

    def _examine(self, chain: "AssociativeResult") -> str:
        """LLM 多角度审视完整联想链。"""
        # 格式化联想链
        chain_lines = [f"种子：{chain.seed}\n"]
        for hop in chain.hops:
            chain_lines.append(f"## 第 {hop.hop} 跳")
            chain_lines.append(f"钩子：{hop.hook}")
            chain_lines.append(f"感悟：{hop.note}")
            if hop.thoughts:
                chain_lines.append("相关独白：")
                for t in hop.thoughts[:2]:
                    chain_lines.append(f"  - {t.get('content', '')[:150]}")
            if hop.memories:
                chain_lines.append("相关记忆：")
                for m in hop.memories[:2]:
                    chain_lines.append(f"  - {m.get('content', '')[:150]}")
            chain_lines.append("")

        chain_text = "\n".join(chain_lines)
        prompt = _EXAMINE_PROMPT.format(chain_text=chain_text[:3000])

        # 构建 system prompt（与 L3 同一格式）
        from .context_pipeline import build_simple_context
        system_prompt = build_simple_context(self._c, mode="internal")

        llm = getattr(self._c.agent, "llm", None)
        if not llm:
            return ""

        try:
            resp = llm.chat(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                tools=None,
            )
            content = resp.content or ""
            logger.debug("[L4Engine] 审视完成 (%d 字)", len(content))

            # 终端展示
            if content:
                from .internal_display import print_markdown
                print_markdown(content, style="color(144)")

            if self._c.drive:
                self._c.drive.consume_energy(0.15)
                self._c.drive.restore_energy(0.2)

            return content
        except Exception as e:
            logger.warning("[L4Engine] LLM 审视失败: %s", e)
            return ""

    # ── Phase 4: 整合 ──────────────────────────────────────────

    @staticmethod
    def _extract_insight(examination: str) -> str:
        """从审视报告中提取一句核心发现。"""
        if not examination:
            return ""
        for sep in ("。", "\n", "！", "？"):
            if sep in examination:
                sentence = examination.split(sep)[0] + sep
                if len(sentence) <= 100:
                    return sentence
        return examination[:100]

    def _integrate(self, pattern_insight: str) -> None:
        """将核心发现写入 SelfModel.growth_events 和 self_cognition。"""
        if not pattern_insight:
            return
        si = self._c.self_image
        if si:
            now = datetime.now().strftime("%Y-%m-%d %H:%M")
            si.history.add_event(
                content=f"[L4 深度联想] {pattern_insight}",
                date=now,
            )
            # 写入 self_cognition（深层模式），供自我认知渲染
            if "深层模式" not in si.mind.self_cognition:
                si.mind.self_cognition["深层模式"] = []
            si.mind.self_cognition["深层模式"].append(
                f"[{now}] {pattern_insight}"
            )
            # 保留最近 10 条
            if len(si.mind.self_cognition["深层模式"]) > 10:
                si.mind.self_cognition["深层模式"] = \
                    si.mind.self_cognition["深层模式"][-10:]
            logger.info("[L4Engine] 发现已记录到 growth_events + self_cognition")

    # ── Phase 5: 转化 ──────────────────────────────────────────

    @staticmethod
    def _extract_behavior_hint(examination: str) -> str:
        """从审视报告提取行为提示。"""
        if not examination:
            return ""
        lines = examination.strip().split("\n")
        for line in reversed(lines):
            line = line.strip()
            if line and len(line) > 10 and len(line) < 200:
                return line
        return ""

    def _store(self, seed: str, examination: str,
               chain: "AssociativeResult") -> None:
        """写入 consciousness_stream（trigger='L4_deep'）。"""
        if not examination:
            return

        hop_summary = " → ".join(
            f"{h.hook[:40]}" for h in chain.hops
        ) if chain and chain.hops else "无联想"

        content = (
            f"种子：{seed[:100]}\n"
            f"联想链：{hop_summary}\n"
            f"审视：{examination[:400]}"
        )

        c = self._c
        if c.agent and hasattr(c.agent, "longterm_memory") and c.agent.longterm_memory:
            c.agent.longterm_memory.store_narrative(
                content=content[:500],
                trigger="L4_deep",
                energy_level=c.body.energy if c.self_image else None,
                user_idle_duration=c.perception.user_idle_duration if c.self_image else None,
                user_id=getattr(c.agent, "user_id", "global"),
            )

        # 经验流
        es = getattr(c.agent, "exp_stream", None)
        if es:
            try:
                es.log(
                    type="l4_deep_association",
                    content=f"L4 深度联想: {seed[:80]} → {chain.total_hops if chain else 0}跳",
                    importance=0.8,
                )
            except Exception as e:
                logger.debug("[L4Engine ExpStream] write failed: %s", e)
