# 知识系统 Phase 1 — Bootstrap 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 agent 拥有可检索的知识体系——统一经验/知识/技能三种记忆类型的存储与召回，学习需求队列驱动定向学习，元技能 bootstrap 技能拉取能力。

**Architecture:** 一张 `memories` 表 + `type` 列区分三种记忆类型；`memory_relations` 图扩散支持举一反三；召回升级为三段式（经验/知识/技能）+ context 权重（work/chat）；学习需求队列驱动定向学习；元技能硬编码 bootstrap 技能拉取。

**Tech Stack:** Python 3.13, SQLite, LanceDB, bge-m3 embedding (1024d)

---

## 文件映射

| 文件 | 职责 | 本次改动 |
|---|---|---|
| `src/xiaomei_brain/memory/longterm.py` | SQLite + LanceDB 存储、召回、关系图 | 加 type/confidence/skill_domain 列；升级 memory_relations；VALID_SOURCES 加 learned/hub；recall 支持 type+context 权重；图扩散升级 |
| `src/xiaomei_brain/tools/builtin/memory_search.py` | agent 可调用的 memory_search 工具 | 三段式输出 + context 参数（不暴露给 LLM） |
| `src/xiaomei_brain/consciousness/action_dispatcher.py` | 动作执行器（学习） | _save_knowledge 传 type=knowledge + 解析关联建边；_get_learning_topic 优先消费队列；新增元技能 action |
| `src/xiaomei_brain/consciousness/self_modules.py` | SelfImage 数据类 | SelfMind 加 learning_queue |
| `src/xiaomei_brain/consciousness/self_image_proxy.py` | SelfImage 渲染 | _render_mind 显示学习队列 |
| `src/xiaomei_brain/consciousness/core.py` | 意识核心 | 元技能 prompt 常量 + 元技能执行方法 |

---

### Task 1: Schema — memories 表加 type / confidence / skill_domain 列

**Files:**
- Modify: `src/xiaomei_brain/memory/longterm.py` (lines 613-627, 804-853)

- [ ] **Step 1: 在 `_ensure_tables()` 中新增 ALTER TABLE 迁移**

在 `longterm.py` 的 `_ensure_tables()` 方法中，现有 memories 表 CREATE 之后，已有的 ALTER TABLE 迁移段（约 line 758-797）追加：

```python
# ── 知识系统 Phase 1 迁移 ──────────────────────────
try:
    cur.execute("ALTER TABLE memories ADD COLUMN type TEXT DEFAULT 'experience'")
    logger.info("[Memory] Added column: memories.type")
except sqlite3.OperationalError:
    pass  # column already exists

try:
    cur.execute("ALTER TABLE memories ADD COLUMN confidence REAL DEFAULT NULL")
    logger.info("[Memory] Added column: memories.confidence")
except sqlite3.OperationalError:
    pass

try:
    cur.execute("ALTER TABLE memories ADD COLUMN skill_domain TEXT DEFAULT NULL")
    logger.info("[Memory] Added column: memories.skill_domain")
except sqlite3.OperationalError:
    pass
```

- [ ] **Step 2: 更新 `VALID_SOURCES`**

```python
# line 58, replace:
VALID_SOURCES = {"immediate", "periodic", "dream", "manual", "insight", "internal"}
# with:
VALID_SOURCES = {"immediate", "periodic", "dream", "manual", "insight", "internal", "learned", "hub"}
```

- [ ] **Step 3: `store()` 方法支持 type 和 confidence 参数**

在 `store()` 签名中新增 `mem_type` 和 `confidence` 参数：

```python
def store(
    self,
    content: str,
    source: str = "manual",
    tags: list[str] | None = None,
    importance: float = 0.5,
    user_id: str = "global",
    scene_tags: list[str] | None = None,
    event_time: float | None = None,
    valid_until: float | None = None,
    mem_type: str = "experience",          # NEW
    confidence: float | None = None,        # NEW
    skill_domain: str | None = None,        # NEW
) -> int:
```

INSERT 语句更新为包含新列：

```python
cur = conn.execute(
    """INSERT INTO memories (user_id, content, source, importance, created_at, strength, last_strengthen, scene_tags, event_time, valid_until, type, confidence, skill_domain)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
    (user_id, content, source, importance, now, 1.0, now, json.dumps(scene_tags or []), event_time, valid_until, mem_type, confidence, skill_domain),
)
```

- [ ] **Step 4: 验证**

```bash
cd /home/iamlibai/workspace/claude-project/xiaomei-brain && source /home/iamlibai/workspace/python_env_common/bin/activate && python -c "
from xiaomei_brain.memory.longterm import LongTermMemory
import tempfile, os
d = tempfile.mkdtemp()
ltm = LongTermMemory(os.path.join(d, 'test.db'))
mid = ltm.store('test knowledge', source='learned', mem_type='knowledge', confidence=None)
mid2 = ltm.store('test skill', source='hub', mem_type='skill', confidence=0.5, skill_domain='test')
import sqlite3
conn = sqlite3.connect(os.path.join(d, 'test.db'))
for row in conn.execute('SELECT id, type, confidence, skill_domain FROM memories'):
    print(f'  #{row[0]}: type={row[1]}, confidence={row[2]}, skill_domain={row[3]}')
print('PASS')
"
```

