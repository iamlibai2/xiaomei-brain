# 注释风格指南（中文版）

xiaomei-brain 代码库中英双语注释规范。

## 原则

1. **中英文彻底分离** — 绝不在同一行混用中英文。方便通过脚本机械拆分出纯英文版或纯中文版。
2. **英文在前，中文在后** — 所有场景统一（docstring、section 标题、行内注释）。
3. **注释独占一行** — 代码行尾不出现 `# 注释` 这种写法。参考：CPython `logging/__init__.py`。
4. **中文注释中术语保留英文** — 如 "Agent 生命周期状态" 而非 "智能体生命周期状态"；
   "LLM 驱动的反思" 而非 "大语言模型驱动的反思"。专有名词、API 名称、模块名、类名一律不翻译。
5. **先读代码，再写注释** — 原始注释可能不准确或不完整。写注释前必须对照实际代码逻辑和
   相关代码交叉验证。

## Section 分隔符

采用 CPython `logging` 模块的三行风格，英文标题一行、中文标题一行：

```python
#---------------------------------------------------------------------------
#   States
#   状态枚举
#---------------------------------------------------------------------------
```

两行标题分开的好处：
- 删掉中文行 → 纯英文版
- 删掉英文行 → 纯中文版

## 模块 docstring

段落级分离：英文段落在前，中文段落在后。每种语言自成体系。

```python
"""Living -- pure lifecycle management base class.

State machine + message queue + main loop + registered periodic tasks.
Contains NO consciousness / Drive / Purpose logic.

纯生命周期管理基类。

状态机 + 消息队列 + 主循环 + 注册式周期任务。
不包含任何 consciousness / Drive / Purpose 逻辑。
"""
```

## 类 docstring

同模块 docstring，段落级分离。

```python
class Living:
    """Pure lifecycle management.

    Provides: state machine, message queue, main loop, 6 state loops,
    registered periodic tasks.

    纯生命周期管理。

    提供：状态机、消息队列、主循环、6 个状态循环、注册式周期任务。
    """
```

## 方法 / 函数注释

### 简短描述（约 3 行以内）

用 `#` 注释，放在方法体内部。不要用 `"""` 套一层。

```python
def _wait_message(self, timeout: float) -> LivingMessage | None:
    # Wait for a message with timeout.
    # 等待消息，超时返回 None。
    try:
        return self._queue.get(timeout=timeout)
    except queue.Empty:
        return None
```

### 多段落描述（超过 3 行）

用 `"""` docstring，段落级分离。

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

### 方法体内注释

相关注释成对出现：英文一行、中文一行。不同注释组之间空行分隔。

```python
# Message queue.
# 消息队列。
self._queue: queue.Queue[LivingMessage | None] = queue.Queue()

# Interoception signals.
# 内感受信号。
self._interoception_signals: Any = None
```

### 流程步骤注释

流水线中的编号步骤：

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

## 数据类 / 枚举字段

注释在字段上方，不在行尾。

```python
class LivingState(Enum):
    # Dormant -- no activity, waiting for message.
    # 休眠 -- 无活动，等待消息。
    DORMANT = "dormant"
    # Waking transition -- loading memory, preparing context.
    # 苏醒过渡 -- 加载记忆，准备上下文。
    WAKING = "waking"
```

## 模块级常量

```python
# Normal cycle.
# 正常心跳。
HEARTBEAT_NORMAL = "normal"
# Trigger DREAMING transition.
# 触发 DREAMING 状态切换。
HEARTBEAT_DREAM = "dream"
```

## 当英文和中文内容相同时

如果注释内容纯粹是代码引用（不含自然语言），两条相同内容没意义。此时应当补充说明性文字，
让两行各有差异。

```python
# 不好 — 两行一模一样：
# /intask /inchat -> ConversationDriver/GoalManager
# /intask /inchat -> ConversationDriver/GoalManager

# 好 — 补充了说明：
# /intask /inchat -- handled by GoalManager via ConversationDriver.
# /intask /inchat -- 由 GoalManager 处理（通过 ConversationDriver）。
```

## 改造一个文件的操作流程

1. **读文件** 及相关代码（注释引用的类/方法/模块）
2. **验证注释准确性** — 对照实际代码逻辑，原始注释可能有错误或遗漏
3. **重写** 按本规范执行
4. **审查 diff** 逐行确认没有逻辑改动
5. **语法检查** `ast.parse` 验证
6. **导入检查** `import` 验证模块正常加载
7. 单文件提交

## 反模式

- ❌ 中英混行：`# English | 中文`
- ❌ 代码行尾注释：`self.x = 1  # 解释`
- ❌ `──` 或 `━━` 分隔符（用 `---`）
- ❌ 中文注释中翻译术语（"LLM"、"API"、"Agent" 等保持原文）
- ❌ 简短描述用 `"""`（用 `#`）
- ❌ 不看代码直接翻译注释
