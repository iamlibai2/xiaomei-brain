# 给 AI Agent 加一张"桌子"——不靠协议的模块间上下文共享

## 问题：L2 分析了半天，Action 根本不知道

xiaomei-brain 是一个多层 AI Agent 框架，参考人脑分层架构。其中有两个关键模块：

- **L2（轻度加柴引擎）**：定期运行，分析当前状态，做意图决策，产出内心独白
- **Action（动作分发器）**：根据意图匹配规则，执行具体行为（工作、问候、学习……）

理论上 L2 的判断应该指导 Action 的执行。但实际上，它们各自调用 LLM，各自维护状态。L2 在内心独白里写了："需要审计认证模块，发现了 3 处安全漏洞"，然后 Action 启动时根本不知道这段分析存在，自己重新想一遍，甚至选了另一个任务来做。

这不是架构缺陷——这是**信息传递的成本太高**。如果每对模块之间都要定义协议、指定接收方、约定格式，那 N 个模块会产生 O(N²) 条通信链路。

人脑不这么干。

## 人脑的解法：一张桌子就够了

想象你工作时的桌面：打开的文件、半杯咖啡、一张便利贴写着"记得改 token 验证逻辑"。你没写备忘录，没用 Jira，没发 Slack——但扫一眼桌子就知道从哪开始。

关键特征：

- **谁都可以往上放东西**，不需要知道谁会来看
- **谁都可以来扫一眼**，不需要请求谁的数据
- **不重要的自然被盖住**，被咖啡杯压住的那张纸过几天就忘了
- **做完了就翻过去**，不再占注意力

这就是 Desk 机制的灵感来源。

## 设计

### 核心原则

> 任何模块都可以往桌上扔东西，任何模块都可以来扫一眼。不需要协议，不需要指定接收方——看到什么算什么，需要什么拿什么。

### DeskItem：桌上的一张纸

每条 item 不是纯文本——它自带元数据。这些元数据决定了它的"重量"（weight），也就是它能留在桌上多久、被看到的概率多大：

```
DeskItem
├─ content       : 内容（截断到 2000 字）
├─ source        : 谁扔的（L2/action/chat/dream/proactive）
├─ intent        : 意图类型（work/express/reflect/remind/dream/greet）
├─ confidence    : L2 意图决策的置信度（0-1）
├─ dopamine      : 写时的情绪热度（0-1）
├─ goal_related  : 是否关联当前目标
├─ created_at    : 写入时间
├─ access_count  : 被读次数
├─ last_accessed : 最近被读时间
└─ completed     : 是否已完成
```

### 权重算法：不靠 LLM，纯数值

这是整个机制的核心。如果让 LLM 判断"这条重要吗"，不仅慢、消耗 token，而且每次判断结果不一致。

直接用算法：

```python
@property
def weight(self) -> float:
    # 做完了就放下——蔡格尼克效应
    if self.completed:
        return 0.05

    # 意图权重：work > reflect > express > remind > dream
    intent_w = {"work": 0.8, "reflect": 0.6, "express": 0.5,
                "remind": 0.4, "dream": 0.3, "greet": 0.3}

    # 基础权重：置信度 + 意图 + 情绪 + 目标关联
    base = (confidence × 0.3 + intent_w × 0.2 +
            dopamine × 0.2 + (0.3 if goal_related else 0))

    # 被反复读加分：越被关注越重要
    access_bonus = min(0.2, access_count × 0.05)

    # 时间衰减：每小时衰减 3%
    decay = 0.97 ^ age_hours

    return (base + access_bonus) × decay
```

设计考量：

| 因子 | 占比 | 为什么 |
|------|------|--------|
| confidence | 30% | L2 决策的可信度直接决定该不该重视 |
| intent | 20% | 工作任务比闲聊重要，大脑天然区分 |
| dopamine | 20% | 情绪热度影响记忆粘性——激动的发现记更牢 |
| goal_related | 30% | 关联目标的是"正事"，不关联的可能是噪音 |
| access_bonus | 最多 20% | 被反复读取说明真的有用，正反馈 |
| decay | 衰减 | 每小时 3%，大约 24 小时后剩一半，不重要的自然淡出 |
| completed | 地板 0.05 | 蔡格尼克效应：做完的事大脑不再惦记 |

