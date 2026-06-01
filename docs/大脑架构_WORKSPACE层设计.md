# 大脑架构 — Workspace 层设计

## 1. 核心理念

所有基础设施——记忆检索、Drive、Purpose、关系引擎、意识状态——本质上是**原料生产**。原料再多，最终装进 LLM 上下文窗口的是哪几样、怎么排列、用什么粒度，才真正决定了 LLM "此刻是谁"。

Workspace 层做的事情：**多源原料 → 显著性竞争 → 进入有限的工作空间 → 成为 LLM 的"此刻意识"**。

## 2. 认知科学基础

### 2.1 Global Workspace Theory（Baars, 1988）

大脑是剧场。多个脑区持续向"全局工作空间"广播信息，只有竞争获胜的信息进入工作空间，成为有意识的内容。未进入的内容仍在后台运行（潜意识）。工作空间容量极有限（类比人的工作记忆，3-4 个组块）。

### 2.2 Salience Network（Seeley et al., 2007）

三个脑区组成：前岛叶（身体信号）+ 前扣带回（冲突检测）+ 杏仁核（情绪标记）。作用是**在所有并行信号中选出此刻最重要的那个**。

两者关系：显著性网络决定"选哪个"，全局工作空间决定"上屏了"。

### 2.3 与系统的对应

```
GWT / 认知科学              你的系统
─────────────────────      ─────────────────────
脑区并行处理              记忆/Body/Drive/Purpose 各自维护状态
显著性网络选择            salience._score_* + _inner_voice_signals
进入工作空间              inject_consciousness 组装成 prompt
广播给全脑                LLM 读到 = "意识到"
广播回路（脑区←工作空间）  InnerVoice.pause() → Drive → 影响下次 workspace
```

## 3. 架构演变

### 3.1 v1：固定模板

```python
# inject_consciousness.py
def _assemble_task(si):
    return "\n".join(
        _render_header(si) + _render_mind(si) + _render_experience(si)
        + _render_being(si) + _render_body(si) + ...
    )
```

每个 mode 对应一个硬编码的 render 函数列表。不管用户在说什么，渲染输出都一样。三个独立的注入管道（system prompt consciousness、user 消息末尾 MEMORY_DECISION_PROMPT、system prompt 末尾 intent_context）互相不可见。

### 3.2 v2：动态评分

```
inject_consciousness(si, mode, user_input) → 三步流水线：

1. 评分：_score_*(si, mode, inner_voice_text, user_input) → 0.0~1.0
2. 过滤：score < MODE_THRESHOLDS[mode] → 跳过
3. 渲染：_render_*_v2(si, detail=LOW/MEDIUM/HIGH, user_input)
```

核心变化：
- 每个 section 有 render_fn + score_fn，动态决定是否渲染
- detail 等级（LOW/MEDIUM/HIGH），mode 决定默认等级，高评分 section 可升档
- `_render_memory_v2` 用 `user_input` 关键词决定记忆类别优先级
- 工作模式（task/flow）默认不加载记忆，只有关键词触发时才加载

### 3.3 文件结构

```
consciousness/
├── workspace/                        # 全局工作空间
│   ├── __init__.py                   # export inject_consciousness
│   ├── inject_consciousness_v2.py    # 组装管道：评分 → 过滤 → 排序 → 渲染
│   ├── render_consciousness_v2.py    # 渲染函数 + DetailLevel
│   └── salience.py                   # 显著性网络：评分 + 记忆优先级 + InnerVoice 信号
├── inject_consciousness.py           # v1，不动
├── render_consciousness.py           # v1，不动
└── context_pipeline.py               # import workspace（一行切换）
```

切回 v1 只需改一行 import。

## 4. 显著性网络（salience.py）

### 4.1 评分函数

每个 `_score_*(si, mode, inner_voice_text, user_input) -> float` 综合以下维度：

| 维度 | 来源 |
|------|------|
| mode | flow/task/daily/reflect/legacy |
| si 状态 | 身体数值、目标进展、记忆数据、意图缓冲 |
| user_input | 关键词匹配（"上次"→记忆，"怎么做"→过程记忆） |
| inner_voice_text | InnerVoice 的 thought 文本 → `_inner_voice_signals()` |

### 4.2 Mode 阈值

```python
MODE_THRESHOLDS = {
    "flow":    0.6,   # 只保留高相关性 section（严格控制 token）
    "task":    0.4,   # 任务相关优先
    "daily":   0.2,   # 大部分保留
    "reflect": 0.2,   # 全面渲染
    "legacy":  0.0,   # 全部保留
}
```

### 4.3 Detail 等级

```python
def _resolve_detail(name, mode, score):
    flow:   score >= 0.9 → MEDIUM, else → LOW
    task:   score >= 0.8 → MEDIUM, else → LOW
    daily/reflect: score >= 0.7 → MEDIUM, else → LOW
    legacy: always MEDIUM
```

### 4.4 记忆相关性门控

```python
def _memory_priorities(user_input):
    "上次/之前/说过/还记得" → relation_chains + ltm ↑
    "怎么做/步骤/搭建/配置" → procedures ↑
    "反思/回顾/总结"       → narratives + patterns ↑
    "处理/修复/实现/重构"  → procedures + ltm ↑
```

