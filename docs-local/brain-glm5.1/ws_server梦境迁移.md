# ws_server.py 梦境迁移到新架构

## 背景

当前 `ws_server.py` 仍在使用旧梦境系统（bak/ 目录下的版本），需要升级到新的 `dream.py` 架构。

### 旧架构问题

```
ws_server.py
├── DreamProcessor(bak/)  ← 旧：从 ConversationLogger(jsonl) 提取 → MemoryStore(jsonl+numpy)
├── DreamScheduler(bak/)    ← 只调度旧 DreamProcessor
└── Agent.dream_scheduler  ← 指向旧调度器
```

**两套并行，混乱：**
- `conversation_db` (SQLite) 在同步写入 — 新系统
- `ConversationLogger` (jsonl) 在写日志文件 — 旧系统
- `MemoryStore` (jsonl+numpy) 存记忆 — 旧系统，已被 `LongTermMemory` 取代
- 两套梦境系统互不知晓

---

## 迁移目标

将 `ws_server.py` 完全迁移到新架构：

```
ws_server.py
├── DreamProcessor(conversation_db, memory_extractor)  ← 新：通用 job 容器
├── DreamScheduler(processor)                         ← 统一调度
└── Agent.dream_scheduler  ← 指向新调度器
```

---

## 具体改动

### 1. 替换导入

```python
# 旧
from xiaomei_brain.memory.dream import DreamProcessor
from xiaomei_brain.memory.scheduler import DreamScheduler
from xiaomei_brain.memory.conversation import ConversationLogger

# 新
from xiaomei_brain.memory.dream import DreamProcessor, DreamScheduler
from xiaomei_brain.memory.dream import make_reinforce_job, make_extract_job
```

### 2. 替换 DreamProcessor 初始化

```python
# 旧
dream_processor = DreamProcessor(
    llm=agent_instance.llm,
    memory=memory,  # MemoryStore 旧系统
    conversation_logger=conversation_logger,
    episodic_memory=episodic,
)

# 新：使用 conversation_db + memory_extractor
from xiaomei_brain.memory.extractor import MemoryExtractor

memory_extractor = MemoryExtractor(
    llm_client=agent_instance.llm,
    longterm_memory=agent_instance.longterm_memory,
    conversation_db=conversation_db,
)

processor = DreamProcessor(conversation_db, memory_extractor)
processor.add_job(*make_reinforce_job(agent_instance.longterm_memory))
processor.add_job(*make_extract_job(memory_extractor, user_id))

dream_scheduler = DreamScheduler(processor, idle_threshold=cfg.dream_idle_threshold)
```

### 3. 移除旧依赖

- 删除 `conversation_logger = ConversationLogger(...)`
- 删除 `memory = agent_instance.memory`（MemoryStore）
- 删除 `episodic = agent_instance.episodic_memory`（如果未实现可保留）

### 4. Agent 构造参数

确认 `Agent.__init__` 支持新的 `dream_scheduler`，移除旧的 `memory=` 和 `conversation_logger=` 参数。

---

## 文件

- `src/xiaomei_brain/ws/server.py` — 主改文件
- `src/xiaomei_brain/agent/core.py` — 检查 `dream_scheduler` 参数是否兼容

---

## 验证

1. ws_server.py 启动无报错
2. idle 5分钟后梦境触发，两个 job 都执行
3. 日志中看到 `[Dream] Job 'reinforce'` 和 `[Dream] Job 'extract'`
4. 对话记录正确存入 `conversation_db`
5. 记忆正确存入 `LongTermMemory`（而非旧的 MemoryStore）

---

## 状态

- [ ] 迁移 ws_server.py 到新架构
- [ ] 移除旧 ConversationLogger / MemoryStore 依赖
- [ ] 验证梦境 job 正确触发
- [ ] 验证数据写入正确路径（SQLite+LanceDB）
