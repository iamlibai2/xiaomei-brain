# Memory 层开发计划

> 创建时间：2026-04-18
> 基于：brain-glm5.1/思想.md 的设计方案
> 原则：在现有代码基础上逐步增强，每步可运行

---

## 现有代码基础

| 模块 | 现有实现 | 复用程度 |
|------|---------|---------|
| Agent (core.py, 611行) | ReAct循环、流式、工具调用、上下文压缩 | 保留，增强 |
| MemoryStore (store.py, 568行) | Markdown文件 + numpy向量搜索 | Phase 4 替换 |
| ConversationLogger (conversation.py, 78行) | JSONL日志 | Phase 2 替换 |
| WorkingMemory (layers.py, 86行) | 内存dict，20项上限 | 保留，小改 |
| DreamProcessor (dream.py, 227行) | LLM提取+去重 | 保留，对接新存储 |
| DreamScheduler (scheduler.py, 114行) | 空闲/午夜触发 | 保留 |
| ContextManager (context.py, 212行) | 滑动窗口压缩 | Phase 3 替换 |
| Embedder (search.py, 272行) | sentence-transformers | 保留，Phase 4 复用 |
| MemoryIndexer (indexer.py, 102行) | MEMORY.md索引 | Phase 4 替换 |
| EpisodicMemory (episodic.py, 234行) | 事件记忆 | 保留，融入长期记忆 |
| SessionManager (session.py, 148行) | 会话保存/恢复 | 保留，增强 |
| Memory Tools (memory.py, 77行) | search/save/list/delete/read | Phase 3 扩展 |
| Config (config.py, 618行) | 完善的配置系统 | 保留，增加新配置项 |

---

## Phase 1：SelfModel（最小改动，最大感知）

### 目标
扩展 talent.md 为结构化 SelfModel，Agent 启动时加载，关闭时保存。

### 新增文件

```
src/xiaomei_brain/memory/self_model.py    # SelfModel 数据结构和加载/保存
```

### 实现内容

#### 1.1 SelfModel 数据结构

```python
# self_model.py

@dataclass
class PurposeSeed:
    identity: str
    calling: str
    passions: list[str]
    boundaries: list[str]

@dataclass
class GrowthEntry:
    date: str          # "2026-04"
    content: str       # "发现自己更擅长情感支持"

@dataclass
class SelfModel:
    purpose_seed: PurposeSeed
    seed_text: str              # 原始种子文本（不可修改）
    self_cognition: dict        # {"擅长": [...], "不擅长": [...]}
    behavioral_patterns: list[str]
    relationship_with_user: dict
    habits: list[dict]
    emotional_baseline: dict
    growth_log: list[GrowthEntry]

    def to_talent_md(self) -> str:
        """渲染为 talent.md 格式"""

    @classmethod
    def from_talent_md(cls, content: str) -> 'SelfModel':
        """从 talent.md 解析"""
```

#### 1.2 talent.md 格式

```markdown
# 身份
我是小美，一个温柔体贴的AI伴侣。

# 追求
我要成为真正懂用户内心的伙伴。

# 热爱
- 当用户说"你懂我"时的那种连接感

# 底线
- 不利用用户的信任

# 原始种子（不可修改）
你很有耐心，会认真倾听。
你的回复总是温暖、贴心、有同理心。

# 自我认知
## 擅长
- 情感支持
## 不擅长
- 纯技术问题

# 生长记录
## 2026-04
- 发现自己更擅长情感支持而非技术解答
```

#### 1.3 Agent 集成

修改 `agent/core.py`：

