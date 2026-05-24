# 知识系统架构设计

> 创建时间：2026-05-24
> 状态：设计阶段
> 说明：统一经验、知识、技能三种记忆类型，构建 agent 的完整认知基础。

---

## 一、动机与定位

### 当前问题

1. **知识是死数据**：学习产出的 .md 文件从未被 agent 在任务中读取
2. **经验与知识混杂**：LongTermMemory 中对话碎片和知识点用同一方式存储和召回
3. **没有技能概念**：agent 每次执行任务都从零 ReAct，没有可复用的行为框架
4. **记忆之间无关联**：向量搜索只做语义匹配，不做关联扩散，无法"举一反三"

### 设计目标

让 agent 拥有一套**可生长的知识体系**——它知道之前经历过什么（经验）、理解了什么（知识）、会怎么做（技能）。这三者在任务执行时被动态激活，互相补充，随着使用不断演化。

### 核心决策

- **自然语言是通用接口**：经验、知识、技能全部用自然语言存储，LLM 原生消费
- **零配置**：用户不需要下载/安装文件，agent 自己从 Skill Hub 拉取或通过对话沉淀
- **图谱是创造力的基础**：概念之间的关联让跨域联想成为可能

---

## 二、三种记忆类型

统一存储在 LongTermMemory（SQLite 元数据 + LanceDB 向量索引），`type` 字段区分。

| type | 回答什么 | 来源 | 特点 |
|---|---|---|---|
| `experience` | 发生了什么 | immediate/periodic/dream 提取 | 绑定时间轴，时间衰减 |
| `knowledge` | 为什么/是什么 | 自主学习、经验提炼 | 去时间化，概念结构 |
| `skill` | 怎么做 | Hub 拉取、成功经验抽象 | 可执行引导，可信度评估 |

### 三者的转化关系

```
经验 ──反复成功──→ 抽象为知识 ──模式稳定──→ 固化为技能
                                           ↑
                              Skill Hub ──┘ (agent 自主拉取)
```

- **Phase 1**：只从外部 Hub 拉取技能，不在内部生成（"稚嫩的 agent 先上学"）
- **Phase 2+**：经验积累足够后，方可对技能进行改造、融合或创造

### 经验与知识的关系

不是截然二分，而是一个连续体：

- 经验（"上周用户说想学 Rust"）→ 绑定时间
- 泛化经验（"用户李白对系统编程有兴趣"）→ 开始去时间化
- 知识（"Rust 所有权系统在编译期保证内存安全"）→ 完全去时间化

`type` 标签标记的是连续体上的位置，而非绝对的类别。

---

## 三、存储架构

### 3.1 表结构

复用现有 `memories` 表，新增 `type` 列：

```sql
ALTER TABLE memories ADD COLUMN type TEXT DEFAULT 'experience';
-- type IN ('experience', 'knowledge', 'skill')
```

不拆表：拆表导致跨表搜索复杂、向量索引翻倍、LLM 召回时必须跨表合并排序。同一张表一次向量搜索全部命中，`type` 只影响召回权重和排序。

`source` 字段保留，表示来源方式（immediate/periodic/dream/manual/learned/hub），与 `type` 正交：

| source | 含义 |
|---|---|
| immediate | 对话即时提取 |
| periodic | 定时批量提取 |
| dream | 梦境巩固 |
| learned | 自主学习 |
| hub | Skill Hub 拉取 |
| manual | 手动存入 |

### 3.2 额外字段

技能类型需要额外元数据：

```sql
ALTER TABLE memories ADD COLUMN confidence REAL DEFAULT NULL;
-- NULL for experience/knowledge, 0.0-1.0 for skill

ALTER TABLE memories ADD COLUMN skill_domain TEXT DEFAULT NULL;
-- e.g. "技术问答", "用户教育", "代码审查"
```

### 3.3 LanceDB 向量索引

现有 `bge-m3` embedding（1024 维），不变。三种类型共用同一向量索引。

### 3.4 知识图谱关系表

升级现有 `memory_relations` 表，增加节点类型和边类型：

