# Project 内核与动画视频制作能力设计

> 状态：已确认，实施中
>
> 本文定义小美如何通过第一个复杂视频项目建立通用 Project 内核。Project
> 属于基础平台；动画视频制作属于可安装能力。本文不把外部 Chat Animation
> Skill 直接接入运行时，只吸收其可验证的制作流程、行业方法和质量控制思想，
> 并使用小美自己的模型、工具、委托、产物和能力包体系重新实现。

参考项目：<https://github.com/xue-xiaobao/chat-animation>（MIT）。本文引用的是
工作流和行业方法，不复制其 Provider、凭据体系或项目运行代码；后续若复用任何
具体源码或资产，必须保留对应许可和第三方声明。

## 1. 一句话定义

`Project` 是一个 Agent 对一件需要跨越多次对话、委托和执行持续推进的真实
工作的长期工作容器。

它不是一轮对话，不是一次委托，不是一个文件夹，也不是 Agent 自己的 Goal。

```text
Agent 的世界
└─ Project：持续推进的一件工作
   ├─ Session：围绕它发生的多次对话
   ├─ Assignment：推进它的一次工作约定
   ├─ ActivityRun：一次真实执行过程
   ├─ ProjectAsset：工作现场中的素材和中间文件
   ├─ Artifact：需要展示、确认或交付的不可变快照
   └─ Capability：Agent 用来完成工作的能力
```

视频制作是第一个 Project 类型，但 Project Core 不认识“镜头”“字幕”或
“关键帧”。未来代码开发、企业文档、数据分析、客户实施等工作复用同一内核。

## 2. 为什么需要独立的 Project 领域

现有系统已经具备：

- Session / Turn：对话现场；
- Assignment：Person 与 Agent 之间的持续工作约定；
- ActivityRun：一次执行或内部活动的观察投影；
- Artifact：对外展示和交付的 Agent 会话资产；
- Goal / PACE：Agent 自己的目的与内部推进机制；
- Capability Package：Skill、Plugin、脚本、资源和能力定义的可安装组合。

这些对象都不能单独表达“同一件长期工作”：

- 一个 Session 太短，也可能只讨论项目的一小部分；
- 一个 Assignment 有明确目标和终点，一个项目可以包含很多 Assignment；
- ActivityRun 只观察一次执行，不保存长期业务现场；
- Artifact 是结果，不是产生结果的工作容器；
- Goal 属于 Agent 自身，不能把企业工作全部改名为 Agent 的人生目标；
- 文件夹只能存文件，不能表达人物范围、进度、关系和历史。

因此 Project 是缺失的长期工作领域层，不替代已有对象。

## 3. 核心边界

| 概念 | 回答的问题 | 是否长期 | 是否执行工作 |
|---|---|---:|---:|
| Session | 这段交流发生在哪里 | 否 | 否 |
| Assignment | Agent 与对方约定完成什么 | 是 | 由 Runner 执行 |
| ActivityRun | Agent 此刻正在做什么 | 否 | 观察一次运行 |
| Project | 这些对话、任务和资产共同属于哪件工作 | 是 | 否 |
| ProjectAsset | 项目现场有哪些可继续使用的工作文件 | 是 | 否 |
| Artifact | 哪些结果已经展示、确认或交付 | 是 | 否 |
| Capability | Agent 会做什么 | 是 | 组合执行组件 |
| Goal / PACE | Agent 自己在追求和推进什么 | 是 | Agent 内部机制 |

关键关系：

```text
Project 1 ── 0..N Session
Project 1 ── 0..N Assignment
Project 1 ── 0..N ProjectStep
Project 1 ── 0..N ProjectAsset
Project 1 ── 0..N ProjectResource

Assignment 1 ── 0..N AssignmentRun
AssignmentRun 1 ── 0..N ActivityRun
ProjectAsset 0..1 ── 0..N Artifact snapshot
```

Project 不拥有 Person。`created_by` 只是事实记录，不表示创建者可以永久控制
Agent 或项目。可见和可使用范围由 `scope_type/scope_id` 表达。

## 4. 设计原则

### 4.1 一 Agent 一世界