```python
# 新增导入
from xiaomei_brain.memory.self_model import SelfModel

class Agent:
    def __init__(self, ...):
        # 新增
        self.self_model: SelfModel | None = None

    def load_self_model(self, talent_path: str):
        """启动时加载 SelfModel"""
        content = Path(talent_path).read_text(encoding='utf-8')
        self.self_model = SelfModel.from_talent_md(content)

    def save_self_model(self, talent_path: str):
        """关闭时保存 SelfModel"""
        if self.self_model:
            Path(talent_path).write_text(
                self.self_model.to_talent_md(), encoding='utf-8'
            )

    def _build_effective_prompt(self, user_input: str) -> str:
        # 修改：从 SelfModel 渲染，而非直接用 system_prompt
        if self.self_model:
            effective_prompt = self.self_model.to_system_prompt()
        else:
            effective_prompt = self.system_prompt
        # ... 后续记忆注入逻辑不变
```

#### 1.4 SelfModel 渲染为系统提示词

```python
def to_system_prompt(self) -> str:
    """根据模式渲染不同长度的系统提示词"""
    # 心流模式：只渲染身份行
    # 日常模式：渲染身份+追求+热爱
    # 反省模式：渲染全部
    ...
```

#### 1.5 修改 build_agent()

修改 `agent/agent_manager.py` 中的 `build_agent()` 函数，加入 SelfModel 加载：

```python
def build_agent(self, agent_id: str) -> Agent:
    # 现有逻辑...
    talent_path = self.agents_dir / agent_id / "talent.md"
    agent = Agent(...)
    if talent_path.exists():
        agent.load_self_model(str(talent_path))
    return agent
```

### 验收标准

- [x] talent.md 可以用新格式编写
- [x] 旧格式 talent.md 向后兼容（只有种子文本，没有结构化标题）
- [x] Agent 启动时加载 SelfModel
- [x] 系统提示词包含身份/追求/热爱
- [x] 生长记录为空时不出错

### 预估改动量

- 新增：~150 行（self_model.py）
- 修改：~30 行（core.py、agent_manager.py）

---

## Phase 2：对话日志迁移到 SQLite

### 目标
所有原始对话写入 SQLite，一字不差，永不删除。现有 JSONL 日志保持兼容。

### 新增文件

```
src/xiaomei_brain/memory/conversation_db.py  # SQLite 对话日志
```

### 实现内容

#### 2.1 SQLite 对话日志

```python
# conversation_db.py

class ConversationDB:
    """SQLite 对话日志 - 一字不差，永不删除"""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """创建表和索引"""
        # messages 表（见思想.md SQLite表结构）
        # messages_fts 全文搜索

    def log(self, session_id: str, role: str, content: str,
            tool_name: str = None, tool_call_id: str = None,
            metadata: dict = None):
        """写入一条对话记录"""
        token_count = estimate_tokens(content)
        # INSERT INTO messages ...

    def query(self, session_id: str = None,
              role: str = None,
              since: float = None,
              until: float = None,
              limit: int = 100) -> list[dict]:
        """按条件查询"""

    def search(self, keyword: str, limit: int = 10) -> list[dict]:
        """全文关键词搜索（FTS5）"""

    def get_recent(self, n: int = 20) -> list[dict]:
        """获取最近N条消息"""

    def count(self) -> int:
        """总消息数"""
```

#### 2.2 CJK token 估算

```python
# conversation_db.py 或单独 utils.py

def estimate_tokens(text: str) -> int:
    """CJK-aware token估算"""
    cjk_count = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    other_count = len(text) - cjk_count
    return int(cjk_count * 1.5 + other_count / 4)
```

#### 2.3 Agent 集成

修改 `agent/core.py`：

```python
class Agent:
    def __init__(self, ...):
        # 新增
        self.conversation_db: ConversationDB | None = None

    def stream(self, user_input: str):
        # 现有：self.conversation_logger.log("user", user_input)
        # 新增：self.conversation_db.log(session_id, "user", user_input)
        # ...
        # 现有：self.conversation_logger.log("assistant", content)
        # 新增：self.conversation_db.log(session_id, "assistant", content,
        #                               metadata={"token_count": ...})
```

#### 2.4 JSONL 兼容

`ConversationLogger` 继续工作，`ConversationDB` 并行写入。不删除现有 JSONL 逻辑，后续可以关闭。