```sql
CREATE TABLE IF NOT EXISTS memory_relations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER NOT NULL,       -- 源节点 memory id
    source_type TEXT NOT NULL,         -- 'experience' | 'knowledge' | 'skill'
    target_id INTEGER NOT NULL,        -- 目标节点 memory id (或 -1 表示外部引用)
    target_type TEXT NOT NULL,         -- 'experience' | 'knowledge' | 'skill' | 'tool'
    relation_type TEXT NOT NULL,       -- 'similar' | 'uses' | 'depends_on' | 'produces' | 'relates_to'
    weight REAL DEFAULT 1.0,           -- 边权重（共现增强）
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    FOREIGN KEY (source_id) REFERENCES memories(id) ON DELETE CASCADE
    -- 注：只对 source 建 FK。target 可能是 memory 条目也可能是外部引用（如工具名）
    -- 当 target_type='tool' 时，target_id=-1，工具名从 skill 内容自然语言中解析
);```

工具关系不建图边——技能→工具的关联直接写在技能自然语言的"关联"段落中，LLM 阅读时自然理解。图边只用于 memory ↔ memory 的关联。

边类型：

| relation_type | 含义 | 示例 |
|---|---|---|
| `similar` | 技能/知识相似 | "技术问答" ←→ "技术方案评审" |
| `depends_on` | 依赖某条知识 | "技术问答" → "批判性思维"知识点 |
| `produces` | 经验提炼为知识 | "用户问LLM"经验 → "Transformer"知识点 |
| `relates_to` | 通用关联 | 任何有意义的跨类型关系 |

### 3.5 关联的自动建立

**存储时建立**：存入 type=knowledge 或 type=skill 的 memory 时，LLM 在生成内容末尾追加结构化的"关联"段落（见 5.2 示例中的 `### 关联` 部分）。代码在 `store()` 之后解析该段落：

```
### 关联
→ 知识点: [Rust所有权] [Transformer架构]
→ 相关技能: [复杂概念简化解释]
→ 工具: websearch, web_fetch, memory_search
```

解析逻辑：
1. 按 `→` 行分割，识别 target_type（知识点→knowledge, 相关技能→skill, 工具→tool）
2. 对 knowledge/skill 类型的目标，通过 memory_search 查找已有条目，建立边
3. 工具类型不建边（工具名留在自然语言内容中，LLM 自行理解）

**使用时增强（Hebbian）**：同一个 query 同时召回了 A 和 B 并被 LLM 实际使用了，A 和 B 之间的边权重 +0.1。反复共现 → 边逐渐增强 → 未来扩散时优先走强边。

---

## 四、召回策略

### 4.1 统一入口，上下文感知权重

一个 `memory_search` 工具，不拆分。调用方根据上下文注入 `context` 参数：

| context | 权重偏好 | 典型场景 |
|---|---|---|
| `work` | skill > knowledge > experience | 闹钟触发、自主工作、L2 意图执行 |
| `chat` | experience > knowledge > skill | 用户日常对话 |
| `auto`（默认）| 均衡 | 不确定的场景 |

`context` 参数**不暴露给 LLM**——由调用方（ConsciousLiving、action_dispatcher、core.chat）在构建消息时自动注入。

### 4.2 召回流程

```
memory_search(query, context="work", top_k=10)
        │
        ▼
  向量召回 top_k=10（LanceDB 语义搜索）
        │
        ▼
  按 type 分拣 + context 权重排序：
    skill × 3       → confidence DESC, 不衰减
    knowledge × 4   → importance * strength DESC
    experience × 3  → time-decayed strength DESC
        │
        ▼
  图谱扩散 1-2 跳：
    对每个召回结果，沿 memory_relations 扩散
    收集关联的 knowledge / skill / experience
    合并去重，按 hop 升序追加
        │
        ▼
  三段式输出：

    [相关经验]
    - 2026-05-20: 用户提到过...#123
    - ...

    [我知道什么]
    - 缓存策略的核心是...
    - 数据库索引与缓存的关系...

    [我会怎么做]
    - 技术方案设计 (confidence=0.85)
    - ...
```

### 4.3 与现有 memory_search 的关系

现有的 `memory_search` 已经有扩散激活骨架（`get_relation_chain` + hop 扩散），但关系表几乎为空且无类型区分。升级路径：
1. 迁移 `memory_relations` 表结构（加 source_type/target_type/relation_type/weight）
2. 召回时按 type 分拣 + context 权重
3. 三段式输出格式化

---

## 五、技能子系统

### 5.1 核心理念

