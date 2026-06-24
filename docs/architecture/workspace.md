# 工作空间层（Workspace）详解

> 对应目录：`src/xiaomei_brain/consciousness/workspace/`
>
> Workspace 层决定 "LLM 此刻看到什么"——即上下文窗口的内容。

---

## 核心理念

所有基础设施——记忆检索、Drive、Purpose、关系引擎、意识状态——本质上是**原料生产**。原料再多，最终装进 LLM 上下文窗口的是哪几样、怎么排列、用什么粒度，才真正决定了 LLM "此刻是谁"。

**Workspace 层做的事情：多源原料 → 显著性竞争 → 进入有限的工作空间 → 成为 LLM 的"此刻意识"**。

---

## 认知科学基础

### Global Workspace Theory（Baars, 1988）

大脑是剧场。多个脑区持续向"全局工作空间"广播信息，只有竞争获胜的信息进入工作空间，成为有意识的内容。未进入的内容仍在后台运行（潜意识）。工作空间容量极有限（人的工作记忆约 3-4 个组块）。

### Salience Network（Seeley et al., 2007）

三脑区组成：前岛叶（身体信号）+ 前扣带回（冲突检测）+ 杏仁核（情绪标记）。作用是在所有并行信号中选出此刻最重要的那个。

### 与系统的对应

```
GWT / 认知科学              你的系统
─────────────────────      ─────────────────────
脑区并行处理              记忆/Body/Drive/Purpose 各自维护状态
显著性网络选择            salience._score_* + inner_voice_signals
进入工作空间              inject_consciousness 组装成 prompt
广播给全脑                LLM 读到 = "意识到"
广播回路（脑区←工作空间）  InnerVoice → Drive → 影响下次 workspace
```

---

## 架构演变

### v1：固定模板

最初的实现：每个 mode 对应一个硬编码的 render 函数列表。

```python
# inject_consciousness_v1.py
def _assemble_task(si):
    return "\n".join(
        _render_header(si) + _render_mind(si) + _render_experience(si)
        + _render_being(si) + _render_body(si) + ...
    )
```

问题：不管用户在说什么，渲染输出都一样；三个独立的注入管道互相不可见。

### v2：动态评分

```python
# inject_consciousness_v2.py
def inject_consciousness(si, mode, user_input):
    # 1. 评分：每个 section 计算显著性 0.0~1.0
    # 2. 过滤：低于阈值的 section 跳过
    # 3. 渲染：以不同详细等级渲染
```

核心变化：每个 section 有 `render_fn` + `score_fn`，动态决定是否渲染以及渲染的详细程度。

### v3：InnerVoice 集成

```python
# inject_consciousness_v3.py
def inject_consciousness(si, mode, user_input, inner_voice_text):
    # InnerVoice 的输出作为额外信号源
    # 影响显著性评分
```

InnerVoice 的自我觉察结果也会进入工作空间，让 LLM "意识到自己的状态"。

---

## 显著性评分

每个 section 的显著性由多个因素综合决定：

```python
def _score_*(si, mode, user_input) -> float:
    """计算某个 section 的显著性评分 0.0~1.0"""

    # 因素包括：
    # - 与用户输入的相关性
    # - 与当前 mode 的相关性
    # - 情绪强度
    # - 最近是否被访问过（避免重复）
    # - InnerVoice 信号的紧急程度
```

**详细等级**：
| 等级 | 说明 | 触发条件 |
|------|------|---------|
| `LOW` | 一句话总结 | 评分低 |
| `MEDIUM` | 关键信息 2-3 句 | 评分中等 |
| `HIGH` | 完整渲染 | 评分高 |

各 mode 的默认详细等级：
| mode | 默认 | 说明 |
|------|------|------|
| `daily` | MEDIUM | 日常对话，中等详细程度 |
| `flow` | LOW | 连续对话，精简渲染 |
| `reflect` | HIGH | 反省模式，详细内心状态 |

---

## 渲染 sections

当前支持的 sections：

| Section | 内容 | 评分依据 |
|---------|------|---------|
| `header` | 当前时间、用户信息 | 总是渲染 |
| `mind` | 内心声音、当前情绪 | InnerVoice 信号 |
| `experience` | 最近经验 | 与用户输入相关性 |
| `being` | 身份信息（identity.md） | mode 相关 |
| `body` | 身体状态 | 有设备时 |
| `self_image` | 自我模型摘要 | mode 相关 |
| `drive` | 情绪/欲望状态 | 情绪强度 |
| `purpose` | 目标状态 | 有活跃目标 |
| `memory` | 语义检索的记忆 | 与用户输入相关性 |

---

## 代码路径

| 功能 | 位置 |
|------|------|
| v1 渲染 | `workspace/inject_consciousness_v1.py` |
| v2 动态评分 | `workspace/inject_consciousness_v2.py` |
| v3 InnerVoice 集成 | `workspace/inject_consciousness_v3.py` |
| 渲染 v1 | `workspace/render_consciousness_v1.py` |
| 渲染 v2 | `workspace/render_consciousness_v2.py` |
| 渲染 v3 | `workspace/render_consciousness_v3.py` |
| 显著性 | `workspace/salience.py` |
| 显著性配置 | `workspace/salience_profile.py` |
