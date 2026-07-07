# Perspective Switching + InnerVoice Loop Phase 1

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When PACE execution gets stuck on a sub-goal, trigger parallel multi-perspective LLM calls to get fresh angles, then retry with clean context instead of mechanically retrying or exiting.

**Architecture:** New `perspectives.py` module for multi-perspective parallel LLM calls. Runner modified to detect InnerVoice "retry" signal + retry count ≥ 1, trigger perspective breakthrough, clear observations, and retry with fresh context. InnerVoice signal already exists (`_extract_continue_signal`), just needs to be wired.

**Tech Stack:** Python stdlib `concurrent.futures.ThreadPoolExecutor`, existing `llm.chat()` interface, existing `_extract_continue_signal()` regex

---

## File Map

| File | Role |
|------|------|
| `src/xiaomei_brain/metacognition/perspectives.py` | [NEW] Multi-perspective engine — config + parallel LLM calls + aggregation |
| `src/xiaomei_brain/metacognition/runner.py` | [MODIFY] Trigger detection, breakthrough call, context reset, retry state |
| `src/xiaomei_brain/metacognition/inner_voice.py` | No changes — `_extract_continue_signal()` and `get_last_thought()` already exist |
| `src/xiaomei_brain/consciousness/task_orchestrator.py` | No changes — `inner_voice` already passed to `PACERunner` |

---

### Task 1: Create `perspectives.py` — multi-perspective engine

**Files:**
- Create: `src/xiaomei_brain/metacognition/perspectives.py`

- [ ] **Step 1: Write the module**

```python
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
```

- [ ] **Step 2: Verify the module imports cleanly**

```bash
cd /home/iamlibai/workspace/claude-project/xiaomei-brain && source /home/iamlibai/workspace/python_env_common/bin/activate && PYTHONPATH=src python3 -c "from xiaomei_brain.metacognition.perspectives import PerspectiveEngine, DEFAULT_PERSPECTIVES; print(f'OK: {len(DEFAULT_PERSPECTIVES)} perspectives')"
```

Expected: `OK: 4 perspectives`

- [ ] **Step 3: Commit**

```bash
git add src/xiaomei_brain/metacognition/perspectives.py
git commit -m "$(cat <<'EOF'
feat: add PerspectiveEngine — multi-perspective parallel LLM calls

4 perspectives (architect, minimalist, user, devil's advocate) run in
parallel via ThreadPoolExecutor. Each gets minimal context (only goal
description, no failure history). Aggregated output as "direction sense"
for executor context injection.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Wire perspective breakthrough into PACE `_run_loop`

**Files:**
- Modify: `src/xiaomei_brain/metacognition/runner.py`

- [ ] **Step 1: Add imports and state flags to `__init__`**

In `runner.py`, add the import at the top (near the other imports):

```python
from .perspectives import PerspectiveEngine
```

In `PACERunner.__init__()`, add state flags after the existing state setup (after line 73):

```python
        # 视角切换状态
        self._perspective_engine: PerspectiveEngine | None = None
        self._perspective_tried: bool = False
```

And in `_reset_run_state()` (around line 1304), add reset for the new flag:

```python
    def _reset_run_state(self) -> None:
        """清理单次运行的临时状态"""
        self._resume_step = None
        self._resume_nudge = ""
        self._skip_post_review = False
        self._exit_reason = self.EXIT_COMPLETED
        self._perspective_tried = False  # 新增
```

- [ ] **Step 2: Add helper methods**

After `_invoke_inner_voice_task_step()`, add two new methods:

```python
    def _check_iv_retry_signal(self) -> bool:
        """检查 InnerVoice 最近一次反省是否包含 'retry' 信号。"""
        if not self._inner_voice:
            return False
        try:
            thought = self._inner_voice.get_last_thought()
            if not thought:
                return False
            from .inner_voice import _extract_continue_signal
            __, reason = _extract_continue_signal(thought)
            return reason == "retry"
        except Exception:
            return False

    def _trigger_perspective_breakthrough(self, goal_description: str) -> str:
        """触发视角切换突破。

        Returns:
            聚合的方向感文本。空字符串表示突破失败。
        """
        try:
            agent = self._agent_provider._get_agent()
            llm = agent.llm
        except Exception:
            logger.warning("[PACERunner] 无法获取 LLM 实例，跳过视角切换")
            return ""

        if self._perspective_engine is None:
            self._perspective_engine = PerspectiveEngine()

        logger.info(
            "[PACERunner] 触发视角切换突破: goal='%s'",
            goal_description[:60],
        )
        direction = self._perspective_engine.run(llm, goal_description)

        if direction:
            print(f"\n[视角切换] 获得突破方向:\n{direction}", flush=True)
        else:
            print(f"\n[视角切换] 所有视角均未产出有效方向", flush=True)

        return direction
