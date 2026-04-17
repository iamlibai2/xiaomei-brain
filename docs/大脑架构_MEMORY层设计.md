# 大脑架构设计：Memory 层（海马-新皮层）

> 创建时间：2026-04-17
> 状态：✅ 讨论完成，已保存

---

## 概述

Memory 层负责**存储和检索**，是整个大脑的"图书馆"。

```
┌─────────────────────────────────────────┐
│  新皮层（Neocortex）                      │
│  存储：事实、概念、经验                    │
└────────────────┬────────────────────────┘
                 │ 检索
                 ▼
┌─────────────────────────────────────────┐
│  海马体（Hippocampus）                   │
│  功能：快速写入、关联检索、情景记忆         │
└─────────────────────────────────────────┘
```

---

## 核心定位：基础设施

**Memory 层是整个大脑架构的核心基础设施。**

```
所有其他层都依赖 Memory：

┌─────────────────────────────────────────────────┐
│  Memory 层（基础设施）                            │
│  所有层都依赖它                                  │
└─────────────────────────────────────────────────┘
    ↑
    │
┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐
│Metacog. │  │ Purpose │  │  Drive  │  │BasalG.  │
└─────────┘  └─────────┘  └─────────┘  └─────────┘
```

| 层 | 依赖 Memory 的什么 |
|---|---|
| **Metacognition** | 学过什么、上次怎么做、策略效果如何 |
| **Purpose** | 用户历史偏好、之前的目标、对话上下文 |
| **Drive** | 奖励历史、情绪状态变化、欲望满足记录 |
| **Basal Ganglia** | 习惯存储、经验记录 |
| **Agent** | 工具使用经验、执行结果 |

**没有 Memory，其他层无法运作。**

---

## 两个功能区

### 1. 工作记忆（Working Memory）

当前任务的上下文，类似电脑内存：

```
当前目标：帮用户写代码
当前进度：已写完函数A，正在写函数B
用户偏好：喜欢简洁的代码
...（临时的、会话结束清空）
```

### 2. 长期记忆（Long-term Memory）

持久存储的知识和经验：

```
事实：
  - "量子计算是基于量子力学原理"
  - "Python 的列表是动态数组"

经验：
  - "上次用户问这个问题，我用这种方法解决了"
  - "用户不喜欢我解释太多"

概念：
  - "AI 是什么"
  - "编程范式有哪些"
```

---

## 主动 vs 被动模式

### 设计决定：混合模式

```
被动模式（默认）：
  → 其他层需要时调用 recall() → 返回结果

主动模式（梦境时）：
  → 空闲时自动整合
  → 主动清理低权重记忆
  → 更新索引
```

**理由**：
- 被动是必须的：避免 Memory 乱推送信息
- 主动是增强：梦境模式空闲时运行，不影响正常流程

---

## 存储结构

### 记忆类型

| 类型 | 特点 | 例子 |
|------|------|------|
| 情景记忆 | 具体时间地点 | "昨天帮用户调试了一个复杂的bug" |
| 语义记忆 | 抽象概念 | "量子计算是基于量子力学" |
| 程序记忆 | 技能/习惯 | "如何重启服务" |
| 偏好记忆 | 用户喜好 | "用户喜欢简洁注释" |

### 记忆条目结构

```python
@dataclass
class MemoryEntry:
    id: str                    # 唯一ID
    type: MemoryType           # 记忆类型
    content: str              # 内容
    embedding: list[float]    # 向量嵌入（用于语义检索）

    # 元数据
    created_at: float         # 创建时间
    last_accessed: float      # 最后访问时间
    access_count: int = 0     # 访问次数
    weight: float = 1.0      # 权重（影响检索排序）

    # 关联
    tags: list[str]          # 标签
    related_ids: list[str]   # 关联记忆ID
    source: str               # 来源：experience / knowledge / preference


class MemoryType(Enum):
    WORKING = "working"           # 当前上下文
    EXPERIENCE = "experience"     # 情景记忆
    KNOWLEDGE = "knowledge"       # 语义记忆（事实、概念）
    PREFERENCE = "preference"     # 偏好记忆
    SKILL = "skill"             # 程序记忆（已在 Basal Ganglia）
```

---

## 技术实现：混合存储方案

### 方案对比

| 方案 | 优点 | 缺点 | 适合 |
|------|------|------|------|
| 纯内存 | 快 | 重启丢失 | Working Memory |
| SQLite | SQL查询、持久化 | 向量搜索弱 | 结构化数据（偏好、索引） |
| 向量数据库 | 语义搜索强 | 需要额外服务 | 知识库 |
| **混合方案** | 各取所长 | 复杂度 | **推荐** |

### 推荐方案：SQLite + FAISS + LLM

```
理由：
- SQLite：结构化存储，跨表关联，持久化
- FAISS：高性能向量索引，毫秒级检索，本地进程内
- LLM：反思总结、评估重要性（按需，不每次调用）
```

