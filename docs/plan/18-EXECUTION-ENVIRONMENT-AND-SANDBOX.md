# Agent 执行环境与沙箱

## 决策

小美不把沙箱写死为 Docker。Agent 通过统一的 Execution Environment
接触命令、后台进程和工作区；具体后端可以替换。

第一阶段提供：

- `protected_host`：宿主机执行，具备工作区、独立 Python 环境、超时、
  取消和进程树保护，但不宣称操作系统级隔离。
- `docker`：后续实现的本地强隔离后端。

未来可以增加本机原生沙箱和 CubeSandbox 等远程后端，而不修改 Agent
Core、Assignment 或 Tool 协议。

## 边界

进入 Execution Environment：

- PowerShell/Bash；
- 后台进程；
- read/write/edit/glob/grep；
- Skill 携带的 Python、Node 和 Shell 脚本。

继续留在 Agent 宿主机：

- LLM、记忆、身份、关系和 Goal；
- 飞书、钉钉等 Channel；
- Embodiment 和本机共享 AI 服务；
- Office COM、系统通知和 Desktop IPC；
- 明确依赖真实设备或宿主机服务的插件。

沙箱约束行为接触现实世界的边界，不创建另一个 Agent，也不复制 Agent
的持久世界。

## 运行关系

```text
实时对话 Core ─┐
委托 Core ─────┼─ ToolExecutionContext ─ ExecutionEnvironment
自主行为 Core ─┘                         ├─ Command Executor
                                         ├─ Workspace Broker
                                         └─ Process Supervisor
```

同一个 Agent 的多个隔离 Core 继承同一 Execution Environment。它们的
ReAct 临时状态互不影响，执行边界则仍属于这个 Agent。

## Protected Host

`Protected Host` 是当前宿主机执行能力的正式名称：

- 只允许工作区、outputs 和显式授权目录；
- 拒绝系统目录和常见凭证目录；
- Python 使用 Agent workspace 下的独立 `.venv`；
- 阻止灾难性机器级命令；
- 限制输出大小和执行时间；
- 支持 Turn 取消、后台进程查询和进程树终止。

它仍然以当前操作系统用户身份创建进程，因此不是强安全沙箱。界面和
协议不得把它描述成 Docker、容器或系统级隔离。

## Docker 后端约束

Docker 后端以 Agent 为隔离单位，而不是以 Person 或会话为单位：

```text
Agent xiaomei -> xiaomei-sandbox-xiaomei
Agent test    -> xiaomei-sandbox-test
```

固定安全规则：

- 只挂载该 Agent 的 workspace；
- 不挂载 Agent 数据库、配置、身份、记忆、用户主目录和 Docker socket；
- Provider 密钥不自动传入；
- drop capabilities、禁止提权并限制 CPU、内存和 PID；
- Docker 不可用时明确失败，不能静默回退到 Protected Host；
- Agent 停止时停止执行中的进程，持久工作区是否保留由后端管理；
- Assignment 和自主行为使用独立工作目录与 execution id。

第一版不开放任意 bind mount、任意 Docker 参数或宿主机逃逸入口。

## 配置归属

执行环境属于 Agent，配置保存在该 Agent 的 `config.json`：

```json
{
  "execution": {
    "backend": "protected_host",
    "network": "enabled",
    "resources": {
      "cpu": 2,
      "memory_mb": 4096,
      "pids": 256
    },
    "docker": {
      "image": "xiaomei-execution:py311-node20"
    }
  }
}
```

Desktop 通过 Agent Gateway RPC 查看和修改设置，不直接执行 Docker CLI。
远程 Agent 返回自己的执行环境状态，Desktop 不推断其实现。

## 实施阶段

### A. 基础环境

- 建立 ExecutionEnvironment 和每 Agent 的管理器；
- 将现有行为迁入 ProtectedHostEnvironment；
- 抽出 WorkspaceBroker；
- Shell 和 Process 通过 ToolExecutionContext 获得环境；
- 隔离 Core 继承同一 Agent 环境。

### B. Docker

- Docker 可用性、镜像与容器生命周期；
- 命令、后台进程、取消和工作目录映射；
- Agent 间容器隔离；
- workspace 挂载和产物回收；
- 无凭证泄漏和无静默降级测试。

### C. Gateway 与 Desktop

- `execution.environment.get/save/status/test/rebuild`；
- Agent 设置中的“执行环境”页面；
- 展示 Protected Host、Docker 未安装、未启动、运行中和异常状态。

### D. 后续后端

- Windows/Linux/macOS 原生受限进程；
- CubeSandbox、OpenShell 或企业远程执行环境；
- 受控网络出口和按能力分发的临时凭证。
