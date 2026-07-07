# 元认知层（Metacognition）详解

> 对应目录：`src/xiaomei_brain/metacognition/`
>
> 元认知是"对自己认知的认知"——Agent 的自我监督与反省系统。

---

## 核心理念

**Agent 不只是"执行"，还要知道自己执行得怎么样。**

```
传统 Agent:
用户 → LLM → 输出（一次单向通道）

有元认知的 Agent:
用户 → LLM → 输出 → 反省 → 调整下次行为
                      ↑
                对自己认知的认知
```

---

## 三子系统

```
Metacognition
├── InnerVoice（内心声音）← 自然的自我觉察
├── PACE（任务监督）← 执行时的"停-评-选-做"
└── CapabilityTracker（能力追踪）← 记录能力边界
```

---

## InnerVoice（内心声音）

> `inner_voice.py`

**统一的、极轻的 LLM 调用**——不是结构化评测，而是自然语言的自我觉察。

```python
class InnerVoice:
    def pause(self, trigger: TriggerType, context: dict) -> Reflection | None:
        """所有反省的统一入口。返回 None 表示跳过。"""
```

### 触发时机

| 触发类型 | 条件 | 内容 |
|---------|------|------|
| `CHAT_TURN` | 每次对话回应后 | "我刚才说得对吗？用户什么反应？" |
| `TASK_STEP` | PACE 一步完成后 | "这个方法好像不太对，要不要换一个？" |
| `TASK_DONE` | 子目标/目标完成 | "做得怎么样？有什么可以改进的？" |
| `SILENCE` | 用户长时间空闲 | "我现在该做什么？有什么可以主动做的？" |

### 输出

```python
@dataclass
class Reflection:
    trigger: TriggerType    # 触发类型
    thought: str            # 自然语言（1-3 句），非结构化
    context_snippet: str = ""
    timestamp: float = ...
```

**示例输出**：

| 触发 | 反省内容 |
|------|---------|
| CHAT_TURN | "他好像不太认同我的建议，可能我理解错了他的问题。" |
| TASK_STEP | "这个 API 调了三次都报错，换个思路试试。" |
| TASK_DONE | "做完了，但代码还可以优化，下次先想清楚再写。" |
| SILENCE | "好久没说话了，上次聊到他喜欢看电影，去了解一下新片？" |

### 冷却机制

InnerVoice 有冷却时间，避免频繁调用浪费 token：

```python
class InnerVoice:
    _last_pause: dict[TriggerType, float] = {}
    _cooldowns: dict[TriggerType, float] = {
        TriggerType.CHAT_TURN: 60,     # 1 分钟
        TriggerType.TASK_STEP: 30,     # 30 秒
        TriggerType.TASK_DONE: 0,      # 无冷却
        TriggerType.SILENCE: 300,      # 5 分钟
    }
```

---

## PACE 任务监督

> `runner.py`

PACE = **P**ause **A**ssess **C**hoose **E**xecute

```
任务执行 → Pause（停一下）
              ↓
         Assess（评估）
           ├─ 进度：有进展吗？
           ├─ 认知：我知道怎么做吗？
           ├─ 卡住：尝试几次了？
           └─ 策略：这个方法有效吗？
              ↓
         Choose（选择）
           ├─ 继续 → Execute
           ├─ 换策略 → 尝试新方法
           ├─ 请求帮助 → 向用户提问
           └─ 放弃 → 承认做不到
              ↓
         Execute → 完成一步 → InnerVoice.pause(TASK_STEP)
```

### 规则检测

7 种规则判断是否卡住或需要调整：

```python
class PACERunner:
    def _detect_buzz(self, context: TaskStepContext) -> str | None:
        """检测是否存在异常信号，返回自然语言提示。"""
        # 1. 工具调用环（同一个工具调了 3+ 次）
        # 2. 空输出（LLM 返回空）
        # 3. 工具调用未输出（调了工具但没返回结果）
        # 4. 过度思考（think 轮次过多）
        # 5. 低容错工具链（连续失败）
        # 6. 缓慢进度（超过预期时间）
        # 7. 大输出堆积（输出不断增长）
```

---

## CapabilityTracker（能力追踪）

> `capability.py`

记录 Agent 的**能力边界**——什么做得好、什么做不好。

```python
class CapabilityTracker:
    def record_attempt(self, task_type: str, success: bool, context: str):
        """记录一次执行尝试的结果。"""

    def estimate_success(self, task_type: str) -> float:
        """预估某类任务的成功率。"""
```

**用途**：
- InnerVoice 参考历史成功率判断"我能不能做到"
- PACE 在 Choose 阶段参考"之前怎么做的"
- 引导学习方向（"我不擅长数据分析，应该多学学"）

---

## 与其他层的交互

```
InnerVoice.pause(trigger)
    │
    ├─ 反省结果 → SelfImage.Mind（注入 LLM 上下文）
    │      LLM 读到："我刚才可能理解错了"
    │      → 下次回复更谨慎
    │
    ├─ 反省结果 → Drive
    │      检测到"我做得不好" → cortisol 上升
    │      检测到"用户不高兴" → oxytocin 下降
    │
    └─ 反省结果 → Purpose
            检测到"这个目标太难" → 自动分解为更小的目标
```

**数据流**：
```
对话 → InnerVoice.pause() → Reflection → SelfImage → LLM 上下文
                                                          ↓
                                                    下次更明智的回复
```

---

## 代码路径

| 功能 | 位置 |
|------|------|
| InnerVoice | `metacognition/inner_voice.py` |
| PACE 循环 | `metacognition/runner.py` |
| 能力追踪 | `metacognition/capability.py` |
| 认知循环 | `metacognition/cognitive_loop.py` |
| 社交感知 | `metacognition/social_perception.py` |
| 社交认知 | `metacognition/social_cognition.py` |
| 类型定义 | `metacognition/types.py` |
| 规则 | `metacognition/rules.py` |
| 自主性 | `metacognition/autonomy.py` |
| 项目心智模型 | `metacognition/project_mental_model.py` |
