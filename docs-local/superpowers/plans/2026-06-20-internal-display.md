# 对话内部处理展示 — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在每轮对话结束后展示 LLM 内部处理结果（记忆提取、内心声音、DAG 压缩、Drive 变化、社交感知），只显示有数据的行。

**Architecture:** 新增 `InternalDisplay` dataclass 挂在 `ConversationDriver` 上，记录各内部事件的结果，每轮结束时 `render()` 输出格式化区块。记忆提取同步记录，内心声音/DAG/定期提取在 daemon 线程完成后记录、下一轮展示。

**Tech Stack:** Python dataclass + ANSI 着色，复用 `boot.py` 的颜色常量

---

## 文件结构

| 文件 | 操作 | 职责 |
|------|------|------|
| `src/xiaomei_brain/consciousness/internal_display.py` | 新建 | InternalDisplay 类 |
| `src/xiaomei_brain/agent/core.py` | 修改 | Agent 添加 `internal_display` 属性，stream() 中记录记忆提取 |
| `src/xiaomei_brain/consciousness/conversation_driver.py` | 修改 | 创建 InternalDisplay，_run_react() 中调用 render/clear，daemon 线程中 record |
| `src/xiaomei_brain/metacognition/inner_voice.py` | 修改 | 暴露 last_drive_deltas 和 last_social_signal |

---

### Task 1: 创建 InternalDisplay 类

**Files:**
- Create: `src/xiaomei_brain/consciousness/internal_display.py`

- [ ] **Step 1: 创建文件，实现 InternalDisplay dataclass**