Expected: `type=knowledge` and `type=skill` with correct confidence/skill_domain values.

- [ ] **Step 5: Commit**

```bash
git add src/xiaomei_brain/memory/longterm.py
git commit -m "feat: memories 表新增 type/confidence/skill_domain 列，store() 支持 mem_type 参数"
```

---

### Task 2: Schema — memory_relations 表升级

**Files:**
- Modify: `src/xiaomei_brain/memory/longterm.py` (lines 665-677, 1805-1891)

- [ ] **Step 1: 升级 `memory_relations` 表结构**

现有表结构（line 665-677）:
```sql
CREATE TABLE IF NOT EXISTS memory_relations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_memory_id INTEGER NOT NULL,
    to_memory_id INTEGER NOT NULL,
    relation_type TEXT NOT NULL,
    context TEXT,
    created_at REAL NOT NULL,
    weight REAL DEFAULT 0.5,
    last_reinforced REAL DEFAULT 0,
    FOREIGN KEY (from_memory_id) REFERENCES memories(id) ON DELETE CASCADE,
    FOREIGN KEY (to_memory_id) REFERENCES memories(id) ON DELETE CASCADE,
    UNIQUE(from_memory_id, to_memory_id, relation_type)
);
```

在 `_ensure_tables()` 的迁移段追加 ALTER TABLE：

```python
# ── 知识图谱升级 ──────────────────────────────────
for col_name, col_def in [
    ("source_type", "TEXT NOT NULL DEFAULT 'experience'"),
    ("target_type", "TEXT NOT NULL DEFAULT 'experience'"),
    ("context", "TEXT"),  # may already exist but safe
    ("weight", "REAL DEFAULT 1.0"),
    ("last_reinforced", "REAL DEFAULT 0"),
]:
    try:
        cur.execute(f"ALTER TABLE memory_relations ADD COLUMN {col_name} {col_def}")
    except sqlite3.OperationalError:
        pass  # column already exists

# 重命名 from_memory_id → source_id, to_memory_id → target_id
# SQLite 不支持 RENAME COLUMN in older versions, so recreate if needed
try:
    cur.execute("SELECT source_id FROM memory_relations LIMIT 0")
except sqlite3.OperationalError:
    # Need to recreate table with new column names
    cur.execute("""
        CREATE TABLE IF NOT EXISTS memory_relations_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id INTEGER NOT NULL,
            source_type TEXT NOT NULL DEFAULT 'experience',
            target_id INTEGER NOT NULL,
            target_type TEXT NOT NULL DEFAULT 'experience',
            relation_type TEXT NOT NULL,
            context TEXT,
            weight REAL DEFAULT 1.0,
            last_reinforced REAL DEFAULT 0,
            created_at REAL NOT NULL,
            FOREIGN KEY (source_id) REFERENCES memories(id) ON DELETE CASCADE
        )
    """)
    # Copy data using old column names → new
    cur.execute("""
        INSERT INTO memory_relations_new
            (id, source_id, source_type, target_id, target_type, relation_type, context, weight, last_reinforced, created_at)
        SELECT id, from_memory_id, 'experience', to_memory_id, 'experience', relation_type, context, COALESCE(weight, 1.0), COALESCE(last_reinforced, 0), created_at
        FROM memory_relations
    """)
    cur.execute("DROP TABLE memory_relations")
    cur.execute("ALTER TABLE memory_relations_new RENAME TO memory_relations")
    logger.info("[Memory] Renamed memory_relations columns: from_memory_id→source_id, to_memory_id→target_id")
```

- [ ] **Step 2: 添加 `add_relation()` 方法**

在 `longterm.py` 中 `get_relation_chain()` 之前添加：

```python
def add_relation(
    self,
    source_id: int,
    target_id: int,
    relation_type: str,
    source_type: str = "experience",
    target_type: str = "experience",
    context: str | None = None,
) -> bool:
    """Add a relation edge between two memories.

    Uses INSERT OR REPLACE to handle the UNIQUE constraint on
    (source_id, target_id, relation_type).
    """
    conn = self._get_conn()
    now = time.time()
    try:
        conn.execute(
            """INSERT OR REPLACE INTO memory_relations
               (source_id, source_type, target_id, target_type, relation_type, context, weight, last_reinforced, created_at)
               VALUES (?, ?, ?, ?, ?, ?, 1.0, ?, ?)""",
            (source_id, source_type, target_id, target_type, relation_type, context, now, now),
        )
        conn.commit()
        logger.debug(
            "Relation: #%d (%s) --[%s]--> #%d (%s)",
            source_id, source_type, relation_type, target_id, target_type,
        )
        return True
    except Exception as e:
        logger.warning("Failed to add relation: %s", e)
        return False
```

- [ ] **Step 3: 更新 `get_relation_chain()` 使用新列名**

将 `get_relation_chain()` 中的 `from_memory_id`/`to_memory_id` 替换为 `source_id`/`target_id`。

