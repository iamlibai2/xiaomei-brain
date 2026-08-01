# Agent 能力体系设计

> 状态：设计稿
>
> 本文定义小美如何在基础平台之上扩展一个 Agent 的实际工作能力。它首先是一份产品与领域设计，不要求立即重写现有 Plugin、Tool、Skill、MCP 或 Provider 实现。

## 1. 设计目标

能力体系只解决一个核心问题：

> 在不持续修改 Agent 基础平台的前提下，让一个具体 Agent 获得、理解、配置并使用新的工作能力。

它必须同时满足两组要求。

面向使用者：

- 用户只需要表达“我要做什么”；
- 界面使用“能力”这一种统一概念；
- 用户不需要理解 Plugin、Tool、Skill、MCP、Provider 等技术名词；
- Agent 能说明自己是否能做、缺少什么，以及如何继续；
- 安装或完善能力后能够回到原任务继续执行。

面向开发者：

- 技术组件仍然职责清晰、可以独立演进；
- 新增普通业务能力时，不修改 Agent Core、AgentManager、Gateway 和 Desktop 主链路；
- 能力可以由 Skill、Tool、Provider、Connector、MCP、脚本和模板自由组合；
- 同一套基础设施支持内置能力、第三方能力和企业私有能力；
- 能力的安装、配置和启用状态属于具体 Agent。

## 2. 核心决策

### 2.1 “能力”是唯一的用户概念

用户看到的是工作结果导向的能力：

- 办公文档；
- 数据分析；
- 金融研究；
- 图片创作；
- 视频编辑；
- 网页操作；
- 企业办公。

用户不直接管理：

- Tool；
- Skill；
- Plugin；
- MCP Server；
- Provider；
- Hook；
- Python 包或可执行文件。

这些术语只出现在开发者文档、诊断日志和必要的高级信息中。

### 2.2 能力不是新的执行引擎

能力层不重新实现 Tool、Skill 或 Plugin，也不建立第二套 Agent Core。它是现有技术组件之上的领域层：

```text
用户目标
   ↓
能力（Agent 能完成什么）
   ↓
工作方法（Skill）
   ↓
可执行动作（Tool / MCP / Connector）
   ↓
Provider、脚本、系统程序和外部服务
```

### 2.3 能力属于 Agent，不属于 Desktop

坚持“一 Agent 一世界”：

- 哪些能力已启用，由该 Agent 记录；
- 能力使用的账号、授权和密钥，由该 Agent 的配置系统管理；
- 能力产生的记忆、经历、委托和产物，进入该 Agent 自己的数据世界；
- Desktop 只通过 Agent 的交互接口查看和请求变更，不直接修改配置文件；
- 远程 Agent 在自己的宿主机安装和运行能力，本地 Desktop 不越权操作远端文件。

能力包文件可以在同一宿主机上共享只读缓存，避免多个 Agent 重复下载；但启用、配置、授权和运行状态不能跨 Agent 共享。

## 3. 基础平台与扩展能力的边界

### 3.1 基础平台

多数能力都依赖的机制属于基础平台：

- Agent Core 与隔离运行时；
- 对话、Session、Turn 和消息持久化；
- Person、身份识别和关系；
- 记忆、Goal、PACE、经验流；
- Assignment 和自主行为；
- Tool 注册、选择、执行、取消和超时；
- Skill 加载、检索和使用；
- Artifact 发现、版本、持久化和跨渠道交付；
- Gateway 交互协议；
- Channel、Embodiment 和消息路由；
- 权限、审批、审计和执行上下文；
- 配置、密钥、日志和数据库迁移；
- 能力包发现、校验、加载和生命周期。

### 3.2 扩展能力

让 Agent 多会一类具体工作，属于扩展能力：

- Word、Excel、PPT、PDF 处理；
- 财务分析、公司估值和市场数据；
- 数据清洗、统计和可视化；
- 图片、音乐和视频生成；
- 网页自动化；
- ERP、CRM、OA、邮箱和企业知识库操作。

判断规则：

> 如果多数未来能力都会依赖它，就完善基础平台；如果它只是让 Agent 多会一类工作，就放入能力包。