Project 的权威状态保存在对应 Agent 自己的 `brain.db` 和数据目录。Desktop
不维护另一份项目数据库，也不存在管理所有 Agent 项目的中央服务。

远程 Agent 的 Project 由远程 Agent 自己维护，本地 Desktop 只读取其 Gateway
投影。

### 4.2 Project 是可选领域

普通问答、一次格式转换、查看系统负载、修改一个小文件，不自动创建 Project。

以下信号适合形成 Project：

- 工作会跨越多次对话；
- 有多个业务阶段；
- 会产生大量工作资产；
- 需要暂停、恢复或持续数天；
- 会产生多个 Assignment；
- 需要长期查询进度和成果；
- Person 明确表达“项目”“长期推进”“以后继续”。

### 4.3 对话优先，界面辅助

创建、查找、继续、追加资料、询问进度和结束项目都必须可以通过自然对话完成。
Desktop 只展示当前项目、最近项目、阶段、委托和产物，不建设复杂项目管理后台。

### 4.4 Project 不成为第二套执行引擎

ProjectService 不运行 LLM，不执行工具，也不维护另一套 Agent Core。

- 长时间工作继续由 Assignment 和隔离 Runner 执行；
- 一次运行继续由 ActivityRun 展示；
- Clarify / Action 继续承担选择和审批；
- Project 只保存持续工作状态与关系。

### 4.5 Agent 主导项目，不编排 Agent

ProjectStep 是 Agent 对工作的认知地图和里程碑，不是 Dify / n8n 式流程节点。
Agent 可以根据现场新增、删除、重命名、合并、重排或重新判断阶段。Project Core
不提供领域阶段模板、不规定下一步，也不因阶段顺序阻止工具调用。

Agent 应在方案形成、计划变化、候选交付和人物确认等自然节点进行项目复盘。复盘
基于真实工具结果、资产和人物原话，同步阶段判断、计划变化、实际偏差、等待原因和
下一步。跳过本身不是错误；没有记录理由、让 Project 与真实交付不一致才是错误。

### 4.6 进度必须诚实

不根据耗时猜测虚假百分比。优先展示：

- 当前阶段；
- 已完成阶段；
- 当前阶段内的已完成单元 / 总单元；
- 正在做什么；
- 等待什么；
- 最近一次有效更新。

### 4.7 Process 是可选交付标准，不是 Agent 的中心

ProjectStep 表达 Agent 当前准备如何工作；ProcessStage 表达本次工作正式必须提交什么。
二者不得共用状态或互相冒充：Skill 提供知识，Agent 自主组织 Project，用户可以选择或
修订 Process，工具只提供资产和事实。

第一版 Process 不执行工具、不自动安排任务、不包含分支、定时器、审批角色或组织结构，
只实现：

- 定义正式阶段及是否要求顺序提交；
- 为阶段定义必需的 ProjectAsset 或事实证据；
- Agent 提交资产、事实和说明；
- 确定性检查提交是否完整；
- 所有必需阶段满足后将 Process 标记为 satisfied。

未绑定 Process 时，Agent 自主判断 Project 是否完成；绑定 Process 后，Agent 的工作方法仍
保持自由，但不能把缺少正式提交的结果称为已经满足该标准。

只有存在可靠总量时才显示数值进度，例如“画面 3 / 8 镜”。

### 4.7 不污染外部工作目录

关联代码仓库、共享目录或客户资料时，小美不默认把自身状态文件写进外部目录。
Project 元数据和检查点始终保存在 Agent 数据目录；外部目录只作为经过授权的
工作根目录。

### 4.8 历史数据平滑升级

ProjectStore 使用独立 schema component，只新增表，不修改现有
`messages`、`group_messages`、`artifacts`、`assignments`、`goals` 和记忆表。

旧 Session、Assignment 和 Artifact 不自动归入虚构 Project。Person 后续可以
通过对话将仍有价值的工作关联到新 Project。

## 5. Project 领域模型

### 5.1 Project

第一版字段：

```text
id
name
summary
project_type
status

scope_type
scope_id
created_by_type
created_by_id

workspace_kind
workspace_uri
state_root

progress_summary
current_step_id
waiting_reason

metadata
revision
created_at
updated_at
completed_at
```

说明：