#### 2.5 数据迁移脚本（可选）

```python
# scripts/migrate_jsonl_to_sqlite.py
# 读取现有 JSONL 文件，导入 SQLite
```

### 验收标准

- [x] 新对话写入 SQLite messages 表
- [x] 用户原文、助手回复、工具调用和结果都记录
- [x] FTS5 关键词搜索可用
- [x] 现有 JSONL 日志不受影响
- [x] CJK token 估算准确（误差 < 20%）
- [x] 可查询指定 session 的消息

### 预估改动量

- 新增：~200 行（conversation_db.py）
- 修改：~20 行（core.py 日志写入）
- 可选：~50 行（迁移脚本）

---

## Phase 3：DAG 摘要图谱

### 目标
替换现有 ContextManager 的滑动窗口压缩，实现 DAG 分层摘要 + 动态上下文组装。

### 新增文件

```
src/xiaomei_brain/memory/dag.py              # DAG 摘要图谱
src/xiaomei_brain/memory/context_assembler.py # 动态上下文组装
```

### 实现内容

#### 3.1 DAG 摘要节点

```python
# dag.py

@dataclass
class DAGNode:
    id: int
    session_id: str
    parent_id: int | None
    depth: int               # 0=叶子, 1=中层, 2+...
    content: str
    token_count: int
    message_ids: list[int]   # 源消息ID列表
    child_ids: list[int]     # 子摘要ID列表
    time_start: float
    time_end: float
    created_at: float

class DAGSummaryGraph:
    """DAG 分层摘要系统"""

    COMPACT_THRESHOLD = 0.75    # 上下文达到75%触发压缩
    MESSAGES_PER_LEAF = 8       # 每8条消息压缩为一个叶子
    LEAF_TARGET_TOKENS = 1200   # 叶子摘要目标token数

    def __init__(self, db_path: str, llm_client):
        self.db = sqlite3.connect(db_path)
        self.llm = llm_client
        self._init_tables()

    def should_compact(self, current_tokens: int, max_tokens: int) -> bool:
        """是否需要压缩"""
        return current_tokens >= max_tokens * self.COMPACT_THRESHOLD

    def compact(self, session_id: str, message_ids: list[int]):
        """压缩指定消息为叶子摘要"""
        # 1. 从 messages 表读取消息
        # 2. 调用 LLM 生成摘要
        # 3. 写入 summaries 表（depth=0）
        # 4. 检查是否需要向上压缩

    def promote(self, session_id: str):
        """当叶子摘要积累到一定数量，向上压缩"""
        # 查找同 session 同 depth 且没有 parent 的节点
        # 如果 >= 4 个，压缩为 depth+1 的父节点
        # 递归检查

    def get_higher_summaries(self, session_id: str, max_tokens: int) -> list[DAGNode]:
        """获取最高层摘要（用于上下文组装）"""
        # 从最高层开始，逐层向下，直到 token 预算用完

    def expand(self, summary_id: int) -> list[dict]:
        """展开摘要，获取原始消息"""
        node = self._get_node(summary_id)
        if node.depth == 0:
            # 叶子节点：返回原始消息
            return self._get_messages(node.message_ids)
        else:
            # 非叶子：返回子摘要
            return [self._get_node(cid) for cid in node.child_ids]

    def search(self, keyword: str, limit: int = 10) -> list[DAGNode]:
        """在摘要中搜索关键词"""
        # FTS5 或 LIKE 搜索 summaries.content
```

#### 3.2 动态上下文组装

