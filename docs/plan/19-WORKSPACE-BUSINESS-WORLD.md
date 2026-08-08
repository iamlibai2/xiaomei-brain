# Workspace 业务世界与 Surface 设计

> 状态：核心方向已确认，等待分阶段实施  
> 本文定义 Workspace 的长期领域模型、第一版边界、现有原型差距和实施顺序。它不要求一次性完成全部对象，也不把 Workspace 建设成传统低代码、OA、权限或工作流平台。

## 1. 一句话定义

`Workspace` 是 Agent 围绕一项持续业务建立并长期维护的数字工作现场。

它不是文件夹、数据库、会话、项目、看板或固定软件页面。它承载 Agent 对一个业务世界的观察、理解、当前事实、行为、历史、数据、资产和交互界面，并随着真实使用逐渐结晶。

`Surface` 是人和 Agent 共同接触、理解和操作这个业务世界的交互表面。

## 2. 出发点

第一版不假设面对一家已经拥有成熟 ERP、CRM、数据仓库和复杂组织制度的企业。默认场景是一家公司或一项业务刚刚开始：没有历史系统负担，但信息仍然可能从对话、文件、飞书、钉钉、邮件、API 和后续接入的外部系统进入。

产品目标不是先复刻传统企业软件，而是让 Agent 陪业务从第一条客户信息、第一份报价和第一笔订单开始，逐渐形成自己的业务结构和交互界面。

```text
真实业务发生
    ↓
Agent 观察、理解并行动
    ↓
稳定的事实、语言、行为和界面逐渐结晶
    ↓
软件从真实使用中生长出来
```

## 3. 根本原则

### 3.1 Agent 是主体

Workspace 是 Agent 所生活和工作的业务现场，不是控制 Agent 的中央系统。Agent 负责理解业务、作出判断和组织工作；基础设施负责保持数据一致、来源可追溯和执行结果可靠。

### 3.2 从业务语言出发

用户不负责设计数据库表、字段、工作流和页面。用户表达自己理解的业务，Agent 将其转化为稳定结构；存在歧义时询问业务问题，而不是技术问题。

### 3.3 自由与精确各居其位

Agent 可以自由理解、计划和选择做法；CollectionService、SchemaResolver 和 ActionService 保证写入、计算和业务改变准确。Process 若未来存在，只规定必须交付或遵守的外部标准，不成为 Agent 的思考中心。

### 3.4 逐渐结晶

一次使用不应立刻制造永久结构。业务对象、术语、Action 和 Surface 可以先作为候选存在，经过重复使用、纠正和真实结果验证后再稳定下来。

### 3.5 第一版聚焦业务，不聚焦防御

第一版不建设复杂角色、权限树、字段 ACL、多级审批和组织流程。先提供覆盖数据库与 Asset 的定期备份作为兜底。身份用于建立关系和责任来源，不立即扩展成传统权限系统。

外部客户端不能绕过 Agent 任意读取或支配其数据；这一边界保护的是 Agent 的主体性，不是建设企业权限平台。

### 3.6 内部改变和外部影响不同

内部数据改变通常可以通过备份恢复。邮件发送、消息外发、付款、公开发布和外部删除等不可逆行为不能假装可回滚，由 Agent 根据后果、Context 和确信程度自主判断是否需要确认。

### 3.7 对话优先，界面辅助

Workspace 的创建、更新、查询和关闭必须能够通过自然对话完成。Surface 为稳定、高频的观察和操作提供便利，但不要求用户学习页面配置、数据绑定或低代码设计器。

## 4. 总体领域模型

```text
Agent
└─ Workspace
   ├─ DataSource   世界从哪里进入或写回
   ├─ Observation  Agent 观察到了什么
   ├─ Context      Agent 如何理解这个业务世界
   ├─ Collection   世界当前是什么状态
   ├─ Action       Agent 如何改变这个世界
   ├─ RecordChange 数据具体如何变化
   ├─ Event        业务中什么已经发生
   ├─ Asset        长期存在的数字对象
   ├─ Dataset      如何提炼和计算业务
   └─ Surface      人与 Agent 如何共同接触和操作世界
```

