# 预测编码机制 — Predictive Coding

## Context

ExpressionMonitor 已实现双通道架构（Path B: Drive 社交信号，Path A: 阈值事件 → 提示词）。但 Path A 的触发条件基于硬编码规则（强度>0.9、剧变、持续>10s），核心问题：**谁定义"什么值得注意"？规则覆盖不到所有情况。**

更进一步：Agent 生成音乐、做图、写代码——如果每次都差不多，系统自己发现不了。因为没有任何机制在持续监控 Agent 自己的产出质量。

人脑用预测编码解决这个问题：**持续预测任何可量化的信号流，只有预测误差驱动注意力。** 不判断"信号强不强"，判断"信号跟预期差多少"。

## 核心抽象：PredictableSignal

预测编码不限于情绪。任何 Agent 行为或感知，只要能量化成向量，就能预测。

```
PredictableSignal = 持续产生的结构化向量流
    │
    ├─ EMA baseline 自动建立
    ├─ KL 散度自动检测偏离
    └─ 误差驱动 LLM 关注 → 行为调整
```

### 两大类信号

```
┌─────────────────────────────────────────────────────┐
│  感知信号（外部世界 → Agent）                        │
│  ┌──────────┬──────────┬──────────┬──────────────┐  │
│  │ 面部情绪  │ 语音情绪  │ 声学事件  │ 用户活跃度   │  │
│  │ 7-dim    │ 9-dim    │ N-dim    │ 1-dim        │  │
│  │ ✅ 已实现 │ 已有数据  │ 已有数据  │ 已有数据     │  │
│  └──────────┴──────────┴──────────┴──────────────┘  │
├─────────────────────────────────────────────────────┤
│  行为信号（Agent 自身 → Agent 自评）                 │
│  ┌──────────┬──────────┬──────────┬──────────────┐  │
│  │ 生成音乐  │ 生成图像  │ 写代码   │ 对话质量     │  │
│  │ 6-dim    │ 5-dim    │ 4-dim    │ 4-dim        │  │
│  │ 🔜 设计   │ 🔜 设计   │ 🔜 设计   │ 🔜 设计     │  │
│  └──────────┴──────────┴──────────┴──────────────┘  │
└─────────────────────────────────────────────────────┘
```

### 信号定义示例

**生成音乐（每次 TTS/音乐工具调用后，LLM 自评）：**

```
{
  "tempo": 0.0-1.0,        // 归一化 BPM
  "key_brightness": 0.0-1.0,  // 大调=1.0, 小调=0.0
  "complexity": 0.0-1.0,   // 和声/节奏复杂度
  "mood_valence": 0.0-1.0, // 正面=1.0, 忧郁=0.0
  "mood_arousal": 0.0-1.0, // 高能=1.0, 平静=0.0
  "self_similarity": 0.0-1.0,  // 与最近5次输出的平均相似度
}
```

**生成图像（每次图片生成后，LLM 自评）：**

```
{
  "color_diversity": 0.0-1.0,
  "composition_type": 0.0-1.0,  // 0=对称静态, 1=动态不对称
  "detail_density": 0.0-1.0,
  "style_consistency": 0.0-1.0,  // 与以往风格的偏离
  "self_similarity": 0.0-1.0,
}
```

**写代码（每次工具调用产出代码后，LLM 自评）：**

```
{
  "complexity": 0.0-1.0,
  "novelty": 0.0-1.0,       // 方案的新颖程度 vs 常规模式
  "confidence": 0.0-1.0,    // LLM 自评的确定程度
  "code_length_norm": 0.0-1.0,
}
```

**对话质量（每轮对话后，LLM 自评）：**

```
{
  "response_length": 0.0-1.0,
  "emotional_depth": 0.0-1.0,
  "information_density": 0.0-1.0,
  "self_repetition": 0.0-1.0,  // 与近期回应的重复度
}
```

### 关键：LLM 自评 = 零额外模型