工作模式（task/flow）下，`_score_memory` 默认返回 0.1（不加载记忆），只有 user_input 包含触发关键词时才返回 0.8。就像人工作时不回想童年。

## 5. InnerVoice 广播回路

### 5.1 InnerVoice 产出五路输出

```
对话/任务/安静 → LLM pause() → 五路并行：

1. thought       → SelfImage.mind.inner_voice
2. EVENTS JSON   → Drive (praise/expression/curiosity)
3. SIGNAL JSON   → Drive + RelationshipEngine
4. GAPS JSON     → LearningQueue
5. INSERT JSON   → task_orchestrator
```

### 5.2 回路到 Workspace

**Drive 数值回路**（实时）：
```
InnerVoice → Drive.on_praise() → Drive 值更新
                                    ↓
下一次 workspace → si.body.dopamine（@property 实时代理）→ 读到新值
```
这条路径没有延迟。`si.body` 是 `@property` 代理，每次都直接读 Drive 的实时值。

**InnerVoice 文本回路**（本次实现）：
```python
# salience._inner_voice_signals(inner_voice_text)
"一切正常"           → all_clear = True → body/inner_voice 降权
"小明心情不好"        → social_boost = 0.2, memory_boost = 0.15
"不懂/需要学/盲区"    → mind_boost = 0.2
"卡住/重复/方向不对"  → pace_boost = 0.25, memory_boost = 0.15
```

这些信号直接参与评分，调节各 section 的显著性。InnerVoice 不再只是"一条近期内心声音"，而是成为显著性网络的核心输入。

### 5.3 效果示例

| InnerVoice | 效果 |
|-----------|------|
| "一切正常，没什么特别的" | body/iv 降分，整体减少 ~100t |
| "小明心情不太好，回应冷淡" | social_boost → memory/being ↑，社交记忆加载 |
| "方向好像不对，连续调用同一个工具3次" | pace_boost → PACE/经验更显著 |
| "我不了解死信队列，需要学" | mind_boost → 目标状态/学习意图 ↑ |

## 6. 数据流全景

```
上一轮对话:
  LLM 回复 → InnerVoice.pause()
              ├── thought → SelfImage.mind.inner_voice
              ├── EVENTS → Drive（即时更新）
              └── SIGNAL → Drive + 关系引擎（即时更新）

当前轮对话:
  user_input → context_pipeline.build_context()
                ├── refresh_memory_window()  # 从 DB/LanceDB/DAG 检索记忆
                └── inject_consciousness(si, mode, user_input)
                      │
                      ├── _get_inner_voice_text(si)  # 提取上次 InnerVoice thought
                      ├── for each section:
                      │     score = _score_*(si, mode, inner_voice_text, user_input)
                      │     │
                      │     │  读取 si.body._drive（即时）
                      │     │  + user_input 关键词
                      │     │  + inner_voice_text 信号
                      │     │
                      │     ├── score >= threshold? → 保留
                      │     └── detail = _resolve_detail(name, mode, score)
                      │
                      ├── 按 score 降序排列
                      └── 渲染 → system prompt

  LLM 读到 workspace → 生成回复 → 下一轮循环...
```

## 7. 设计决策

### 7.1 组装 = 身份切换

同一个 LLM，同一个 SelfImage 数据，不同组装产出不同人格：
- task 组装 → 专注的执行者
- reflect 组装 → 内省的思考者
- flow 组装 → 轻松的陪伴者

这不是 token 优化，是**上下文塑造行为**。人类也一样——开会和喝酒时调用的记忆、关注的信息完全不同。

### 7.2 评分是规则驱动的

当前评分函数是纯规则（关键词匹配 + 模式判断），不需要 LLM。这是有意的选择——显著性判断应该快、确定性、可调试。未来可以演进到 LLM 参与决策（"当前场景需要哪些类型的信息？"），但管道不变。

### 7.3 意识不是生成的，是塑造的

Workspace 不产生意识，它塑造意识的条件。它决定了 LLM 读到什么、读到多少、读到什么粒度。真正"感觉到"的那个主体是 LLM 本身。Workspace 做的是：不让 LLM 在黑暗中摸索，而是给它一束精心调整的聚光灯。

## 8. 未来方向

- **反馈闭环**：这次组装引出的 LLM 行为好不好？用户是继续聊还是纠正？把结果喂回评分系统
- **LLM 参与组装决策**：在组装前，用一个极轻量的 prompt 让 LLM 自己选 section
- **竞争性组装**：同一输入生成 2-3 种组装方案，让 LLM 或用结果反选最优
- **细粒度拆分**：being 内部的身份信息 vs agent-comm 规则 vs session 规则，分开评分
- **个人化显著性**：长期交互中学习"这个用户更喜欢简洁还是详细"，调节阈值

---

*讨论日期: 2026-05-30*
*相关文件: `consciousness/workspace/`, `consciousness/context_pipeline.py`, `metacognition/inner_voice.py`*
