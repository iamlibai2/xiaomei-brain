# 记忆系统升级设计：碎片存储 + 场景标签 + 关系权重

## 设计目标

三层架构：存储层（碎片+场景标签）→ 检索层（场景过滤+语义+关系扩散）→ 加固层（梦境共现加固+衰减）

---

## 改动1：`memory/longterm.py` — 存储层

### 1a. 记忆主表加场景标签

```python
# _init_tables() 中加迁移
def _init_tables(self):
    # ... 现有表创建 ...

    # 迁移：场景标签字段
    try:
        self.conn.execute("ALTER TABLE memories ADD COLUMN scene_tags TEXT DEFAULT '[]'")
    except sqlite3.OperationalError:
        pass  # 字段已存在

    # 迁移：记忆关系表加权重
    try:
        self.conn.execute("ALTER TABLE memory_relations ADD COLUMN weight REAL DEFAULT 0.5")
        self.conn.execute("ALTER TABLE memory_relations ADD COLUMN last_reinforced REAL DEFAULT 0")
    except sqlite3.OperationalError:
        pass

    # 新表：记忆共现追踪
    self.conn.execute("""
        CREATE TABLE IF NOT EXISTS memory_co_occur (
            mem_a_id INTEGER NOT NULL,
            mem_b_id INTEGER NOT NULL,
            count INTEGER DEFAULT 1,
            last_occur REAL NOT NULL,
            PRIMARY KEY (mem_a_id, mem_b_id)
        )
    """)
```

### 1b. 新增方法

```python
def store(self, content, source=None, tags=None, importance=0.5, user_id="global",
          scene_tags=None):
    """存记忆，支持 scene_tags 参数"""
    # 在现有 store 上加 scene_tags 参数，默认 None
    # 写入时：scene_tags 为 None 时存 '[]'，否则存 json.dumps(scene_tags)
    ...

def add_scene_tag(self, memory_id, scene_tag):
    """给已有记忆追加场景标签"""
    cur = self.conn.execute("SELECT scene_tags FROM memories WHERE id = ?", (memory_id,))
    row = cur.fetchone()
    if not row:
        return
    tags = json.loads(row[0] or "[]")
    if scene_tag not in tags:
        tags.append(scene_tag)
        self.conn.execute("UPDATE memories SET scene_tags = ? WHERE id = ?",
                          (json.dumps(tags), memory_id))
        self.conn.commit()

def get_by_scene(self, scene_tag, user_id="global", limit=50):
    """按场景标签筛选记忆"""
    cur = self.conn.execute(
        "SELECT id, content, scene_tags, importance, created_at FROM memories "
        "WHERE user_id = ? AND deleted = 0",
        (user_id,)
    )
    result = []
    for row in cur.fetchall():
        tags = json.loads(row[2] or "[]")
        if scene_tag in tags:
            result.append({
                "id": row[0], "content": row[1],
                "scene_tags": tags, "importance": row[3],
                "created_at": row[4],
            })
    return result[:limit]

def add_relation(self, from_memory_id, to_memory_id, relation_type,
                 context="", weight=0.5):
    """建关系时带权重（现有方法加 weight 参数，默认 0.5）"""
    ...

def reinforce_relation_weight(self, rel_id, boost=0.1):
    """加固关系权重：weight += boost * (1 - weight)"""
    cur = self.conn.execute(
        "SELECT weight FROM memory_relations WHERE id = ?", (rel_id,)
    )
    row = cur.fetchone()
    if not row:
        return
    old_weight = row[0]
    new_weight = min(1.0, old_weight + boost * (1.0 - old_weight))
    self.conn.execute(
        "UPDATE memory_relations SET weight = ?, last_reinforced = ? WHERE id = ?",
        (new_weight, time.time(), rel_id)
    )
    self.conn.commit()

def decay_relation_weights(self, threshold_days=7, decay_rate=0.95, min_weight=0.05):
    """衰减长期未加固的关系权重"""
    cutoff = time.time() - threshold_days * 86400
    cur = self.conn.execute(
        "SELECT id, weight FROM memory_relations WHERE last_reinforced < ? AND last_reinforced > 0",
        (cutoff,)
    )
    for row in cur.fetchall():
        rel_id, weight = row
        new_weight = weight * decay_rate
        if new_weight < min_weight:
            new_weight = 0.0  # 标记为休眠
        self.conn.execute(
            "UPDATE memory_relations SET weight = ? WHERE id = ?",
            (new_weight, rel_id)
        )
    self.conn.commit()

def get_related_with_weight(self, memory_id, min_weight=0.3, relation_type=None):
    """获取关联记忆，按 weight 过滤+降序"""
    if relation_type:
        cur = self.conn.execute(
            "SELECT r.id, m.id, m.content, r.relation_type, r.weight "
            "FROM memory_relations r JOIN memories m ON "
            "(r.to_memory_id = m.id AND r.from_memory_id = ?) "
            "WHERE r.weight >= ? AND r.relation_type = ? AND m.deleted = 0 "
            "ORDER BY r.weight DESC",
            (memory_id, min_weight, relation_type)
        )
    else:
        cur = self.conn.execute(
            "SELECT r.id, m.id, m.content, r.relation_type, r.weight "
            "FROM memory_relations r JOIN memories m ON "
            "(r.to_memory_id = m.id AND r.from_memory_id = ?) "
            "WHERE r.weight >= ? AND m.deleted = 0 "
            "ORDER BY r.weight DESC",
            (memory_id, min_weight)
        )
    return [
        {"rel_id": r[0], "memory_id": r[1], "content": r[2],
         "relation_type": r[3], "weight": r[4]}
        for r in cur.fetchall()
    ]

def _record_co_occur(self, memory_ids):
    """记录一组记忆共现（在 recall 末尾调用）"""
    if len(memory_ids) < 2:
        return
    now = time.time()
    # 两两组合
    for i in range(len(memory_ids)):
        for j in range(i + 1, len(memory_ids)):
            a, b = memory_ids[i], memory_ids[j]
            if a == b:
                continue
            a_id, b_id = (a, b) if a < b else (b, a)
            self.conn.execute(
                "INSERT INTO memory_co_occur (mem_a_id, mem_b_id, count, last_occur) "
                "VALUES (?, ?, 1, ?) "
                "ON CONFLICT(mem_a_id, mem_b_id) DO UPDATE SET "
                "count = count + 1, last_occur = ?",
                (a_id, b_id, now, now)
            )
    self.conn.commit()
```