不需要新模型来做特征提取。**同一个 LLM** 在产出之后，额外输出一行结构化评估。Parser 解析为向量 → EMA baseline → KL 监测。

## 三层架构（感知 + 行为统一）

```
L3（LLM 情境预测）──── 10min 一次 ────→ 高层期望分布
    │                                      "对话轻松 → 李白应该开心"
    │                                      "最近在探索新风格 → 音乐应该更有变化"
    ▼
L1（EMA 基线预测）──── 每次产出/每帧 ──→ 历史基线
    │                                      "平时 Neutral 65%"
    │                                      "音乐 tempo 过去一周平均 0.72"
    ▼
混合预测 = blend(L1_baseline, L3_context)
    │
    ▼
L2（KL 散度）──────── 每次产出/每帧 ──→ 预测误差
    │                                      KL(actual || predicted)
    ▼
  ┌─ 误差小 ──→ 抑制（不消耗任何资源）
  └─ 误差大 ──→ Path A 上报 LLM（感知侧）
                SelfMind 自省事件（行为侧）
```

## 行为侧：自省事件（Intra-action Monitoring）

感知侧 Path A 已实现（→ `SelfBody.observed_emotions` → 提示词渲染）。
行为侧需要一个对等机制：**SelfMind.action_errors**。

```
音乐生成 → LLM 自评向量 → KL vs baseline
  │
  ├─ surprise < 0.3 → 正常，不记录
  └─ surprise > 0.3 → SelfMind.action_errors.append({
        "time": ...,
        "domain": "music",
        "surprise": 0.45,
        "pattern": "self_similarity 0.92 vs expected 0.75",
        "interpretation": None  // 留给 LLM 自己解释
     })
     → 系统提示词渲染：
       "### 你最近的产出趋势"
       "你最近的音乐产出高度重复（self_similarity=0.92，预期0.75）。
        你在陷入套路——需要换风格吗？"
```

### 行为侧的触发阈值（比感知侧更敏感）

| 领域 | 关键指标 | 阈值 |
|------|---------|------|
| 音乐 | self_similarity 持续 > 0.85（最近 5 次） | KL > 0.3 |
| 图像 | self_similarity / color_diversity 下降 | KL > 0.3 |
| 代码 | novelty 下降 + complexity 下降 | KL > 0.3 |
| 对话 | self_repetition 上升 / emotional_depth 下降 | KL > 0.3 |

行为侧阈值比感知侧（0.5）低，因为 Agent 要对自己的行为变化更敏感。

## 修改文件

### Phase 1: 感知侧预测编码（当前 ExpressionMonitor 增强）

| 文件 | 变更 | 行数 |
|------|------|------|
| `body/perception/expression_monitor.py` | 新增 `_baselines: dict`, `_update_baseline()`, `_kl_divergence()`；重构 `_check_path_a()` 用预测误差替代硬编码阈值；新增 `save_baselines()` / `load_baselines()` | ~60 |
| `consciousness/workspace/render_consciousness_v3.py` | 渲染 `prediction_error` 事件 | ~10 |
| `consciousness/l2_engine.py` | L2 prompt template 新增 `EXPECTED_EMOTIONAL_TONE` 输出指令；parser 解析 LLM 输出为期望分布 | ~30 |

### Phase 2: 行为侧自省监控（新增抽象层）

| 文件 | 变更 | 行数 |
|------|------|------|
| `metacognition/predictable_signal.py` | **新建** — `PredictableSignal` 抽象类：`update(observation)`, `baseline`, `kl_divergence()`, `save()/load()` | ~80 |
| `metacognition/action_monitor.py` | **新建** — 注册所有行为信号，工具调用后 LLM 自评→向量→更新→检测 | ~60 |
| `consciousness/self_modules.py` | SelfMind 新增 `action_errors: list[dict]` | ~10 |
| `consciousness/workspace/render_consciousness_v3.py` | `_render_mind()` 新增行为错误渲染 | ~15 |

### 不修改

