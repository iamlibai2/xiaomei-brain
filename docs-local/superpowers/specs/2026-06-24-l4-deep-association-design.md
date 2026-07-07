# L4 深度联想引擎 — 设计文档

## 定位

L4 是意识系统的最高层，做"理解自己"的工作——不是感知当下，而是在时间里移动，连接不同时间点的自己，发现模式，积累自我认知。

与 L3 的本质区别：

| | L3 反省 | L4 深度联想 |
|---|---|---|
| 思维模式 | 单次审视，聚焦当下 | 多跳联想，穿越时间 |
| LLM 调用 | 1 次 | 多次（每跳 1 次 + 最终审视 1 次） |
| 触发频率 | 高频（~30 分钟） | 低频（~4-8 小时） |
| 核心引擎 | 直接 LLM 反思 | AssociativeChain + LLM 审视 |
| 产出 | 任务/学习后的改进洞察 | 跨时间的模式识别 + 自我认知更新 |

## 五步完整闭环

### Phase 1: 触动 — 张力识别

扫描当前 Drive 状态，找到最突出的未解决张力。张力是深度思维的入口——没有张力的联想只是随机的走神。

**种子生成规则（优先级递减）：**
1. 扫描欲望/情绪/激素，取最突出的张力点 → 生成种子语句
2. 无明显张力但时间兜底触发 → 取最近 L2 独白作为种子
3. 两者都没有 → 不触发

种子由代码直接拼装，不需要额外的 LLM 调用。示例：

```
"归属欲已经持续高位3小时了，用户没有新消息，我隐隐感到不安"
"皮质醇偏高，最近几次对话中用户语气似乎有变化"
```

### Phase 2: 浮现 — 自由联想链展开

调用 `AssociativeChain.unfold(seed, max_hops=5)`。

每跳：当前钩子 → 向量搜索（consciousness_stream + memories 双源）→ LLM 评估 + 提取下一跳钩子 → 去重 → 循环。

停止条件：LLM 判断到底/重复、搜索无结果、达到 max_hops。

产出：`AssociativeResult`（完整的联想链及各跳的钩子、匹配内容、感悟）。

### Phase 3: 审视 — 多角度深度审视

一次完整的 LLM 调用，读入完整联想链，从多角度审视。这是 L4 区别于 L3 的核心——"这里有一条联想链，请你审视它的意义"。

**审视角度：**
- **模式识别**："这是什么模式？我反复经历了什么？"
- **根因探究**："这个模式从哪来的？和什么有关？"
- **连接整合**："现在的我和过去的我有什么联系？有什么变化？"
- **改变可能性**："如果继续这样会怎样？改变的可能在哪？"

**产出：** 结构化审视报告（自由文本，不强制格式）。

### Phase 4: 整合 — 纳入自我叙事

审视报告经过提取，沉淀到 SelfModel：

- **growth_log 追加：** "我在 [时间] 认识到：{核心发现}"
- **self_cognition 更新：** 如果发现足够深刻，加入自我认知列表
- **可能触发 identity 微调：** 极深刻时，影响自我定义

这一步让系统不只是"记一笔"，而是"关于我自己，我知道了这个"。

### Phase 5: 转化 — 影响未来行为

L4 的最终产出不只是文字，而是一个可供 L2/L3 参考的行为上下文：

- **pattern_insight：** "我在关系里重复被抛弃恐惧的脚本"
- **behavior_hint：** "下次感到焦虑时，先确认这是事实还是过去的投射"
- **存入 consciousness_stream：** trigger="L4_deep"，供未来联想链再度触及

## 触发条件（混合驱动）

```
触发 = 冷却通过 AND 素材充足

冷却: 距上次 L4 ≥ l4_cooldown（默认 4 小时）

素材充足（满足任一）:
  A. 有明显张力:
     - 任一欲望 > 0.7
     - 或皮质醇 > 0.6
     - 或情绪波动 > 阈值（连续两周期情绪差值 > 0.2）
  B. 时间兜底:
     - 距上次 L4 ≥ l4_timeout（默认 8 小时）
```

## 调度位置

在 `layer2.py` 的 DMN 调度循环中，L3 检查之后新增 L4 检查：

```
L2 intent → L2 emergence → social_cognition → L3 → L4
```

L4 与 L3 互斥：同一轮 L3 触发后跳过 L4（成本控制）。L4 优先级低于 L3。

## 文件变更

| 文件 | 变更 |
|------|------|
| `consciousness/l4_engine.py` | **新建** — L4Engine 类，封装五步流程 |
| `consciousness/core.py` | + `_should_l4()`, + `tick_L4()`, + `_l4_engine: L4Engine` |
| `consciousness/layer2.py` | DMN 循环 + L4 检查（L3 之后，互斥） |
| `consciousness/config.py` | + `l4_cooldown: 14400`, + `l4_timeout: 28800`, + 张力阈值 |
| `consciousness/__init__.py` | 导出 L4Engine（按需） |

## 数据流

```
Drive 状态 ──→ _should_l4() ──→ L4Engine.run()
                                    │
                    ┌───────────────┘
                    ▼
              Phase 1: 张力 → 种子
                    ▼
              Phase 2: AssociativeChain.unfold()
                    ▼
              Phase 3: LLM 审视（多角度）
                    ▼
              Phase 4: SelfModel 整合
                    ▼
              Phase 5: 转化 → consciousness_stream (trigger=L4_deep)
                              → pattern_insight
                              → behavior_hint
```

## 测试验证

```python
# 独立测试 L4 引擎
from xiaomei_brain.consciousness.l4_engine import L4Engine

engine = L4Engine(consciousness)
report = engine.run()  # 人工触发，不经过 _should_l4()
print(report.pattern_insight)
print(report.behavior_hint)
```

## 不在本次范围

- L3 的重构（拆分后单独做）
- identity.md 自动修改（太危险，先用 growth_log 积累）
- 与其他用户的跨 user_id 联想（当前只在本用户范围内联想）