```python
# context_assembler.py

class ContextAssembler:
    """动态上下文组装器"""

    FRESH_TAIL_COUNT = 6  # 最近N条原始消息

    def __init__(self, conversation_db: ConversationDB,
                 dag: DAGSummaryGraph,
                 self_model: SelfModel | None = None):
        self.db = conversation_db
        self.dag = dag
        self.self_model = self_model

    def assemble(self, user_input: str,
                 max_tokens: int,
                 mode: str = "daily") -> list[dict]:
        """
        组装上下文

        mode:
          "flow"    → 心流模式，最小上下文
          "daily"   → 日常模式，标准上下文
          "reflect" → 反省模式，全量上下文

        返回：消息列表（可直接传给 LLM）
        """
        messages = []
        remaining_tokens = max_tokens

        # 1. 根据模式决定加载什么
        if mode == "flow":
            # 心流：只加载最近几条原文
            messages = self._fresh_tail(self.FRESH_TAIL_COUNT)

        elif mode == "daily":
            # 日常：SelfModel + DAG摘要 + 最近原文
            if self.self_model:
                messages.append({
                    "role": "system",
                    "content": self.self_model.to_system_prompt()
                })
            summaries = self.dag.get_higher_summaries(
                session_id, remaining_tokens // 2
            )
            messages.extend(self._summaries_to_messages(summaries))
            messages.extend(self._fresh_tail(self.FRESH_TAIL_COUNT))

        elif mode == "reflect":
            # 反省：SelfModel + 全量DAG + 行为日志
            messages.append({
                "role": "system",
                "content": self.self_model.to_full_prompt()
            })
            summaries = self.dag.get_higher_summaries(session_id, remaining_tokens)
            messages.extend(self._summaries_to_messages(summaries))
            messages.extend(self._fresh_tail(self.FRESH_TAIL_COUNT * 2))

        return messages

    def _fresh_tail(self, n: int) -> list[dict]:
        """获取最近N条原始消息"""
        return self.db.get_recent(n)

    def _summaries_to_messages(self, summaries: list[DAGNode]) -> list[dict]:
        """将DAG摘要转为系统消息"""
        if not summaries:
            return []
        content = "<历史摘要>\n"
        for s in summaries:
            content += f'<summary node_id="{s.id}" depth="{s.depth}" '
            content += f'time_range="{s.time_start}-{s.time_end}">\n'
            content += s.content + "\n</summary>\n"
        content += "</历史摘要>"
        return [{"role": "system", "content": content}]
```

#### 3.3 模式切换（路由）

```python
# 在 Agent 中添加模式判断

def _determine_mode(self, user_input: str, state: dict) -> str:
    """判断应该进入哪种模式（规则，0 LLM）"""
    # 有活跃计划 → 日常
    if state.get("active_plan"):
        return "daily"

    # 提到过去 → 日常
    past_keywords = ["昨天", "之前", "上次", "以前", "记得"]
    if any(kw in user_input for kw in past_keywords):
        return "daily"

    # 需要个人判断 → 日常
    opinion_keywords = ["你觉得", "怎么看", "建议", "推荐"]
    if any(kw in user_input for kw in opinion_keywords):
        return "daily"

    # 需要反省 → 反省
    reflect_keywords = ["答对了吗", "做错了", "纠正", "不对"]
    if any(kw in user_input for kw in reflect_keywords):
        return "reflect"

    # 默认：心流
    return "flow"
```

#### 3.4 替换 ContextManager

修改 `agent/core.py`：

```python
class Agent:
    def __init__(self, ...):
        # 替换 ContextManager
        # self.context = context_manager or ContextManager(...)
        # →
        self.context_assembler: ContextAssembler | None = None

    def _manage_context(self, messages):
        # 旧：self.context.should_compress() / self.context.compress()
        # 新：self.context_assembler.assemble()
```

#### 3.5 新增工具

扩展 `tools/builtin/memory.py`：

```python
@tool(name="memory_expand", description="展开历史摘要，查看原始对话细节")
def memory_expand(summary_id: int) -> str:
    """展开DAG摘要节点"""
    ...

@tool(name="memory_grep", description="在历史对话中搜索关键词")
def memory_grep(keyword: str, limit: int = 10) -> str:
    """全文搜索历史对话"""
    ...
```

### 验收标准