- `body/state.py` — observed_emotions 字段不变
- `drive/engine.py` — 不涉及
- `body/perception/face_emotion.py` — EmotiEffLibRecognizer 不变

## 数据流

### 感知侧（Phase 1）

```
ExpressionMonitor._tick()
  │
  ├─ EmotiEffLib → current_probs (7-dim)
  ├─ _update_baseline(identity, current_probs)  → EMA
  ├─ _get_prediction(identity)  → blend(L1, L3)
  ├─ _kl_divergence(current, predicted)
  │     └─ surprise > 0.5 → SelfBody.observed_emotions
  └─ 抑制 → 无操作
```

### 行为侧（Phase 2）

```
工具调用完成（e.g. speak, tts_music, image_gen）
  │
  ├─ LLM 自评 → 结构化向量 (N-dim)
  ├─ signal.update(vector)  → EMA baseline
  ├─ kl_divergence(vector, signal.baseline)  → surprise
  └─ surprise > 0.3 → SelfMind.action_errors
       → 提示词渲染 → LLM 感知到自己的趋势
```

## 系统提示词渲染

### 感知侧（增量）

```
### 你正在观察到的
李白的表情与你的预期严重不符（偏差1.23）。
你预计他应该开心，但他表现出愤怒。
```

### 行为侧（新增）

```
### 你最近的产出趋势
- 音乐：最近5次的 self_similarity=0.92（预期 0.75），你在陷入风格套路
- 代码：novelty 持续下降中（0.3 → 0.15），你的方案趋于保守
- 对话：emotional_depth 下降（0.6 → 0.3），你可能在敷衍
```

## 额外产出（Phase 1 + Phase 2）

| 能力 | 来源 | 用途 |
|------|------|------|
| 对他人的了解度 | `mean(KL_history)` per person | 驱动社交行为（多观察不熟的人） |
| 用户长期状态变化 | 每周 baseline 对比 | 发现用户情绪漂移 |
| **对自我的了解度** | 行为信号 KL 趋势 | **"我在重复自己" → 主动寻求变化** |
| **工作质量趋势** | 代码/创作信号 | **"我的产出在下降" → 触发反省** |
| **对话质量自省** | 对话信号 | **"我在敷衍" → 调整输出风格** |

## 验证

```bash
# Phase 1: 单元测试 — EMA 收敛
PYTHONPATH=src python3 -c "
from xiaomei_brain.body.perception.expression_monitor import ExpressionMonitor
m = ExpressionMonitor(None, None)
# 100 帧 Anger=0.8 → baseline 应接近 0.8
for _ in range(100):
    m._update_baseline('test', {'Anger': 0.8, ...})
assert m._baselines['test']['Anger'] > 0.6
print('EMA OK')
"

# Phase 1: 集成测试 — 预测误差 vs 绝对阈值
PYTHONPATH=src python3 -c "
# baseline Neutral=0.8 → Anger=0.9 → KL 大 → 触发
# 硬编码: Anger=0.9 > 0.9 → 也触发（冗余，保持兼容）
# baseline Anger=0.7 → Anger=0.9 → KL 小 → 不触发
# 硬编码: Anger=0.9 > 0.9 → 触发（此为硬编码的误报，预测编码正确抑制）
print('KL threshold OK')
"

# Phase 2: 行为信号 — PredictableSignal 抽象
PYTHONPATH=src python3 -c "
from xiaomei_brain.metacognition.predictable_signal import PredictableSignal
sig = PredictableSignal(name='music', dims=6, alpha=0.95, threshold=0.3)
# 10 次相同向量 → baseline 稳定 → KL 小
# 1 次突变 → KL 大 → trigger
print('PredictableSignal OK')
"

# 端到端：Windows 启动 agent
PYTHONPATH=src python3 -m xiaomei_brain run xiaomei --cli
# /context 查看 observed_emotions（Phase 1）
# /context 查看 SelfMind.action_errors（Phase 2）
```