- 数据库属于单个 Agent，不重复保存 `agent_id`；
- `project_type` 是扩展能力定义的稳定字符串，例如 `video.production`、
  `software.codebase`、`document.workspace`，Core 不使用硬编码枚举；
- `scope_type/scope_id` 第一版支持 `person`、`group` 和 `internal`；
- `created_by_*` 用于审计，不构成所有权；
- `workspace_uri` 只由 ProjectService 产生和校验，不接受模型任意伪造路径；
- `metadata` 保存类型扩展的少量可查询摘要，不保存大型工作流状态；
- `revision` 用于事件与客户端快照去重。

### 5.2 ProjectStatus

Project 状态只表达长期工作的生命周期：

```text
active        正在持续推进，当前没有 Runner 也仍可保持 active
completed     项目目标已经达成
discontinued  明确不再继续，不表示执行失败
```

不设置 `failed`：失败属于 AssignmentRun 或 ActivityRun，一次执行失败不意味着
整个项目失败。

不设置 `paused`：等待、暂停和重试属于当前 Assignment。长期项目暂时没有动作
仍然是 active，通过最近更新时间自然排序。

允许：

```text
active       → completed / discontinued
completed    → active
discontinued → active
```

重新变为 active 必须产生明确事件并增加 revision。

### 5.3 ProjectStep

ProjectStep 表达跨多次执行仍然存在的项目阶段或里程碑，不等同于某次
ActivityRun 的临时步骤。

```text
project_id
step_id
parent_step_id
title
position
status
summary
completed_units
total_units
metadata
updated_at
```

状态：

```text
pending / running / waiting_review / completed / needs_revision / skipped
```

领域 Skill 提供阶段经验，Agent 根据当前目标建立并调整 ProjectStep。视频可以参考
“编导、画面、运动、声音、合成、验收”；代码项目可以参考“分析、实现、测试、交付”。
Core 不理解这些名称，也不要求采用完整模板。

### 5.4 ProcessInstance 与 ProcessSubmission

第一版每个 Project 最多绑定一个当前 ProcessInstance。定义包含 `ordered`、正式阶段及每阶段
的提交要求；定义可以依据用户决定修订。ProcessSubmission 保存提交说明、ProjectAsset ID、
事实证据、完整性检查结果和仍缺少的要求。

Process 只支持两类通用要求：

- `asset`：提交的 ProjectAsset 中必须存在指定 kind，可选指定 role；
- `evidence`：提交中必须存在指定事实键，可选要求一个明确值；关键技术事实可要求
  `from_asset: true`，此时只读取已登记 ProjectAsset 的元数据，不相信 Agent 自报。

Process Core 不理解音轨、视频时长或分镜。是否要求 `has_audio: true`、`has_audio: false`，由
具体 Process 定义决定。

### 5.4 ProjectAsset

ProjectAsset 是项目可以继续工作的可变资产索引，二进制仍在文件系统中。

```text
id
project_id
role
kind
name
relative_uri
mime_type
size
sha256
status
source_type
source_id
producer
provider
model
parent_asset_id
metadata
created_at
updated_at
```

资产角色：

| role | 含义 | 默认是否展示 |
|---|---|---:|
| source | Person 提供或项目引用的原始资料 | 按需 |
| working | 可继续修改的工作文件 | 否 |
| cache | 可重新生成的缓存 | 否 |
| review | 样片、联系表、试听文件 | 是 |
| deliverable | 最终交付候选 | 是 |

ProjectAsset 可以被覆盖或更新；Artifact 仍是一个对外展示的不可变快照。一个
Asset 在不同时间可以产生多个 Artifact，Project 表只引用关系，不复制二进制。

### 5.5 ProjectResource

ProjectResource 连接已经拥有自身权威存储的对象，不复制其内容：

```text
project_id
resource_type
resource_key
relation
metadata
created_at
```

第一版用于关联 Artifact、Assignment、KnowledgeSource、外部系统记录等。Session
因为存在“一个 Session 最多关联一个当前 Project”的约束，单独使用
ProjectSession。Assignment 的主要归属仍以 `scope_type=project` 为准，
ProjectResource 只在需要表达 deliverable、reference 等具体关系时补充记录。

### 5.6 ProjectEvent