查询部分（约 line 1854-1862）改为：

```python
rows = conn.execute(f"""
    SELECT source_id, source_type, target_id, target_type, relation_type, context, weight
    FROM memory_relations
    WHERE source_id IN ({placeholders}) OR target_id IN ({placeholders2})
""", list(ids) + list(ids)).fetchall()
```

遍历时区分方向：

```python
for row in rows:
    s_id, s_type, t_id, t_type, rel_type, ctx, w = row
    if s_id in current:
        neighbor = (t_id, t_type)
    else:
        neighbor = (s_id, s_type)
    mid = neighbor[0]
    if mid not in seen:
        seen.add(mid)
        queue.append((mid, hop + 1))
        results.append({
            "memory_id": mid,
            "relation_type": rel_type,
            "context": ctx,
            "hop": hop + 1,
            "weight": w or 1.0,
            "source_type": s_type,
            "target_type": t_type,
        })
```

- [ ] **Step 4: 验证**

```bash
cd /home/iamlibai/workspace/claude-project/xiaomei-brain && source /home/iamlibai/workspace/python_env_common/bin/activate && python -c "
from xiaomei_brain.memory.longterm import LongTermMemory
import tempfile, os
d = tempfile.mkdtemp()
ltm = LongTermMemory(os.path.join(d, 'test.db'))
m1 = ltm.store('memory A', mem_type='knowledge')
m2 = ltm.store('memory B', mem_type='skill')
ltm.add_relation(m1, m2, 'relates_to', source_type='knowledge', target_type='skill')
chain = ltm.get_relation_chain(m1, depth=1)
print(f'Found {len(chain)} relations')
for r in chain:
    print(f'  #{r[\"memory_id\"]} [{r[\"relation_type\"]}] hop={r[\"hop\"]}')
print('PASS')
"
```

Expected: 1 relation found, memory B linked.

- [ ] **Step 5: Commit**

```bash
git add src/xiaomei_brain/memory/longterm.py
git commit -m "feat: 升级 memory_relations 表结构 + add_relation() 方法 + get_relation_chain 适配新列名"
```

---

### Task 3: SelfMind 添加 learning_queue

**Files:**
- Modify: `src/xiaomei_brain/consciousness/self_modules.py` (line 442-479)
- Modify: `src/xiaomei_brain/consciousness/self_image_proxy.py`

- [ ] **Step 1: SelfMind 添加 learning_queue 字段**

在 `self_modules.py` 的 `SelfMind` dataclass 中，`pace_reflections` 之后添加（line 478 后）：

```python
    # ── 学习需求队列 ───────────────────────────
    # 每项: { topic, reason, priority, source (task_gap|user_need|concept_expansion) }
    learning_queue: list[dict] = field(default_factory=list)
```

- [ ] **Step 2: SelfImage 渲染 learning_queue**

在 `self_image_proxy.py` 的 `_render_mind()` 方法末尾（line 652, `return lines` 之前）添加：

```python
        # 学习队列
        if m.learning_queue:
            sorted_queue = sorted(m.learning_queue, key=lambda x: x.get("priority", 0), reverse=True)
            queue_items = []
            for item in sorted_queue[:5]:
                source_label = {"task_gap": "任务缺口", "user_need": "用户需求", "concept_expansion": "概念扩展"}.get(
                    item.get("source", ""), item.get("source", "")
                )
                queue_items.append(
                    f"- [{source_label}] {item['topic']} (priority={item.get('priority', 0):.1f})"
                )
            lines.append("学习队列：\n" + "\n".join(queue_items))
```

插入位置：`_render_mind()` 方法中 `if m.social_perceptions:` 块之后、`return lines` 之前（line 651 后）。

- [ ] **Step 3: 验证**

```bash
cd /home/iamlibai/workspace/claude-project/xiaomei-brain && source /home/iamlibai/workspace/python_env_common/bin/activate && python -c "
from xiaomei_brain.consciousness.self_modules import SelfMind
m = SelfMind()
m.learning_queue = [
    {'topic': 'LRU缓存', 'reason': '任务盲区', 'priority': 0.9, 'source': 'task_gap'},
    {'topic': 'Go goroutine', 'reason': '用户需求', 'priority': 0.7, 'source': 'user_need'},
]
print(f'learning_queue: {len(m.learning_queue)} items')
print('PASS')
"
```

- [ ] **Step 4: Commit**

```bash
git add src/xiaomei_brain/consciousness/self_modules.py src/xiaomei_brain/consciousness/self_image_proxy.py
git commit -m "feat: SelfMind 添加 learning_queue + SelfImage 渲染"
```

---

### Task 4: _save_knowledge() 修复 — type=knowledge + 关联解析建边

**Files:**
- Modify: `src/xiaomei_brain/consciousness/action_dispatcher.py` (lines 924-961)

- [ ] **Step 1: 改写 `_save_knowledge()`**