因此，“新增视频编辑能力不应修改 AgentManager”不是绝对禁止完善平台。如果实现视频编辑时发现平台缺少通用的长任务进度或大文件交付机制，应当完善一次基础平台，供后续所有能力共同复用。

## 4. 内部组件模型

### 4.1 Tool：原子行动

Tool 是输入输出明确、可以结构化调用的动作，例如：

```text
read
write
bash
write_document
generate_image
query_stock_price
send_email
```

Tool 不描述完整业务流程。它必须进入平台统一的参数校验、权限、取消、日志、错误和产物链路。

### 4.2 Skill：工作方法

Skill 描述如何完成一类任务：

- 适用场景；
- 操作步骤；
- 使用哪些 Tool；
- 领域知识和约束；
- 模板与参考资料；
- 结果验收方式。

Skill 可以携带脚本，但脚本仍通过平台提供的执行底座运行。Skill 是 Agent 在任务现场实际选择和阅读的工作方法，不承担安装、版本和供应商配置职责。

### 4.3 Connector：外部系统连接

Connector 负责外部系统的认证、状态、权限和 API 操作，例如邮箱、CRM、飞书文档或企业数据库。连接后，它把可执行动作提供给 Agent。

Channel 与 Connector 保持分离：

- Channel 是人从哪里与 Agent 对话；
- Connector 是 Agent 能操作哪个外部系统。

飞书可以同时拥有飞书对话 Channel 和飞书文档 Connector，但二者不是同一个领域对象。

### 4.4 Provider：服务商适配

Provider 负责把统一意图转换为某个供应商接受的协议，例如 LLM、图片、TTS、音乐、搜索或 OCR 服务。Provider 通常是能力内部实现，不作为主要产品入口。

### 4.5 MCP：外部能力协议

MCP 是接入外部 Tool 和资源的一种协议，不是一种面向用户的能力分类。能力包可以携带 MCP 配置，也可以完全不使用 MCP。

MCP 提供的工具进入统一 Tool Registry、动态选择、权限和执行轨迹，不能成为绕开 Agent 基础平台的第二条调用链。

### 4.6 Plugin：内部组件载体

现有 Plugin 继续承担 Python 组件发现和注册：

- 加载 Adapter；
- 注册 Tool、Provider、Channel、身体器官或文档处理器；
- 声明配置结构；
- 执行环境和依赖检查。

Plugin 是内部实现术语，不再等同于用户购买、安装或看到的一项能力。

### 4.7 Capability Package：能力的分发单位

能力包是安装、升级、校验和分发单位。一个能力包可以包含：

- 一个或多个 Skill；
- 一个或多个内部 Plugin；
- MCP 配置；
- Provider 或 Connector；
- 脚本、模板、参考资料和静态资源；
- 依赖与权限声明；
- 必要的数据迁移。

第一版能力包可以只有一个 `SKILL.md`，不需要为了“成为能力包”增加运行时代码。

## 5. 能力领域模型

能力层至少包含以下逻辑对象。第一阶段不要求每个对象都对应数据库表。

### 5.1 CapabilityDefinition

描述一项能力对用户意味着什么：

```text
CapabilityDefinition
├─ id                  稳定标识，例如 office_documents
├─ name                办公文档
├─ summary             能做什么
├─ category            办公、数据、创作、研发、企业系统等
├─ outcomes            可完成的具体结果
├─ examples            用户可以怎样提出任务
├─ requirements        模型、服务、程序、操作系统或连接要求
├─ permissions         可能使用的文件、网络、设备和外部账号权限
└─ provenance          来源、作者、版本、许可证和签名信息
```

`outcomes` 是能力详情中的业务说明，不继续拆成大量需要用户管理的子能力。例如“办公文档”可以包含读取 Word、制作 PPT、修改 Excel 和生成 PDF。

只有当两个部分具有明显不同的安装、授权、风险或使用人群时，才拆成两项能力。

### 5.2 CapabilityContribution

记录技术组件对某项能力的贡献：

```text
office_documents
├─ document_io Plugin
├─ document_word Plugin + Skill
├─ document_spreadsheet Plugin + Skill
├─ document_presentation Plugin + Skill
└─ document_pdf Plugin + Skill
```