核心链路：

```text
对话 / 文件 / Channel / 邮件 / API
                ↓
           DataSource
                ↓
           Observation
                ↓ 由 Context 帮助理解
              Agent
                ↓
             Action
                ↓
     Collection + RecordChange + Event
                ↓
             Dataset
                ↓
             Surface
```

## 5. Workspace

### 5.1 形成条件

以下信号适合形成 Workspace：

- 存在明确的持续业务意图；
- 开始出现多个持续变化的业务对象；
- 同类信息需要反复更新、查询或采取行动；
- 用户明确要求长期跟踪或经营；
- 多个 Session、Assignment、Project 和 Asset 开始围绕共同业务目的聚集。

一次知识问答、格式转换、临时数据分析或单个短期委托通常不创建 Workspace。Agent 可以先保留未归属的 Observation 与 Asset，持续性明确后再创建 Workspace 并回溯关联已有内容。

### 5.2 业务边界

Workspace 由共同的业务目的、业务对象和业务规则界定，不按人物、渠道、文件类型或软件功能拆分。

第一天不应预先拆成销售、财务、合同、客户等多个 Workspace。只有不同方向开始拥有相对独立的目的、对象、Context、生命周期和经营指标时才考虑拆分。

### 5.3 与现有对象的关系

| 对象 | 含义 | 与 Workspace 的关系 |
|---|---|---|
| Agent | 持续存在的行动主体 | 一个 Agent 可以生活在多个 Workspace 中 |
| Person | Agent 认识和交往的人 | 可参与多个 Workspace，但不拥有 Agent 或 Workspace |
| Session | 一段对话现场 | 默认聚焦一个 Workspace，每个 Turn 可单独关联 |
| Assignment | 一次有目标和交付的委托 | 可在 Workspace 中执行，完成后结束 |
| Project | 一个有开始、终点和持续工作现场的复杂事务 | 可属于 Workspace，完成后成果仍留在 Workspace |
| Goal / PACE | Agent 自身追求和推进机制 | 不等同于外部业务 Workspace |
| Surface | 业务交互界面 | 一个 Workspace 可以拥有多个 Surface |

### 5.4 生命周期

第一版只保留：

- `active`：仍在发生和被关注；
- `closed`：业务已经停止，但历史完整保留。

不增加归档箱和复杂整理功能。最近使用的 Workspace 自然排列在前，关闭后可以再次激活。

### 5.5 所有权

Workspace 属于对应 Agent 的世界。`created_by_person_id` 只记录事实，不表示创建者永久拥有或控制它。Person 关联用于理解参与关系和向 Desktop 投影相关内容，不在第一版发展为角色和权限矩阵。

## 6. DataSource 与 Observation

### 6.1 DataSource

DataSource 是业务事实进入 Workspace 的稳定来源，以及必要时写回外部世界的出口，例如：

- Desktop、飞书、钉钉等对话入口；
- 本地文件、邮箱、外部文档；
- 数据库、API、设备和后续企业系统。

第一版主要支持三种语义：

- `capture`：提取事实并写入 Workspace，适合从零开始的业务；
- `reference`：内容留在外部，Workspace 保存稳定引用；
- `external_authority`：未来外部成熟系统拥有最终事实，Workspace 查询或缓存。

第一版默认使用 `capture`，不提前建设复杂双向同步平台。

### 6.2 Observation

Observation 表示 Agent 收到了一条信息，但尚未确认它具体意味着什么。它保存来源、外部定位、原始内容或 Asset 引用、来源人物、发生时间、接收时间、处理状态和可能关联的业务对象。

Observation 不是业务事实。客户说“钱已经转了”只能证明“客户报告已付款”；收到银行流水或财务确认后，才可能形成“回款已到账”Event。

无法确定对象、语义或事实性质时，信息继续留在 Observation 中，不急于污染 Collection。

## 7. Collection 与 SchemaResolver

### 7.1 Collection

Collection 保存 Workspace 内部可持续变化的当前业务事实，例如客户、报价、合同、应收和回款。它不是每个 Collection 一张动态 SQL 表，也不是一块没有规则的 JSON。

