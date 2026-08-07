# Agent 能力开发边界

## 1. 决策

“能力”是面向用户的产品概念，也是安装、启用和状态展示的统一边界；它不是新的代码类型。

一个能力可以由 Skill、Tool、Plugin、MCP、Runtime、Process、模板或已有基础平台能力组合而成。能力清单只描述用户能完成什么、由哪些组件支撑、当前依赖是否满足，不负责加载或执行组件。

因此，新增能力时不得默认创建新的 Agent Core、专用调度器或新的注册体系。优先复用现有执行底座，只在真实场景暴露出共性平台缺口时扩展基础平台。

## 2. 分层

```text
用户看到：Capability
                 │
        ┌────────┼────────┐
        ▼        ▼        ▼
      Skill    Tool     Runtime/MCP
      怎么做    本机动作    外部系统与账户
        │        │        │
        └────────┴────────┘
                 │
          Agent 执行底座
  Core、工具选择、执行环境、附件、产物、项目、委托
```

- **Capability**：用户能获得什么结果。
- **Skill**：完成工作的知识、方法和判断标准。
- **Tool**：确定性的本机动作或领域操作。
- **Plugin**：把 Tool、Provider、Channel、Runtime 等代码接入基础平台的技术机制。
- **Runtime/MCP**：外部程序、账户、授权、远程数据和受控动作。
- **Process**：可选的正式交付标准，不替 Agent 计划和执行工作。
- **能力包**：能力的安装和分发载体，内部仍由上述组件独立加载。

## 3. 四种实现形态

### 3.1 只有 Skill

已有工具足以完成工作，只缺少领域知识或稳定方法时使用。

适合合同审查、会议纪要、行业研究、写作规范等。不得为了包装一个 Skill 创建空 Tool 或空 Runtime。

### 3.2 Skill + 已有 Tool

需要组合文件、Shell、联网搜索、办公文档或其他现有工具时使用。

Skill 说明何时调用、如何判断和怎样交付；不要把同一流程重新硬编码为新的专用 Tool。

### 3.3 Skill + Runtime/MCP

需要外部账户、OAuth、企业系统数据或远程受控动作时使用。

Runtime/MCP 管理连接、授权和执行环境，Skill 管理业务方法。不得把供应商账户状态写入 Agent Core，也不得为每个外部 API 在 AgentManager 中增加硬编码。

需要用户配置时，Runtime 通过统一状态协议返回 `setup_forms`。每张表单绑定一个动作，并明确作用域：

- `agent`：应用凭据、服务地址等属于当前 Agent 的配置；
- `person`：OAuth、授权码和外部账户等只属于当前人物的配置。

Desktop 根据字段声明生成输入界面，Gateway 只转发通用的 `start/complete/status/cancel` 动作。具体能力不得新增专用设置页面或专用 RPC。外部账户元数据与加密凭据统一由 `ExternalAccountStore` 保存，并由 Agent 初始化阶段作为通用依赖注入 Runtime；插件不得自行创建另一套账户库。

### 3.4 Skill + 专业领域 Tool

通用工具无法可靠完成确定性处理时使用，例如 Office 结构化修改、FFmpeg 合成、媒体探测或可复现统计计算。

专业 Tool 应注册到现有 Plugin/Tool 体系；多个能力可共享的逻辑进入稳定领域层，能力包只引用它，不复制一份新的基础设施。

## 4. 内置能力与可安装能力

二者使用相同能力清单和状态模型，区别只在分发方式。

### 内置能力

随小美基础平台发布，适用于立即可用、普遍需要或与基础体验紧密相关的能力。当前包括办公文档、基础数据分析和飞书办公入口。

### 可安装能力

通过 `.xmcap` 安装并由每个 Agent 独立启用，适用于行业能力、实施交付能力或体积和依赖较大的能力。当前视频制作是参考实现。

不得为了目录统一把所有内置能力搬入 `capability-packages/`，也不得让可安装能力绕过统一的 Plugin、Skill 和 Capability 加载器。

## 5. 能力运行依赖

能力清单可声明由宿主环境提供的依赖：

```yaml
requirements:
  tools:
    - target: create_project
      label: 项目工作现场
  executables:
    - target: ffmpeg
      label: FFmpeg 媒体合成
      outcomes: [composed_video]
  capabilities:
    - target: office_documents
      label: 办公文档能力
      required: false
      setup_section: capabilities
  services:
    - target: example_service
      label: 示例服务
      setup_section: capabilities
```