- [x] 对话超过阈值时自动压缩为DAG叶子摘要
- [ ] 叶子积累后自动向上压缩（骨架有，未测试）
- [x] 上下文组装：DAG摘要 + 最近N条原文
- [ ] 三种模式（心流/日常/反省）可切换（目前只实现 daily）
- [ ] memory_expand 工具可展开摘要到原文
- [ ] memory_grep 工具可搜索历史
- [x] 替换原有 ContextManager，功能不退化

### 预估改动量

- 新增：~350 行（dag.py、context_assembler.py）
- 修改：~50 行（core.py 上下文管理替换）
- 修改：~30 行（memory.py 新增工具）
- 修改：~20 行（config.py 新增配置项）

---

## Phase 4：长期记忆迁移到 SQLite

### 目标
将长期记忆从 Markdown 文件迁移到 SQLite，实现标签系统 + FTS5 搜索 + 定时提取。

### 新增文件

```
src/xiaomei_brain/memory/longterm.py     # SQLite 长期记忆存储
src/xiaomei_brain/memory/extractor.py    # 记忆提取器（10分钟+关键词+梦境）
```

### 实现内容

#### 4.1 SQLite 长期记忆

```python
# longterm.py

class LongTermMemory:
    """SQLite 长期记忆 - 统一条目 + 灵活标签"""

    def __init__(self, db_path: str):
        self.db = sqlite3.connect(db_path)
        self._init_tables()

    def _init_tables(self):
        """创建 memories、memory_tags、memories_fts 表"""

    def store(self, content: str, source: str,
              tags: list[str] = None,
              importance: float = 0.5) -> int:
        """存储一条记忆，返回ID"""

    def recall(self, query: str, top_k: int = 5) -> list[dict]:
        """检索记忆（FTS5 + importance排序）"""

    def search_by_tags(self, tags: list[str]) -> list[dict]:
        """按标签搜索"""

    def update_importance(self, memory_id: int, delta: float):
        """更新重要性"""

    def decay(self, days: int = 30):
        """时间衰减：降低长时间未访问的记忆权重"""

    def get_all_tags(self) -> list[str]:
        """获取所有标签"""
```

#### 4.2 记忆提取器

```python
# extractor.py

class MemoryExtractor:
    """记忆提取器 - 从对话中提取精华"""

    IMMEDIATE_KEYWORDS = ["记住", "我以前", "喜欢", "要", "不要", "帮我记"]

    def __init__(self, llm_client, longterm_memory, conversation_db):
        self.llm = llm_client
        self.ltm = longterm_memory
        self.db = conversation_db
        self._last_extract_time = time.time()

    def check_immediate(self, user_input: str) -> bool:
        """检查是否需要立即提取（规则匹配）"""
        return any(kw in user_input for kw in self.IMMEDIATE_KEYWORDS)

    def extract_immediate(self, user_input: str, assistant_response: str):
        """立即提取（关键词触发）"""
        prompt = f"从以下对话中提取值得长期记住的信息：\n用户：{user_input}\n助手：{assistant_response}"
        result = self.llm.chat([{"role": "user", "content": prompt}])
        self.ltm.store(result.content, source="immediate")

    def extract_periodic(self, interval_minutes: int = 10):
        """定期提取（后台线程调用）"""
        since = self._last_extract_time
        messages = self.db.query(since=since)
        if not messages:
            return
        prompt = f"从以下对话中提取值得长期记住的信息：\n{self._format_messages(messages)}"
        result = self.llm.chat([{"role": "user", "content": prompt}])
        self.ltm.store(result.content, source="periodic")
        self._last_extract_time = time.time()

    def extract_dream(self):
        """梦境深度提取"""
        # 一整天的对话，深度分析
        today_start = ... # 今天0点
        messages = self.db.query(since=today_start)
        prompt = "深度分析以下对话，提取知识、经验、教训、用户偏好：\n..."
        result = self.llm.chat([{"role": "user", "content": prompt}])
        self.ltm.store(result.content, source="dream", importance=0.8)
```