---

## 改动2：`memory/longterm.py` — 检索层

### 2a. `recall()` 加 scene 参数

```python
def recall(self, query, user_id="global", top_k=10, sources=None, scene=None):
    """增强 recall：支持场景过滤"""
    # ── 如果有 scene 参数，先按场景标签过滤候选集 ──
    scene_filter_ids = None
    if scene:
        scene_memories = self.get_by_scene(scene, user_id, limit=100)
        if scene_memories:
            scene_filter_ids = [m["id"] for m in scene_memories]
        else:
            # 场景无结果，直接返回空
            return []

    # ── 语义搜索 ──
    # 现有语义搜索逻辑不变，但如果 scene_filter_ids 有值，
    # 在 LanceDB 搜索时加 id 过滤（或搜索后过滤）
    # 注意：LanceDB 不直接支持 SQL 过滤，可以在内存中过滤
    ...
    result = self._semantic_search(query, user_id, top_k * 3, sources)

    # ── 场景过滤（如果有） ──
    if scene_filter_ids is not None:
        result = [r for r in result if r["id"] in scene_filter_ids]

    # ── 取 top_k ──
    result = result[:top_k]

    # ── 共现记录 ──
    if len(result) >= 2:
        self._record_co_occur([r["id"] for r in result])

    # ── 关联扩散：如果结果不足 top_k，从关联记忆中补 ──
    if len(result) < top_k and result:
        related_ids = set()
        for r in result:
            related = self.get_related_with_weight(r["id"], min_weight=0.3)
            for rel in related:
                related_ids.add(rel["memory_id"])
        # 排除已在结果中的
        existing_ids = {r["id"] for r in result}
        fill_ids = related_ids - existing_ids
        if fill_ids:
            fill_memories = self.get_by_ids(list(fill_ids), user_id)
            # 按关系 weight 排序补入
            fill_memories.sort(
                key=lambda m: max(
                    (r.weight for rel_list in
                     [self.get_related_with_weight(m["id"], min_weight=0.3)]
                     for r in rel_list),
                    default=0
                ),
                reverse=True
            )
            result.extend(fill_memories[:top_k - len(result)])

    return result
```