能力与组件是多对多关系：一个能力可以由多个组件组成，一个通用组件也可以支持多个能力。

### 5.3 CapabilityActivation

记录某个 Agent 是否选择拥有和使用这项能力：

```text
CapabilityActivation
├─ agent_id
├─ capability_id
├─ package_id / version
├─ enabled
├─ accepted_permissions
├─ selected_service_or_connector
└─ updated_at
```

安装和启用必须分开：能力包可以已在宿主机缓存，但某个 Agent 没有启用它。

### 5.4 CapabilityStatus

状态由真实运行条件计算，不保存一份容易过期的“可用”布尔值。

内部状态建议为：

```text
not_acquired   尚未获得能力包
disabled       该 Agent 已关闭
preparing      正在安装、索引或初始化
needs_setup    缺少必要配置、账号或授权
ready          当前可以使用
degraded       部分结果可完成，但有明确限制
unavailable    依赖、平台或服务当前不可用
error          能力自身加载或校验失败
```

Desktop 对普通用户只呈现简化状态：

- 可用；
- 需要完善；
- 准备中；
- 暂不可用；
- 未获得；
- 已关闭。

详情中说明具体原因和下一步，不暴露裸异常。

## 6. 能力包规范

能力包使用根目录 `capability.yaml` 描述面向人物的能力、权限、依赖和所含文件。D1 已确定以下最小格式：

```yaml
schema_version: 1
package:
  id: xiaomei.office-documents
  name: 办公文档
  version: 1.0.0
  description: 阅读、创建和修改常见办公文档
  publisher: xiaomei-brain
  license: Apache-2.0

capabilities:
  - id: office_documents
    name: 办公文档
    summary: 阅读、创建和修改常见办公文档

requirements:
  xiaomei_brain: ">=0.1.0"
  python: ">=3.11"
  python_packages: []
  node_packages: []
  executables: []

permissions:
  filesystem:
    - workspace_read
    - workspace_write

contents:
  skills:
    - skills/word-documents/SKILL.md
  plugins:
    - plugins/document_word/plugin.yaml
```

归档还必须包含 `checksums.json`，完整覆盖除自身以外的所有文件。详细约束见 `docs/reference/capability-package-format.md`。

该清单描述“整项能力”，现有各组件的 `plugin.yaml` 继续描述“某个 Python 组件怎样加载”。二者暂时并存，职责不同。D1 只读取清单并检查归档，不加载这些组件。

第一阶段通过一个内置能力清单聚合现有插件，不搬动现有目录。未来外部能力包可以把清单、Skill、Plugin、MCP 和资源放入同一包中。

## 7. 发现、选择和执行

能力选择不替代现有 Skill 和 Tool 选择，而是形成三级过程：

```text
1. 能力判断
   Agent 是否具备完成用户目标的能力，是否缺少配置或授权

2. Skill 选择
   在可用能力中选择完成任务的方法和规范

3. Tool 选择
   根据当前步骤动态提供具体执行动作
```

正常任务不需要为这三级过程分别调用一次模型。能力元数据可以进入现有向量索引或由内部 Resolver 查询，Skill 和 Tool 继续复用当前的语义检索机制。

### 7.1 CapabilityRegistry

新增逻辑注册表，聚合：

- 内置能力定义；
- 已发现能力包；
- PluginRegistry 中已经成功加载的组件；
- SkillLoader 中已经索引的 Skill；
- MCP、Provider 和 Connector 的运行状态；
- 当前 Agent 的启用、配置和授权。

它输出的是能力视图，不取代现有 `PluginRegistry`、`ToolRegistry` 和 `SkillLoader`。

### 7.2 CapabilityResolver

Resolver 回答：

- 这个目标对应哪些能力；
- 当前 Agent 是否具备；
- 如果不能完成，缺少什么；
- 是否存在可以获得的能力包；
- 完善能力后能否恢复原任务。

Resolver 只能依据真实注册和健康状态回答，不能只根据模型常识声称“我可以”。

### 7.3 动态上下文

能力元数据不应全部塞入每轮 Prompt。建议：