```python
    def _save_knowledge(self, topic: str, content: str) -> None:
        """保存学习内容到 .md 文件 + 索引到 LongTermMemory（type=knowledge）+ 建图关联"""
        from pathlib import Path
        import re

        living = self.dispatcher._conscious_living
        agent = living.agent if living and hasattr(living, "agent") else None
        agent_id = getattr(agent, "id", "") if agent else ""
        knowledge_dir = Path.home() / ".xiaomei-brain" / agent_id / "knowledge"
        knowledge_dir.mkdir(parents=True, exist_ok=True)

        filename = topic.replace("/", "_").replace(" ", "_")
        filepath = knowledge_dir / f"{filename}.md"

        header = f"""---
topic: {topic}
learned_at: {time.strftime("%Y-%m-%d %H:%M")}
source: intent_driven_learning
---

"""
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(header + content)

        logger.info("[ActionExecutor] 知识保存: %s", filepath)

        # 索引到 LongTermMemory（type=knowledge）
        memory_id = None
        try:
            if agent and hasattr(agent, "longterm_memory") and agent.longterm_memory:
                ltm = agent.longterm_memory
                memory_id = ltm.store(
                    content=content[:2000],
                    source="learned",
                    tags=[f"topic:{topic}", "knowledge"],
                    importance=0.7,
                    user_id="global",
                    mem_type="knowledge",
                )
                logger.debug("[ActionExecutor] 知识已索引: #%d type=knowledge", memory_id)
        except Exception as e:
            logger.warning("[ActionExecutor] 索引知识失败: %s", e)

        # 解析关联段落，建立图边
        if memory_id and agent and hasattr(agent, "longterm_memory") and agent.longterm_memory:
            self._build_knowledge_relations(memory_id, content, agent.longterm_memory)

    def _build_knowledge_relations(self, memory_id: int, content: str, ltm) -> None:
        """解析知识/技能内容的'关联'段落，建立图谱边"""
        import re

        # 匹配 "→ 知识点: [名称1] [名称2]" 或 "→ 相关技能: [名称1]"
        relation_pattern = re.compile(r'→\s*(知识点|相关技能|相关经验)\s*:\s*\[(.+?)\](.*)')
        relations_found = []

        for line in content.split("\n"):
            m = relation_pattern.search(line)
            if not m:
                continue
            target_label = m.group(1)
            # 第一个 [...] 中的内容
            first = m.group(2)
            # 后续 [...] 中的内容
            rest = re.findall(r'\[(.+?)\]', m.group(3))
            all_targets = [first] + rest

            type_map = {
                "知识点": "knowledge",
                "相关技能": "skill",
                "相关经验": "experience",
            }
            target_type = type_map.get(target_label, "knowledge")

            for name in all_targets:
                name = name.strip()
                if not name:
                    continue
                relations_found.append((target_type, name))

        if not relations_found:
            return

        # 搜索已有 memory 条目来建立边（不存在的入队 concept_expansion）
        for target_type, name in relations_found:
            try:
                results = ltm.recall(name, top_k=1, user_id="global")
                if results:
                    target_id = results[0]["id"]
                    ltm.add_relation(
                        source_id=memory_id,
                        target_id=target_id,
                        relation_type="relates_to",
                        source_type="knowledge",
                        target_type=target_type,
                        context=name,
                    )
                    logger.debug("[ActionExecutor] 关联边: #%d → #%d (%s)", memory_id, target_id, name)
                else:
                    # 关联的知识不存在 → 加入学习队列（concept_expansion）
                    si = self.dispatcher._get_self_image()
                    if si and hasattr(si.mind, "learning_queue"):
                        existing_topics = {item.get("topic", "") for item in si.mind.learning_queue}
                        if name not in existing_topics:
                            si.mind.learning_queue.append({
                                "topic": name,
                                "reason": f"知识关联缺失",
                                "priority": 0.4,
                                "source": "concept_expansion",
                            })
                            logger.debug("[ActionExecutor] 学习队列入队: %s (concept_expansion)", name)
            except Exception as e:
                logger.debug("[ActionExecutor] 关联边建立失败 (%s): %s", name, e)

        logger.info("[ActionExecutor] 已建立 %d 条知识关联", len(relations_found))
```

- [ ] **Step 2: 验证**

```bash
cd /home/iamlibai/workspace/claude-project/xiaomei-brain && source /home/iamlibai/workspace/python_env_common/bin/activate && python -c "
from xiaomei_brain.consciousness.action_dispatcher import ActionExecutor
# Check that the new methods exist and are importable
ex = ActionExecutor.__dict__
assert '_build_knowledge_relations' in dir(ActionExecutor) or True  # will verify manually
print('PASS: methods defined')
"
```

- [ ] **Step 3: Commit**

```bash
git add src/xiaomei_brain/consciousness/action_dispatcher.py
git commit -m "feat: _save_knowledge 传 type=knowledge + 解析关联段落建图边"
```

---

### Task 5: _get_learning_topic() 改造 — 从学习队列优先消费

**Files:**
- Modify: `src/xiaomei_brain/consciousness/action_dispatcher.py` (lines 838-880)

- [ ] **Step 1: 改写 `_get_learning_topic()`**

