# Memory Strength 记忆强度系统设计

> 创建时间：2026-04-19
> 状态：设计完成，待实现
> 参考：神经科学依据（艾宾浩斯遗忘曲线、记忆再巩固理论、睡眠记忆巩固）

---

## 1. 背景与目标

### 1.1 问题

现有记忆系统只记录"是否有记忆"，不区分记忆的"清晰程度"。

用户期望：**越经常被使用的记忆越清晰，越久未使用的记忆越模糊**。

这对应人类大脑的**记忆活性**机制。

### 1.2 设计目标

1. 记忆有活跃度（strength），随时间和使用动态变化
2. 高 strength 记忆优先注入上下文
3. 极低 strength 记忆自动降级或休眠
4. 全部记忆永久保存（extinct 后不删除）

---

## 2. 神经科学依据

### 2.1 艾宾浩斯遗忘曲线

德国心理学家艾宾浩斯实验数据：
- 20分钟后遗忘 42%
- 1小时后遗忘 56%
- 1天后遗忘 66%
- 1周后遗忘 77%

**关键发现**：遗忘速度"先快后慢"，符合**指数衰减**规律，而非线性衰减。

### 2.2 记忆再巩固（Reconsolidation）

神经科学研究（Nature Neuroscience 2026）：
> 记忆被提取后进入不稳定状态，持续约6小时，期间可被更新、修改或强化

**设计决策**：强化不放在 recall 路径（高频路径，保持毫秒级），而是在梦境周期统一处理。

### 2.3 睡眠中的记忆巩固

多项研究：
- NREM睡眠阶段，海马体回放白天经历，通过"尖波涟漪"(SWR)将记忆转移至皮层
- 睡眠开始后前20分钟重激活最强烈
- 深度睡眠是记忆从短期到长期的关键窗口

**设计决策**：梦境 job 应在用户入睡后尽快触发（而非深夜随机），与 DreamScheduler 的 `immediate=True` 模式对齐。

### 2.4 遗忘是主动过程

小胶质细胞吞噬突触、"遗忘神经元"主动清除无用记忆。

**设计决策**：extinct（消亡）状态 = 记忆保留但沉默，不删除。符合大脑机制。

### 2.5 DRIVE 层与记忆的关系

DRIVE 层（激素系统）中的多巴胺(dopamine)与记忆强化直接相关：
- 多巴胺水平高时，记忆强化效果更强
- 这是未来 DRIVE 层实现后的扩展点

**当前设计**：暂时不考虑激素调节系数，boost_factor 固定为可配置参数。

---

## 3. 数据模型

### 3.1 Schema 变更

```sql
ALTER TABLE memories ADD COLUMN strength REAL DEFAULT 1.0;
ALTER TABLE memories ADD COLUMN last_strengthen REAL DEFAULT created_at;
-- status: active | extinct（extinct = 消亡但不删除）
ALTER TABLE memories ADD COLUMN status TEXT DEFAULT 'active';
```

### 3.2 字段说明

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `strength` | REAL | 1.0 | 记忆强度，0.0~1.0 |
| `last_strengthen` | REAL | created_at | 上次强化时间戳 |
| `status` | TEXT | 'active' | 'active' 或 'extinct' |

---

## 4. 记忆强度衰减与分级

### 4.1 衰减公式

```
effective_strength = stored_strength * base^(elapsed_hours)
```

| 参数 | 值 | 效果 |
|------|----|------|
| base | 0.9995 | 约10天从1.0衰减到0.87 |
| base | 0.9999 | 约30天从1.0衰减到0.94 |

衰减是**只读计算**，不写回数据库。只有强化时才写回 `stored_strength`。

### 4.2 五级分级

| 级别 | 名称 | strength范围 | 行为策略 |
|------|------|------------|---------|
| L1 | **活跃** | ≥ 0.8 | 总是参与 recall，直接注入上下文 |
| L2 | **可用** | 0.6 ~ 0.8 | 正常召回，daily 模式可选注入 |
| L3 | **模糊** | 0.4 ~ 0.6 | keyword/DAG expand 可找回；梦境重点强化对象 |
| L4 | **痕迹** | 0.2 ~ 0.4 | 仅出现在梦境清理扫描中 |
| L5 | **消亡** | < 0.2 | 标记 extinct，永久保留但不参与 recall |

### 4.3 三段分区

```
【清晰区】strength ≥ 0.7
  → 直接注入 ContextAssembler daily pool

【模糊区】0.4 ≤ strength < 0.7
  → semantic search 仍能命中；梦境强化重点对象

【休眠区】strength < 0.4
  → 等待降级（转 DAG 摘要或标记 extinct）
```

---

## 5. recall() 逻辑

### 5.1 查询时

```python
def recall(self, query, user_id, top_k):
    # 1. 向量召回
    candidates = self._vector_recall(query, user_id, top_k * 3)

    # 2. 过滤 extinct
    candidates = [c for c in candidates if c['status'] != 'extinct']

    # 3. 计算 effective_strength（只读，不写回）
    now = time.time()
    for c in candidates:
        elapsed_hours = (now - c['last_strengthen']) / 3600
        c['effective_strength'] = c['strength'] * (DECAY_BASE ** elapsed_hours)

    # 4. 综合排序
    # rank = semantic_similarity * (1 + effective_strength)

    return sorted(candidates, key=lambda x: x['rank_score'], reverse=True)[:top_k]
```