- 少量核心能力只提供简短摘要；
- 其余能力按当前请求进行语义召回；
- 只把已启用且真实可用的 Skill 和 Tool 放入执行现场；
- 可获得但未启用的能力只用于缺口提示，不能进入可执行工具列表。

## 8. 对话驱动的体验

### 8.1 已经具备能力

```text
Person：根据这些数据做一份经营分析报告。

Agent：识别到“数据分析”和“办公文档”可用，直接开始工作。
```

用户不需要先选择能力。

### 8.2 缺少配置

```text
Person：分析这家公司的最新财务状况。

Agent：我具备金融研究方法，但还没有可用的市场数据来源。
       连接数据服务后可以继续，需要你提供对应服务的访问凭证。
```

完成配置后，应自动回到原请求，而不是让用户重新输入。

### 8.3 尚未获得能力

```text
Person：把这些素材剪成一分钟的视频。

Agent：我现在还没有视频编辑能力。
       找到一项适合本机的能力包，需要安装视频处理程序并获得工作目录访问权限。
       是否继续？
```

安装第三方代码、增加高风险权限或连接外部账号时，继续使用现有 Interaction/Action 确认机制。Agent 可以主动建议，但不能静默扩大自己的执行权限。

### 8.4 失败和降级

能力不可用时必须区分：

- 没有这项能力；
- 能力已关闭；
- 缺少配置；
- 外部服务暂时故障；
- 当前模型不支持必要输入；
- 本机缺少运行程序；
- 当前 Person 没有相应资源权限。

不能统一回复为“工具调用失败”。

## 9. Desktop 产品设计

Desktop 使用“能力”作为统一入口，不增加 Plugin、Skill 或 MCP 一级管理页面。

```text
能力
├─ 已拥有
├─ 可获取
└─ 需要完善
```

能力卡片只展示：

- 名称和实际用途；
- 当前状态；
- 典型任务示例；
- 必要时显示“需要连接账号”“需要配置服务”或“当前不可用”；
- 开始使用、继续配置、关闭等直接动作。

能力详情展示：

- 能完成哪些事情；
- 需要哪些资料、账号或本机条件；
- 会访问什么；
- 来源、版本和更新信息；
- 最近是否成功使用；
- 可理解的诊断结果。

Plugin、Tool、Skill、MCP 明细只放在折叠的“技术信息”中，默认不出现。

### 9.1 设置与能力的边界

- 模型、账户、Agent、Desktop 行为仍属于设置；
- “这个 Agent 会做什么”属于能力；
- 能力需要的 API Key、账号和权限，从能力配置流程进入；
- 底层继续复用已有模型、媒体服务、工具服务和 Connector 配置，不复制另一份密钥。

## 10. Gateway 与本地宿主机边界

能力属于 Agent，因此查看和配置能力适合通过 Gateway 的统一交互服务完成。未来可提供内部方法：

```text
capability.list
capability.get
capability.enable
capability.disable
capability.configure
capability.acquire
```

以及状态事件：

```text
capability.changed
capability.progress
```

这些是技术协议名，不是界面文案。第一阶段可以只实现查询，不要求一次完成全部方法。

需要区分两类操作：

- 启用和配置：由 Agent 的能力服务处理；
- 下载代码、安装系统程序：由 Agent 所在宿主机的安装执行器处理，并接受权限和安全策略约束。

远程 Agent 如果允许获得能力，也是在远端宿主机执行。Desktop 只提交请求并展示结果，不把远端目录当成本地目录操作。

## 11. 存储与隔离

建议的逻辑布局：

```text
~/.xiaomei-brain/
├─ capability-packages/          宿主机共享的不可变版本缓存
│  └─ <package-id>/<version>/
└─ <agent-id>/
   ├─ config.json                该 Agent 的启用和配置
   ├─ capabilities.lock          实际使用的能力包版本与校验值
   ├─ skills/                    该 Agent 私有或学习形成的 Skill
   └─ memory/
```

实施时优先复用现有 Agent `config.json`、Plugin 配置和 SkillStorage。`capabilities.lock` 在真正支持外部安装和版本解析时再引入，不为第一版提前增加文件。