第一版使用通用表承载 Collection Definition 与 Record，结构由服务层管理。随着业务稳定，底层可以从 JSON 记录逐步结晶为索引、Dataset、类型化表或外部系统映射，而不改变上层语义。

### 7.2 稳定身份

Collection 和 Field 使用不可变 ID。显示名称、别名和存储方式可以改变，Action、Dataset 和 Surface 始终引用稳定 ID。

Field Definition 至少描述：

- 标准名称和别名；
- 业务含义；
- 所属对象；
- 数据类型、单位或币种；
- 业务角色和时间含义；
- 成熟状态与修订号。

### 7.3 SchemaResolver

模型可以提出业务概念，但不能直接随意创建数据库结构。所有结构解析经过 SchemaResolver：

1. 稳定 ID、标准名称和别名的确定性匹配；
2. 对象、类型、单位、业务角色和向量语义的综合匹配；
3. 明确新概念进入 `candidate`；
4. 无法确定则保留 Observation，必要时询问业务问题。

向量只负责召回候选，不能单独决定合并。“预算”“报价金额”和“合同金额”即使相似，也必须按业务角色区分。

### 7.4 成熟状态与无损修正

Collection 和 Field 第一版使用：

- `candidate`；
- `active`；
- `deprecated`。

合并、重命名和迁移保持无损：旧定义指向规范定义，历史值和 Event 保留，不直接物理删除。重复业务对象由 EntityResolver 使用确定性标识、外部 ID、名称地址组合和语义信息判断；无法确认时宁可暂时并存，不错误合并。

### 7.5 存储与性能

- 常用范围、时间和状态使用固定索引；
- 高频动态字段可使用 SQLite JSON 表达式索引；
- 长文本使用 FTS；
- 语义检索使用向量索引；
- 大规模聚合物化为 Dataset；
- Agent 通过 count、find、aggregate 和 query 接口工作，不把全部记录塞入上下文。

## 8. Context

Context 是 Agent 对业务语言、规则、计算口径、边界和决定形成的可追溯认识，不是普通记忆，也不是不断增长的一整段提示词。

### 8.1 层级

- `person`：个人表达和工作偏好；
- `transaction`：当前客户、项目或事务的临时约定；
- `workspace`：当前业务长期稳定的语言与规则；
- `organization`：未来多个 Workspace 共用的正式制度，第一版仅预留。

### 8.2 类型

- 术语定义；
- 默认做法；
- 强制约束；
- 生效决定；
- 计算口径；
- 业务边界。

默认做法允许具体事务覆盖，强制约束不能被个人偏好绕过。冲突处理综合规则性质、范围、具体程度、来源、时间和是否允许例外，而不是简单按层级覆盖。

### 8.3 结晶与使用

Context 可以经历 `observed → candidate → established → formal → superseded`。一句偶然表达不能直接成为公司规则，明确长期表述、跨对象重复、多人一致实践、正式文件和后续纠正共同提供证据。

每次行动只构建与当前 Person、Workspace、业务对象和 Action 相关的 ContextSnapshot；强制约束始终包含，其他内容按稳定 ID、标签和语义检索。ActionRun 保存当时使用的 Context 引用，避免规则变化后无法解释历史行为。

## 9. Action、ActionRun 与行为结晶

### 9.1 定义

Action 是一个具有明确业务意义的改变，不是工具调用或固定 Workflow。它描述输入、前置条件、效果、完成标准、安全边界和证据，但不规定 Agent 必须如何思考和完成工作。

技术实现应使用 `BusinessActionDefinition` / `BusinessActionRun` 或 `WorkspaceAction` 命名，与现有 Gateway 对话协议中的 `action.proposed` / `action.completed` 审批交互区分。

### 9.2 与其他对象的关系

- Tool 是实现机制，Action 是业务含义；
- Assignment 可以包含多个 Action；
- Process 可以规定交付标准，但不替代 Agent；
- ActionRun 记录一次尝试；
- Event 只记录已经成立的业务事实。

