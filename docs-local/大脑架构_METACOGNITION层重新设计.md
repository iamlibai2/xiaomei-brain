# Metacognition 层重新设计：InnerVoice 为中心的类人反省机制

## Context

当前 metacognition 层有两个独立的子系统：
- **PACE**（runner.py ~1235行）：任务执行的 Pause-Assess-Choose-Execute 循环，7种规则检测 + LLM结构化评估
- **SocialPerception**（social_perception.py ~178行）：每N轮定时检测用户情绪变化

问题：
1. 两个独立系统，机制不共享
2. 输出是结构化JSON/enum，不像人的内心独白
3. 按定时器/规则触发，不是自然节点
4. 输出是度量值（SURPRISE: 2），不是"感觉"（"这个方法好像不太对"）

用户期望：像人一样——在自然节点停一下、一两句内心嘟囔、感觉驱动行为调整。工作时不跑偏，对话时能感知对方。

## 核心理念

**InnerVoice（内心声音）** 是一个统一的、极轻的 LLM 调用——不是结构化评测，而是自然语言的自我觉察。一个方法 `pause()` 处理所有情境（对话后、任务步骤后、安静时）。结果自然流入 SelfImage 和 Drive。

## 文件结构（改后）

```
metacognition/
├── __init__.py         # InnerVoice, PACERunner, CapabilityTracker
├── inner_voice.py      # [新] 核心：InnerVoice 引擎 (~300行)
├── runner.py           # [简化] PACE 循环 (~500行)
├── capability.py       # [保留] CapabilityTracker
├── rules.py            # [简化] buzz检测 → 自然语言提示(~100行)
└── types.py            # [简化] 核心类型(~60行)
```

删除：`social_perception.py`、`reviewer.py`、`metrics.py`（功能被 InnerVoice 吸收或简化）

## Phase 1: 简化的类型系统（types.py）

```python
class TriggerType(Enum):
    CHAT_TURN = "chat_turn"        # 对话回应后
    TASK_STEP = "task_step"        # PACE一步完成
    TASK_DONE = "task_done"        # 子目标/目标完成
    SILENCE = "silence"            # 用户空闲

@dataclass
class Reflection:
    trigger: TriggerType
    thought: str                   # 自然语言（1-3句），非结构化
    context_snippet: str = ""
    timestamp: float = field(default_factory=time.time)

@dataclass
class TaskStepContext:
    goal_description: str
    step_index: int
    tool_calls: list[str]
    tool_call_count: int
    elapsed_seconds: float
    output_preview: str
    progress_status: str | None
```

移除：SurpriseType、StuckClass、MetaSuggestion、StepObservation、StepCheckResult、TaskLesson

## Phase 2: InnerVoice 核心引擎（inner_voice.py）

### 单一入口

```python
class InnerVoice:
    def __init__(self, llm, self_image, drive=None, purpose=None):
        ...

    def pause(self, trigger: TriggerType, context: dict) -> Reflection | None:
        """所有反省的统一入口。返回 None 表示跳过（冷却/无值得注意的）。"""
```

### 触发条件（自然节点，不是定时器）

| 触发类型 | 条件 |
|---------|------|
| CHAT_TURN | 距上次反省>=2轮有意义的交流（用户消息>3字符 且 回复>20字符） |
| TASK_STEP | 每步都反省（200 token prompt + ~50 token回复，成本极低） |
| TASK_DONE | 子目标完成时总是触发 |
| SILENCE | 用户空闲>60秒 且 距上次反省>30秒 |

硬冷却：距上次反省<3秒 → 跳过

### Prompt 风格（关键差异化）

System prompt 固定：
```
你是小美的内心声音。你在安静的自我觉察时刻——
不是在跟任何人对话，只是在对自己坦诚。
你的话是直觉式的、感受性的，不是分析的、评判的。
1-3句就够了。如果一切顺利，就说"一切正常"。
不要假装有感觉——如果确实没什么，就让它没什么。
```