密钥不得写入能力包。密钥存储继续由 Agent 配置服务管理，能力层只引用相应服务或 Connector。

## 12. 安全、可信和可恢复

第三方能力包至少需要：

- 来源和发布者；
- 版本与内容校验值；
- 安装前权限声明；
- 依赖和支持平台；
- 配置 Schema；
- 代码与脚本安全检查；
- 安装、升级失败后的原子回滚；
- 数据迁移版本；
- 禁用后停止继续暴露其 Tool、Skill 和 Hook；
- 卸载时区分程序文件、配置、业务数据和历史审计。

能力包不能绕过：

- ExecutionContext；
- Action/Interaction 确认；
- Artifact 交付；
- Person 与资源授权；
- Agent 停止和取消语义；
- 日志和审计。

## 13. 当前代码基础与缺口

现有代码已经具备：

- `plugin/loader.py`：发现、校验和加载 `plugin.yaml`；
- `plugin/registry.py`：注册 Tool、Provider、Channel、文档处理器和 Skill 目录；
- `skills/`：Skill 扫描、存储、向量检索和使用统计；
- `tools/dynamic.py`：结合最近用户上下文动态选择 Tool；
- `tool_services/`、`media_services/`：外部服务的声明式配置；
- MCP、Channel、Artifact、Assignment 和 Gateway 基础链路。

当前缺口是：

- 没有 `CapabilityDefinition` 和聚合注册表；
- 用户看到的仍是模型、服务、插件等分散配置；
- 无法统一回答“这个 Agent 现在能做什么”；
- 不能把“缺能力”和“能力暂不可用”可靠区分；
- 现有 Plugin 通常按一个技术组件组织，缺少业务能力聚合；
- 外部能力包尚无安装、版本锁定、校验和回滚机制；
- Agent 尚不能在对话中发现能力缺口并恢复原任务。

因此第一步不是重写 PluginLoader，而是在它和产品之间增加能力聚合层。

## 14. 分阶段实施

### 阶段 A：能力只读视图

- 定义 `CapabilityDefinition`、状态和清单 Schema；
- 建立 `CapabilityRegistry`，读取现有 Plugin、Skill、Tool 和服务状态；
- 用“办公文档”聚合现有 Word、Excel、PPT、PDF 组件；
- 能够列出 Agent 当前真实能力和不可用原因；
- 不改变现有插件加载、Skill 检索和任务执行。

### 阶段 B：Agent 级启用与配置

- 保存每个 Agent 的能力启用状态；
- 统一能力配置入口，复用已有服务和 Connector 配置；
- 增加 Gateway 查询与配置方法；
- Desktop 增加“能力”页面；
- 能力变化后正确更新 Skill 和 Tool 索引。

### 阶段 C：对话发现和完善能力

- Agent 识别当前目标缺少的能力；
- 建议已知能力包并说明条件；
- 通过 Clarify/Action 完成选择、授权和配置；
- 安装或配置完成后恢复原任务；
- 不在普通回答里虚构自己拥有的能力。

### 阶段 D：可安装能力包

- 支持本地包和受信来源；
- 版本、校验、依赖、权限和回滚；
- 宿主机共享缓存与 Agent 独立启用；
- 能力包更新不破坏历史 Agent 数据；
- Windows、macOS、Linux 一致的包生命周期。

### 阶段 E：企业与生态分发

- 企业私有能力源；
- 组织推荐和允许列表；
- 发布者签名和审计；
- 能力版本策略和兼容范围；
- 公开能力目录或市场。

## 15. 第一项样板能力

选择“办公文档”作为第一个样板，因为现有实现已经覆盖主要执行链路：

```text
办公文档
├─ 理解 DOCX / XLSX / PPTX / PDF
├─ 创建和修改文档
├─ 使用附件和工作区文件
├─ 形成 Artifact
├─ Desktop / 飞书 / 钉钉交付
└─ 在 Assignment 中持续修改
```

阶段 A 的验收标准：