失败、取消或等待中的 ActionRun 不能制造成功 Event。

### 9.3 自动发现稳定行为

每次通用 Collection 改变都保存结构化操作轨迹：业务意图、对象、字段、前后值、来源 Turn、发起人物和结果。PatternDetector 对操作进行语义归一和结构指纹聚合，重点观察：

- 相同结构是否在不同记录和 Turn 中反复出现；
- 业务意图是否一致；
- 输入与结果形态是否稳定；
- 是否产生明确业务价值；
- 失败和用户纠正是否形成反例。

确定性聚合先筛选候选，只有有价值的模式才交给隔离 LLM 归纳名称和业务语义。候选 Action 通过历史成功案例的只读重放验证后进入 `active`。它不能扩大既有能力、降低不可逆行为的审慎程度或把个人偏好提升为组织规则。候选失败时仍可回到基础 Collection 操作。

## 10. RecordChange 与 Event

### 10.1 四层记录必须分开

- 技术日志：程序发生了什么；
- ActionRun：Agent 尝试做什么；
- RecordChange：数据字段如何变化；
- Event：业务世界中什么已经成为事实。

Event 使用业务过去式，例如“报价已发送”“合同已签订”“回款已到账”，不记录 SQL、工具调用和页面刷新。

### 10.2 当前状态与历史并存

第一版不采用完整 Event Sourcing。Collection 直接保存当前状态；RecordChange 保存机械、完整的字段变化；Event 保存简洁、有业务意义的历史事实。内部更新在同一 SQLite 事务中写入当前状态、RecordChange 和 Event。

外部行为无法使用本地事务回滚。只有外部系统明确确认成功后才产生对应 Event，并保存幂等键、外部编号和结果；响应不确定时不能盲目重试并制造重复业务事实。

### 10.3 时间、证据与更正

Event 区分实际发生时间 `occurred_at` 与 Agent 记录时间 `recorded_at`，关联业务对象、ActionRun、发起人物、Observation、Asset 和 RecordChange。

Event 不直接编辑。发现错误时新增更正 Event，并通过 `supersedes_event_id` 指向旧事实；Collection 更新当前值，旧历史仍可解释。

Event 是 Agent 业务时间感、Context 形成、Action 模式发现和主动关注的重要依据，但 Event 本身不自动触发机械 Workflow。

## 11. Asset

Asset 是 Agent 世界中具有稳定身份、明确来源和业务关联的数字对象。文件路径只是存储细节。

### 11.1 与现有概念的关系

- Attachment：Asset 在一次消息中的输入关系；
- Artifact：Asset 在一次回复或委托中的交付关系；
- Preview / Rendition：可重新生成的预览表示，不是新的业务 Asset；
- Dataset：结构化、可计算的数据对象，可引用 Asset 作为来源或导出为 Asset。

同一 Asset 可以被多个 Session、Workspace、Observation、Event、Record 和 Dataset 引用，不必反复复制。内容哈希可用于物理去重，但相同字节不代表同一业务 Asset。

### 11.2 三种性质

- `working`：可持续修改，保持同一 asset_id；
- `evidence`：已经成为合同、流水、已发送报价等业务证据，不可覆盖；
- `external`：内容位于飞书、钉钉、邮箱、云盘或其他外部系统，保存稳定外部引用和可选缓存。

不建设面向用户的复杂版本系统。工作 Asset 直接修改；当内容被发送、签署或用于不可变业务 Event 时，自动生成隐藏的不可变证据快照，Event 指向实际发生时的内容。

### 11.3 AssetService

工具通过 asset_id 工作，由 AssetService 负责路径解析、执行现场授权、文件锁、原子替换、哈希更新、Desktop 刷新和远程传输。模型不再依赖猜测 attachments、outputs、images、music 或 Project 目录。

Asset 属于 Agent 的统一资产注册表，通过链接表达与 Person、Session、Workspace、Observation、Event、Record、Dataset 和 ActionRun 的关系。第一版不发展复杂资产 ACL。

## 12. Dataset

Dataset 是 Collection 与 Surface 之间可复用、可追溯的结构化分析结果。第一版支持：