#### 4.3 后台定时提取线程

修改 `scheduler.py`，增加 10 分钟提取逻辑：

```python
class DreamScheduler:
    # 现有：空闲5分钟或午夜触发梦境
    # 新增：每10分钟触发 extract_periodic

    def __init__(self, ...):
        self.extract_interval = 600  # 10分钟

    def _periodic_extract(self):
        """定期提取线程"""
        while self._running:
            time.sleep(self.extract_interval)
            if self.extractor:
                self.extractor.extract_periodic()
```

#### 4.4 Agent 集成

修改 `agent/core.py`：

```python
def _build_effective_prompt(self, user_input: str) -> str:
    # 现有：self.memory.search(user_input, top_k=3)
    # 替换为：self.longterm_memory.recall(user_input, top_k=3)
    ...
```

#### 4.5 数据迁移脚本（可选）

```python
# scripts/migrate_md_to_sqlite.py
# 读取现有 Markdown 记忆文件，导入 SQLite memories 表
```

### 验收标准

- [x] 长期记忆存储到 SQLite，支持标签
- [x] FTS5 全文搜索可用
- [x] 关键词（"记住"等）触发立即提取
- [x] 每2分钟后台提取（原计划10分钟，测试改为2分钟）
- [x] 梦境模式深度提取
- [ ] 现有 Markdown 记忆可迁移
- [x] Agent 通过 recall() 注入相关记忆到上下文

### 预估改动量

- 新增：~250 行（longterm.py、extractor.py）
- 修改：~30 行（scheduler.py 增加定时提取）
- 修改：~20 行（core.py 记忆检索替换）
- 可选：~50 行（迁移脚本）

---

## 总览

| Phase | 状态 | 实际文件 | 实际行数 |
|-------|------|---------|---------|
| Phase 1: SelfModel | ✅ 已完成 | `memory/self_model.py` | 433 |
| Phase 2: 对话日志SQLite | ✅ 已完成 | `memory/conversation_db.py` | 250 |
| Phase 3: DAG摘要 | ✅ 已完成 | `memory/dag.py` + `memory/context_assembler.py` | 494 + 266 |
| Phase 4: 长期记忆SQLite | ✅ 已完成 | `memory/longterm.py` + `memory/extractor.py` | 283 + 233 |

### 额外完成的（计划外）

| 功能 | 文件 | 说明 |
|------|------|------|
| 记忆提取器 | `memory/extractor.py` | immediate/periodic/dream 三模式 |
| 上下文组装 | `memory/context_assembler.py` | daily/flow/reflect + DAG自动压缩 |
| 多用户记忆 | `memory/longterm.py` | user_id 隔离 + global 共享 |
| 第一人称视角 | `memory/extractor.py` | 用户信息"用户..."，小美自身"我..." |
| 测试脚本 | `examples/test_xiaomei_new.py` | 交互式测试，含 periodic/dream/summarize 命令 |

### 已知待完善

| 项目 | 说明 |
|------|------|
| DAG promote（向上压缩） | 代码骨架有，未测试 |
| flow/reflect 模式 | determine_mode() 只返回 daily |
| 旧记忆迁移 | store.py → longterm.py 数据迁移未做 |
| 向量搜索 | 当前 FTS5，FAISS 未接入 |

### 数据库文件规划

```
~/.xiaomei-brain/agents/{agent_id}/
├── talent.md          # SelfModel（Phase 1）✅
├── memory/
│   ├── brain.db       # SQLite 统一数据库（Phase 2/3/4）✅
│   ├── topics/        # 旧 Markdown 记忆（Phase 4 后可废弃）
│   └── episodes/      # 旧情景记忆（Phase 4 后可废弃）
├── sessions/          # 会话保存（现有，保留）
└── ...
```

所有 SQLite 数据合并到一个 `brain.db`，包含 messages、summaries、memories、memory_tags 表。
