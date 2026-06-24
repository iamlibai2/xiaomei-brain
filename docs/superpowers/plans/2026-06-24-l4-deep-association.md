# L4 深度联想引擎 — 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 L4 深度联想引擎——五步闭环（触动→浮现→审视→整合→转化），让系统从"感知自己"升级到"理解自己"。

**Architecture:** 新建 `l4_engine.py` 封装五步流程，在 `core.py` 添加触发判断和执行入口，在 `layer2.py` DMN 循环中 L3 之后插入 L4 检查。L4 与 L3 同轮互斥（优先 L3），低频触发（4h 冷却，8h 兜底）。

**Tech Stack:** Python, AssociativeChain, Drive API, SelfModel (growth_events), consciousness_stream

---

### Task 1: 添加 L4 配置项

**Files:**
- Modify: `src/xiaomei_brain/consciousness/config.py:31-32`

- [ ] **Step 1: 在 ConsciousnessConfig 中添加 L4 配置**

```python
# 在 l3_cooldown 下面添加：
l4_cooldown: float = 14400.0       # L4 深度联想冷却（秒，默认 4 小时）
l4_timeout: float = 28800.0        # L4 定期兜底（秒，默认 8 小时）
l4_desire_threshold: float = 0.7   # 欲望张力阈值
l4_cortisol_threshold: float = 0.6 # 皮质醇张力阈值
```

- [ ] **Step 2: 验证语法**

Run: `PYTHONPATH=src python3 -c "from xiaomei_brain.consciousness.config import ConsciousnessConfig; c=ConsciousnessConfig(); print(c.l4_cooldown, c.l4_timeout)"`

Expected: `14400.0 28800.0`

- [ ] **Step 3: 提交**

```bash
git add src/xiaomei_brain/consciousness/config.py
git commit -m "feat: add L4 config (cooldown/timeout/tension thresholds)"
```

---

### Task 2: 创建 L4Engine

**Files:**
- Create: `src/xiaomei_brain/consciousness/l4_engine.py`

- [ ] **Step 1: 创建 l4_engine.py**

```python
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
        2. 最近 L2 意识涌现独白
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

        # 从 consciousness_stream 获取最近 L2 独白
        ltm = getattr(self._c.agent, "longterm_memory", None)
        if ltm:
            try:
                # 用简单的近因召回
                recent = ltm.get_narratives(limit=3)
                if recent:
                    # 取最近一条非 L4 的内容
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

    def _extract_insight(self, examination: str) -> str:
        """从审视报告中提取一句核心发现。"""
        if not examination:
            return ""
        # 取第一句作为摘要
        for sep in ("。", "\n", "！", "？"):
            if sep in examination:
                sentence = examination.split(sep)[0] + sep
                if len(sentence) <= 100:
                    return sentence
        return examination[:100]

    def _integrate(self, pattern_insight: str) -> None:
        """将核心发现写入 SelfModel.growth_events。"""
        if not pattern_insight:
            return
        si = self._c.self_image
        if si:
            now = datetime.now().strftime("%Y-%m-%d %H:%M")
            si.history.add_event(
                content=f"[L4 深度联想] {pattern_insight}",
                date=now,
            )
            logger.info("[L4Engine] 发现已记录到 growth_events")

    # ── Phase 5: 转化 ──────────────────────────────────────────

    def _extract_behavior_hint(self, examination: str) -> str:
        """从审视报告提取行为提示。"""
        if not examination:
            return ""
        # 简单提取：取最后一段或最后一句
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

        # 组装存储内容：种子 + 联想摘要 + 审视
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
```

- [ ] **Step 2: 验证语法**

Run: `PYTHONPATH=src python3 -c "from xiaomei_brain.consciousness.l4_engine import L4Engine, L4Report; print('OK')"`

Expected: `OK`

- [ ] **Step 3: 提交**

```bash
git add src/xiaomei_brain/consciousness/l4_engine.py
git commit -m "feat: add L4Engine with five-phase deep association cycle"
```

---

### Task 3: 在 core.py 添加 L4 触发和执行

