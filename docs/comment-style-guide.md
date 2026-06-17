# Comment Style Guide

Bilingual (EN/CN) comment conventions for the xiaomei-brain codebase.

## Principles

1. **English and Chinese are completely separated** -- never mixed on the same line.
   This allows mechanical extraction of pure-English or pure-Chinese versions via script.
2. **English first, Chinese second** -- in all cases (docstrings, section headers, inline comments).
3. **Comments are standalone lines** -- no trailing `# comments` on the same line as code.
   Reference: CPython `logging/__init__.py`.
4. **Technical terms stay in English within Chinese text** -- e.g. "Agent 生命周期状态",
   not "智能体生命周期状态"; "LLM 驱动的反思", not "大语言模型驱动的反思".
5. **Read the code before writing comments** -- original comments may be inaccurate or
   incomplete. Verify against the actual implementation and related code.

## Section separators

Use the CPython `logging` three-line style with one English title line and one Chinese title line:

```python
#---------------------------------------------------------------------------
#   States
#   状态枚举
#---------------------------------------------------------------------------
```

The two title lines enable splitting:
- Remove Chinese lines → pure English version
- Remove English lines → pure Chinese version

## Module docstrings

Paragraph-level separation: English paragraphs first, then Chinese paragraphs.
Each language block is self-contained.

```python
"""Living -- pure lifecycle management base class.

State machine + message queue + main loop + registered periodic tasks.
Contains NO consciousness / Drive / Purpose logic.

纯生命周期管理基类。

状态机 + 消息队列 + 主循环 + 注册式周期任务。
不包含任何 consciousness / Drive / Purpose 逻辑。
"""
```

## Class docstrings

Same paragraph-level separation.

```python
class Living:
    """Pure lifecycle management.

    Provides: state machine, message queue, main loop, 6 state loops,
    registered periodic tasks.

    纯生命周期管理。

    提供：状态机、消息队列、主循环、6 个状态循环、注册式周期任务。
    """
```

## Method / function comments

### Short descriptions (≤ ~3 lines total)

Use `#` comments inside the method body. Do NOT use `"""` for trivial one-liners.

```python
def _wait_message(self, timeout: float) -> LivingMessage | None:
    # Wait for a message with timeout.
    # 等待消息，超时返回 None。
    try:
        return self._queue.get(timeout=timeout)
    except queue.Empty:
        return None
```

### Multi-paragraph descriptions (> ~3 lines)

Use `"""` docstrings with paragraph-level separation.

```python
def run(self) -> None:
    """Main loop -- blocking.

    DORMANT -> WAKING -> AWAKE -> (state loops) -> DORMANT -> ...
    FatalLLMError 402 (insufficient balance) triggers DORMANT with periodic
    recovery. FatalLLMError 401/403 terminates the program.

    主循环，阻塞运行。

    DORMANT -> WAKING -> AWAKE -> (状态循环) -> DORMANT -> ...
    FatalLLMError 402（欠费）触发 DORMANT 并定期恢复。
    FatalLLMError 401/403 终止程序。
    """
```

### Method body inline comments

Group-related comments in pairs: English first, Chinese second. Each pair separated
by a blank line from the next pair.

```python
# Message queue.
# 消息队列。
self._queue: queue.Queue[LivingMessage | None] = queue.Queue()

# Interoception signals.
# 内感受信号。
self._interoception_signals: Any = None
```

### Code-flow step comments

Numbered steps in a pipeline:

```python
# 1. Ignore empty messages.
# 1. 忽略空消息。
if not msg.content:
    return

# 2. Re-entry guard.
# 2. 防重入。
if living._chatting:
    return
```

## Data class / Enum fields

Comments above the field, not inline.

```python
class LivingState(Enum):
    # Dormant -- no activity, waiting for message.
    # 休眠 -- 无活动，等待消息。
    DORMANT = "dormant"
    # Waking transition -- loading memory, preparing context.
    # 苏醒过渡 -- 加载记忆，准备上下文。
    WAKING = "waking"
```

## Module-level constants

```python
# Normal cycle.
# 正常心跳。
HEARTBEAT_NORMAL = "normal"
# Trigger DREAMING transition.
# 触发 DREAMING 状态切换。
HEARTBEAT_DREAM = "dream"
```

## When English and Chinese are identical

For comments that are pure code references (no natural language), keep two lines
but make them meaningfully different, or skip the Chinese line if it adds zero value.

```python
# Bad -- both lines identical:
# /intask /inchat -> ConversationDriver/GoalManager
# /intask /inchat -> ConversationDriver/GoalManager

# Good -- add explanatory text:
# /intask /inchat -- handled by GoalManager via ConversationDriver.
# /intask /inchat -- 由 GoalManager 处理（通过 ConversationDriver）。
```

## Process for reformatting a file

1. **Read the file** and all related code that the comments reference
2. **Verify comment accuracy** against actual code behavior -- original comments
   may be wrong or incomplete
3. **Rewrite** applying the conventions above
4. **Review the diff** line by line for logic changes
5. **Run `ast.parse`** to verify syntax
6. **Run `import`** to verify module loads cleanly
7. Commit the single file

## Anti-patterns

- ❌ Mixed-line comments: `# English | 中文`
- ❌ Inline trailing comments: `self.x = 1  # explanation`
- ❌ `──` or `━━` section separators (use `---`)
- ❌ Translating technical terms in Chinese text (keep "LLM", "API", "Agent", etc. as-is)
- ❌ Using `"""` for single-line descriptions (use `#`)
- ❌ Translating comments without reading the code first
