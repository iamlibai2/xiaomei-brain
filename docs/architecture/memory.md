# 记忆层（Memory）详解

> 对应目录：`src/xiaomei_brain/memory/`
>
> 记忆层是整个架构的**基础设施**——所有其他层都依赖它。

---

## 核心理念

记忆层模拟人脑的海马体-新皮层架构：

```
┌─────────────────────────────────────────┐
│  新皮层（Neocortex）                      │
│  存储：事实、概念、经验                    │
│  对应：LongTermMemory, DAG 摘要           │
└────────────────┬────────────────────────┘
                 │ 检索
                 ▼
┌─────────────────────────────────────────┐
│  海马体（Hippocampus）                   │
│  功能：快速写入、关联检索、情景记忆         │
│  对应：ConversationDB, Extractor          │
└─────────────────────────────────────────┘
```

所有其他层对记忆的依赖：

| 层 | 依赖 Memory 的什么 |
|---|---|
| **Metacognition** | 学过什么、上次怎么做、策略效果 |
| **Purpose** | 用户历史偏好、之前的目标、对话上下文 |
| **Drive** | 奖励历史、情绪状态变化、欲望满足记录 |
| **Agent** | 工具使用经验、执行结果 |

---

## 六种记忆系统

### 1. ConversationDB（对话日志）

> `conversation_db.py`

存储所有原始对话消息，永不删除。

```python
class ConversationDB:
    """SQLite 数据库，存储原始对话日志。"""

    def append(self, user_id: str, session_id: str, role: str, content: str, msg_id: str):
        """写入一条消息。"""

    def recent(self, user_id: str, session_id: str, limit: int = 40) -> list[dict]:
        """获取最近 N 条消息。"""

    def search(self, user_id: str, query: str, limit: int = 10) -> list[dict]:
        """FTS5 全文搜索。"""

    def sessions(self, user_id: str) -> list[dict]:
        """列出用户的所有会话。"""
```

- 存储格式：`(id, user_id, session_id, role, content, msg_id, created_at)`
- 使用 **FTS5** 支持全文搜索
- 每个 Agent 一个 `brain.db` 文件

### 2. DAG 摘要（层次化压缩）

> `dag.py`

将对话历史压缩为 **有向无环图（DAG）** 结构，避免上下文窗口被历史撑爆。

```
原始消息 (每 8 条)
    │
    ▼
叶子摘要 (Leaf Node) ← 每 8 条消息压缩为 1 个叶子
    │
    ▼
父摘要 (Parent Node) ← 多个叶子压缩为更高级摘要
    │
    ▼
根摘要 (Root Node)   ← 整个会话的最高层摘要
```

```python
class DAGSummaryGraph:
    def compact(self, messages: list[dict], session_id: str) -> str | None:
        """每 8 条消息 → 生成叶子摘要。返回摘要文本。"""

    def get_context(self, session_id: str, max_tokens: int = 4000) -> str:
        """获取压缩后的历史上下文（分层摘要）。"""

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        """向量搜索相关摘要节点。"""
```

**关键设计**：
- 每 **8 条**消息压缩为一个叶子摘要
- 叶子摘要使用 LLM 生成
- 摘要节点存储在 LanceDB 中，支持向量检索
- 叶子用"发现"的 4K token 窗口生成

### 3. 长期记忆（LongTermMemory）

> `longterm.py`

语义化记忆，用向量检索。笔记、事实、概念、经验。

```python
class LongTermMemory:
    def remember(self, content: str, source: str, user_id: str, metadata: dict = None):
        """存储一条长期记忆。"""

    def recall(self, query: str, user_id: str, top_k: int = 10) -> list[dict]:
        """语义检索相关记忆。"""

    def forget(self, memory_id: str):
        """删除/衰减一条记忆。"""
```

- 使用 **LanceDB** 本地向量数据库
- Embedding 模型：**BAAI/bge-m3**（1024 维，中文优化）
- 强度衰减模型（5 级）：`ACTIVE → STRONG → NORMAL → WEAK → EXTINCT`
- 记忆以**第一人称视角**存储（"我"的视角）
- 多人场景用 `user_id` 隔离