**Files:**
- Modify: `src/xiaomei_brain/consciousness/core.py`

- [ ] **Step 1: 在 import 区域添加 L4Engine 导入**

在 `from .l3_engine import L3Engine` 下方添加：
```python
from .l4_engine import L4Engine
```

- [ ] **Step 2: 在 __init__ 中添加 L4 初始化变量**

在 `self._l3_engine: L3Engine | None = None` 下方添加：
```python
self._l4_engine: L4Engine | None = None
self._last_l4_time: float = time.time()      # 启动后等冷却才触发 L4
```

- [ ] **Step 3: 在 L3 方法区域后面添加 L4 方法**

在 `_get_l3_engine()` 方法之后添加：
```python
    # ── L4: 深度联想（低频，多次 LLM 调用） ───────────────────────

    def tick_L4(self) -> "L4Report":
        """L4 深度联想 → 委托给 L4Engine。"""
        if self._l4_engine is None:
            self._l4_engine = L4Engine(self)
        report = self._l4_engine.run()
        return report

    def _should_l4(self, agent_state: str = "awake") -> bool:
        """判断是否应该触发 L4 深度联想。

        条件：冷却 + 足够能量 + 有素材。
        与 L3 互斥：同一轮 L3 触发后 L4 不再触发（由 layer2 保证）。
        """
        # SLEEPING/DREAMING/WORKING 中不做深度联想（成本高）
        if agent_state in ("sleeping", "dreaming", "working"):
            return False

        # 能量不足
        energy = self.self_image.body.energy
        if energy < 0.3:
            return False

        # 冷却检查
        elapsed_since_last = time.time() - self._last_l4_time
        if elapsed_since_last < self._cc.l4_cooldown:
            return False

        # 有张力素材
        if self._has_l4_tension():
            return True

        # 时间兜底
        if elapsed_since_last >= self._cc.l4_timeout:
            return True

        return False

    def _has_l4_tension(self) -> bool:
        """检查是否有足够的张力驱动 L4。"""
        drive = self.drive
        if not drive:
            return False

        # 欲望超阈值
        for d in [
            drive.desire.belonging,
            drive.desire.cognition,
            drive.desire.achievement,
            drive.desire.expression,
        ]:
            if d > self._cc.l4_desire_threshold:
                return True

        # 皮质醇偏高
        if drive.hormone.cortisol > self._cc.l4_cortisol_threshold:
            return True

        return False
```

- [ ] **Step 4: 验证语法**

Run: `PYTHONPATH=src python3 -c "from xiaomei_brain.consciousness.core import Consciousness; print('OK')"`

Expected: `OK`

- [ ] **Step 5: 提交**

```bash
git add src/xiaomei_brain/consciousness/core.py
git commit -m "feat: add L4 trigger (_should_l4) and execution (tick_L4) to Consciousness"
```

---

### Task 4: 在 layer2.py DMN 循环中接入 L4

**Files:**
- Modify: `src/xiaomei_brain/consciousness/layer2.py:189-199`

- [ ] **Step 1: 在 L3 执行块之后添加 L4 检查**

在 L3 的 try/except 块结束后（`self._log(f"{ts} L3 tick_L3 ERROR: {e}")` 行之后），DREAM 检查之前，添加：

```python
                    # L4: 深度联想（L3 同轮互斥：L3 触发了就跳过 L4）
                    if not skip_l3 and not l3_triggered and self._c._should_l4(agent_state):
                        self._log(f"{ts} L4 触发 [深度联想] agent_state={agent_state} → tick_L4")
                        logger.info("[Layer2] L4 触发（深度联想，agent_state=%s）", agent_state)
                        self._c._last_l4_time = time.time()
                        try:
                            self._c.tick_L4()
                            self._log(f"{ts} L4 tick_L4 完成")
                        except Exception as e:
                            self._log(f"{ts} L4 tick_L4 ERROR: {e}")
                            logger.warning("[Layer2] tick_L4 出错: %s", e)
```

需要先提取 L3_triggered 标志。修改 L3 块：