```python
"""InternalDisplay — 对话内部处理结果展示。

每轮对话结束后，以 boot 风格区块展示记忆提取、内心声音、DAG 压缩等。
"""

from __future__ import annotations

from dataclasses import dataclass, field


# ── 颜色（与 boot.py 保持一致）────────────────────────────
C_DIM = "\033[38;5;73m"  # dusty teal
RESET = "\033[0m"


@dataclass
class InternalDisplay:
    """收集并格式化展示内部处理结果。

    用法:
        display = InternalDisplay()
        display.record_memory("ADD|标签|内容")
        display.record_inner_voice("今天状态不错...", ["归属欲 0.5→0.6"], "user_happy(0.7)")
        display.render()  # 有数据才输出，否则 silence
        display.clear()   # 清空，准备下一轮
    """

    _memory_actions: list[str] = field(default_factory=list)
    _inner_voice_thought: str = ""
    _inner_voice_drive: list[str] = field(default_factory=list)
    _inner_voice_signal: str = ""
    _dag_compact_count: int = 0
    _dag_compact_tokens: int = 0
    _periodic_count: int = 0

    # ── Record ────────────────────────────────────────────

    def record_memory(self, memory_block: str) -> None:
        """记录本轮记忆提取结果。

        Args:
            memory_block: LLM 输出的 <MEMORY> 原始文本
        """
        if not memory_block or not memory_block.strip():
            return
        for summary in _parse_memory_summaries(memory_block):
            self._memory_actions.append(summary)

    def record_inner_voice(self, thought: str, drive_deltas: list[str], signal: str) -> None:
        """记录内心声音结果（来自上一轮的 daemon 线程）。"""
        if thought:
            self._inner_voice_thought = thought
        if drive_deltas:
            self._inner_voice_drive = drive_deltas
        if signal:
            self._inner_voice_signal = signal

    def record_dag_compact(self, count: int, tokens: int) -> None:
        """记录 DAG 压缩结果。"""
        self._dag_compact_count = count
        self._dag_compact_tokens = tokens

    def record_periodic_extract(self, count: int) -> None:
        """记录定期记忆提取结果。"""
        self._periodic_count = count

    # ── Render ────────────────────────────────────────────

    def has_data(self) -> bool:
        return bool(
            self._memory_actions
            or self._inner_voice_thought
            or self._dag_compact_count
            or self._periodic_count
        )

    def render(self) -> None:
        """输出格式化的内部处理区块。无数据则 silence。"""
        if not self.has_data():
            return
        print()
        print(f"  {C_DIM}── 本轮内部处理 ──{RESET}", flush=True)
        for line in self._render_lines():
            print(f"  {C_DIM}│{RESET} {line}", flush=True)
        print(f"  {C_DIM}└────────{RESET}", flush=True)

    def _render_lines(self) -> list[str]:
        lines: list[str] = []

        # 🧠 记忆
        if self._memory_actions:
            lines.append("🧠 " + " · ".join(self._memory_actions))

        # 💭 内心声音
        if self._inner_voice_thought:
            thought = self._inner_voice_thought[:80]
            if len(self._inner_voice_thought) > 80:
                thought += "…"
            lines.append(f"💭 内心声音: {thought}")

        # 📈 Drive 变化
        if self._inner_voice_drive:
            lines.append("📈 Drive: " + " · ".join(self._inner_voice_drive))

        # 👤 社交感知
        if self._inner_voice_signal:
            lines.append(f"👤 社交感知: {self._inner_voice_signal}")

        # 📦 DAG
        if self._dag_compact_count:
            lines.append(f"📦 DAG: {self._dag_compact_count} 条消息 → 摘要 ({self._dag_compact_tokens} tokens)")

        # 🗂 定期提取
        if self._periodic_count:
            lines.append(f"🗂 定期提取: {self._periodic_count} 条记忆")

        return lines

    def clear(self) -> None:
        """清空所有数据，准备下一轮。"""
        self._memory_actions.clear()
        self._inner_voice_thought = ""
        self._inner_voice_drive.clear()
        self._inner_voice_signal = ""
        self._dag_compact_count = 0
        self._dag_compact_tokens = 0
        self._periodic_count = 0


# ── 记忆块解析 ────────────────────────────────────────────

def _parse_memory_summaries(memory_block: str) -> list[str]:
    """从 MEMORY block 中提取人类可读的摘要行。

    支持两种格式：
    1. JSON: {"actions": [{"action": "ADD", "content": "...", ...}]}
    2. 行格式: ADD|tag|content
    """
    summaries: list[str] = []
    block = memory_block.strip()
    if not block:
        return summaries

    # JSON 格式
    import json
    try:
        data = json.loads(block)
        if isinstance(data, dict):
            actions = data.get("actions", [])
            for a in actions:
                if isinstance(a, dict):
                    summaries.append(_fmt_json_action(a))
            return summaries
    except (json.JSONDecodeError, TypeError):
        pass

    # 行格式
    for line in block.split("\n"):
        line = line.strip()
        if not line:
            continue
        action, preview = _fmt_line_action(line)
        if action:
            summaries.append(f"{action} \"{preview}\"")

    return summaries


def _fmt_json_action(a: dict) -> str:
    action = a.get("action", "?")
    content = a.get("content", "")
    preview = content[:30].replace("\n", " ")
    if len(content) > 30:
        preview += "…"
    return f'{action} "{preview}"'


def _fmt_line_action(line: str) -> tuple[str, str]:
    """解析行格式: ADD|tag|content → (action_label, preview)"""
    parts = line.split("|", 2)
    if len(parts) < 2:
        return ("", "")
    action = parts[0].strip().upper()
    if action not in ("ADD", "UPDATE", "MERGE", "DELETE"):
        return ("", "")
    content = parts[2].strip() if len(parts) > 2 else ""
    preview = content[:30].replace("\n", " ")
    if len(content) > 30:
        preview += "…"
    # 中文标签映射
    label = {"ADD": "新增", "UPDATE": "更新", "MERGE": "合并", "DELETE": "删除"}.get(action, action)
    return (label, preview)
```

- [ ] **Step 2: 语法验证**

```bash
python3 -c "import py_compile; py_compile.compile('src/xiaomei_brain/consciousness/internal_display.py', doraise=True); print('OK')"
```

- [ ] **Step 3: 快速功能测试**