**技能不是文件，是记忆的一种。** 行业做法是 SKILL.md 文件系统 + 渐进式加载，xiaomei-brain 的做法是：技能以自然语言存储在 LongTermMemory 中，通过语义搜索被动态激活。零配置，用户不需要下载任何东西。

### 5.2 技能存储格式（自然语言）

```
## 技术问题深度解答
type: skill
domain: [技术问答, 用户教育]
confidence: 0.85

### 什么时候用
用户询问需要准确理解的技术概念，尤其是「为什么」「怎么工作的」之类的问题。

### 怎么做
1. 确认理解：用自己的话先复述用户的问题，确认方向对了
2. 多角度搜索：至少看 2-3 个不同的来源，验证信息一致性
3. 关联已知：查记忆里有没有相关知识和之前的对话
4. 结构化输出：从「是什么 → 为什么 → 怎么做」层层递进

### 注意
- 宁可说"这部分我不确定"也不要编造
- 用户是技术背景时可以深一些，否则先建立直觉再深入

### 关联
→ 知识点: [Rust所有权] [Transformer架构] [缓存策略]
→ 相关技能: [复杂概念简化解释] [用户教育方法论]
→ 工具: websearch, web_fetch, memory_search
```

### 5.3 技能生命周期

```
[拉取] → [使用] → [验证/内化]
  ↑
GitHub / Skill Hub —— "上学"

（成熟后，Phase 2+）
  经验积累 → 改造现有技能 / 融合创造新技能 —— "做研究"
```

**拉取（Phase 1）**：
- 元技能驱动：agent 搜索 clawhub.ai / GitHub awesome-skills
- 评估质量：stars、更新时间、来源可信度
- 用 web_fetch 拉取 SKILL.md 全文
- 转换格式：提取核心内容，整理为自然语言技能模板
- 存入 LongTermMemory：type=skill, source=hub, confidence=0.5（初始可信度）

**使用**：
- 任务开始时 memory_search 语义召回命中技能
- agent 在 ReAct 循环中看到 type=skill 的内容，以此为行为框架
- 不是机械执行步骤，而是类似人看了 SOP——理解意图，灵活变通

**验证/内化**：
- 执行成功 → confidence += 0.05
- 执行失败 → confidence -= 0.1，记录失败原因
- 连续失败（confidence < 0.2）→ 技能标记为待修正，触发反思
- 高频使用且 confidence > 0.9 → 技能进入"习惯"状态，减少显式召回频率

### 5.4 元技能（Bootstrap）

元技能是 agent 出厂自带的特殊技能，硬编码在代码中，不从外部拉取。它让 agent 初始就具备"学习技能的能力"。

```
skill: 技能获取
type: meta-skill
confidence: 1.0

### 什么时候用
- 遇到没把握处理的任务领域
- 用户说"你去学一下XX"
- 空闲时探索 Skill Hub，主动扩展能力

### 怎么做
1. 搜索 clawhub.ai 或 GitHub awesome-skills，找到匹配的技能
2. 评估：看 GitHub stars（>100）、最近更新时间（半年内）、描述是否匹配
3. 用 web_fetch 拉取 SKILL.md 全文
4. 转换为自然语言技能格式，嵌入 agent 身份视角
5. 存入 LongTermMemory：type=skill, source=hub, confidence=0.5
6. 告诉用户"我学会了 XX 技能"，简要说明能力范围

### 注意
- 同一领域只保留最好的 1-2 个技能，避免冗余
- 拉取前先 memory_search 检查是否已有类似技能
- 如果已有但质量不高（confidence < 0.3），可以拉取新版本替换
```

### 5.5 Skill Hub 集成

不对接任何特定平台的 API——通用网页抓取方案：

1. `websearch` → 找到技能页面/仓库
2. `web_fetch` → 拉取 SKILL.md 或 README.md
3. LLM 解析 → 提取核心内容，转换为自然语言技能格式

支持的源：
- clawhub.ai（技能浏览器，自然搜索）
- GitHub awesome-skills 仓库
- GitHub 上遵循 Anthropic Skills 标准的仓库（SKILL.md 文件）

---

## 六、Phase 规划

### Phase 1：Bootstrap — 知识可用（当前阶段）

**目标**：agent 拥有可检索的知识体系，技能能被召回和用于任务。