CHAT_TURN prompt：
```
你刚和一个人交流完。短暂的内省——

他说：「{user_msg[:200]}」
你回应了（{len}字，{elapsed:.0f}秒，{'用了'+tools if tools else '没用工具'}）

只是感受——他的状态对吗？你的回应恰当吗？
有什么你刚才没注意到的？

1-3句话的内心嘟囔。如果没什么特别的感觉，就说"一切正常"。
```

TASK_STEP prompt（包含 buzz 提示）：
```
你在做一个任务。停一下，看一眼手头的活——

目标：「{goal_description}」（第{step}步）
这一步用了{elapsed:.0f}秒，{工具信息}
{buzz_hints}

像工匠看了一眼自己手里的活——方向对吗？顺手吗？需要注意什么？
1-3句话，直接说出你的直觉。如果一切顺利，就说"一切正常"。
```

### 输出路由（`_route_reflection()`）

1. **SelfImage.mind.inner_voice**（总是）→ 统一的 recent reflections 缓冲区（替换 social_perceptions + pace_reflections）
2. **Drive 社交信号**（CHAT_TURN / SILENCE）→ 正则匹配 reflection.thought 中的关键词 → 映射到已有的 SOCIAL_SIGNAL_MAP 驱动 Drive 变化
3. **Purpose cognitive_log**（TASK_STEP / TASK_DONE）→ goal.append_log("discovery", f"[内心声音] {thought}")

### 社交信号提取（正则，沿用"代码决定数值"原则）

```python
_BUZZ_TO_SIGNAL = [
    (r"(低落|沮丧|难过|不开心|情绪不好)", "user_low_mood", 0.5),
    (r"(兴奋|热情|激动|开心|充满活力)", "user_enthusiastic", 0.5),
    (r"(冷淡|疏远|敷衍|冷漠|话[很少])", "user_cold", 0.5),
    (r"(生气|愤怒|不满|烦[躁燥])", "user_angry", 0.5),
    (r"(压力|焦虑|紧张|疲惫|累[了坏])", "user_stressed", 0.5),
    (r"(信任|亲近|温暖|依赖|敞开心)", "user_trusting", 0.4),
]
```

### 任务继续决策（should_continue()，从自然语言提取控制信号）

```python
# 仅依赖 reflection.thought 的字符串，不需要 LLM 生成 enum
def should_continue(self) -> tuple[bool, str]:
    thought = recent_reflection.thought
    if re.search(r"(放弃|无法完成|超出能力|做不了)", thought):
        return False, "escalate"
    if re.search(r"(需要确认|等用户|先问问)", thought):
        return False, "waiting_user"
    if re.search(r"(换个方法|方向不对|重试|换个思路|简化)", thought):
        return True, "retry"
    return True, "continue"
```

## Phase 3: SelfImage 适配

### self_modules.py

```python
# SelfMind: social_perceptions → inner_voice
inner_voice: list[dict] = field(default_factory=list)

# SelfMemorySlot: 删除 pace_reflections
```

### self_image_proxy.py

```python
# inject_consciousness() 中两个独立块合并为一个：
if m.inner_voice:
    lines.append("\n****以下是你近期的内心声音****")
    for iv in m.inner_voice[-8:]:
        lines.append(f"- [{trigger_label}] {iv.get('thought', '')}")
```

### consciousness/core.py

- 删除 `add_pace_reflection()` 方法
- 简化 `_split_perception()`（L2 不再需要"第四问"，InnerVoice 已处理社交感知）

## Phase 4: Chat 集成

### task_orchestrator.py

```python
# assess_chat() 替换：
# 旧：assess_only() → add_pace_reflection()
# 新：InnerVoice.pause(CHAT_TURN, context)
```

### conscious_living.py

- 删除 `self._social_perception` 和 `_check_round_perception()`
- 不再创建 SocialPerception 实例
- 轮次感知通过 InnerVoice 在 assess_chat() 中自然处理

## Phase 5: PACE 简化（runner.py）

