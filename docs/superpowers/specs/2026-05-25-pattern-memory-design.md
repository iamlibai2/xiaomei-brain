# Pattern Memory 设计 Spec

> 模式记忆：在梦境中从 ExperienceStream 提取跨时间的统计规律，存入 LTM，通过已有注入点影响决策。

**目标**：让系统从"反应式"升级为"预判式"——现在系统感知每个事件并反应，但缺少一个东西定期回头看数据找规律。模式记忆填补这个缺口。

**核心原则**：零新基础设施。存储复用 LTM `memories` 表，检索复用已有 API，注入走已有 SelfImage 渲染路径。

---

## 模块结构

新建一个文件，三个类：

```
src/xiaomei_brain/memory/pattern.py    ← 唯一新文件
```

| 类 | 职责 |
|---|---|
| `PatternExtractor` | 在梦境中查询数据源 → 构建 prompt → 调 LLM → 解析输出 |
| `PatternStorage` | 存/查/改 LTM `type="pattern"` 记录 |
| `PatternInjector` | 五个注入点的检索 + 格式化 |

---

## 数据结构

```python
@dataclass
class Pattern:
    """一条模式记忆"""
    content: str          # "用户深夜活跃度是白天3倍，深夜话题更深"
    category: str         # user_behavior / self_efficacy / interaction
    subcategory: str      # temporal_rhythm / topic_cluster / mood_trend / error_pattern / strategy / learning / depth_pattern / transition
    confidence: float     # 0.0-1.0
    evidence: str         # 支持该模式的证据摘要
    scene_tags: list[str] # ["深夜", "技术对话"]
    memory_id: int        # 对应 LTM memories 表 ID（存储后回填）
```

## 模式类别

| 类别 | 子类 | 说明 | 示例 |
|---|---|---|---|
| user_behavior | temporal_rhythm | 用户时间节奏 | "深夜活跃度是白天3倍" |
| user_behavior | topic_cluster | 话题偏好趋势 | "最近3周聊了6次量化交易" |
| user_behavior | mood_trend | 用户情绪趋势 | "用户情绪连续走低" |
| self_efficacy | error_pattern | 系统出错规律 | "web_fetch抓公众号100%失败" |
| self_efficacy | strategy | 策略有效性 | "主动问候成功率75%，白天差" |
| self_efficacy | learning | 学习效果反馈 | "学了量化交易后没在对话中用上" |
| interaction | depth_pattern | 交互深度规律 | "用户情绪低时先共情更有效" |
| interaction | transition | 话题过渡规律 | "聊AI架构→聊量化→聊游戏" |

---

## 梦境时序

Pattern 提取插入 DreamEngine 的 `run()` 串行流程，作为独立阶段：

```
DreamEngine.run():
  阶段1: 情绪整理（已有）
  阶段2: 记忆整理（已有）
  阶段2.5: Procedure巩固（已有）
  阶段2.x: Narrative整合（已有）
  阶段3: ★ Pattern提取（新增）    ← 位置：Narrative 之后、L3 之前
  阶段4: L3 火焰燃烧（已有）
  阶段5: 反省（已有）
```

放在 L3 之前的原因是：提取的模式可以作为输入影响 L3 的深度意识报告，但不和 L3 合并调用（各自独立 prompt）。

DreamEngine 当前没有 `exp_stream` 引用，需要注入：

```python
# conscious_living.py 中 DreamEngine 实例化处添加
exp_stream=exp_stream,  # 已有变量，直接传入
```

DreamEngine 构造函数新增参数 `exp_stream`。

---

## Prompt 设计

**调用方式**：单次 LLM 调用（非 ReAct），和 `_run_flame_burn()` 模式一致。

**输入数据**：
- 24h ExperienceStream：按类型过滤，取最近 N 条
- 24h 对话摘要：从 DAG 或 ConversationDB 获取概要
- 24h 社交信号：SocialPerception 序列
- 已有 patterns：`search_by_tags(["pattern"])` 全量加载

**输出格式**：JSON 数组

```json
{
  "patterns": [
    {
      "content": "用户深夜活跃度是白天3倍，深夜话题以技术为主",
      "category": "user_behavior",
      "subcategory": "temporal_rhythm",
      "confidence": 0.85,
      "evidence": "过去24h内，21:00-02:00出现8条用户消息，08:00-18:00仅2条",
      "scene_tags": ["深夜", "技术对话"],
      "action": "ADD"
    },
    {
      "content": "主动问候成功率从60%上升到75%",
      "category": "self_efficacy",
      "subcategory": "strategy",
      "confidence": 0.72,
      "evidence": "过去24h主动问候4次，3次用户积极回复",
      "scene_tags": ["问候", "白天"],
      "action": "UPDATE",
      "existing_pattern_id": 42
    }
  ]
}
```

action 取值与记忆系统命名一致：
- `ADD`：首次发现，创建新记录
- `UPDATE`：已有模式置信度变化（上调或下调）
- `MERGE`：两条已有模式合并

## 置信度管理

- 新发现模式：confidence 由 LLM 初始化（0.3-0.5）
- 再次观察到：confidence += 0.1（上限 0.95）
- 未观察到（已有模式不在本次输出中）：PatternStorage 自动衰减 confidence *= 0.9
- 出现反例或 LLM 明确标记 weaken：confidence -= 0.2（下限 0.05）
- confidence < 0.1：可以考虑归档（软删除或标记为 extinct）

---

## 五个注入点

| # | 注入点 | 时机 | 检索方式 | 格式 |
|---|---|---|---|---|
| 1 | 系统提示词 | 每轮对话 | `search_by_tags(["pattern"])` 按 confidence 取 top-3 | 每行一条，"我注意到：" |
| 2 | L2 intent | 加柴周期 | `recall(当前情境描述)` 语义匹配 top-2 | 单行，"当前情境相关模式：" |
| 3 | 对话上下文 | 用户发消息 | `recall(用户消息)` 语义匹配 top-2 | 单行，附加在上下文末尾 |
| 4 | 学习选题 | 学习触发 | `search_by_tags(["pattern", "topic_cluster"])` | 候选主题按模式加权 |
| 5 | 梦境提取 | 每次梦境 | `search_by_tags(["pattern"])` 全量 | 供 LLM 对比 |

---

## 与其他系统的关系

- **不碰 ProcedureMemory** — 模式记忆是独立模块
- **不碰 Narrative 记忆** — 叙事记忆是关于"我是谁"的瞬间认知转变，模式记忆是关于"正在发生什么"的跨时间规律，各存各的
- **复用 LTM** — `type="pattern"` 和 `type="knowledge"`/`type="experience"` 并存于同一 memories 表
- **依赖 ExperienceStream** — DreamEngine 需要 exp_stream 引用，ConsciousLiving 已有，传入即可
- **不影响已有梦境阶段** — 在 Narrative 和 L3 之间插入，前面各阶段不需要改动

---

## 未来扩展（不在本 spec 范围内）

- **深度复盘**：每周一次，7天全量窗口，合并低置信度碎片，清理过时模式
- **ReAct 升级**：如果单次 prompt 提取质量不够，升级到 ReAct 模式做交叉验证
- **模式 → 程序记忆**：高置信度策略模式自动生成程序记忆（"这种情况这么做更好"）