注意：`_semantic_search` 和 `get_by_ids` 需确认是否已存在，不存在则补充。

---

## 改动3：提取 prompt — 产出原子碎片+场景标签

### 3a. 修改 `EVERY_TURN_EXTRACT_PROMPT`

当前 prompt 倾向于让 LLM 输出整句。改为：

```
从对话中提取值得长期记忆的原子信息。
规则：
- 每一条只包含一个原子事实/偏好/经验，不要合并
- 用 scene_tags 标记适用的场景（如"家里""公司""成都旅游""开会"等）
- 如果这条记忆适用于所有场景，scene_tags 为 []
```

JSON action 格式加 scene_tags 字段：

```json
{
  "actions": [
    {
      "type": "ADD",
      "tag": "偏好",
      "content": "用户喜欢吃水煮鱼",
      "scene_tags": ["家里", "川菜馆"]
    },
    {
      "type": "ADD",
      "tag": "偏好",
      "content": "用户讨厌香菜",
      "scene_tags": []
    }
  ],
  "relations": [...]
}
```

### 3b. `memory/extractor.py` — `_execute_json_actions()` 解析 scene_tags

```python
# 在 ADD 分支中，读取 scene_tags 字段
scene_tags = action_item.get("scene_tags", None)
if scene_tags is None and tag == "偏好":
    # 旧格式兼容，无 scene_tags
    pass

# 调用 store 时传入
memory_id = self.ltm.store(
    content=content, source=source, tags=[tag],
    importance=imp, user_id=user_id,
    scene_tags=scene_tags,  # 新增参数
)
```

---

## 改动4：`consciousness/dream/memory_jobs.py` — 新增 RelationReinforceJob

新建一个 Job 类，在 DREAMING 阶段执行：

```python
@dataclass
class RelationReinforceResult:
    reinforced_count: int = 0      # 加固了多少条关系
    created_count: int = 0         # 新建了多少条关系
    decayed_count: int = 0         # 衰减了多少条关系
    scene_clustered: int = 0       # 自动打了场景标签的记忆数

class RelationReinforceJob:
    """梦境阶段：加固记忆间关系权重 + 场景标签聚类"""

    def __init__(self, ltm: LongTermMemory, llm=None, user_id="global"):
        self.ltm = ltm
        self.llm = llm
        self.user_id = user_id

    def run(self) -> RelationReinforceResult:
        result = RelationReinforceResult()

        # 1. 共现 → 加固/建关系
        self._reinforce_from_co_occur(result)

        # 2. 衰减未使用的边
        self._decay_old_relations(result)

        # 3. 场景聚类（可选，依赖 LLM）
        if self.llm:
            self._cluster_scenes(result)

        return result

    def _reinforce_from_co_occur(self, result):
        """读 co_occur 表，top 50 对加固/建边"""
        cur = self.ltm.conn.execute(
            "SELECT mem_a_id, mem_b_id, count FROM memory_co_occur "
            "ORDER BY count DESC LIMIT 50"
        )
        pairs = cur.fetchall()
        for a_id, b_id, count in pairs:
            # 查是否已有关系
            rel_cur = self.ltm.conn.execute(
                "SELECT id, weight FROM memory_relations "
                "WHERE (from_memory_id = ? AND to_memory_id = ?) "
                "   OR (from_memory_id = ? AND to_memory_id = ?)",
                (a_id, b_id, b_id, a_id)
            )
            existing = rel_cur.fetchone()
            if existing:
                # 已有关系 → 加固
                self.ltm.reinforce_relation_weight(existing[0], boost=0.1)
                result.reinforced_count += 1
            elif count >= 3:
                # 共现 >= 3 次且无关系 → 新建 co_occur 边，低权重起步
                self.ltm.add_relation(
                    from_memory_id=a_id,
                    to_memory_id=b_id,
                    relation_type="co_occur",
                    context="auto: high co-occurrence",
                    weight=0.2,
                )
                result.created_count += 1

    def _decay_old_relations(self, result):
        """衰减长期未加固的关系"""
        self.ltm.decay_relation_weights()
        result.decayed_count = 0  # 具体数量可在 decay 方法返回

    def _cluster_scenes(self, result):
        """（可选）对无场景标签的记忆做聚类"""
        cur = self.ltm.conn.execute(
            "SELECT id, content, tags FROM memories "
            "WHERE user_id = ? AND deleted = 0 AND scene_tags = '[]' "
            "ORDER BY importance DESC LIMIT 20",
            (self.user_id,)
        )
        untagged = cur.fetchall()
        if len(untagged) < 5:
            return

        # 调 LLM 判断场景归属
        memory_text = "\n".join(
            f"[{row[0]}] {row[1]}" for row in untagged
        )
        prompt = f"""分析以下记忆属于什么场景（如家里/公司/旅游/运动/学习等）。
为每条记忆分配 1~2 个场景标签，如果无法判断则留空。

记忆列表：
{memory_text}

输出 JSON:
{{"scene_assignments": [{{"id": 1, "scenes": ["家里"]}}, ...]}}
"""
        response = self.llm.chat(
            messages=[{"role": "user", "content": prompt}],
        )
        try:
            import json
            data = json.loads(response.content)
            for assign in data.get("scene_assignments", []):
                mem_id = assign["id"]
                scenes = assign.get("scenes", [])
                for scene in scenes:
                    self.ltm.add_scene_tag(mem_id, scene)
                    result.scene_clustered += 1
        except Exception:
            pass
```