每次有意义的领域变化追加事实事件：

```text
id
project_id
event_type
actor_type
actor_id
payload
idempotency_key
created_at
```

第一版事件：

- `project.created`
- `project.updated`
- `project.step_changed`
- `project.asset_registered`
- `project.asset_updated`
- `project.assignment_linked`
- `project.completed`
- `project.reopened`
- `project.discontinued`

事件记录事实和审计，不保存模型原始思维链。

### 5.7 ProjectSession

一个 Session 第一版最多关联一个 Project；一个 Project 可以关联多个 Session。

```text
session_id
project_id
bound_by_type
bound_by_id
created_at
updated_at
```

切换项目不会改写旧消息归属。若当前会话已经实质属于另一个 Project，Agent
应建议新建会话；明确切换时只影响后续对话上下文。

## 6. 存储与工作空间

### 6.1 新增表

`ProjectStore` 在 `brain.db` 中使用独立 schema version，第一版新增：

```text
projects
project_events
project_steps
project_assets
project_resources
project_sessions
```

不向现有 Assignment 表增加 `project_id`。现有 Assignment 已支持：

```text
scope_type = "project"
scope_id   = project_id
```

ProjectService 通过该作用域查询所属 Assignment。Artifact 与 ProjectAsset 的
关系使用 `project_resources` 建立引用，正式展示仍使用现有 Artifact 表与权限
边界。

### 6.2 三种工作空间

#### managed

Agent 托管全部工作文件，适合视频、文档和数据分析：

```text
~/.xiaomei-brain/<agent>/projects/<project_id>/
```

#### linked

关联外部目录，适合 Git 仓库和企业共享目录：

```text
Agent 状态：~/.xiaomei-brain/<agent>/projects/<project_id>/state/
工作根目录：D:\workspace\customer-project
```

工具执行现场只获得已经授权的工作根目录，不允许模型把任意路径写入 Project。

#### virtual

没有唯一文件根目录，适合客户支持、招聘、法务事项等逻辑项目。资源通过附件、
KnowledgeSource、企业连接器和 Artifact 关联。

### 6.3 托管项目目录

Project Core 只保证通用目录：

```text
<project>/
├─ state/          原子写入的项目状态和检查点
├─ source/         托管的原始输入
├─ work/           类型能力的工作现场
├─ review/         等待确认的材料
└─ deliverables/   最终交付候选
```

视频能力可以在 `work/` 下建立 `script/visual/motion/audio/composition`，但这些
目录不是 Project Core 的硬编码。

### 6.4 清理策略

第一版不自动删除项目文件：

- 未完成项目永不自动清理；
- 能力包卸载不删除项目数据；
- `source`、`review`、`deliverable` 和状态文件默认保留；
- Person 可以通过对话要求“清理这个项目的中间素材”；
- 清理只删除 `working/cache` 且必须先展示范围和大小并获得确认；
- 删除后 ProjectAsset 保留事实记录并标记 `removed`，不伪装成从未存在。

## 7. ProjectService

`ProjectService` 是唯一领域写入口，负责：

- 校验 Project 状态转换；
- 创建并验证 managed/linked/virtual 工作空间；
- 校验已验证 Person 与 Project scope；
- 管理 ProjectStep 和 ProjectAsset；
- 建立 Artifact、Assignment 和企业资料等 ProjectResource 引用；
- 绑定 Session；
- 为 Assignment 提供 `scope_type=project` 上下文；
- 追加 ProjectEvent；
- 使用 revision 防止陈旧写入覆盖新状态；
- 生成对 Desktop 和 Channel 安全的公共快照。

模型不能直接写数据库，也不能通过参数提交未授权绝对路径。

### 7.1 对话工具

第一版提供少量内部工具，不把技术管理暴露给普通用户：

```text
project_create
project_find
project_get
project_update
project_link_resource
project_complete
```

工具由 Agent 对话 Core 调用 ProjectService。Person 说“创建视频项目”“继续上次
项目”“把这个委托归到当前项目”即可，不需要知道工具名。

类型能力不直接操作 ProjectStore。例如视频 Skill 通过受控的项目上下文和工具
更新阶段、资产与进度。

### 7.2 ProjectRuntimeContext