在 L3 的 if 块内部，添加 `l3_triggered = True`：
```python
                    # L3: 沉思
                    l3_triggered = False
                    if not skip_l3 and self._c._should_l3(agent_state):
                        l3_triggered = True
                        self._log(...)
                        ...
```

或者更简单的方式：在处理 L3 的 try 前面记录：

将第190行改为：
```python
                    # L3: 沉思（sleep guard 在 _should_l3() 内，同轮 L2=SLEEP 也跳过）
                    l3_triggered = False
                    if not skip_l3 and self._c._should_l3(agent_state):
                        l3_triggered = True
                        self._log(f"{ts} L3 触发 [沉思] agent_state={agent_state} → tick_L3")
```

- [ ] **Step 2: 验证语法**

Run: `PYTHONPATH=src python3 -c "from xiaomei_brain.consciousness.layer2 import Layer2; print('OK')"`

Expected: `OK`

- [ ] **Step 3: 提交**

```bash
git add src/xiaomei_brain/consciousness/layer2.py
git commit -m "feat: wire L4 into DMN loop (after L3, mutual exclusion)"
```

---

### Task 5: 手动触发测试

**Files:**
- Create: `examples/test_l4.py`

- [ ] **Step 1: 创建测试脚本**

```python
"""测试 L4 深度联想引擎 — 手动触发。

Usage:
    PYTHONPATH=src python examples/test_l4.py
"""

import logging
import os
import sys
import warnings

os.environ["HF_HUB_OFFLINE"] = "1"

warnings.filterwarnings("ignore")
for _name in ["sentence_transformers", "transformers", "httpx", "httpcore",
              "filelock", "huggingface_hub", "urllib3", "torch"]:
    logging.getLogger(_name).setLevel(logging.ERROR)

from xiaomei_brain import AgentManager
from xiaomei_brain.consciousness.l4_engine import L4Engine


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(name)s - %(levelname)s - %(message)s",
    )

    base_dir = os.path.expanduser("~/.xiaomei-brain")
    manager = AgentManager(base_dir=base_dir)

    agent_id = "itboy"
    agent = manager.build_agent(agent_id)
    if agent is None:
        agent_id = "xiaomei"
        agent = manager.build_agent(agent_id)

    if agent is None:
        print("没有找到可用的 agent")
        sys.exit(1)

    # 检查是否有 consciousness
    if not hasattr(agent, "consciousness") or agent.consciousness is None:
        print("Agent 没有 consciousness，请使用 ConsciousLiving 模式")
        sys.exit(1)

    c = agent.consciousness
    engine = L4Engine(c)

    print(f"Agent: {agent_id}")
    print(f"Drive: {'有' if c.drive else '无'}")
    if c.drive:
        print(f"  归属欲: {c.drive.desire.belonging:.2f}")
        print(f"  认知欲: {c.drive.desire.cognition:.2f}")
        print(f"  皮质醇: {c.drive.hormone.cortisol:.2f}")
    print()

    # 检查是否能生成种子
    seed = engine._generate_seed()
    print(f"种子: {seed[:100] if seed else '(无)'}")
    print()

    if not seed:
        print("没有种子，跳过 L4")
        return

    # 运行完整 L4
    print("=" * 60)
    print("运行 L4 深度联想...")
    print("=" * 60)
    print()

    report = engine.run()

    print()
    print("=" * 60)
    print(f"L4 完成: {report.elapsed:.2f}s")
    if report.skipped:
        print(f"跳过: {report.reason}")
    else:
        print(f"联想跳数: {report.chain.total_hops if report.chain else 0}")
        print(f"核心发现: {report.pattern_insight}")
        print(f"行为提示: {report.behavior_hint}")
    print("=" * 60)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 运行测试**

Run: `PYTHONPATH=src python examples/test_l4.py`

Expected: 能看到种子生成和 L4 执行流程（成败取决于是否有 Drive 和 consciousness 数据）

- [ ] **Step 3: 提交**

```bash
git add examples/test_l4.py
git commit -m "test: add L4 engine manual trigger test"
```
