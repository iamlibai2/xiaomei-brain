# 快速入门

> 5 分钟，从零到第一次对话。

---

## 前置要求

- Python 3.11+
- 一个 LLM API Key（以下任选）：
  - [智谱 AI](https://open.bigmodel.cn/) — 国内首选，GLM 系列
  - [DeepSeek](https://platform.deepseek.com/) — 开源标杆
  - [OpenAI](https://platform.openai.com/) — 全球领先
  - MiniMax / 豆包 / 任意 OpenAI 兼容 API

## 安装

```bash
pip install xiaomei-brain
```

> **建议安装后立即下载 Embedding 模型**，免去首次启动等待：
> ```bash
> xiaomei-brain install
> ```

或开发模式：

```bash
git clone https://github.com/iamlibai2/xiaomei-brain.git
cd xiaomei-brain && pip install -e .
```

## 创建你的第一个 Agent

```bash
xiaomei-brain setup
```

卡片式向导会让你：

1. **取名字** — 给你的 AI 伙伴起名（如"小美"）
2. **选性格** — 温柔、幽默、冷静、热情...或自定义
3. **配置模型** — 选择 Provider + 输入 API Key
4. **确认信息** — 检查无误后完成

不到 3 分钟。

## 开始对话

```bash
xiaomei-brain run <名字> --cli
```

你会看到：

```
╭──────────────────────────────────────────────────────╮
│  🌸 小美大脑系统已上线                              │
│                                                      │
│  模型: GLM-5.1                                       │
│  记忆: 0 条                                          │
│  目标: 待设定                                        │
│                                                      │
│  输入消息开始对话，输入 /help 查看命令                 │
╰──────────────────────────────────────────────────────╯

  👤 你好，小美

❯ 今天心情不太好
  [....] 正在思考...

  🌸 怎么啦？和我说说，我在这里听着呢。
```

## 常用命令

| 命令 | 说明 |
|------|------|
| `/memory` | 查看最近的记忆 |
| `/drive` | 查看情绪和欲望状态 |
| `/purpose` | 查看当前目标 |
| `/stats` | 最近 7 天统计 |
| `/help` | 查看所有命令 |
| `/exit` | 退出对话 |

## 下一步

| 如果你... | 去看... |
|-----------|---------|
| 想理解系统架构 | [架构总览](../architecture/01-OVERVIEW.md) |
| 想自定义 Agent | [身份配置指南](../guides/01-AGENT-CONFIGURATION.md) |
| 想给 Agent 加新能力 | [工具开发指南](../guides/02-TOOL-DEVELOPMENT.md) |
| 想接入公众号/钉钉 | [渠道接入指南](../guides/03-CHANNEL-DEVELOPMENT.md) |