不新增与现有执行现场平行的上下文系统。ProjectRuntimeContext 是一个可选、不可变
的值对象，被组合进现有 `AssignmentExecutionContext`，并在每次工具调用时继续
投影到 `ToolExecutionContext`：

```text
AssignmentExecutionContext
└─ project: ProjectRuntimeContext | None
   ↓
ToolExecutionContext
└─ project: ProjectRuntimeContext | None
```

隔离 Runner 创建时由 ProjectService 捕获可信快照：

```text
project_id
project_type
scope_type / scope_id
state_root
work_root
workspace_kind
allowed_assets
active_assignment_id
```

它由 Agent 运行时创建，不接受模型自报。Assignment Runner、Shell、文件工具、
媒体工具和 Artifact 发现都从该上下文取得工作根目录。工具如需登记工作资产，
通过 ToolExecutionContext 提供的受控回调提交候选文件，再由 ProjectService 校验
路径、计算哈希并写入 ProjectAsset；插件不能直接写 ProjectStore。

## 8. Assignment、Activity 与 Artifact 集成

### 8.1 Assignment

需要长期执行的项目工作继续创建 Assignment：

```text
scope_type = project
scope_id   = <project_id>
```

Project 可以有多个 Assignment：首次制作、后续重做、补充数据、代码实现、测试
与发布分别形成不同工作约定。对同一个交付物的小修改可以 reopen 原 Assignment；
实质不同的新工作创建新 Assignment。

### 8.2 ActivityRun

Activity 继续以 AssignmentRun 为 source。Project 关系通过 Assignment scope
投影，不新增 Project 执行器：

```text
Project
└─ Assignment
   └─ AssignmentRun
      └─ ActivityRun
```

### 8.3 Artifact

不是所有 ProjectAsset 都进入对话：

- `working/cache` 默认不创建可见 Artifact；
- `review` 生成 Artifact 并触发 Clarify；
- `deliverable` 生成 Artifact 并关联 Assignment 交付物；
- Artifact 点击后仍使用现有授权读取与预览链路；
- 飞书、钉钉只接收 review/final 等明确投影，不发送所有中间帧。

## 9. Gateway 与 Desktop

### 9.1 协议

第一版新增只读 RPC：

```text
project.list
project.get
project.current
```

不提供客户端任意写入的 `project.create` 或 `project.set_status`。创建和状态变化
由 Agent 对话核心调用 ProjectService 决定，保持 Agent 是领域主体。

领域变化发布：

```text
project.created
project.updated
```

`project.updated` 携带 revision 和安全快照，Desktop 只接受更高 revision。
ProjectAsset 对外展示继续使用既有 `artifact.*` 事件，不建立重复文件协议。

### 9.2 Desktop 第一版

不新增项目管理一级页面。统一右侧栏“工作”区域增加当前项目上下文：

```text
工作
├─ 当前项目：节俭悖论科普视频
├─ 当前阶段：画面生成 3 / 8
├─ 正在执行的 Assignment
├─ 等待确认的样片
├─ 最近产物
└─ 查看项目详情
```

项目详情使用现有右侧工作栏/抽屉承载：

- 项目摘要；
- 阶段时间线；
- 相关 Assignment；
- review 与 deliverable；
- 最近活动；
- 工作空间类型和占用空间等诊断信息。

最近项目按 `updated_at` 自然排序，不增加归档、标签树、甘特图或复杂管理功能。

## 10. 视频制作作为第一个 Project 类型

### 10.1 能力边界

动画视频制作能力负责：

```text
需求与编导
→ 分镜与视觉方案
→ 静态画面
→ 内容动画与转场
→ 口播与音乐
→ 字幕与合成
→ 技术及观看验收
→ 最终 MP4
```

它不自带另一套身份、对话、委托、文件权限、模型设置或产物系统。

### 10.2 从参考 Skill 吸收的知识

重新编写小美自己的视频 Skill，保留以下可复用行业方法：