- table；
- metric set；
- time series。

Dataset 保存稳定 ID、来源、计算摘要、Schema、修订号和实际数据引用。小数据可以保存在数据库，大数据使用受管文件或其他存储。更新采用原子替换，第一版不建设完整历史版本和回滚界面。

Dataset 不等同于 Excel 或 CSV。上传文件首先是 Asset，解析后可以形成 Dataset；Dataset 导出为 Excel 时再产生一个 Asset。

## 13. Surface

Surface 是人和 Agent 共同接触、理解和操作 Workspace 的交互表面。它不是只读 View，也不等同于 Electron Window 或 Desktop Shell。

### 13.1 两种表达

标准 Surface 使用声明式组件，保证稳定数据绑定、主题、刷新和跨平台呈现。第一版组件包括：

- metric；
- text；
- table；
- record；
- bar；
- line；
- pie；
- timeline；
- asset；
- group。

自由表达通过现有 Visualize 生成 HTML、SVG、Canvas 等 Asset，并嵌入 Surface。标准 Surface 负责稳定业务使用，自由表达负责特殊演示和创意呈现。

### 13.2 数据与行为

Surface 只保存如何看和如何交互，不保存业务真相。组件绑定 Dataset、Collection 查询或 Asset；输入和按钮表达业务意图并调用 Action，不能直接修改数据库。

一次性展示形成临时 Surface；反复使用或明确要求保留后形成持久 Surface。一个 Surface 可以带参数，在不同客户、项目、时间范围和负责人上复用。

Action 完成并产生 Event 后，相关 Dataset 标记失效，正在显示的 Surface 按事件重新读取，不使用固定周期全量轮询。

### 13.3 与现有 UI 的关系

- Desktop Shell：整个应用外壳；
- Electron Window：操作系统物理窗口；
- Surface：业务交互界面；
- Visualize：可嵌入 Surface 的自由可视化 Asset；
- 演示台：将多个 Surface 与 Asset 组织为演示现场。

产品界面直接显示“客户经营”“项目进展”等具体名称，不要求用户学习 Surface 术语。

## 14. 最小备份兜底

第一版先完成简单、可靠的 Agent 数据备份，不扩展复杂恢复产品：

- 使用 SQLite 一致性备份覆盖 `brain.db`；
- 备份 Asset 注册信息和受管文件；
- 定时执行，并在数据库迁移前执行；
- 保留有限数量的最近快照；
- 备份结果写入日志并能被 Desktop 查看；
- 第一版允许整体恢复，不先做字段级、记录级和可视化回滚。

### 14.1 存储布局决定

Workspace 权威数据只存在 Agent 所在宿主机。Desktop 是通过 Gateway 访问 Agent 世界的交互身体，只保存窗口、选中项等界面状态或可丢弃缓存，不建立第二份 Workspace 事实数据库。

每个 Agent 使用一份独立 Workspace 数据库，而不是每个 Workspace 一份数据库：

```text
<agent-root>/
├─ brain.db
├─ workspaces/
│  └─ workspaces.db
└─ backups/
```

`brain.db` 继续保存人物、会话、记忆、意识等 Agent 内部世界；`workspaces.db` 保存持续业务数据。两者都属于同一个 Agent，只是按领域和负载分开。跨库只保存稳定 ID，不建立依赖跨数据库事务的外键。

不采用“一 Workspace 一 SQLite 文件”，避免大量连接、迁移文件、跨 Workspace 查询和备份协调问题。未来大规模 Dataset 与 Asset 内容进入受管文件或外部存储，元数据仍由该 Agent 的 `workspaces.db` 统一管理。

## 15. 建议的核心服务边界