---

## 改动5：`consciousness/dream/memory_organizer.py` — 接入管道

```python
@dataclass
class MemoryOrganizeResult:
    reinforced: int = 0
    extracted: int = 0
    relations_reinforced: int = 0    # 新增
    relations_created: int = 0       # 新增
    scene_clustered: int = 0         # 新增

class MemoryOrganizer:
    def organize(self, ...) -> MemoryOrganizeResult:
        result = MemoryOrganizeResult()

        # 1. 单条记忆加固（已有）
        reinforce_result = self.jobs["reinforce"].run()
        result.reinforced = len(reinforce_result)

        # 2. 提取新记忆（已有）
        extract_result = self.extractor.extract_dream(...)
        result.extracted = len(extract_result)

        # 3. 关系权重加固 + 场景聚类（新增）
        if self.ltm:
            relation_job = RelationReinforceJob(
                ltm=self.ltm, llm=self.llm, user_id=self.user_id
            )
            rel_result = relation_job.run()
            result.relations_reinforced = rel_result.reinforced_count
            result.relations_created = rel_result.created_count
            result.scene_clustered = rel_result.scene_clustered

        return result
```

---

## 改动6：`consciousness/dream/dream_engine.py` — DreamReport 加字段

```python
@dataclass
class DreamReport:
    # ... 现有字段 ...
    relations_reinforced: int = 0   # 新增
    relations_created: int = 0      # 新增
    scene_clustered: int = 0        # 新增
```

在 dream cycle 日志中输出新增字段。

---

## 改动清单汇总

| # | 文件 | 改动 | 行数 |
|---|---|---|---|
| 1 | `memory/longterm.py` — `_init_tables` | 迁移 scene_tags + weight + co_occur 表 | 15 |
| 2 | `memory/longterm.py` — 新增方法 | store 加 scene_tags, add_scene_tag, get_by_scene, add_relation 加 weight, reinforce_relation_weight, decay_relation_weights, get_related_with_weight, _record_co_occur | 80 |
| 3 | `memory/longterm.py` — recall | 加 scene 参数，场景过滤，关联扩散，共现记录 | 40 |
| 4 | `prompts/` — 提取 prompt | 碎片化 + scene_tags 输出 | 15 |
| 5 | `memory/extractor.py` — JSON actions | 解析 scene_tags 字段 | 10 |
| 6 | `consciousness/dream/memory_jobs.py` | 新增 RelationReinforceJob | 80 |
| 7 | `consciousness/dream/memory_organizer.py` | organize 加第三步入管道 | 20 |
| 8 | `consciousness/dream/dream_engine.py` | DreamReport 加字段 | 3 |
| 9 | `consciousness/dream/__init__.py` | 导出新类 | 1 |

**总计约 260 行新代码，零重构。**

---

## 实施顺序建议

1. **第一步**：改 `longterm.py` 的数据结构（表迁移 + 新方法）— 这是地基，不改其他代码跑不了
2. **第二步**：改 `extractor.py` + prompt — 让新存的数据带有 scene_tags
3. **第三步**：改 `recall()` + `get_related()` — 检索层用场景过滤和权重排序
4. **第四步**：改 dream 模块 — 加固 + 衰减 + 场景聚类，闭环