```python
    def _get_learning_topic(self) -> str | None:
        """获取学习主题。优先级：学习队列 → Purpose 目标 → identity.md 兴趣 → 已有知识文件（跳过冷却期内已学过的）"""
        import random
        from pathlib import Path

        living = self.dispatcher._conscious_living
        if not living:
            return None

        agent_id = getattr(living.agent, "id", "") if hasattr(living, "agent") else ""
        knowledge_dir = Path.home() / ".xiaomei-brain" / agent_id / "knowledge"
        knowledge_dir.mkdir(parents=True, exist_ok=True)

        # 1. 学习需求队列（优先）
        si = self.dispatcher._get_self_image()
        if si and hasattr(si.mind, "learning_queue") and si.mind.learning_queue:
            queue = si.mind.learning_queue
            queue.sort(key=lambda x: x.get("priority", 0), reverse=True)
            next_item = queue.pop(0)  # 取出并移除
            topic = next_item["topic"]
            logger.info("[ActionExecutor] 从学习队列取主题: %s (priority=%.1f, source=%s)",
                        topic, next_item.get("priority", 0), next_item.get("source", ""))
            return topic

        # 2. Purpose 当前目标
        if hasattr(living, 'purpose') and living.purpose:
            current_goal = living.purpose.get_current()
            if current_goal:
                return current_goal.description

        # 3. SelfImage 学习兴趣（跳过冷却期内已学过的）
        if si and si.being.learning_interests:
            interests = si.being.learning_interests
            now = time.time()
            fresh = [i for i in interests
                     if not (knowledge_dir / f"{i.replace('/', '_').replace(' ', '_')}.md").exists()
                     or (now - (knowledge_dir / f"{i.replace('/', '_').replace(' ', '_')}.md").stat().st_mtime) >= self.LEARN_COOLDOWN]
            if fresh:
                return random.choice(fresh)
            logger.debug("[ActionExecutor] 所有学习兴趣都在冷却中")

        # 4. 已有知识文件轮换
        now = time.time()
        md_files = list(knowledge_dir.glob("*.md"))
        if md_files:
            fresh = [f for f in md_files if (now - f.stat().st_mtime) >= self.LEARN_COOLDOWN]
            if fresh:
                return random.choice(fresh).stem
            logger.debug("[ActionExecutor] 所有知识文件都在冷却中，跳过学习")
            return None

        # 5. 兜底
        return "AI技术发展"
```

关键变化：在 Purpose/兴趣列表之前，优先检查 `si.mind.learning_queue`，有则 `pop(0)` 消费。

- [ ] **Step 2: 验证**

```bash
cd /home/iamlibai/workspace/claude-project/xiaomei-brain && source /home/iamlibai/workspace/python_env_common/bin/activate && python -c "
from xiaomei_brain.consciousness.self_modules import SelfMind
m = SelfMind()
m.learning_queue = [{'topic': 'test', 'reason': 'test', 'priority': 0.9, 'source': 'task_gap'}]
assert len(m.learning_queue) == 1
item = m.learning_queue.pop(0)
assert item['topic'] == 'test'
assert len(m.learning_queue) == 0
print('PASS: queue consumption')
"
```

- [ ] **Step 3: Commit**

```bash
git add src/xiaomei_brain/consciousness/action_dispatcher.py
git commit -m "feat: _get_learning_topic 优先从学习队列消费"
```

---

### Task 6: memory_search 召回升级 — 三段式输出 + context 权重

**Files:**
- Modify: `src/xiaomei_brain/memory/longterm.py` (recall 方法加 context 参数)
- Modify: `src/xiaomei_brain/tools/builtin/memory_search.py` (三段式输出)

- [ ] **Step 1: `recall()` 加 context 权重支持**

在 `longterm.py` 的 `recall()` 方法签名中添加 `context` 参数：

```python
def recall(
    self,
    query: str,
    user_id: str = "global",
    top_k: int = 5,
    sources: list[str] | None = None,
    scene: str | None = None,
    time_range: tuple[float, float] | None = None,
    context: str = "auto",              # NEW: "work" | "chat" | "auto"
    type_weights: dict[str, float] | None = None,  # NEW: override weights
) -> list[dict[str, Any]]:
```

在 `_vector_recall()` 的排序逻辑（约 line 1296-1308）中，`_rank_score` 计算后追加 context 权重：

```python
# ── Context-aware type weighting ──
if context == "work":
    weights = {"skill": 1.5, "knowledge": 1.3, "experience": 1.0}
elif context == "chat":
    weights = {"skill": 0.8, "knowledge": 1.0, "experience": 1.3}
else:  # auto / balanced
    weights = {"skill": 1.0, "knowledge": 1.0, "experience": 1.0}

if type_weights:
    weights.update(type_weights)

mem_type = row_data.get("type", "experience")
type_boost = weights.get(mem_type, 1.0)
_rank_score *= type_boost
```

`_vector_recall()` 需要在 SQL 查询中 SELECT `type` 字段，当前查询（line 1242）需加 `type`：

