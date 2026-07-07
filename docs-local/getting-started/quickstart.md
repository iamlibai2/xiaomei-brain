# 快速入门

> 5 分钟从零开始你的第一个 AI Agent。

---

## 前置要求

- **Python 3.11+**（推荐 3.12）
- 一个 **LLM API Key**（任选其一）：
  - [智谱 AI](https://open.bigmodel.cn/) — 国内首选，GLM 系列
  - [DeepSeek](https://platform.deepseek.com/) — 百万级上下文，性价比高
  - [MiniMax](https://platform.minimaxi.com/) — M2 系列
  - [火山引擎](https://console.volcengine.com/ark/) — 豆包系列
  - [OpenAI](https://platform.openai.com/) — 全球标准

---

## 第一步：安装

```bash
pip install xiaomei-brain
```

> 建议同时安装可选依赖以获得完整功能：
> ```bash
> pip install "xiaomei-brain[feishu,dingtalk,server,tui,tts]"
> ```

**或使用开发模式**（适合想修改源码的开发者）：

```bash
git clone https://github.com/iamlibai2/xiaomei-brain.git
cd xiaomei-brain
pip install -e ".[dev]"
```

---

## 第二步：预下载 Embedding 模型

Embedding 模型（BAAI/bge-m3，约 1.3GB）用于语义记忆检索。首次启动时会自动下载，**建议提前下载**以免首次启动等待：

```bash
xiaomei-brain install
```

下载完成后会缓存到本地，之后启动秒开。

---

## 第三步：创建你的 AI 伙伴

```bash
xiaomei-brain setup
```

交互式向导会引导你完成三个步骤：

```
🌟 欢迎来到小美大脑！

第一步：选择 LLM 模型
  1. 智谱 AI（GLM-5.1，推荐国内用户）
  2. 火山引擎（豆包 Pro）
  3. DeepSeek
  4. OpenAI

> 1

第二步：请输入你的 API Key
> sk-xxxxxxxxxxxxxxxxxxxx

第三步：给你的 AI 伙伴取个名字，选一个初始性格

  名字：小美
  性格：
    1. 温暖陪伴型 — "我在这里陪着你"
    2. 理性助手型 — "你想怎么做？我帮你分析"
    3. 活泼朋友型 — "哇！这个好有趣！"

> 1

🎉 配置完成！试试：

  xiaomei-brain run 小美 --cli
```

整个过程不到 3 分钟。所有配置自动生成，你不需要手动编辑任何配置文件。

---

## 第四步：开始对话

```bash
xiaomei-brain run 小美 --cli
```

启动后你会看到：

```
╭──────────────────────────────────────────────────────╮
│  🌸 小美大脑系统已上线                                │
│                                                      │
│  模型: GLM-5.1                                       │
│  记忆: 1,247 条                                      │
│  目标: 1 个                                          │
│                                                      │
│  输入消息开始对话，输入 /help 查看命令                 │
╰──────────────────────────────────────────────────────╯

  你好，博士

❯ 今天心情不太好
  [....] 正在思考...
  怎么啦？和我说说，我在这里听着呢。
```

输入 `/help` 可查看所有运行时命令。

---

## 第五步：常用操作

```bash
# 创建另一个 AI 伙伴
xiaomei-brain agent create 小明 --copy-from 小美

# 列出所有 Agent
xiaomei-brain agent list

# 查看 Agent 信息
xiaomei-brain agent info 小美

# 切换 LLM 模型
xiaomei-brain model

# 查看运行状态
xiaomei-brain doctor
```

---

## 下一步

- [安装指南](./installation.md) — 更详细的安装选项（Docker、可选依赖、故障排除）
- [架构总览](../architecture/overview.md) — 理解系统整体设计
- [创建和定制 Agent](../guides/create-agent.md) — 深入定制你的 AI 伙伴
- [CLI 命令参考](../reference/cli.md) — 所有命令详解