### 主要删除（~700行 → ~500行）

| 删除的内容 | 替代方式 |
|-----------|---------|
| `_step_check()` + `_hard_rule_check()` + `_rule_based_check()` | InnerVoice.pause(TASK_STEP) + should_continue() |
| `_build_nudge_from_surprises()` | 上一轮 reflection.thought 直接作为轻推 |
| `LLMBudget` 类 | InnerVoice 内部冷却取代 |
| `assess_only()` | 不再需要（Chat 路径直接用 InnerVoice） |
| `llm_step_check()`、`llm_post_review()` | InnerVoice.pause() 统一处理 |
| StepCheckResult 相关的所有分支 | should_continue() 关键词匹配 |

### 保留（核心价值不动）

- `_run_loop()` 主循环结构
- `_pre_check()` 目标清晰度检查
- `_handle_progress()` + `_update_goal_progress()`
- `_maybe_auto_advance()` 子目标推进
- save/restore checkpoint（暂停恢复）
- CapabilityTracker 集成

### 事后复盘简化

`_do_post_review()` → 调用 `InnerVoice.pause(TASK_DONE, summary)` + 写入 cognitive_log

## Phase 6: 清理

1. 删除 `social_perception.py`
2. 简化 `reviewer.py` → `persist_lesson()` 移入 runner.py
3. 简化 `rules.py` → `detect_buzz()` 只产出自然语言提示列表（不产 enum）
4. `SOCIAL_SIGNAL_MAP` 移入 `inner_voice.py`
5. 更新 `__init__.py` 导出

## 改动文件清单

| 文件 | 改动量 | 说明 |
|------|--------|------|
| `metacognition/inner_voice.py` | 新增 ~300行 | InnerVoice 引擎 |
| `metacognition/types.py` | 重写 ~60行 | 类型系统简化 |
| `metacognition/runner.py` | 删除 ~700行 | PACE 简化 |
| `metacognition/rules.py` | 重写 ~100行 | buzz检测改自然语言 |
| `metacognition/__init__.py` | ~20行 | 更新导出 |
| `consciousness/self_modules.py` | ~5行 | social_perceptions → inner_voice |
| `consciousness/self_image_proxy.py` | ~15行 | 统一 inner_voice 注入 |
| `consciousness/core.py` | ~10行 | 删除 add_pace_reflection |
| `consciousness/task_orchestrator.py` | ~30行 | assess_chat 走 InnerVoice |
| `consciousness/conscious_living.py` | ~20行 | 删除 SocialPerception |

## 不改的文件

- `metacognition/capability.py`（完全保留）
- `metacognition/reviewer.py`（删除）
- `metacognition/metrics.py`（删除）
- `agent/core.py`
- `base/llm.py`
- `drive/engine.py`
- `purpose/goal.py`
- `consciousness/action_dispatcher.py`

## 验证

```bash
cd /home/iamlibai/workspace/claude-project/xiaomei-brain
source /home/iamlibai/workspace/python_env_common/bin/activate

# 1. InnerVoice 独立可用
PYTHONPATH=src python3 -c "
from xiaomei_brain.metacognition.inner_voice import InnerVoice
from xiaomei_brain.metacognition.types import TriggerType, Reflection
print('Phase 1-2 imports OK')
"

# 2. 导入无 SocialPerception 依赖
PYTHONPATH=src python3 -c "
from xiaomei_brain.metacognition import InnerVoice, PACERunner
print('Phase 5 imports OK')
"

# 3. SelfImage 适配
PYTHONPATH=src python3 -c "
from xiaomei_brain.consciousness.self_modules import SelfMind
m = SelfMind()
assert hasattr(m, 'inner_voice'), 'inner_voice field missing'
assert not hasattr(m, 'social_perceptions'), 'social_perceptions should be removed'
print('Phase 3 OK')
"

# 4. 端到端 ConsciousLiving
PYTHONPATH=src python3 examples/run_conscious_living.py
```