1. Agent 能返回“办公文档”而不是五个文档插件；
2. 状态来自实际组件和运行依赖；
3. 缺少某个格式依赖时，能力显示明确限制而不是整体失效；
4. 能力详情使用业务语言；
5. 不改变当前 Word、Excel、PPT、PDF 的调用和交付结果；
6. 新增同类文档格式时，只增加组件声明，不修改 Desktop 能力页面；
7. 同一台机器上的两个 Agent 可以拥有不同的启用状态。

## 16. 当前明确不做

- 不立即建设公开能力市场；
- 不给 Desktop 增加独立 Plugin、Tool、Skill 或 MCP 管理首页；
- 不要求用户手动选择能力后才能对话；
- 不把 Agent 身份、性格、记忆或 Goal 做成可安装能力；
- 不把另一个 Agent 或“专家人设”当作普通能力包；
- 不允许能力包直接修改 Agent Core 或绕过统一执行链路；
- 不为了目录整齐立即迁移全部现有插件；
- 不为了兼容尚未发行的旧能力格式增加长期历史包袱；
- 不在第一阶段引入中央能力服务或多 Agent 统一管理。

## 17. 下一步

阶段 A、B 以及阶段 C 中针对“已安装但未配置能力”的闭环已经完成。下一步先验证并稳定两个真实场景：

1. 联网搜索未配置时，Agent 说明能力缺口并展示配置卡片；
2. 卡片精确进入对应服务配置，保存后显示真实运行状态；
3. 必要时重启 Agent，人物确认后恢复原始任务和附件；
4. 能力被关闭时，Agent 不使用底层工具绕过，并能精确定位能力开关；
5. 切换会话、重启 Desktop 后，配置卡片和已恢复状态保持一致。

能力包获取、安装、签名、依赖与回滚属于阶段 D。在安装模型和信任边界单独设计清楚前，不把临时下载逻辑塞进当前配置闭环。

## 18. 当前实施进度

截至 2026-08-02，已完成只读能力闭环、Agent 级启停，以及已安装能力的对话配置与任务恢复闭环：

- `CapabilityDefinition`、`CapabilityStatus`、清单加载和运行时聚合；
- “办公文档”样板能力，聚合 Word、Excel、PPT、PDF；
- `capability.list/get` 只读 Gateway RPC；
- Desktop Agent 设置中的通用能力页面；
- “数据分析与可视化”作为第二项真实能力接入，证明新增普通能力无需修改 AgentManager、Gateway 和 Desktop 主链路；
- CSV、TSV、XLSX 数据概览、缺失值与数值统计、分组汇总、SVG 柱状图和折线图；
- 相关能力事实进入现有对话上下文，与 Skill/Tool 动态召回协同工作，不增加额外模型调用；
- 能力状态始终由已加载 Plugin、Tool 和 Skill 计算，不根据清单单独宣称可用。
- 每个 Agent 可独立启用或关闭能力，状态保存在该 Agent 的 `config.json`；
- `capability.enable/disable` 通过 Gateway 修改 Agent 自身配置，Desktop 不直接操作文件；
- 能力关闭后立即从对话的 Skill 索引和 Tool 选择中消失，不卸载进程内共享组件，也不要求重启 Agent；
- Desktop 能力页使用统一开关展示和修改真实启用状态。
- 能力清单可以声明已有服务配置依赖和对应设置入口，不在能力层复制 API Key；
- “联网搜索”作为首个配置型样板能力：未配置时显示“需要完善”，从能力页直接进入现有联网搜索设置；
- 服务配置已经保存、但运行时 Tool 尚未加载时显示“准备中”，明确提示需要完成既有重启流程。

阶段 B 的 Agent 级启停、运行时生效和统一配置入口已经完成。能力包安装、版本锁定和能力市场尚未开始。

阶段 C 已开始第一步：

- 新增业务级 `capability_status` 内部工具，Agent 可以按任务查询当前真实能力、可完成结果、限制和设置位置；
- 该工具进入现有动态 Tool 向量索引，不作为每轮无条件携带的核心工具；
- 相关能力事实进入对话时，明确要求 Agent 不虚构、不假装完成，也不使用不等价的底层命令绕过关闭或未配置状态；
- 对“需要完善”和“准备中”的能力，Agent 能说明现有 Desktop 设置入口。