### Desk：公用桌面

```python
class Desk:
    MAX_ITEMS = 20       # 桌上最多放 20 张纸
    MIN_WEIGHT = 0.15    # 低于此阈值"沉底"，不返回
```

**公共接口**：

| 方法 | 语义 | 谁调用 |
|------|------|--------|
| `drop(content, source, intent)` | 扔一条上桌 | L2/Action/Chat 写入 |
| `peek(limit=5)` | 扫一眼，按权重排序 | 各 LLM 入口读取 |
| `touch(item)` | 标记被读，权重微涨 | `peek_for_prompt()` 自动调用 |
| `complete(item)` | 做完，权重归零 | Action 完成后标记 |
| `complete_by_source("L2")` | 批量消费某来源 | Action 完成后消费 L2 分析 |
| `clear_completed()` | 清理已完成+沉底 | 定期或 `_prune()` 触发 |
| `peek_for_prompt(limit=5)` | 返回可直接注入 prompt 的文本 | SelfImage 组装时调用 |

**自动补全**：`drop()` 时如果不传 `dopamine`，自动从 Drive（边缘系统）取当前多巴胺水平；不传 `goal_related`，自动从 Purpose（目标系统）判断是否关联当前目标。调用方只需关心"我要说什么"，权重由上下文自动决定。

**淘汰机制**：不是 FIFO，是按 weight。`_prune()` 先清理已完成和沉底的，超过 20 条时保留前 20 名。重要的纸不会被挤掉，不重要的自然消失。

### 序列化：跨会话持久化

Desk 随 SelfImage 的 JSON 快照一起存取。Agent 启动时恢复桌面状态，不会丢掉之前的分析。但 `from_dict()` 后会立即 `clear_completed()`，确保已完成项不残留。

## 读写路径

### 数据流

```
                    ┌──────────────────────────────┐
                    │          Desk（桌面）          │
                    │   MAX=20, MIN_WEIGHT=0.15    │
                    └──────┬───────────┬───────────┘
                           ↑ WRITE     │ READ
                           │           │
L2 tick() 完成后            │     inject_consciousness()
  ├─ 意图决策 (source="L2",  │        │
  │   intent="work")        │   _assemble_daily()
  └─ 意识涌现摘要            │   _assemble_task()
     (intent="reflect")     │   _assemble_reflect()
                            │        │
Action 完成后                │   _render_desk()
  ├─ drop 工作结果           │   → peek_for_prompt()
  └─ complete_by_source("L2")│   → 注入 system prompt
                            │   → touch() 标记已读
```

### 写入点

**L2 Engine** — `tick()` 结束时调用 `_drop_to_desk()`：

```python
# 1. 意图决策 —— 最高置信度
desk.drop(
    content=f"L2 意图决策：work — 审计认证模块，发现3处安全漏洞",
    source="L2",
    intent="work",
    confidence=0.85,
)

# 2. 意识涌现摘要 —— 供后续模块参考
desk.drop(
    content=f"L2 内心独白：认证模块的token验证逻辑不够严谨...",
    source="L2",
    intent="reflect",
    confidence=0.6,
)
```

**Action Executor** — 工作和闹钟完成后：

```python
# 投放工作结果
si.desk.drop(
    content=f"Work 完成：审计了认证模块，修复了3处漏洞，已提交代码",
    source="action",
    intent="work",
    confidence=0.7,
)

# 消费 L2 的分析
si.desk.complete_by_source("L2")
```

### 读取点：不需要额外代码

所有 LLM 调用统一通过 `inject_consciousness()` → `_render_desk()` → `peek_for_prompt()`。LLM 看到的 system prompt 里会多一段：

```
****以下是桌面上的上下文（之前的思考/分析/进展，不是记忆）****
桌上有 2 条相关上下文：
── L2 work（刚刚, w=0.91）──
L2 意图决策：work — 审计认证模块，发现3处安全漏洞
── L2 reflect（刚刚, w=0.45）──
L2 内心独白：认证模块的token验证逻辑不够严谨，需要重点关注...
```