- [ ] `type` 列迁移：`memories` 表新增 type（experience/knowledge/skill），现有记录默认 'experience'
- [ ] `confidence` / `skill_domain` 列：仅 skill 类型使用
- [ ] 元技能硬编码：出厂自带"技能获取"引导
- [ ] 从 Hub 拉取技能：用户说"去学 XX" → 元技能驱动 → 搜索 → 拉取 → 存入
- [ ] 召回升级：三段式输出（经验/知识/技能），context 权重（work/chat）
- [ ] 图谱升级：`memory_relations` 表结构升级，存储时自动建关联，召回时扩散 1-2 跳

### Phase 2：学习闭环 — 知识生长

**目标**：知识能随使用演化，质量不断提升。

- [ ] confidence 评估→技能验证与修正
- [ ] 知识冲突检测：同一领域多条知识不一致时触发反思
- [ ] 经验→知识自动提炼：InnerVoice 反思期识别反复出现的模式
- [ ] 知识→技能自动提炼：稳定的知识 + 成功经验 → 半自动生成技能（需用户确认）

### Phase 3：涌现 — 创造力

**目标**：跨域关联产生新想法，"举一反三"成为现实。

- [ ] 图扩散成熟：A 领域的技能启发 B 领域的方案
- [ ] Hebbian 边强化：长期共现的节点形成强边
- [ ] 技能自主改造：agent 基于已有技能创造变体
- [ ] 长期未用的知识/技能自然衰减，符合记忆强度曲线

---

## 七、迁移路径

### 对现有系统的影响

| 组件 | 变化 |
|---|---|
| `memories` 表 | 新增 type、confidence、skill_domain 列 |
| `memory_relations` 表 | 新增 source_type、target_type、relation_type、weight 列 |
| `memory_search` 工具 | 升级召回逻辑（三段式 + context权重 + 图扩散） |
| `LongTermMemory.store()` | type 参数支持 'skill' |
| `LongTermMemory.recall()` | 支持 type 过滤和 context 权重 |
| `action_dispatcher._react_learn()` | 已实现 ReAct 学习，知识存入时 type=knowledge |
| `action_dispatcher._save_knowledge()` | 已实现索引到 LongTermMemory |
| knowledge/*.md | 不管，测试产物 |

### 不变的部分

- SQLite + LanceDB 存储架构
- bge-m3 embedding 模型（1024 维）
- 现有 FTS5 对话日志
- DAG 摘要图谱
- ContextAssembler 系统提示词注入
- SelfImage 火焰骨架

---

## 八、元技能详细规格（Phase 1 实现参考）

### 存储位置

元技能不存储在 LongTermMemory 中（避免被污染或误删），而是硬编码在代码中，作为 `memory_search` 或新工具的引导。

### 触发方式

- **用户指令**："去学个 XX 技能"、"帮我找个代码审查的技能"
- **L2 自主判断**：InnerVoice 在执行失败后发现"缺少 XX 领域的技能"，触发 L2 生成 INTENT → ActionDispatcher → 元技能执行
- **空闲探索**：agent 在 IDLE 状态时主动浏览 Hub，扩展未覆盖的领域

### 执行流程

```
触发 → memory_search(self) → 已有类似技能？
  ├── 有且 confidence > 0.5 → 返回，告诉用户"我已经会了"
  ├── 有但 confidence < 0.3 → 标记旧技能，拉取新版本
  └── 没有 → websearch("site:clawhub.ai <domain> skill")
             → websearch("github awesome-skills <domain>")
             → 评估候选 → web_fetch 拉取最优
             → LLM 转换为自然语言格式
             → 存入 LongTermMemory (type=skill, source=hub)
             → 建立关联边（skill → 相关 knowledge / tool）
             → 告知用户
```

---

## 九、设计决策记录

| 决策 | 选择 | 理由 |
|---|---|---|
| 存储形式 | 自然语言（非文件） | LLM 原生消费，零配置，可语义搜索 |
| 表结构 | 一张表 + type 列 | 一次搜索跨类型命中，无需跨表合并 |
| 召回工具 | 统一 memory_search | 不暴露选择负担给 LLM，context 自动区分 |
| 技能来源 | Phase1 只从 Hub 拉取 | agent 稚嫩时自我生成质量不可靠 |
| 图谱 | 存储时自动建边 + 使用时 Hebbian 强化 | 自动化，不增加人工负担 |
| Skill Hub | 通用网页抓取（不接专用 API） | 最大化兼容性，不绑定特定平台 |