- 编导先于付费生成；
- 先明确受众、结论、叙事弧、台词、视觉隐喻和转场；
- 风格定义形成项目快照，制作中不无声漂移；
- 使用首尾关键帧约束动画；
- 区分硬切、独立转场和融合转场；
- 口播音频作为最终时间轴，调整画面而不粗暴加速声音；
- 高成本阶段先做一镜样片；
- 单镜失败和修改只返工受影响镜头；
- 使用联系表、首尾帧、完整解码、FFprobe、字幕和音画同步验收；
- 外部任务 ID、请求摘要、模型和文件哈希必须持久化以便恢复。

不复制：

- Agnes / MiMo 专用 Provider；
- 独立凭据目录；
- 外部 Skill 自己的项目管理实现；
- 与小美 Plugin、Assignment、Artifact 重复的脚本。

### 10.3 视频阶段参考

```text
01 brief          需求和约束
02 director       结论、台词、叙事弧和风格
03 storyboard     镜头、关键帧和转场计划
04 visual         静态画面与视觉样片
05 motion         内容动画和转场
06 audio          口播、音乐与声音验收
07 composition    时间线、字幕和最终合成
08 acceptance     技术验收和观看确认
```

这是视频 Skill 提供的领域认知参考，不是初始化时固定写入 Project 的八个关卡。
Agent 应根据目标建立更合适的阶段地图：默片可以没有 audio；已有素材剪辑可以省略
visual；较小项目可以合并 director 和 storyboard，也可以增加品牌审核等特有阶段。

### 10.4 视频资产目录

```text
work/
├─ script/
├─ storyboard/
├─ visual/
├─ motion/
├─ audio/
└─ composition/
```

所有模型返回的临时 URL 必须立即下载到项目目录。ProjectAsset 记录模型、
Provider、请求 ID、参数摘要、哈希、父资产和当前状态。

### 10.5 执行方式

完整视频生产固定使用 Assignment；快速工具操作不强制形成 Project：

| 请求 | 执行现场 |
|---|---|
| 从需求制作完整视频 | Project + Assignment |
| 多镜头批量生成或配音 | Project + Assignment |
| 单个 MP4 转 GIF | 当前 Turn 工具调用 |
| 从视频提取一帧 | 当前 Turn 工具调用 |
| 为已有视频重新加字幕 | 可根据文件大小与时长决定 Turn 或 Assignment |

Assignment 等待样片确认时进入 `waiting_person`，实时对话保持可用。确认结果写入
Assignment checkpoint 和 ProjectEvent，Agent 重启后能够继续。

### 10.6 使用小美自己的媒体服务

第一阶段统一治理现有媒体模型：

- 图片：MiniMax、Seedream；
- TTS：MiniMax、VoxCPM；
- 音乐：MiniMax；
- 视频：通过新的具体 Provider Plugin 接入；
- 合成：本地 FFmpeg / FFprobe 工具插件。

媒体服务目录统一负责发现、配置、启停、连接测试和状态，不强行统一不同模型的
所有生成参数。每个 Provider Plugin 自己定义工具参数和结果适配。

视频能力包只声明需要“图片生成、TTS、可选音乐、视频生成、FFmpeg 合成”等
组件，由 CapabilityRegistry 给出 ready / degraded / needs_setup 状态。

## 11. 能力包结构

建议能力包：

```text
video-production.xmcap
├─ capabilities/
│  └─ video_production.yaml
├─ skills/
│  └─ video-production/
│     ├─ SKILL.md
│     └─ references/
│        ├─ directing.md
│        ├─ storyboard.md
│        ├─ visual-continuity.md
│        ├─ transitions.md
│        ├─ narration-and-timing.md
│        └─ quality-assurance.md
├─ plugins/
│  └─ video_composition/
├─ scripts/
│  ├─ compose.py
│  ├─ probe.py
│  └─ contact_sheet.py
└─ resources/
   ├─ schemas/
   └─ style-presets/
```

具体视频 Provider 可以作为独立能力包安装，避免把所有供应商耦合进视频制作
知识包。`video-production` 能力根据已启用组件判断能制作何种视频。

## 12. 安全、恢复与幂等