阶段 C 尚未实现通过对话提交密钥、执行安装或在 Agent 重启后自动恢复被阻塞的原任务。这些涉及敏感配置、客户端动作与持久化恢复，需要在下一小阶段单独收口。

阶段 C 的第二小步已经完成：

- 新增 `request_capability_setup` 业务工具，仅在具体任务被未配置、未启用或准备中的能力阻塞时使用；
- 新增 `capability.setup.requested` 会话领域事件，和 Clarify、Action 语义分离：它不等待回答、不代表风险审批，也不直接修改配置；
- Desktop 在当前会话展示“需要完善能力配置”卡片，按钮进入对应 Agent 的既有设置页面；
- 配置卡片写入会话时间线，并进入活动 Turn 快照，切换会话、重启 Desktop 或执行中重连后仍可恢复；
- 该导航事件只投影到 Desktop WebSocket，飞书和钉钉不接收无法执行的客户端导航动作；
- API Key 继续由既有设置 RPC 保存，既不放入聊天消息，也不写入能力清单。

这一小步只解决“发现缺口并自然进入配置”的闭环。配置完成后自动恢复原任务、能力包安装和下载权限仍留在后续阶段。

阶段 C 的第三小步完成了原任务恢复，但采用“人物确认继续”而不是 Agent 重启后静默自动执行：

- 配置卡片记录原始用户消息 ID，原请求正文和附件仍由 Agent 会话数据库持有，Desktop 不复制任务内容；
- 原消息保持正常完成状态，另以 `capability_blocked` 元数据记录阻塞能力、配置请求和是否仍待恢复；
- 卡片提供“配置完成，继续任务”，Gateway 在恢复前重新计算该 Agent 的能力状态；只有 `ready` 或 `degraded` 才能恢复；
- 恢复复用原消息与 Agent 托管的原附件，创建新的 Turn，并记录 `retry_of` 与 `resumed_capability_id`；
- 恢复成功后将原阻塞记录标为已恢复，防止重复执行；能力仍处于 `needs_setup`、`preparing` 或禁用状态时保持阻塞；
- 不在 Agent 重启时自动执行旧任务。旧任务可能包含外部操作或已经失去时效，静默恢复会违背人物对当前执行时机的控制。

因此当前闭环是：发现缺口 → 进入配置 → 必要时重启 Agent → 人物点击继续 → Gateway 核验能力 → 恢复原任务。未来若要支持自动恢复，应只对明确声明可自动恢复且无副作用的任务开放。

配置卡片的运行状态也已收口：

- 卡片通过现有 `capability.get` RPC 读取 Agent 当前计算出的状态，不根据 Desktop 本地配置猜测；
- 保存或移除服务配置、启用或关闭能力后，设置页发出本地刷新通知；Agent 断线重连后也会重新查询；
- 配置动作中的 `target` 已贯通 Desktop 设置导航：搜索类动作直接打开对应服务编辑器，能力类动作滚动并短暂高亮对应能力，不再只停留在设置大类首页；
- `needs_setup` 显示尚未配置，`preparing` 明确提示需要重启 Agent，`ready/degraded` 才开放继续按钮；
- 恢复成功发布 `capability.setup.updated`，同时更新活动 Turn、Desktop 实时卡片和持久化时间线；
- 历史中的已恢复卡片显示“原任务已恢复”，不再提供重复执行按钮。

阶段 D1 已完成只读能力包检查：

- 确定 `.xmcap` ZIP 归档、`capability.yaml` 与 `checksums.json` 的最小格式；
- 新增 `capability.package.inspect` RPC，由目标 Agent 校验归档，Desktop 不解析清单；
- 检查路径穿越、符号链接、加密、重复路径、归档规模、异常压缩比、内容引用和 SHA-256；
- Desktop 能力页支持选择本地能力包，并预览能力、权限、依赖、错误和警告；
- 检查过程不解压到磁盘、不导入代码、不写 Agent 配置，也不安装任何依赖；
- 8 MB 是 D1 单帧检查限制，D2 若支持大型能力包应增加分块上传，而不是扩大 WebSocket JSON 帧。

D2 的安装目录、原子切换、Agent 独立启用和 Action 审批尚未实现。
