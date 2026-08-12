# Desktop 统一初始化

## 目标

Desktop 只维护一条启动链路：安装后的首次初始化、初始化中断恢复、已有安装升级和日常启动，都由同一个 `BootstrapManager` 根据真实状态裁定。初始化不是普通页面，也不应在每次启动时重新执行。

它复用现有身份、Runtime、本机 AI 服务、Agent 管理和模型设置能力，不重新实现第二套账户或 Agent 系统。

## 四阶段

### 1. 统一状态与入口

- Electron 主进程的 `BootstrapManager` 是初始化状态的唯一来源。
- Renderer 通过 `bootstrap.*` IPC 读取状态和提交阶段动作，不自行拼接文件检查。
- 状态保存在 Desktop 用户数据目录的 `bootstrap-state.json`，只记录初始化进度与选择，不保存身份密码、模型密钥或 Agent 数据。
- 未完成的阶段可以重试；完成标记使用临时文件加原子替换写入。

### 2. 首次初始化

首次安装先选择一种初始化体验，两种模式共享同一套状态机、安装器和完成标记，不维护两套底层逻辑。

#### 快速开始

面向不关心技术细节的普通用户：

1. Desktop 自动准备 Python、Node.js 和体积较小、兼容性更稳定的 CPU 推理环境；CUDA 可在之后升级。
2. 自动下载并启动必需的 Embedding 模型，界面只展示统一进度，不暴露 pip、CUDA 或模型文件细节。
3. 准备过程中静默创建初始本地 Agent `xiaomei`，显示名为“小美”，不把 Agent 运维概念暴露给普通用户。
4. 环境准备完成后，创建或恢复本机身份并设置密码。
5. 启动并连接小美，复用现有模型设置能力添加 API Key、测试并选择主模型。
6. 模型真实可用后写入完成标记，进入会话界面。

#### 自定义设置

面向希望控制本机资源和功能范围的用户：

1. 准备安装包内置的 Python 与 Node.js Runtime。
2. 选择 CPU 或 CUDA 推理环境。
3. 选择必需的 Embedding 模型及其运行设备并完成下载、启动。
4. 自主选择是否安装 FFmpeg、STT、TTS、人脸识别和声纹识别；每项可选择现有目录支持的模型和运行设备，跳过的服务不阻塞核心对话。
5. 所选组件处理完成后，创建或恢复本机身份并设置密码。
6. 设置初始本地 Agent 的名称和职责，配置主模型并完成初始化。

### 3. 日常启动与修复

- 初始化完成后，启动时先展示稳定的状态页，不提前渲染新会话页或错误页，避免页面闪烁。
- 身份锁定时立即展示解锁页；Runtime 恢复和共享 Embedding 启动在解锁后继续。
- Agent 停止或被删除属于正常管理状态，不会重新触发首次初始化。
- Runtime、推理依赖或 Embedding 模型缺失时进入修复阶段，只修复缺失组件，不重建身份或覆盖 Agent 数据。
- 初始化失败时保留当前阶段，提供重试和打开日志目录入口。
- 老版本已有本机账户时即视为已有安装；即使只连接远程 Agent、没有本地 Agent，也只修复缺失组件，不要求重新初始化。

### 4. 验收与发布

正式发布安装包前至少完成以下验收：

| 场景 | 预期结果 |
| --- | --- |
| 全新 Windows 用户安装 | 先选择快速开始或自定义设置，再完成对应初始化流程 |
| 快速开始 | 仅展示统一准备进度，默认使用 CPU，不要求用户理解 pip、CUDA 或 Embedding |
| 自定义设置 | 可以分别选择 FFmpeg、STT、TTS、人脸识别和声纹识别，跳过后仍可完成初始化 |
| 在任一初始化阶段关闭 Desktop | 重启后回到未完成阶段，不重复已完成动作，不产生第二个初始 Agent |
| 已有开发版数据升级 | 身份、Person、Agent、会话、记忆和模型配置保留，正常进入登录或主界面 |
| 身份处于锁定状态 | 快速显示解锁页，不等待 Runtime 解压或模型启动 |
| 初始化完成后停止 Agent | 正常显示 Agent 未运行状态，不进入初始化 |
| 初始化完成后删除所有 Agent | 正常进入 Agent 管理，不偷偷创建新的小美 |
| Runtime 或 Embedding 文件损坏 | 进入对应修复阶段，修复后恢复正常启动 |
| CPU 环境 | 不下载 CUDA 依赖，Embedding 能在 CPU 启动 |
| CUDA 环境 | 只安装所选 CUDA 推理依赖，Embedding 能使用所选设备 |
| FFmpeg 未选择或安装失败 | 核心对话仍可使用，媒体能力明确显示不可用 |
| 升级 Desktop 应用 | 不删除 `%USERPROFILE%\.xiaomei-brain` 下的 Agent 数据 |

安装包体积较大的完整构建只在候选版本收束时执行；日常开发使用 TypeScript 构建、状态机测试和现有数据升级测试验证。

开发环境可以安全预览初始化界面：

```powershell
$env:XIAOMEI_BOOTSTRAP_PREVIEW="1"
npm run dev
```

也可以将值设为 `welcome`、`identity`、`runtime`、`inference`、`embedding`、`optional_services`、`agent` 或 `model`，直接打开对应阶段。预览模式只使用进程内模拟状态，不写 `bootstrap-state.json`，不安装组件，不创建或启动 Agent，也不修改现有身份、模型和历史数据。关闭终端后环境变量自然失效；也可以执行 `Remove-Item Env:XIAOMEI_BOOTSTRAP_PREVIEW` 后正常启动。

## 数据边界

```text
Desktop userData/bootstrap-state.json
  └─ 初始化进度、模式、CPU/CUDA、可选服务与初始 Agent ID

%USERPROFILE%/.xiaomei-brain
  ├─ 身份与 Person
  ├─ Agent 配置、数据库、记忆和会话
  ├─ 模型与共享服务状态
  └─ 工作区和产物
```

卸载或升级 Desktop 不删除第二部分。Bootstrap 只协调这些已有子系统，不拥有它们的业务数据。

## 非目标

- 不在初始化器中复制账户管理、Agent 管理或模型设置逻辑。
- 不把 STT、TTS、人脸、声纹等可选服务变成首次启动的阻塞条件。
- 不因普通 Agent 离线或远程 Agent 不可达而进入修复模式。
- 不在每次启动时重新下载、重新安装或重新创建资源。