**参考业界实践**：AI Agent 记忆系统主流架构 = SQLite 存历史 + 向量数据库做语义检索 + LLM 做反思总结

### 存储结构

```
memory/
├── working.json      # Working Memory 持久化
├── ltm.db           # SQLite 数据库（索引、标签、关联）
├── vectors.bin      # FAISS 向量索引
├── vectors.bin.ids  # 向量 ID 映射
└── dream/          # 梦境模式数据
    └── consolidate_queue.json
```

---

## 分层摘要结构

### 设计决定：两种方案

| 方案 | 结构 | 特点 | 当前选择 |
|------|------|------|---------|
| 方案A | **树结构** | 简单，每个节点一个父节点 | ✅ 采用 |
| 方案B | DAG（有向无环图） | 灵活，一个节点可多父节点 | 备选 |

**理由**：
- 对于记忆系统，分层摘要本质是树，不需要图
- 树实现更简单，调试更方便
- Lossless-claw 用 DAG 是因为对话消息可能和多主题相关，需要交叉引用
- 记忆系统（知识、经验、偏好）不需要这种灵活性

### 方案A：树结构（当前采用）

```
根节点（最高层摘要）
    ↓
子节点（中层摘要）
    ↓
子节点（叶子节点 = 原始消息块）
```

### 方案B：DAG 结构（参考 Lossless-claw）

```
原始消息 → 叶子节点 → 中层节点 → 高层节点
    ↓           ↓           ↓
 8条消息    叶子摘要    中层摘要

每一层都与源信息保持链接：
  高层摘要 → 可以展开 → 获取原始细节

特点：
- 一个节点可以有多个父节点
- 更灵活，适合交叉引用
- 实现更复杂
```

### 共用特性

无论树还是 DAG，都支持：

```
✅ 动态上下文组装：
   - 分层摘要（宏观脉络）
   - 最近 N 条原始消息（细节）

✅ 按需展开：
   - recall() 返回摘要
   - expand() 获取原始细节

✅ lcm_grep 关键词搜索
✅ lcm_describe 查看节点内容
```

```
Memory 层
    │
    ├── Working Memory（当前上下文）
    │
    ├── Short-term Memory（分层摘要 DAG）
    │     │
    │     ├── 叶子节点：原始消息分块
    │     │     └── 每 8 条消息生成一个叶子摘要
    │     │
    │     ├── 中层节点：叶子摘要的摘要
    │     │     └── 当叶子积累够多，生成更高层
    │     │
    │     └── 高层节点：抽象总结
    │           └── 最浓缩的记忆
    │
    ├── Long-term Memory（持久知识）
    │     └── 知识库、经验库、偏好库
    │
    └── Dream Mode（巩固）
          └── 梦境时：整合 → 更新权重 → 清理
```

### 梦境模式（巩固）

```python
class DreamMode:
    """梦境模式 - 记忆整合"""

    def activate(self, memory):
        """空闲时激活"""
        # 1. 获取当天经历
        today_events = memory.working.get_today_events()

        # 2. 回放 + 整合
        for event in today_events:
            # 生成/更新叶子节点
            memory.create_leaf_summary(event)

            # 如果叶子积累够多，生成更高层
            if memory.leaf_count > THRESHOLD:
                memory.create_higher_summary()

        # 3. 更新权重
        memory.update_weights()

        # 4. 清理低权重记忆
        memory.cleanup_low_weight()

        # 5. 重建索引
        memory.rebuild_index()
```

---

## 检索算法

### 多路召回 + 合并排序

```python
def recall(self, query: str, context: dict = None, top_k: int = 5) -> list[RecallResult]:
    """
    检索记忆

    1. 多路召回
    2. 合并排序
    3. 去重过滤
    """
    results = []

    # 1. 精确匹配（SQLite）
    exact = self._exact_match(query)
    results.extend(exact)

    # 2. 标签匹配
    tagged = self._tag_match(query)
    results.extend(tagged)

    # 3. 向量语义搜索（FAISS，毫秒级）
    semantic = self._semantic_search(query, top_k=10)
    results.extend(semantic)

    # 4. 关联扩展
    if results:
        related = self._expand_related([r.id for r in results])
        results.extend(related)

    # 5. 合并排序
    ranked = self._rank_results(results, query, context)

    return ranked[:top_k]


def _rank_results(self, results: list, query: str, context: dict) -> list[RecallResult]:
    """
    综合评分排序

    score =
        relevance * 0.4 +        # 向量相似度
        recency * 0.2 +         # 最近访问
        weight * 0.3 +          # 记忆权重
        context_match * 0.1     # 与当前上下文匹配
    """
    for r in results:
        r.score = (
            r.relevance * 0.4 +
            r.recency * 0.2 +
            r.weight * 0.3 +
            r.context_match * 0.1
        )

    return sorted(results, key=lambda x: x.score, reverse=True)
```