涵盖三种组装模式（daily 日常对话 / task 任务执行 / reflect 反思内省），desk 始终出现在 inner_voice 之后、记忆之前——位置固定，LLM 形成稳定预期。

## 生命周期示例

一个完整的 L2 → Action 循环：

```
[L2 醒来，分析状态]
  └─ L2 tick() 完成
     ├─ drop("意图：work — 审计认证", source="L2", intent="work")
     └─ drop("内心独白：token验证有问题...", source="L2", intent="reflect")
     → Desk: 2 条

[桌面状态]
  L2/work    w=0.91  ← 高权重：置信度 0.85 + work 意图 + goal_related
  L2/reflect w=0.45

[Action 触发 WORK]
  inject_consciousness() 中看到桌面：
  "桌上有 2 条相关上下文..."
  LLM 知道：L2 已经判断要做 work，范畴是"认证模块审计"
  → 不会重新决策，直接拿 L2 的分析当起点

[Action 执行完成]
  ├─ drop("Work 完成：修复了3处token验证漏洞", source="action")
  └─ complete_by_source("L2") → L2 两条 weight → 0.05
  → Desk: 1 条活跃（action 的结果）

[时间流逝]
  1 小时后 action/work w=0.70×0.97=0.68
  24 小时后 w≈0.70×0.49=0.34
  48 小时后 w≈0.70×0.23=0.16  ← 接近沉底阈值
  → 不重要的自然消失，重要的会在下一次 peek 时因 access_bonus 保持活跃
```

## 设计决策回顾

### 为什么不需要 FIFO？

人类的记忆不是先进先出。重要的记忆（情绪激动时留下的、关联目标的、反复回忆的）会粘住，不重要的自然遗忘。FIFO 是最差的淘汰策略。

### 为什么 "被读了" 不用 LLM 判断？

`touch()` 是代码层面标记的——只要 `peek_for_prompt()` 返回了这条就 +1。不需要 LLM 判断"我读了吗"，因为放进 prompt 就等于读了。简单、可预测、不消耗 token。

### 为什么 complete_by_source 而不是逐条 complete？

Action 启动时看到了 L2 的分析，执行完成后 L2 的分析就应该"翻过去"。不需要逐条指定要完成哪些——"L2 上一轮的分析"作为一个整体被消费，语义清晰。

### 为什么不定义协议？

如果要定义"L2 到 Action 的通信协议"，你需要：
1. 定义消息格式
2. 定义路由规则
3. 定义序列化方式
4. 维护双向引用
5. 每增加一个模块，所有可能相关的模块都要更新

而 Desk 只需要一个操作：`drop(content, source="L2")`。接收方不需要任何适配——它看到的 system prompt 里自动就多了相关内容。这是"无需协议"的真正含义：不是没有规则，是规则降到了最低。

## 局限和后续

1. **桌面 item 不能太大**——content 截断到 2000 字，如果 L2 产出了很长分析需要通过"保存到记忆 + 桌面上放引用"的方式
2. **不支持结构化数据**——当前只能放文本，如果 Action 需要结构化的 L2 输出（如具体的漏洞列表），需要走记忆系统
3. **序列化依赖 SelfImage**——Desk 本身不独立持久化，随 SelfImage 快照一起，适合当前场景但如果 Desk 膨胀可能需要独立存储
4. **"被读了但没用"无法检测**——touch 只记录放进 prompt 了，不判断 LLM 是否真的采纳了内容

## 总结

Desk 本质上是在模仿一个非常古老的 UI 隐喻——桌面。这个隐喻之所以经久不衰，不是因为它高效，是因为它**符合认知**。不需要学，不需要配置，不需要维护。

对 AI Agent 的模块间通信来说，最重要的洞察是：**大部分时候不需要精确通信**。L2 不需要"告诉" Action 什么——它只需要把想法放在一个大家都看得到的地方。Action 自己会看，自己会判断。就像你不会给同事的每个文件都写 README——放在桌上就行了。