- ProjectService 校验所有工作根目录和相对路径；
- 模型密钥继续由 Agent 媒体配置系统管理，不写入 Project；
- 外部调用前保存请求摘要和幂等键；
- 获得远端 task ID 后先持久化再轮询；
- 下载文件后记录大小和 SHA-256；
- 重启后优先查询已有 task，不重复提交付费任务；
- ProjectStep 状态由 Agent 根据工具事实、用户目标和现场判断更新，Core 不自动裁决；
- Action 审批只用于真实风险动作，不把每次 FFmpeg 或读写项目目录都变成审批；
- Project 公共快照不暴露宿主机绝对路径和 API Key；
- Artifact 继续按 Person 和 Session 权限读取，不绕过 Agent 直接打开任意文件。

## 13. 实施阶段

### 阶段 P1：Project Core

- 新增 Project models/store/service；
- 独立数据库 schema migration；
- managed / linked / virtual 工作空间；
- ProjectStep、ProjectAsset、ProjectResource 和 ProjectEvent；
- Session 绑定；
- 对话工具；
- 单元测试和历史数据库升级测试。

### 阶段 P2：现有领域接入

- Assignment 使用既有 project scope；
- Activity 从 Assignment scope 投影 Project；
- review/deliverable ProjectAsset 进入 Artifact；
- ProjectRuntimeContext 组合进 AssignmentExecutionContext 和 ToolExecutionContext；
- 确认普通对话、旧 Assignment 和旧 Artifact 不受影响。

### 阶段 P3：Gateway 与 Desktop

- `project.list/get/current`；
- `project.created/updated`；
- 右侧栏当前项目和阶段；
- 项目详情中的 Assignment、Activity 和 Artifact；
- Desktop 重启后恢复当前 Project 投影。

### 阶段 V1：媒体服务治理

- 媒体服务增加 `video`；
- VoxCPM 纳入统一媒体配置；
- 图片、TTS、音乐、视频服务统一展示状态；
- Artifact 授权目录支持视频项目；
- FFmpeg / FFprobe 依赖检测。

### 阶段 V2：视频制作能力包

- 编导、分镜、转场、声音时钟和验收 Skill；
- FFmpeg 合成、字幕、探测和联系表工具；
- Project 类型 `video.production`；
- 视频步骤与资产规则；
- 先使用已配置模型，不引入外部 Skill 的凭据体系。

### 阶段 V3：真实闭环验收

制作一个 20～30 秒、多镜头、带中文口播和字幕的科普视频，验证：

1. 通过对话创建 Project 和 Assignment；
2. 实时对话不被后台制作阻塞；
3. 编导和样片可以通过 Clarify 确认；
4. 图片、TTS、音乐和视频模型均由 Agent 配置系统提供；
5. Desktop 正确展示阶段、等待原因、样片和最终产物；
6. Agent 在任一阶段重启后能够安全继续；
7. 中间工作资产不污染聊天和源码目录；
8. 最终 MP4 能通过 Desktop、飞书和钉钉交付；
9. 能力包停用后项目历史和产物仍可读取；
10. 能力包重新启用后可以继续原 Project。

## 14. 第一版明确不做

- 多 Agent 共同拥有或调度同一个 Project；
- 中央项目管理服务；
- 团队组织权限和复杂成员角色；
- 甘特图、看板、标签树和项目管理后台；
- 自动删除历史中间素材；
- 跨 Project 素材市场和公共素材库；
- 能力市场在线下载；
- 自动安装 FFmpeg、Python 或模型运行时；
- 将旧 Session 和 Assignment 自动归入 Project；
- 将 Project 强制挂接到 Goal / PACE；
- 为不同 Project 类型编写不同 ProjectService。

## 15. 建议新增和修改的代码

### 基础平台新增

```text
src/xiaomei_brain/projects/
├─ __init__.py
├─ models.py
├─ store.py
├─ service.py
├─ workspace.py
├─ context.py
└─ tools.py

src/xiaomei_brain/gateway/methods/projects.py
```

### 基础平台修改

```text
src/xiaomei_brain/agent/instance.py
src/xiaomei_brain/assignments/execution_context.py
src/xiaomei_brain/assignments/isolated_runner.py
src/xiaomei_brain/activity/service.py
src/xiaomei_brain/gateway/schemas.py
src/xiaomei_brain/gateway/server_methods.py
src/xiaomei_brain/gateway/event_projection.py
src/xiaomei_brain/tools/execution_context.py
```

### Desktop