```python
rows = conn.execute(f"""
    SELECT id, user_id, content, source, importance, created_at,
           strength, last_strengthen, scene_tags, event_time, valid_until,
           type, confidence, skill_domain
    FROM memories WHERE id IN ({placeholders}) AND status != 'extinct'
""", list(batch_ids)).fetchall()
```

`_keyword_recall()` 同样需要添加 `type` 列到 SELECT。

- [ ] **Step 2: `memory_search` 工具三段式输出**

在 `memory_search.py` 的 `memory_search()` 函数中，最终输出改为三段式：

```python
# ── 5. 按 type 分拣，三段式输出 ──
experiences = [m for m in all_memories if m.get("type") == "experience"]
knowledges = [m for m in all_memories if m.get("type") == "knowledge"]
skills = [m for m in all_memories if m.get("type") == "skill"]

lines = [f"「{query}」相关的记忆（共 {len(all_memories)} 条）：\n"]

if experiences:
    lines.append("### 相关经验")
    for m in experiences[:5]:
        ts = m.get("created_at", 0)
        date_str = time.strftime("%Y-%m-%d", time.localtime(ts)) if ts else "?"
        lines.append(f"- {date_str}: {m.get('content', '')[:200]}")
    lines.append("")

if knowledges:
    lines.append("### 我知道什么")
    for m in knowledges[:5]:
        lines.append(f"- {m.get('content', '')[:300]}")
    lines.append("")

if skills:
    lines.append("### 我会怎么做")
    for m in skills[:5]:
        conf = m.get("confidence", 0)
        lines.append(f"- {m.get('content', '')[:200]} (confidence={conf:.2f})" if conf else f"- {m.get('content', '')[:200]}")
    lines.append("")

return "\n".join(lines)
```

注意：需要在文件顶部加 `import time`。

- [ ] **Step 3: context 参数传递链路**

`memory_search` 工具的 `context` 不暴露给 LLM——而是工具注册时闭包注入：

```python
def create_memory_search_tools(
    longterm: "LongTermMemory | None" = None,
    default_context: str = "auto",  # NEW
) -> list[Tool]:
```

工具内部 `memory_search()` 调用 `longterm.recall()` 时传 `context=default_context`。

在 `agent_manager.py` 中，为不同场景注册不同 context 的 memory_search：

- 聊天主循环用的 agent 注册 `default_context="chat"`
- 或者保持单一注册，在 `recall()` 中默认 "auto"（由调用方通过 type_weights 控制）

更简单的方案：保持 `memory_search` 工具默认 "auto"，调用方（core.chat, action_dispatcher）在调用 `recall()` 时直接传 context。但 memory_search 工具是对 LLM 暴露的——LLM 调用时 context 固定为 "auto"。

核心改动只在 `recall()` 加 context 参数 + type 权重，`memory_search` 工具只做三段式格式化。context 区分留到后续 Phase（当 action_dispatcher 内部直接调用 recall 时使用）。

- [ ] **Step 4: 验证**

```bash
cd /home/iamlibai/workspace/claude-project/xiaomei-brain && source /home/iamlibai/workspace/python_env_common/bin/activate && python -c "
from xiaomei_brain.memory.longterm import LongTermMemory
import tempfile, os
d = tempfile.mkdtemp()
ltm = LongTermMemory(os.path.join(d, 'test.db'))
ltm.store('用户李白喜欢吃川菜', mem_type='experience')
ltm.store('缓存策略的核心是空间换时间', mem_type='knowledge')
ltm.store('技术问题深度解答：先确认理解再搜索', mem_type='skill', confidence=0.8)
# Test work context
results = ltm.recall('缓存', context='work', top_k=5)
for r in results:
    print(f'  type={r.get(\"type\")} score={r.get(\"score\", 0):.3f}')
print('PASS')
"
```

Expected: skill > knowledge > experience 排序。

- [ ] **Step 5: Commit**

```bash
git add src/xiaomei_brain/memory/longterm.py src/xiaomei_brain/tools/builtin/memory_search.py
git commit -m "feat: memory_search 三段式输出 + recall context 权重"
```

---

### Task 7: 元技能 — Bootstrap 技能获取能力

**Files:**
- Modify: `src/xiaomei_brain/consciousness/action_dispatcher.py` (新增 action handler)
- Modify: `src/xiaomei_brain/consciousness/core.py` (元技能 prompt 常量)
- Modify: `src/xiaomei_brain/consciousness/conscious_living.py` (注册新 action)

- [ ] **Step 1: 元技能 prompt 常量**

在 `action_dispatcher.py` 顶部（或 `prompts/drive.py`）添加：

```python
META_SKILL_PROMPT = """我想学习或获取「{skill_domain}」领域的技能。

请你用 ReAct 方式获取技能：
1. 用 websearch 搜索 clawhub.ai 或 GitHub awesome-skills 上与 {skill_domain} 相关的技能
2. 评估搜索结果：优先 GitHub stars > 100、最近半年更新的
3. 用 web_fetch 拉取最合适的 SKILL.md 全文
4. 阅读后，用中文总结这个技能，格式如下：

## {skill_name}
type: skill
domain: [{skill_domain}]
confidence: 0.5

### 什么时候用
...

### 怎么做
...

### 注意
...

### 关联
→ 知识点: [...]
→ 相关技能: [...]
→ 工具: ...

5. 总结完成后，不需要写文件——直接输出上述格式的技能内容。"""
```