```

- [ ] **Step 3: Modify the RETRY_DIFFERENT / SIMPLIFY branch**

In `_run_loop()`, replace the existing RETRY_DIFFERENT / SIMPLIFY branch (lines 470-475):

Old code:
```python
            # RETRY_DIFFERENT / SIMPLIFY: 不退出，不推进子目标，重试当前步骤
            if check.suggestion in (MetaSuggestion.RETRY_DIFFERENT, MetaSuggestion.SIMPLIFY):
                current_goal_retries += 1
                logger.info("[PACERunner] %s: %s (retry %d/%d)", check.suggestion.value, check.reasoning, current_goal_retries, max_retries_per_goal)
                step_index += 1
                continue
```

New code:
```python
            # RETRY_DIFFERENT / SIMPLIFY: 不退出，不推进子目标，重试当前步骤
            if check.suggestion in (MetaSuggestion.RETRY_DIFFERENT, MetaSuggestion.SIMPLIFY):
                iv_retry = self._check_iv_retry_signal()

                # 视角切换突破条件：
                # 1. InnerVoice 检测到 "方向不对" → 立即触发
                # 2. 已重试 ≥ 1 次 → 保底触发
                # 3. 本子目标尚未触发过视角切换
                should_breakthrough = (
                    (iv_retry or current_goal_retries >= 1)
                    and not self._perspective_tried
                )

                if should_breakthrough:
                    goal_desc = self._current_goal_desc()
                    direction = self._trigger_perspective_breakthrough(goal_desc)
                    self._perspective_tried = True

                    if direction:
                        # 清空 observations + 注入方向感
                        self._observations = []
                        if current_context:
                            current_context = direction + "\n\n" + current_context
                        else:
                            current_context = direction
                        current_goal_retries = 0
                        logger.info(
                            "[PACERunner] 视角切换 → 清空上下文，重新执行 (iv_retry=%s, retries=%d)",
                            iv_retry, current_goal_retries,
                        )
                        step_index += 1
                        continue
                    # 方向感生成失败 → 走正常重试

                current_goal_retries += 1
                logger.info("[PACERunner] %s: %s (retry %d/%d)", check.suggestion.value, check.reasoning, current_goal_retries, max_retries_per_goal)
                step_index += 1
                continue
```

- [ ] **Step 4: Reset `_perspective_tried` on sub-goal advance**

When advancing to a new sub-goal, `_perspective_tried` must be reset. Find all places where `current_goal_retries = 0` is set on sub-goal advance and add `self._perspective_tried = False` after each occurrence.

The locations are:

1. After `REPORT_PARTIAL / CLARIFY` auto-advance (around line 443):
```python
                    step_index += 1
                    current_goal_retries = 0  # 推进到新子目标，重置重试计数
                    self._perspective_tried = False  # 新增
```

2. When advancing via `_maybe_auto_advance` after CONTINUE (around line 497):
```python
            step_index += 1
            current_goal_retries = 0  # 推进到新子目标，重置重试计数
            self._perspective_tried = False  # 新增
