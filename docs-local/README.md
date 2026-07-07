# Xiaomei Brain 文档

> 欢迎来到 xiaomei-brain 的技术文档！一个仿人脑架构的多 Agent AI 框架。

---

## 📖 文档目录

### 🚀 快速开始

| 文档 | 说明 |
|------|------|
| [快速入门](./getting-started/quickstart.md) | 5 分钟从零开始你的第一个 AI Agent |
| [安装指南](./getting-started/installation.md) | pip / Docker / 开发模式安装详解 |

### 🏗️ 架构详解

| 文档 | 说明 |
|------|------|
| [架构总览](./architecture/overview.md) | 系统架构、数据流、关键设计决策 |
| [意识层](./architecture/consciousness.md) | 4 层心跳、SelfImage、意图系统、梦境 |
| [记忆层](./architecture/memory.md) | 6 种记忆系统、DAG 摘要、语义检索 |
| [驱动层](./architecture/drive.md) | 情绪、激素、欲望、激励系统 |
| [目的层](./architecture/purpose.md) | 3 级目标层次、意图理解 |
| [元认知层](./architecture/metacognition.md) | InnerVoice、PACE、能力追踪 |
| [工作空间层](./architecture/workspace.md) | 显著性竞争、上下文组装 |

### 🛠️ 开发者指南

| 文档 | 说明 |
|------|------|
| [创建和定制 Agent](./guides/create-agent.md) | 配置、Identity 文件、性格模板 |
| [渠道接入指南](./guides/channel-integration.md) | 接入新消息平台（飞书/钉钉/自定义） |
| [插件开发指南](./guides/plugin-development.md) | 工具/渠道/Provider 插件开发 |
| [工具开发指南](./guides/tool-development.md) | 内置工具和自定义工具开发 |

### 📚 参考手册

| 文档 | 说明 |
|------|------|
| [CLI 命令参考](./reference/cli.md) | 全部命令行和运行时命令 |
| [配置参考](./reference/configuration.md) | config.json + config.yaml 完整说明 |
| [API 参考](./reference/api.md) | 核心 Python API |

### 🤝 贡献

| 文档 | 说明 |
|------|------|
| [贡献指南](../CONTRIBUTING.md) | 环境准备、开发流程、PR 规范 |

---

## 项目文件结构

```
xiaomei-brain/
├── src/xiaomei_brain/
│   ├── agent/           # Agent 核心：ReAct 循环、工具调用
│   ├── memory/          # 记忆系统：存储、摘要、召回
│   ├── consciousness/   # 意识层：心跳、梦境、意图
│   │   └── workspace/   # 工作空间：显著性评分、上下文组装
│   ├── drive/           # 驱动层：情绪、激素、欲望
│   ├── purpose/         # 目的层：目标管理、意图理解
│   ├── metacognition/   # 元认知：InnerVoice、PACE
│   ├── gateway/         # 网关：消息路由、连接管理
│   ├── cli/             # CLI 命令
│   ├── llm/             # LLM 客户端
│   ├── tools/           # 工具系统（内置 + Provider）
│   │   ├── builtin/     # 内置工具
│   │   └── provider/    # 第三方 API 工具
│   ├── plugin/          # 插件加载系统
│   ├── plugins/         # 插件实现
│   │   ├── channels/    # 渠道插件（飞书/钉钉/CLI/P2P）
│   │   ├── tools/       # 工具插件
│   │   └── providers/   # Provider 插件
│   ├── config/          # 配置定义
│   ├── body/            # 具身层
│   ├── learn/           # 学习系统
│   ├── schedule/        # 定时任务
│   ├── tui/ / tui_v2/   # 终端 UI
│   ├── prompts/         # 提示词模板
│   ├── base/            # 基础设施
│   └── contacts/        # 联系人管理
├── tests/               # 测试
├── examples/            # 示例代码
├── docs/                # 本文档
├── pyproject.toml       # 项目配置
├── Dockerfile           # Docker 构建
└── README.md            # 项目首页
```

---

## 快速链接

- [GitHub 仓库](https://github.com/iamlibai2/xiaomei-brain)
- [Issue 反馈](https://github.com/iamlibai2/xiaomei-brain/issues)
- [开源许可证 MIT](../LICENSE)