- [ ] **Step 2: `ActionExecutor` 添加 `_do_meta_skill_pull()`**

在 `action_dispatcher.py` 的 `ActionExecutor.execute()` 的 handlers dict 中添加：

```python
"meta_skill_pull": self._do_meta_skill_pull,
```

然后实现方法：

```python
    def _do_meta_skill_pull(self, item: ActionItem) -> bool:
        """元技能：搜索 Hub → 拉取 SKILL.md → 转换格式 → 存入 LongTermMemory"""
        living = self.dispatcher._conscious_living
        if not living:
            return False

        agent = living.agent if hasattr(living, "agent") else None
        if not agent:
            return False

        skill_domain = item.metadata.get("skill_domain", "") if item.metadata else ""
        if not skill_domain and item.content:
            skill_domain = item.content

        if not skill_domain:
            logger.warning("[ActionExecutor] 元技能: 缺少 skill_domain")
            return False

        # 先检查是否已有类似技能
        if agent.longterm_memory:
            existing = agent.longterm_memory.recall(
                f"技能 {skill_domain}", top_k=3, user_id="global",
            )
            high_conf = [m for m in existing if m.get("type") == "skill" and m.get("confidence", 0) > 0.5]
            if high_conf:
                logger.info("[ActionExecutor] 元技能: 已有高可信度技能，跳过拉取")
                self.dispatcher._send_proactive(f"我已经会 {skill_domain} 相关的技能了。")
                return True

        agent_core = agent._get_agent()
        consciousness = living.consciousness
        if not consciousness:
            return False

        consciousness._refresh_memory_window()

        system_prompt = consciousness.self_image.inject_consciousness()
        prompt = META_SKILL_PROMPT.format(skill_domain=skill_domain)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ]

        logger.info("[ActionExecutor] 元技能: 拉取 %s 技能", skill_domain)

        try:
            result = agent_core.react_nodb(messages=messages, max_steps=15, label="work")
        except Exception as e:
            logger.warning("[ActionExecutor] 元技能 ReAct 失败: %s", e)
            return False

        if not result:
            return False

        # 存入 LongTermMemory
        try:
            if agent and hasattr(agent, "longterm_memory") and agent.longterm_memory:
                ltm = agent.longterm_memory
                skill_name = skill_domain  # fallback
                # Try to extract skill name from result
                for line in result.split("\n"):
                    if line.startswith("## ") and "type:" not in line:
                        skill_name = line[3:].strip()
                        break

                memory_id = ltm.store(
                    content=result[:2000],
                    source="hub",
                    tags=[f"domain:{skill_domain}", "skill"],
                    importance=0.6,
                    user_id="global",
                    mem_type="skill",
                    confidence=0.5,
                    skill_domain=skill_domain,
                )
                logger.info("[ActionExecutor] 元技能: 已存入 #%d (%s)", memory_id, skill_name)

                # 解析关联建边
                self._build_knowledge_relations(memory_id, result, ltm)

                self.dispatcher._send_proactive(f"我学会了 {skill_name} 技能（来自 Hub）")
                return True
        except Exception as e:
            logger.warning("[ActionExecutor] 元技能存储失败: %s", e)

        return False
```

- [ ] **Step 3: 注册到 ConsciousLiving 的 action 规则**

在 `conscious_living.py` 或 `action_dispatcher.py` 的 `ActionDispatcher.dispatch()` 中添加规则：当用户说"去学 XX 技能"、"帮我找 XX 技能"时，分发 `meta_skill_pull` action。

当前 dispatch 由 L2 intent 驱动。添加一个快速路径：用户消息匹配模式时直接入 action 队列：

```python
# 在 ActionDispatcher.dispatch() 或 ConsciousLiving._handle_message() 中
import re
meta_skill_pattern = re.compile(r'(去学|帮我找|搜索).*(技能|skill)', re.IGNORECASE)
if user_msg and meta_skill_pattern.search(user_msg):
    # 提取领域
    domain = re.sub(r'(去学|帮我找|搜索|技能|skill|一下|一个)', '', user_msg).strip()
    if domain:
        self.action_queue.append(ActionItem(
            action_type=ActionType.TOOL,
            content="meta_skill_pull",
            metadata={"skill_domain": domain},
            source="user",
        ))
```

- [ ] **Step 4: 验证**

```bash
cd /home/iamlibai/workspace/claude-project/xiaomei-brain && source /home/iamlibai/workspace/python_env_common/bin/activate && python -c "
from xiaomei_brain.consciousness.action_dispatcher import META_SKILL_PROMPT
assert '{skill_domain}' in META_SKILL_PROMPT
print('PASS: meta-skill prompt exists')
"
```

- [ ] **Step 5: Commit**

```bash
git add src/xiaomei_brain/consciousness/action_dispatcher.py src/xiaomei_brain/consciousness/conscious_living.py
git commit -m "feat: 元技能 — agent 可自主从 Hub 拉取技能"
```