```text
WorkspaceService
    Workspace 生命周期、关系和当前现场

WorkspaceResolver
    判断当前 Turn 属于已有 Workspace、需要新建或暂不归属

ObservationService
    统一接收不同 DataSource 的原始观察

CollectionService
    Collection、Record、查询、聚合和事务写入

SchemaResolver / EntityResolver
    业务结构与对象的语义一致性

ContextService / ContextResolver
    Context 的形成、证据、冲突与现场快照

ActionService / PatternDetector
    业务 Action 执行、ActionRun 和稳定模式发现

EventService
    业务 Event、证据、幂等和更正

AssetService
    Asset 注册、存储解析、修改、快照和关联

DatasetService
    Dataset 计算、查询、失效和原子更新

SurfaceService
    临时与持久 Surface、数据绑定和交互定义
```

这些 Service 提供可靠领域操作，不运行第二套 Agent，不自行决定业务目标，也不构成中央 Workflow 引擎。

## 16. 当前原型审查

### 16.1 值得保留

当前 `src/xiaomei_brain/workspaces/` 已经建立：

- 独立 models / store / service / tools 模块；
- `brain.db` 中的版本化 SQLite Schema；
- create、get、list、update 与 revision 冲突检测；
- Gateway `workspace.list` / `workspace.get`；
- `workspace.created` / `workspace.updated` 事件投影；
- Desktop 独立入口和组件渲染；
- Person 切换时清空旧投影；
- 后端、Gateway 和 Desktop 基础测试。

这些证明 Agent、Gateway、Desktop 的基本闭环已经跑通，应保留其模块边界和通信外壳。

### 16.2 核心差距

当前一条 `workspaces` 记录同时承担了 Workspace 和 Surface：

```text
Workspace = name + description + spec_json.components
```

由此产生的问题：

1. Workspace 必须至少包含一个展示组件，无法先作为空的持续业务现场形成；
2. metric、table 和 chart 直接嵌入值，没有 Collection 与 Dataset；
3. 更新要求整份替换 spec，不能表达业务事实级变化；
4. 当前 `scope_type=person` 被解释为 Person 所有权，与 Agent 拥有自身世界的原则不符；
5. 没有 Workspace 生命周期、目的、当前现场和 Session / Turn 关联；
6. 没有 DataSource、Observation、Context、Collection、SchemaResolver、Action、RecordChange、Event、Asset 和 Dataset；
7. Desktop 页面实际上是第一版 SurfaceRenderer，而不是完整 Workspace；
8. 工具描述和部分测试文本存在历史编码损坏，需要在迁移时清理；
9. `projects/workspace.py` 中的 ProjectWorkspace 指文件工作目录，与新领域 Workspace 同名但含义不同；
10. `ArtifactWorkspace` 和 `MainShell` 中的局部 `surface` 变量也与正式领域术语存在命名冲突。

### 16.3 收束方向

- 保留 `xiaomei_brain.workspaces` 作为领域根模块；
- 将现有 `spec_json` 迁移为一个默认 Surface，而不是继续扩展为万能 JSON；
- Workspace 本体只保存身份、目的、生命周期和关系；
- Desktop `WorkspacesPage` 演进为 Workspace 导航与 Surface 容器；
- 原有组件渲染逻辑迁入独立 SurfaceRenderer；
- 逐步清理 Project 文件目录和 Artifact 编辑器中的“workspace”同名概念，但不在第一阶段扩大改动。

## 17. 数据迁移原则

开发阶段不维持长期双轨兼容，但已有开发数据库不能无声丢失：

1. Schema 升级前执行一次 Agent 数据备份；
2. 每条现有 Workspace 保留原 id、名称、描述、创建时间和更新时间；
3. 新建对应 Workspace 本体；
4. 将旧 `spec_json.components` 迁移为该 Workspace 的默认 Surface；
5. 旧 `scope_id` 迁移为创建来源和人物关联，不再表示永久所有权；
6. 升级成功后只运行新结构，不保留两套写入路径；
7. 迁移失败必须停止启动并保留原数据库与可读错误，不静默创建空库。

## 18. 第一版实施范围

第一版以“从零经营一项客户业务”为真实纵向场景：

```text
用户描述一项新业务
    ↓
Agent 形成 Workspace
    ↓
从对话和文件收到客户、需求和报价信息
    ↓
形成 Observation 与 Collection
    ↓
通过通用 Action 更新客户阶段和报价事实
    ↓
产生 RecordChange 与 Event
    ↓
形成客户汇总 Dataset
    ↓
生成可持续刷新的客户经营 Surface
```