### 按需展开（参考 lcm_expand）

```python
def recall(self, query: str, context: dict = None, top_k: int = 5) -> RecallResult:
    # 1. 检索相关记忆
    matched = self._search_summaries(query)

    # 2. 返回摘要
    result = RecallResult(
        summary=matched.summary,
        memory_id=matched.id,
        can_expand=True  # 标记可以展开
    )

    # 3. 如果需要细节，展开
    if context.get('need_details'):
        result.expanded = self._expand(matched.id)

    return result


def expand(self, memory_id: str) -> str:
    """展开摘要，获取原始内容"""
    node = self.get_node(memory_id)
    if node.is_leaf:
        return node.original_content
    # 递归展开所有子节点
    children = self.get_children(memory_id)
    return "\n".join(self.expand(child.id) for child in children)
```

---

## 与其他层的关系

```
┌─────────────────────────────────────────────────┐
│  Memory 层                                       │
│                                                  │
│  被依赖：                                        │
│  ← Metacognition（需要知道学了什么）              │
│  ← Purpose（需要用户偏好、历史）                  │
│  ← Drive（需要奖励历史）                         │
│  ← Basal Ganglia（需要习惯存储）                 │
│  ← Agent（需要经验参考）                         │
│                                                  │
│  依赖：                                          │
│  → SQLite（结构化存储）                          │
│  → FAISS（向量索引）                             │
│  → LLM（反思总结，按需）                         │
└─────────────────────────────────────────────────┘
```

### 典型流程

```
Agent 执行任务
    ↓
记录结果 → Memory.store()
    ↓
Metacognition 需要知道什么
    ↓
Memory.recall() → 返回相关记忆
    ↓
影响 Basal Ganglia 决策
    ↓
梦境模式空闲时
    ↓
巩固 Working → Long-term
```

---

## 完整接口

```python
class Memory:
    """Memory 层统一接口"""

    def __init__(self, config: MemoryConfig):
        # Working Memory
        self.working = WorkingMemory(config.working_memory_path)

        # Long-term Memory
        self.sqlite = SQLiteStore(config.ltm_db_path)
        self.vector = VectorStore(config.vector_index_path)

        # 向量化模型
        self.embedding_model = config.embedding_model

        # 梦境模式
        self.dream = DreamMode(self)

    # ========== 核心接口 ==========

    def store(self, content: str, memory_type: MemoryType, **kwargs):
        """存储记忆"""
        # 1. 生成向量
        embedding = self.embedding_model.encode(content)

        # 2. 存入 SQLite
        entry = MemoryEntry(
            id=str(uuid.uuid4()),
            type=memory_type,
            content=content,
            embedding=embedding,
            **kwargs
        )
        self.sqlite.add(entry)

        # 3. 存入向量索引
        self.vector.add(entry.id, embedding)

        # 4. 标记待巩固
        if memory_type != MemoryType.WORKING:
            self.consolidation_queue.append(entry.id)

    def recall(self, query: str, context: dict = None, top_k: int = 5) -> list[RecallResult]:
        """检索记忆"""
        ...

    # ========== 梦境模式 ==========

    def start_dream(self):
        """开始梦境模式"""
        self.dream.consolidate()

    # ========== 展开 ==========

    def expand(self, memory_id: str) -> str:
        """展开摘要，获取原始内容"""
        ...
```

---

## 设计决定

| 项目 | 决定 |
|------|------|
| 主动/被动 | 混合模式：被动为默认，主动在梦境时 |
| 存储方案 | SQLite + FAISS + LLM |
| 向量数据库 | FAISS（单机进程内，毫秒级检索） |
| 分层摘要 | 参考 Lossless-claw，DAG 结构 |
| LLM 使用 | 按需调用（反思总结），不每次检索都调用 |

---

## 与 Lossless-claw 对比

| Lossless-claw | 我们的设计 | 说明 |
|---|---|---|
| DAG 分层摘要 | DAG 分层结构 | 从具体到抽象 |
| 全量持久化 SQLite | SQLite + FAISS | 原始内容存 SQLite，向量存 FAISS |
| 按需展开 lcm_expand | expand() 方法 | 可还原原始细节 |
| 动态上下文组装 | recall() + expand() | 摘要 + 细节 |
| 无向量搜索 | FAISS 向量检索 | 语义匹配更快 |

---

## 关键洞察

1. **Memory 是基础设施**：所有层都依赖它，是整个架构的核心
2. **混合存储最优**：SQLite + FAISS + LLM 各取所长
3. **向量数据库必要**：毫秒级检索，不需要每次都调 LLM
4. **分层摘要参考 Lossless-claw**：平衡保留细节和节省资源
5. **梦境模式主动整合**：空闲时自动巩固记忆