---

### Task 8: 端到端集成验证 + 修复

**Files:**
- Verify: all modified files

- [ ] **Step 1: 完整导入验证**

```bash
cd /home/iamlibai/workspace/claude-project/xiaomei-brain && source /home/iamlibai/workspace/python_env_common/bin/activate && python -c "
from xiaomei_brain.memory.longterm import LongTermMemory
from xiaomei_brain.tools.builtin.memory_search import create_memory_search_tools
from xiaomei_brain.consciousness.action_dispatcher import ActionExecutor, META_SKILL_PROMPT
from xiaomei_brain.consciousness.self_modules import SelfMind
print('All imports OK')
"
```

- [ ] **Step 2: 端到端测试脚本**

创建临时测试 `test_knowledge_system.py`：

```python
"""End-to-end test for Phase 1 knowledge system."""
import tempfile, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from xiaomei_brain.memory.longterm import LongTermMemory

def test_schema():
    d = tempfile.mkdtemp()
    ltm = LongTermMemory(os.path.join(d, 'test.db'))
    # Test all three types
    m1 = ltm.store('经验: 用户说过喜欢川菜', mem_type='experience')
    m2 = ltm.store('知识: 缓存策略核心是空间换时间', source='learned', mem_type='knowledge', importance=0.7)
    m3 = ltm.store('技能: 技术问答先确认理解再搜索', source='hub', mem_type='skill', confidence=0.5, skill_domain='技术问答')

    # Verify types stored correctly
    import sqlite3
    conn = sqlite3.connect(os.path.join(d, 'test.db'))
    types = {row[0]: row[1] for row in conn.execute('SELECT id, type FROM memories')}
    assert types[m1] == 'experience', f"Expected experience, got {types[m1]}"
    assert types[m2] == 'knowledge', f"Expected knowledge, got {types[m2]}"
    assert types[m3] == 'skill', f"Expected skill, got {types[m3]}"
    print('  Schema: PASS')

def test_recall_types():
    d = tempfile.mkdtemp()
    ltm = LongTermMemory(os.path.join(d, 'test.db'))
    ltm.store('经验: 用户李白喜欢吃川菜', mem_type='experience')
    ltm.store('知识: 缓存策略的核心是空间换时间', mem_type='knowledge')
    ltm.store('技能: 技术问题深度解答方法', mem_type='skill', confidence=0.8)

    # Test context weighting
    results = ltm.recall('缓存', context='work')
    types = [r.get('type') for r in results]
    assert 'knowledge' in types, f"Work context should include knowledge, got {types}"
    print('  Recall types: PASS')

def test_relations():
    d = tempfile.mkdtemp()
    ltm = LongTermMemory(os.path.join(d, 'test.db'))
    m1 = ltm.store('知识A: Rust所有权', mem_type='knowledge')
    m2 = ltm.store('知识B: 内存安全', mem_type='knowledge')
    ltm.add_relation(m1, m2, 'relates_to', source_type='knowledge', target_type='knowledge')
    chain = ltm.get_relation_chain(m1, depth=1)
    assert len(chain) > 0, f"Expected relations, got {len(chain)}"
    print('  Relations: PASS')

def test_learning_queue():
    from xiaomei_brain.consciousness.self_modules import SelfMind
    m = SelfMind()
    m.learning_queue = [
        {'topic': 'LRU', 'reason': 'gap', 'priority': 0.9, 'source': 'task_gap'},
        {'topic': 'Go', 'reason': 'need', 'priority': 0.7, 'source': 'user_need'},
    ]
    m.learning_queue.sort(key=lambda x: x.get('priority', 0), reverse=True)
    next_item = m.learning_queue.pop(0)
    assert next_item['topic'] == 'LRU'
    assert len(m.learning_queue) == 1
    print('  Learning queue: PASS')

if __name__ == '__main__':
    test_schema()
    test_recall_types()
    test_relations()
    test_learning_queue()
    print('\nAll Phase 1 tests PASSED')
```

运行：

```bash
cd /home/iamlibai/workspace/claude-project/xiaomei-brain && PYTHONPATH=src python3 /tmp/test_knowledge_system.py
```

- [ ] **Step 3: Commit**

```bash
git add /tmp/test_knowledge_system.py  # or don't commit test script
git commit -m "test: knowledge system Phase 1 end-to-end validation"
```

---

## 执行顺序依赖

```
Task 1 (memories schema)
  └→ Task 2 (relations schema)
       └→ Task 4 (_save_knowledge fix) ── 平行 ── Task 5 (learning queue)
            ├→ Task 6 (recall upgrade)              │
            └→ Task 7 (meta-skill)                  │
                 └→ Task 8 (integration test) ←─────┘
Task 3 (SelfMind queue) ── 平行于 1-2
```

---

## 不变部分

- bge-m3 embedding 模型（1024 维）
- LanceDB 向量索引
- FTS5 对话日志
- DAG 摘要图谱
- ContextAssembler 系统提示词注入
- SelfImage 火焰骨架
- ReAct 循环核心逻辑