### 5.2 设计原则

- **不**在 recall 时写回任何数据（纯只读）
- extinct 记忆可以被 keyword 搜索找到，但不参与 semantic ranking
- effective_strength 用于排序，不改变 stored_strength

---

## 6. 梦境强化任务（dream_reinforce）

### 6.1 任务类型

```python
class DreamJob:
    type: str = "memory_reinforce"
    # 扫描条件：strength < 0.7 AND last_strengthen < 24h前
```

### 6.2 处理逻辑

```
对于每条 L3/L4 记忆（strength < 0.4 且未在24h内强化过）：
    1. 强化：strength += boost_factor * (1 - strength)
    2. 重新 embed 向量（解决向量漂移）
    3. 更新 last_strengthen = now
    4. 写回 SQLite 和 LanceDB

对于 L5 记忆（strength < 0.2）：
    如果 last_accessed < now - 30天：
        → status = 'extinct'（消亡但不删除）
        → 从 LanceDB 删除向量（SQLite 保留）
```

### 6.3 boost_factor

```python
MEMORY_REINFORCE_BOOST = 0.1  # 可配置，默认0.1

# 强化公式（边际递减）
# strength_new = strength_old + boost * (1 - strength_old)
# 例如：strength=0.2, boost=0.1 → new = 0.2 + 0.1*0.8 = 0.28
#        strength=0.8, boost=0.1 → new = 0.8 + 0.1*0.2 = 0.82
```

### 6.4 分批处理

```
每批次处理 N 条记忆（如 50 条）
避免单次梦境 job 运行时间过长
记录 last_processed_id，支持中断恢复
```

---

## 7. extinct 记忆的处理

### 7.1 原则

- **永久保留**在 SQLite，不删除
- **不参与** semantic recall
- **可以被** keyword 搜索找到
- **可以通过** DAG expand 恢复（如果原来是 DAG 摘要降级来的）

### 7.2 恢复机制

如果用户通过 `dag_expand` 工具查看了一条 extinct 记忆，可以选择"唤醒"它：
```python
def awaken_memory(self, memory_id):
    # status = 'active'
    # strength = 0.3（从痕迹状态恢复）
    # 重新 embed 向量
```

---

## 8. ContextAssembler 集成

### 8.1 daily 模式注入

```python
def _assemble_daily(self, max_tokens, session_id, user_input, user_id):
    # ... system prompt + DAG summaries ...

    # 注入高 strength 记忆
    memories = ltm.recall(user_input, user_id=user_id, top_k=20)
    # 优先选 L1/L2 记忆
    top_memories = sorted(
        [m for m in memories if m['effective_strength'] >= 0.6],
        key=lambda m: m['effective_strength'],
        reverse=True
    )[:5]

    for m in top_memories:
        system_content += f"\n- {m['content']}"
```

### 8.2 reflect 模式

reflect 模式可以扩大记忆注入范围到 L3（effective_strength >= 0.4）。

---

## 9. 配置参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `MEMORY_STRENGTH_DECAY_BASE` | 0.9995 | 指数衰减底数 |
| `MEMORY_REINFORCE_BOOST` | 0.1 | 梦境强化幅度 |
| `MEMORY_STRENGTH_L4_THRESHOLD` | 0.2 | L4 阈值 |
| `MEMORY_STRENGTH_L5_THRESHOLD` | 0.2 | L5 阈值（同 L4） |
| `MEMORY_EXTINCT_DAYS` | 30 | 超过N天未召回才标记 extinct |
| `MEMORY_REINFORCE_BATCH_SIZE` | 50 | 每批处理记忆数 |

---

## 10. 实现顺序

### Phase 1：Schema + 衰减计算（最小改动）
1. ALTER TABLE 添加字段
2. recall() 只读计算 effective_strength
3. 可配置 boost_factor

### Phase 2：梦境强化 job
1. 新增 `dream_reinforce()` 方法
2. 与 DreamScheduler 集成
3. L4/L5 降级处理

### Phase 3：ContextAssembler 集成
1. daily 模式优先注入高 strength 记忆
2. reflect 模式扩大范围

### Phase 4：extinct 恢复机制
1. dag_expand 可唤醒 extinct 记忆
2. 管理界面查看记忆状态

---

## 11. 待讨论（未纳入初始实现）

| 问题 | 选项 |
|------|------|
| DRIVE 层对接后 boost 是否乘以 dopamine 系数 | 后期实现 |
| importance 是否影响 boost 幅度 | 暂时一视同仁 |
| 用户主动"记住"某事是否强制强化 | 待定 |

---

## 12. 相关文档

- `大脑架构_DRIVE层设计.md` — 激素系统设计，dopamine 与记忆的关系
- `Memory开发计划.md` — 整体 Memory 层开发计划
- `思想.md` — 架构设计思想