第一版必须证明：

- 不要求用户设计表和字段；
- 同义对象和字段不会快速失控；
- 原始来源可以追溯；
- 数据变化和业务 Event 一致；
- Surface 读取真实 Dataset，而不是复制静态数字；
- Agent 可以通过自然语言继续修改数据与 Surface；
- 重启 Agent 和 Desktop 后状态仍然存在；
- 定期备份能够兜底恢复整个 Agent 数据现场。

## 19. 分阶段实施计划

### 阶段 A：备份与领域骨架

- 增加最小 Agent 数据备份；
- 将现有 Workspace 与 Surface 拆分；
- 增加 Workspace purpose、status、last_active_at；
- 迁移旧 spec 为默认 Surface；
- 保持现有 Desktop 原型继续可用。

### 阶段 B：业务事实纵向闭环

- Observation；
- Collection Definition、Field Definition、Record；
- SchemaResolver 与最小 EntityResolver；
- 通用创建、查找和更新业务记录；
- RecordChange 与基础业务 Event；
- 用一个真实客户经营场景验收。

### 阶段 C：Dataset 与 Surface

- table、metric set、time series Dataset；
- Surface 绑定 Dataset，不再嵌入静态业务值；
- record、timeline、asset、group 组件；
- Event 驱动失效和刷新；
- 临时 Surface 与持久 Surface。

### 阶段 D：Context 与 Action 结晶

- Context 分层、证据和现场快照；
- BusinessActionDefinition / Run；
- OperationObserver 与 PatternDetector；
- 候选 Action 的历史只读验证；
- 默认规则、个案覆盖和更正链路。

### 阶段 E：Asset 与 DataSource 收束

- 统一 Asset 注册与 asset_id 工具访问；
- Attachment、Artifact、Workspace 和 Project Asset 关联；
- working、evidence、external 三类 Asset；
- 对话、文件和现有 Channel 进入统一 Observation；
- 后续按真实需求增加邮箱、数据库和企业系统来源。

每个阶段都必须产生可对话、可查看、可重启恢复的真实纵向结果，不能只增加空接口和抽象层。

## 20. 明确暂缓

- 复杂企业权限和角色体系；
- 多级审批和 OA 流程；
- 字段级、记录级 ACL；
- 完整 Event Sourcing；
- 可视化数据库和 Schema 设计器；
- 拖拽式低代码页面编辑器；
- 通用 ETL 与双向同步平台；
- 全局行业本体库；
- 多 Workspace 主数据治理；
- 完整 Asset 版本管理页面；
- 字段级和 Event 级可视化恢复；
- 多 Agent 中央调度与协作。

## 21. 判断实现是否走偏

出现以下迹象时应暂停并重新审查：

- 用户必须先学习表、字段、流程和权限才能开始工作；
- 每新增一种业务都必须修改 AgentManager、Gateway 和 Desktop；
- Workspace 再次退化为一个大 JSON 看板；
- Surface 直接保存业务数字或直接写数据库；
- 模型能够绕过 Service 直接创建字段和修改记录；
- Event 变成工具日志；
- Action 变成固定 Workflow；
- 每个不可逆或可恢复动作都要求审批；
- Person 创建了 Workspace 就被解释为拥有 Agent；
- 为未来可能需要的企业场景提前建设大量抽象而没有真实业务验证。

## 22. 最终愿景

```text
Observation 让 Agent 看见世界
Context     让 Agent 理解世界
Collection  保存世界当前的样子
Action      让 Agent 改变世界
Event       让改变留下历史
Asset       保存世界中的数字对象
Dataset     让 Agent 提炼世界
Surface     让人与 Agent 共同接触世界
Workspace   让这一切围绕持续业务长期存在
```

小美的中心仍然是 Agent。Workspace 不是另一套固定软件，而是 Agent 与真实业务长期相处后逐渐形成的业务世界；Surface 不是传统软件预先写死的页面，而是这个世界在当下需要中的可交互呈现。