支持的分类：

- `tools`：Agent ToolRegistry 中的工具。
- `executables`：Agent 宿主环境 `PATH` 中的系统程序。
- `capabilities`：同一 Agent 的其他能力。
- `services`：已注册的 Runtime Probe 或 Tool Service。

每项依赖支持：

- `target`：稳定标识；
- `label`：用户可理解的名称；
- `required`：默认 `true`，设为 `false` 时缺失只让能力降级；
- `setup_section`：可用的设置入口；
- `outcomes`：只影响指定交付结果，省略时影响整个能力。

依赖缺失只影响真实依赖它的结果。例如缺少 FFmpeg 时仍可完成视频策划，但不能声称可以合成成片。

能力清单中的 `requirements` 是**运行时依赖状态**；能力包根 `capability.yaml` 中的 `requirements` 是**归档安装兼容性**。两者目的不同，不得混用。当前安装器不会自动安装 Python、Node、FFmpeg 等外部依赖。

## 6. 当前四个参考能力

### 办公文档

`document_io` 提供统一读写入口，Word、Spreadsheet、Presentation 和 PDF 插件分别注册 Writer、Extractor 与 Skill，共享 `documents/` 领域服务。新增格式不修改 AgentManager。

### 数据分析

`analyze_data` 提供确定性统计，Skill 负责分析顺序和解释边界；办公文档作为可选依赖，用于正式报告交付。增加 SQL、Notebook 或 Dashboard 时，应先判断是否属于通用数据领域基础设施。

### 飞书办公

Runtime 管理 lark-cli、应用配置、Person 授权和执行环境，官方 lark Skills 指导 Agent 通过通用 Shell 操作。飞书 API 不逐个包装成小美专用 Tool。

### Gmail

Gmail 插件组合 Runtime、邮件 Tool 和 Skill。Google OAuth 应用配置属于 Agent，邮箱授权和令牌属于 Person；两者通过通用动作表单和外部账户存储完成，不在 Desktop、Gateway 或 AgentManager 中保留 Gmail 分支。未来 QQ Mail 等能力应复用同一边界，只新增自己的 Capability 清单、Plugin/Runtime、Tool 和 Skill。

### QQ 邮箱

QQ 邮箱是通用外部账户平台的第二个参考实现。Runtime 用 Person 级表单接收邮箱地址与授权码，连接时验证 IMAP/SMTP，并将授权码交给统一账户库加密保存；Tool 负责搜索、阅读、发送、回复和附件边界，Skill 负责邮件安全规则。基础平台中不包含 QQ 邮箱专用页面、RPC 或 AgentManager 分支。

### 视频制作

可安装能力包组合 Capability、Skill、项目 Tool 和 Process。项目保存工作现场，Process 约束正式提交，FFmpeg/FFprobe 作为特定结果的运行依赖。视频 Provider 仍通过独立媒体插件提供。

## 7. 何时允许修改基础平台

满足以下任一条件才修改基础平台：

1. 至少两个领域需要相同机制；
2. 缺少统一机制会迫使能力侵入 Agent Core；
3. 涉及身份、权限、执行环境、附件或产物等必须统一保证的边界；
4. 现有扩展点无法真实表达能力状态或安全约束。

只服务一个领域的参数、提示词、API 映射、文件格式或工作方法应留在对应 Skill、Plugin 或领域实现中。

## 8. 开发检查清单

新增能力前确认：

1. 用户要获得的结果是否已经用 Capability Outcome 表达；
2. 是否只安装 Skill 就能完成；
3. 是否可以复用已有 Tool、Runtime 或 MCP；
4. 新代码是领域确定性操作，还是把模型流程不必要地固化；
5. 外部依赖是否在能力清单中如实声明；
6. 缺少某项依赖时，是否只影响真实相关的 Outcome；
7. 是否修改了 AgentManager 或 Agent Core；如果修改，是否确实补的是共性平台能力；
8. 能力停用后，其 Tool 和 Skill 是否不再进入 Agent 选择范围；
9. 可安装能力是否通过完整性校验、激活隔离和重启加载测试；
10. 用户是否只需要理解“能做什么”，而不必理解底层 Plugin、Tool 或 Runtime。
