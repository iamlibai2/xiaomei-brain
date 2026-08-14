---
name: capability-authoring
description: 将已经验证有效的工作方法、工具组合或业务能力整理成可安装的小美能力包
version: 1.0.0
tags: [capability, package, xmcap, plugin, tool, process, skill]
requires_tools: [write, read, edit, glob, build_capability, present_artifacts]
---

# 能力包开发方法

当人物明确要求把一套已经形成的方法做成能力、导出能力包，或创建可在其他 Agent 上安装的能力时使用。本技能不用于普通的一次性任务。

## 先判断需要什么

- 只有领域知识、步骤建议和判断经验：使用 Skill。
- 需要确定性读写、计算或调用现有领域代码：增加 Tool Plugin。
- 需要约束必须提交的结果，而不限制 Agent 如何工作：增加 Process。
- 需要外部账户、长期客户端或本机运行组件：增加 Runtime Plugin。
- 能力包只是安装和分发载体；Skill、Plugin、Tool、Process、Runtime 仍按各自加载机制工作。
- 不要为了目录整齐复制 Agent Core、数据库、Workspace 或通用领域基础设施。

## 开发位置

所有源码必须位于当前 Agent Workspace，例如：

```text
work/capabilities/customer-analysis/
├─ capability.yaml
├─ capabilities/customer_analysis.yaml
├─ skills/customer-analysis/SKILL.md
├─ plugins/customer_analysis/plugin.yaml
├─ plugins/customer_analysis/adapter.py
├─ plugins/customer_analysis/tool.py
├─ processes/
└─ resources/
```

按实际需要创建文件，不要求每个能力都包含所有目录。不得把能力源码写入小美源码仓库、Agent 数据库目录或 `inputs/`。

## 根清单

`capability.yaml` 至少包含：

```yaml
schema_version: 1
package:
  id: local.customer-analysis
  name: 客户分析
  version: 0.1.0
  description: 分析客户经营数据并形成结论
  publisher: local
  license: Proprietary
capabilities:
  - id: customer_analysis
    name: 客户分析
    summary: 分析客户经营数据并形成结论
permissions:
  filesystem: [workspace_read, workspace_write]
  network: []
  process: []
  secrets: []
requirements:
  xiaomei_brain: ">=0.1.0"
  python: ">=3.11"
  python_packages: []
  node_packages: []
  executables: []
contents:
  capabilities: [capabilities/customer_analysis.yaml]
  skills: [skills/customer-analysis/SKILL.md]
  plugins: []
  processes: []
  resources: []
```

`contents` 必须精确列出所有要进入归档的文件。不要手写 `checksums.json`，构建工具会生成。

每个 `capabilities/*.yaml` 是面向用户的能力清单，至少包含真实的结果和组成部分：

```yaml
id: customer_analysis
name: 客户分析
summary: 分析客户经营数据并形成结论
category: productivity
version: "0.1.0"
source: local.customer-analysis
components:
  - id: skill_customer_analysis
    kind: skill
    target: customer-analysis
    label: 客户分析工作方法
    required: true
outcomes:
  - id: analysis_report
    name: 客户分析报告
    description: 形成可复核的客户经营分析
    components: [skill_customer_analysis]
examples:
  - 分析这份客户数据并给出经营建议
boundaries:
  - 不替代客户数据源本身
```

## 安全与数据边界

- 不得写入 API Key、密码、Token、Cookie、个人身份凭据或客户真实数据。
- 不得打包日志、缓存、数据库、产物、`.git`、`__pycache__` 或虚拟环境。
- 能力配置只声明需要的 Secret 名称，真实值由安装后的 Agent 配置系统保存。
- 可安装能力不能覆盖内置 Capability、Skill 或 Plugin。
- 当前安装器不会自动安装额外 Python、Node、FFmpeg 或其他系统依赖；如能力需要这些依赖，应如实声明并向人物说明当前限制。

## 构建和试用

1. 用 `read` 复核清单和关键代码，不要在明显缺文件时构建。
2. 每个调用工具的 Skill 都应在 frontmatter 中声明 `requires_tools`。文档中的工具名和参数必须以当前 Agent 的真实 Tool Schema 为准，不要依赖记忆猜测。
3. 如果要写工具速查表，“必传参数”必须完整列出真实 Schema 的 `required`；不要把概念名称、返回字段或旧参数名写成调用参数。
4. 调用 `build_capability(source_dir=..., activate=false)` 生成并检查 `.xmcap`。构建会进行工具契约检查，并在失败结果中返回所引用工具的真实参数清单。
5. 调用 `present_artifacts` 交付返回的 `output_path`。
6. 只有人物明确说“加载试试”“立即启用”或同等含义时，才使用 `activate=true`。
7. 立即启用会只影响当前 Agent，并在回复完成后自动重启。重启恢复后再进行真实能力测试。
8. 修改已安装的同 ID 能力时必须提升版本号；同一 ID 和版本不能对应不同内容。

构建失败时根据错误修改能力源码后再试，不要绕过检查器，也不要直接修改安装仓库。