```text
src/xiaomei_brain/desktop/main/ipc-handlers.ts
src/xiaomei_brain/desktop/main/preload.ts
src/xiaomei_brain/desktop/renderer/store/core.ts
src/xiaomei_brain/desktop/renderer/components/right-sidebar/ProjectPanel.tsx
```

### 视频能力

视频能力优先作为 `.xmcap` 内容开发，不写入 Project Core。若基础平台尚不能从
源码内方便开发能力包，可以先放入开发用 fixture，验证后再导出正式能力包。

## 16. 验收原则

Project Core 完成的标准不是“新增了一张 projects 表”，而是：

> 同一个 Agent 能够在不阻塞实时对话的情况下，围绕一件长期工作跨越多次
> 对话、委托、执行和重启持续推进；工作资产、对外产物和进度边界清晰；更换
> 视频为代码、文档或数据分析时不需要重写 Project 基础平台。

## 17. 实施状态（2026-08-03）

已完成：

- P1 Project Core：领域模型、独立 schema、Store、Service、三类工作空间、
  Step / Asset / Resource / Event / Session、对话工具与上下文渲染；
- P2 基础接入：Project scope 沿用现有 Assignment / Activity，项目上下文进入
  AssignmentExecutionContext、隔离 Core 与 ToolExecutionContext，项目委托的交付物
  同步登记为 ProjectAsset；
- P3 观察闭环：`project.list/get/current`、`project.created/updated`，Desktop 右栏
  以独立第七个“项目”栏目展示当前项目、阶段进度及委托、活动、资产数量；
- 历史数据库升级测试、人物隔离测试、执行隔离回归和 Desktop 构建验证。

V1 已完成：

- 统一媒体服务类别扩展到 `image / tts / music / video`；
- VoxCPM 作为本地媒体服务进入统一配置目录，不再游离于媒体设置之外；
- 新增 `media.runtime.status`，确定性检测 Agent 所在机器的 FFmpeg / FFprobe；
- Desktop 媒体服务页展示本地运行依赖和视频服务类别。
- 新增 MiniMax 视频插件，同一插件分别适配 MiniMax-H3/V2 与
  MiniMax-Hailuo-2.3/V1；
- 视频任务异步创建、持久化 `task_id`、轮询状态并下载最终 MP4；
- 当前消息的图片、视频和音频附件通过 `attachment_id` 进入 H3 多模态参考链路，
  不允许模型直接提交任意本机路径；
- 项目会话的成片写入项目 `deliverables/` 并登记为项目资产，普通会话写入 Agent
  自己的视频目录；中断后可以通过任务查询工具恢复。

Project 当前独立展示是为了清楚观察开发过程，仍不建设复杂项目管理后台；创建、
推进和结束继续优先通过对话完成。

V2 已完成第一版：

- 新增可导出、安装和激活的 `xiaomei.video-production` 能力包；
- Skill 提供需求、编导、分镜、视觉、动态、音频、合成和验收等领域参考，由 Agent
  为每个项目建立可调整的阶段地图；
- 六个项目工具覆盖初始化、分镜持久化、当前附件入库、FFprobe 探测、联系表和
  FFmpeg 时间线合成；
- 视频生成模型输出按 `scene_id` 写入项目 `work/motion/` 并登记为工作资产，只有
  合成候选成片进入 `deliverables/`；
- 视频生成服务不可用时保留策划、分镜和已有素材，由 Agent 判断继续其他工作还是等待；
- 已验证能力包的确定性导出、检查、安装、激活、六个工具加载，以及本机 FFmpeg
  双镜头合成和时长探测。
- 新增 Agent 主导的 `review_project` 复盘：一次性记录阶段判断、计划变化、实际
  偏差、等待原因和下一步；Desktop 项目页展示最近复盘，但不引入固定工作流。
- 新增独立的轻量 Process：可为视频选择快速三阶段、完整八阶段或自定义交付标准；
  Process 只校验正式提交，不执行或编排 Agent 的实际工作。

尚未完成：V3 真实视频闭环验收。需要可用的视频生成额度后，以一个 20～60 秒的真实项目
验证模型生成、口播、字幕、合成、Desktop 阶段展示、重启恢复和跨渠道最终交付。