### 4. 经验系统（Experience）

> `experience.py`, `experience_stream.py`

将经历提炼为"情境→决策→结果→教训"结构。

```python
@dataclass
class Experience:
    context: str          # 当时的情境
    decision: str         # 做了什么决策
    outcome: str          # 结果如何
    lesson: str           # 学到了什么
    timestamp: float
    user_id: str
```

- 在梦境阶段自动提取
- 用于指导未来的类似情境决策
- 支持向量检索

### 5. 过程记忆（Procedure）

> `procedure.py`

**学会的工作流程**。记录"遇到 X 情境时，按 Y 步骤做"。

```python
@dataclass
class Procedure:
    trigger: str          # 触发条件
    steps: list[str]      # 步骤序列
    success_rate: float   # 成功率
    user_id: str
```

- 从成功/失败的经验中提炼
- 逐步积累的过程性知识
- 支持版本演化

### 6. 模式识别（Pattern）

> `pattern.py`

**统计行为模式**。通过分析历史数据发现规律。

```python
@dataclass
class Pattern:
    name: str
    condition: dict       # 条件
    probability: float    # 概率
    confidence: float     # 置信度
```

- 用户行为模式（"用户一般早上问天气"）
- 对话模式（"每次提到考试，用户会焦虑"）
- 自动发现和维护

---

## SelfModel（自我模型）

> `self_model.py`

SelfModel 是 Agent 的"自我认知"——从 `identity.md` 加载并解析。

```python
class SelfModel:
    def load(self, agent_id: str) -> dict:
        """从 identity.md 加载身份信息。"""

    def get_system_prompt(self, user_id: str) -> str:
        """组装 system prompt（身份 + 性格 + 追求 + 记忆上下文）。"""
```

`identity.md` 的 section 包括：
- `# 名字` — 你是谁
- `# 性格` — 核心性格特征
- `# 特质` — 具体性格维度
- `# 价值观` — 道德罗盘
- `# 存在意义` — 使命宣言
- `# 追求` — 行为指南
- `# 热爱` / `# 底线` — 喜好与红线
- `# 擅长` / `# 不擅长` — 能力边界
- `# 学习兴趣` — 主动学习方向

详见 [Identity 指南](../guides/create-agent.md#identity-文件格式)。

---

## 记忆提取器

> `extractor.py`

在对话后自动提取记忆，有三种模式：

| 模式 | 触发条件 | 提取内容 |
|------|---------|---------|
| **immediate** | 关键词触发（如"记得""上次"） | 立即提取相关对话为记忆 |
| **periodic** | 每 10 轮对话 | 批量总结最近对话 |
| **dream** | 空闲 >5min | 深度反思和经验提取 |

---

## 关键设计

| 设计 | 说明 |
|------|------|
| **第一人称视角** | 记忆是"我"的经历，非客观事实库 |
| **强度衰减** | 5 级衰减，低强度记忆自动消亡 |
| **混合检索** | 向量语义检索 + 关键词 FTS5 搜索 |
| **分层压缩** | DAG 结构，不同层级提供不同粒度的历史摘要 |
| **多用户隔离** | `user_id` 隔离 + 全局共享知识 |
| **单文件存储** | SQLite + LanceDB 都在 `brain.db` 目录 |

---

## 代码路径

| 功能 | 位置 |
|------|------|
| 对话日志 | `memory/conversation_db.py` |
| DAG 摘要 | `memory/dag.py` |
| 长期记忆 | `memory/longterm.py` |
| 经验系统 | `memory/experience.py` |
| 过程记忆 | `memory/procedure.py` |
| 模式识别 | `memory/pattern.py` |
| 记忆提取 | `memory/extractor.py` |
| 自我模型 | `memory/self_model.py` |
| 记忆搜索 | `memory/search.py` |
| 里程碑 | `memory/milestone.py` |
| 叙事记忆 | `memory/narrative.py` |
| 记忆协议 | `memory/protocol.py` |