```bash
PYTHONPATH=src python3 -c "
from xiaomei_brain.consciousness.internal_display import InternalDisplay
d = InternalDisplay()
assert not d.has_data()
d.record_memory('ADD|技术|Python很强大')
assert d.has_data()
d.render()
d.clear()
assert not d.has_data()
# JSON format
d.record_memory('{\"actions\": [{\"action\": \"ADD\", \"content\": \"用户喜欢Python\"}, {\"action\": \"UPDATE\", \"content\": \"周末习惯爬山\"}]}')
d.render()
print('---')
d.clear()
d.record_inner_voice('用户状态不错', ['归属欲 0.5→0.6'], 'user_happy(0.7)')
d.record_dag_compact(8, 512)
d.render()
print('All OK')
"
```

- [ ] **Step 4: Commit**

```bash
git add src/xiaomei_brain/consciousness/internal_display.py
git commit -m "feat: add InternalDisplay for conversation processing visibility"
```

---

### Task 2: Agent.stream() 中记录记忆提取

**Files:**
- Modify: `src/xiaomei_brain/agent/core.py` (line ~401-404, Agent 类)

- [ ] **Step 1: 在 Agent 类上添加 internal_display 属性**

`src/xiaomei_brain/agent/core.py` 的 `Agent.__init__()` 中添加（在现有属性附近）:

```python
self.internal_display = None  # 由 ConversationDriver 注入
```

- [ ] **Step 2: 在 memory_block 提取后记录**

修改 `src/xiaomei_brain/agent/core.py`，在 `execute_block()` 调用之后（~line 404）:

找这段代码（约 401-404 行）:
```python
                        memory_block, clean_content = self.memory_extractor.extract_memory_block(content)
                        logger.info(...)
                        if memory_block:
                            self.memory_extractor.execute_block(memory_block, user_id=self.user_id)
```

改为:
```python
                        memory_block, clean_content = self.memory_extractor.extract_memory_block(content)
                        logger.info(...)
                        if memory_block:
                            self.memory_extractor.execute_block(memory_block, user_id=self.user_id)
                            if self.internal_display:
                                self.internal_display.record_memory(memory_block)
```

- [ ] **Step 3: 语法验证**

```bash
python3 -c "import py_compile; py_compile.compile('src/xiaomei_brain/agent/core.py', doraise=True); print('OK')"
```

- [ ] **Step 4: Commit**

```bash
git add src/xiaomei_brain/agent/core.py
git commit -m "feat: wire memory extraction into InternalDisplay in Agent.stream()"
```

---

### Task 3: InnerVoice 暴露 drive deltas 和 social signal

**Files:**
- Modify: `src/xiaomei_brain/metacognition/inner_voice.py`

- [ ] **Step 1: 在 InnerVoice.__init__() 添加 last 属性**

在 `InnerVoice.__init__()` 末尾添加:

```python
# 最近一次的 drive/signal 变化（供 InternalDisplay 读取）
self.last_drive_deltas: list[str] = []
self.last_social_signal: str = ""
```

- [ ] **Step 2: 在 _apply_drive_events() 末尾记录 deltas**

`_apply_drive_events()` (inner_voice.py:207-266) 从 JSON 解析 5 个维度并调用 `drive.on_*()`。在其末尾（`logger.info("[InnerVoice] EVENTS:...` 之后）添加:

```python
        # 记录变化描述（供 InternalDisplay 读取）
        deltas: list[str] = []
        if praise > 0.1:
            deltas.append(f"赞美 +{praise:.1f}")
        if criticism > 0.1:
            deltas.append(f"批评 +{criticism:.1f}")
        if expression > 0.3:
            deltas.append(f"表达欲 +{expression:.1f}")
        if curiosity > 0.3:
            deltas.append(f"好奇心 +{curiosity:.1f}")
        if boundary > 0.3:
            deltas.append(f"边界侵犯 anger{boundary:.1f}")
        self.last_drive_deltas = deltas
```

- [ ] **Step 3: 在 _apply_social_signal() 中记录 signal**

`_apply_social_signal()` (inner_voice.py:268-300) 从 JSON 解析 `social_signal` 和 `intensity`。在 `if signal_type and intensity > 0.1:` 分支内，`drive.apply_social_signal()` 之后添加:

```python
                self.last_social_signal = f"{signal_type}({min(intensity, 1.0):.1f})"
```

在方法开头（`if not self._drive or not signal_text: return` 之前）重置:

```python
        self.last_social_signal = ""
```

- [ ] **Step 4: Commit**

```bash
git add src/xiaomei_brain/metacognition/inner_voice.py
git commit -m "feat: expose last_drive_deltas and last_social_signal from InnerVoice"
```

---

### Task 4: ConversationDriver 创建 InternalDisplay 并注入 Agent

**Files:**
- Modify: `src/xiaomei_brain/consciousness/conversation_driver.py`

- [ ] **Step 1: 在 ConversationDriver.__init__() 中创建 InternalDisplay**

在 `ConversationDriver.__init__()` 末尾（约 line 83 之后）添加:

```python
# 内部处理展示
self.display = InternalDisplay()
```

注意在文件顶部添加 import:
```python
from xiaomei_brain.consciousness.internal_display import InternalDisplay
```

- [ ] **Step 2: 注入到 Agent**

在 `_run_react()` 中，`agent = parent.agent._get_agent()` 之后（约 line 212）添加:

```python
agent.internal_display = self.display
```

- [ ] **Step 3: 语法验证**

```bash
python3 -c "import py_compile; py_compile.compile('src/xiaomei_brain/consciousness/conversation_driver.py', doraise=True); print('OK')"
```

- [ ] **Step 4: Commit**

```bash
git add src/xiaomei_brain/consciousness/conversation_driver.py
git commit -m "feat: create InternalDisplay in ConversationDriver and inject to Agent"
```

---

### Task 5: 在 daemon 线程中收集 InnerVoice / DAG / 定期提取结果

**Files:**
- Modify: `src/xiaomei_brain/consciousness/conversation_driver.py`

- [ ] **Step 1: 修改 _invoke_inner_voice_chat_turn() — 完成时 record**

在 `_invoke_inner_voice_chat_turn()` 的 daemon 线程函数 `_run()` 中（约 line 417-423），调用 `iv.on_chat_turn()` 之后添加:

```python
            def _run():
                try:
                    iv.on_chat_turn(
                        elapsed=_elapsed, tools=_tools, user_name=_user_name,
                        recent_dialogue=_dialogue)
                    # 记录结果到 InternalDisplay
                    thought = iv.get_last_thought()
                    deltas = getattr(iv, 'last_drive_deltas', [])
                    signal = getattr(iv, 'last_social_signal', '')
                    if thought or deltas or signal:
                        self.display.record_inner_voice(thought, deltas, signal)
                except Exception as e:
                    logger.debug("[ConversationDriver] InnerVoice chat_turn 失败: %s", e)
```

注意需要用 `self.display` 引用 InternalDisplay，需要确保 daemon 线程能访问。使用闭包捕获 `display = self.display`:

```python
            display = self.display
            def _run():
                try:
                    iv.on_chat_turn(...)
                    thought = iv.get_last_thought()
                    deltas = getattr(iv, 'last_drive_deltas', [])
                    signal = getattr(iv, 'last_social_signal', '')
                    if thought or deltas or signal:
                        display.record_inner_voice(thought, deltas, signal)
                except Exception as e:
                    ...
```

- [ ] **Step 2: 修改 _invoke_dag_compact() — 完成时 record**

在 `_invoke_dag_compact()` 的 daemon 线程函数中（约 line 445-448），调用 `_agent._auto_compact()` 之后添加:

```python
            display = self.display
            def _run():
                try:
                    _agent._auto_compact(_session_id, max_tokens=4000, messages=None)
                    # 从 _agent.on_compact 获取最后一次的数据
                    # on_compact 已在 _auto_compact 中被调用，这里暂无简单方式获取
                    # 替代方案：为 DAG compact 添加单独的数据捕获
                except Exception as e:
                    ...
```

实际上 `_auto_compact` 通过 `on_compact` callback 传递数据。更好的方案是使用一个临时变量捕获:

在 `_invoke_dag_compact()` 方法体中（启动 daemon 线程之前），设置一个临时 callback:

```python
            _compact_data = {}
            _orig_on_compact = _agent.on_compact
            def _capture_compact(data):
                _compact_data.update(data)
            _agent.on_compact = _capture_compact

            display = self.display
            def _run():
                nonlocal _compact_data
                try:
                    _agent._auto_compact(_session_id, max_tokens=4000, messages=None)
                    count = _compact_data.get("compact_count", 0)
                    tokens = _compact_data.get("summary_tokens", 0)
                    if count:
                        display.record_dag_compact(count, tokens)
                except Exception as e:
                    logger.debug("[ConversationDriver] DAG compact 失败: %s", e)
                finally:
                    _agent.on_compact = _orig_on_compact
```

- [ ] **Step 3: 修改 _invoke_memory_extract() — 完成时 record**

`extract_periodic()` (extractor.py:87-127) 返回 `list[int]`（记忆ID列表）。

在 daemon 线程中，调用后记录:

```python
            display = self.display
            def _run():
                try:
                    result = _extractor.extract_periodic(user_name=user_name)
                    count = len(result) if result else 0
                    if count:
                        display.record_periodic_extract(count)
                except Exception as e:
                    logger.warning("[ConversationDriver] 记忆提取失败: %s", e)
                finally:
                    _self._extracting = False
```

- [ ] **Step 4: 语法验证**

```bash
python3 -c "import py_compile; py_compile.compile('src/xiaomei_brain/consciousness/conversation_driver.py', doraise=True); print('OK')"
```

- [ ] **Step 5: Commit**

```bash
git add src/xiaomei_brain/consciousness/conversation_driver.py
git commit -m "feat: record InnerVoice/DAG/periodic results in daemon threads"
```

---

### Task 6: 在 _run_react() 末尾渲染并清空

**Files:**
- Modify: `src/xiaomei_brain/consciousness/conversation_driver.py`

- [ ] **Step 1: 在 _run_react() 中，agent.stream() 返回后调用 render/clear**

在 `agent.stream()` 循环结束后（约 line 252），`RoundScheduler.tick()` （约 line 337-343）之前:

在 `display_content = gm.remove_progress_tag(content)` 之后、`print("\033[90m" + "─" * self.term_width + "\033[0m")` 之后添加:

```python
                    # ── 展示内部处理 ──
                    self.display.render()
                    self.display.clear()
```

放在 `[本轮耗时 ...]` 输出之后（~line 313 之后），`RoundScheduler.tick()` 之前。

- [ ] **Step 2: 语法验证**

```bash
python3 -c "import py_compile; py_compile.compile('src/xiaomei_brain/consciousness/conversation_driver.py', doraise=True); print('OK')"
```

- [ ] **Step 3: Commit**

```bash
git add src/xiaomei_brain/consciousness/conversation_driver.py
git commit -m "feat: render InternalDisplay after each conversation round"
```

---

---

### Task 7: 集成验证

- [ ] **Step 1: 运行 CLI 验证记忆提取即时显示**

```bash
PYTHONPATH=src python3 -m xiaomei_brain run xiaomei --cli
```

输入一段对话，等待 LLM 回复后观察是否有 `── 本轮内部处理 ──` 区块出现。确认:
- 🧠 记忆行在 LLM 回复后立即显示
- 💭 内心声音行在下一轮显示（如果有触发）

- [ ] **Step 2: 验证 DAG 压缩显示**

连续对话多轮（8+ 轮），观察 📦 DAG 行是否出现。

- [ ] **Step 3: 验证无数据时 silence**

如果 LLM 回复中无 `<MEMORY>` 块，且无 pending 的 daemon 线程结果，确认不显示区块。

---

## 自检清单

- [ ] spec 覆盖率：记忆提取 ✅ / 内心声音 ✅ / DAG ✅ / 定期提取 ✅ / Drive ✅ / 社交感知 ✅
- [ ] 无 placeholder：所有任务有具体代码
- [ ] 类型一致：InternalDisplay 方法签名在各处调用一致