```

3. When `_try_advance_to_next` auto-advances (around line 443, same location as #1 — already covered).

- [ ] **Step 5: Verify the module imports cleanly**

```bash
cd /home/iamlibai/workspace/claude-project/xiaomei-brain && source /home/iamlibai/workspace/python_env_common/bin/activate && PYTHONPATH=src python3 -c "from xiaomei_brain.metacognition.runner import PACERunner; print('OK')"
```

Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add src/xiaomei_brain/metacognition/runner.py
git commit -m "$(cat <<'EOF'
feat: wire perspective breakthrough into PACE retry path

When RETRY_DIFFERENT/SIMPLIFY is triggered:
- InnerVoice "retry" signal OR retry_count >= 1 → perspective breakthrough
- Clears observations, injects direction sense into context, resets retries
- Falls through to normal retry if breakthrough fails or already tried
- Perspective state resets on sub-goal advance

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Integration test — verify end-to-end flow

**Files:**
- Create: `examples/test_perspective_breakthrough.py`

- [ ] **Step 1: Write integration test script**

```python
"""测试视角切换突破 — 端到端验证。

模拟 PACE 在执行子目标时的视角切换流程：
1. PerspectiveEngine.run() 并行调用多视角
2. 聚合方向感文本
3. 注入 context 继续执行
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from xiaomei_brain.metacognition.perspectives import (
    PerspectiveEngine, DEFAULT_PERSPECTIVES,
)
from xiaomei_brain.metacognition.inner_voice import _extract_continue_signal


def test_perspectives_config():
    """验证视角配置正确。"""
    assert len(DEFAULT_PERSPECTIVES) >= 3, f"视角数量不足: {len(DEFAULT_PERSPECTIVES)}"
    for p in DEFAULT_PERSPECTIVES:
        assert "name" in p, f"视角缺 name: {p}"
        assert "prompt" in p, f"视角 {p['name']} 缺 prompt"
        assert len(p["prompt"]) > 50, f"视角 {p['name']} prompt 太短"
    print(f"[OK] {len(DEFAULT_PERSPECTIVES)} 个视角配置正确")


def test_extract_continue_signal_retry():
    """验证 InnerVoice '方向不对' → 'retry' 信号提取。"""
    # 模拟 InnerVoice 产出的各种"方向不对"表达
    cases = [
        ("方向不对，感觉在绕圈子", "retry"),
        ("换个方法试试看吧", "retry"),
        ("换个思路可能更好", "retry"),
        ("这个角度不对", "retry"),
        ("换个角度重新想", "retry"),
        ("需要简化一下", "retry"),
        ("一切正常，继续", "continue"),
        ("放弃吧，做不了", "escalate"),
        ("需要确认一下用户意图", "waiting_user"),
    ]
    for thought, expected in cases:
        __, reason = _extract_continue_signal(thought)
        assert reason == expected, f"「{thought}」→ {reason}，期望 {expected}"
    print(f"[OK] {len(cases)} 个信号提取用例全部通过")


def test_engine_creation():
    """验证 PerspectiveEngine 创建和默认配置。"""
    engine = PerspectiveEngine()
    assert engine._perspectives == DEFAULT_PERSPECTIVES
    assert engine._timeout == 30.0

    # 自定义视角
    custom = [{"name": "测试", "prompt": "你是一个测试视角。"}]
    engine2 = PerspectiveEngine(perspectives=custom)
    assert engine2._perspectives == custom
    print("[OK] PerspectiveEngine 创建正常")


def test_call_perspective_static():
    """验证 _call_perspective 静态方法的消息构建逻辑（不调 LLM）。

    创建一个 mock LLM 验证消息格式正确。
    """
    class MockLLM:
        def chat(self, messages):
            # 验证消息结构
            assert len(messages) == 2
            assert messages[0]["role"] == "system"
            assert messages[1]["role"] == "user"
            assert "测试子目标" in messages[1]["content"]
            # 返回格式正确的响应
            class Resp:
                content = "从测试视角看，问题可能在于假设本身。"
            return Resp()

    result = PerspectiveEngine._call_perspective(
        MockLLM(), "测试", "你是测试视角。", "测试子目标：验证消息结构",
    )
    assert result == "从测试视角看，问题可能在于假设本身。"
    print("[OK] _call_perspective 消息构建正确")


def test_empty_result_handling():
    """验证所有视角失败时的空结果处理。"""
    engine = PerspectiveEngine()
    assert engine.run(None, "test") == ""
    print("[OK] 空结果处理正确")


if __name__ == "__main__":
    test_perspectives_config()
    test_extract_continue_signal_retry()
    test_engine_creation()
    test_call_perspective_static()
    test_empty_result_handling()
    print("\n=== 全部测试通过 ===")
```

- [ ] **Step 2: Run the test**

```bash
cd /home/iamlibai/workspace/claude-project/xiaomei-brain && source /home/iamlibai/workspace/python_env_common/bin/activate && PYTHONPATH=src python3 examples/test_perspective_breakthrough.py
```

Expected: All 5 tests pass with `=== 全部测试通过 ===`

- [ ] **Step 3: Commit**

```bash
git add examples/test_perspective_breakthrough.py
git commit -m "$(cat <<'EOF'
test: add perspective breakthrough integration tests

Covers: perspectives config validation, InnerVoice signal extraction,
engine creation, message building, empty result handling.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```
