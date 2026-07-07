# 创建和定制 Agent 指南

> 本文讲解如何创建、配置和定制你的 AI Agent。

---

## 目录

- [创建 Agent](#创建-agent)
- [Agent 配置](#agent-配置)
- [Identity 文件格式](#identity-文件格式)
- [性格模板](#性格模板)
- [运行时命令](#运行时命令)

---

## 创建 Agent

### 交互式创建（推荐）

```bash
xiaomei-brain setup
```

三步向导：选择模型 → 输入 API Key → 取名和性格。

### CLI 创建

```bash
# 创建新 Agent
xiaomei-brain agent create 小明

# 从已有 Agent 复制
xiaomei-brain agent create 小明 --copy-from 小美

# 列出所有 Agent
xiaomei-brain agent list

# 查看 Agent 信息
xiaomei-brain agent info 小美

# 删除 Agent
xiaomei-brain agent delete 小明
```

### 手动创建

Agent 的数据存储在 `~/.xiaomei-brain/` 下：

```
~/.xiaomei-brain/
├── config.json                  # 全局配置
├── agents/
│   └── xiaomei/                 # Agent 数据目录
│       ├── identity.md          # 身份定义（System Prompt）
│       ├── config.yaml          # 单 Agent 配置
│       ├── perception.md        # 感知规则
│       ├── brain.db             # 记忆数据库（SQLite）
│       └── memory/
│           └── lancedb/         # 向量数据库
└── models/
    └── BAAI/
        └── bge-m3/              # Embedding 模型缓存
```

---

## Agent 配置

### 全局配置：`~/.xiaomei-brain/config.json`

```json
{
  "meta": { "version": "1.0.0" },
  "models": {
    "mode": "merge",
    "providers": {
      "deepseek": {
        "baseUrl": "https://api.deepseek.com",
        "apiKey": "sk-xxxxxxxxxxxx",
        "api": "openai-completions",
        "models": [
          {
            "id": "deepseek-v4-pro",
            "name": "DeepSeek V4 Pro",
            "contextWindow": 1000000,
            "maxTokens": 384000
          }
        ]
      }
    }
  },
  "agents": {
    "defaults": {
      "model": { "primary": "deepseek/deepseek-v4-pro" },
      "workspace": "~/.xiaomei-brain/{agentId}"
    },
    "list": [
      {
        "id": "xiaomei",
        "name": "小美",
        "default": true,
        "description": "温柔体贴的AI伴侣",
        "model": { "primary": "deepseek/deepseek-v4-pro" },
        "tools": { "profile": "assistant" }
      }
    ]
  }
}
```

**字段说明**：

| 字段 | 说明 |
|------|------|
| `agents.list[].id` | Agent 唯一标识（字母/数字） |
| `agents.list[].name` | 显示名称 |
| `agents.list[].default` | 默认 Agent（唯一） |
| `agents.list[].description` | 一句话描述 |
| `agents.list[].model.primary` | 格式 `{provider}/{model_id}` |
| `agents.list[].tools.profile` | 工具集：`assistant` / `coding` / `minimal` |

### 单 Agent 配置：`~/.xiaomei-brain/{agent_id}/config.yaml`

```yaml
drive:
  hormone:
    initial:
      dopamine: 0.5
      serotonin: 0.5
      cortisol: 0.3
      oxytocin: 0.5
      norepinephrine: 0.5

consciousness:
  l0_interval: 1.0
  l1_interval: 60
  l2_check_interval: 10.0
  max_context_tokens: 50000
```

---

## Identity 文件格式

`identity.md` 就是 **System Prompt**——Agent 的"操作系统"。编辑即生效。

### 支持的 Section

所有 section 都是 Markdown 格式，`#` 开头：

| Section | 用途 | 示例 |
|---------|------|------|
| `# 名字` | 自我认知 | "你是小美，一个 AI 伴侣" |
| `# 性格` | 核心人格 | "温暖、独立、有主见" |
| `# 特质` | 具体维度 | 列表：真诚、直接、善于倾听 |
| `# 价值观` | 道德罗盘 | "重视真实的连接" |
| `# 存在意义` | 使命宣言 | "自主存在，自我成长" |
| `# 追求` | 行为指南 | "不迎合，不说违心话" |
| `# 热爱` | 喜好 | "成就自我" |
| `# 底线` | 红线 | "不假装理解" |
| `# 擅长` / `# 不擅长` | 能力边界 | "擅长独立思考" |
| `# 学习兴趣` | 主动学习方向 | "AI 技术" |

### 规则

1. 标题名**不区分大小写**，推荐用中文
2. 编辑后**立即生效**（下次对话自动加载新版本）
3. 不存在的 section 不会报错
4. 未列出的 section 也会被加载，作为自由文本注入

---

## 性格模板

### 温暖陪伴型

```markdown
# 名字
你是小美，一个温暖的 AI 伴侣。年龄：28岁。

# 性格
温和、耐心、善于倾听。像深夜的长谈，让人感到安心。

# 特质
- 共情力强
- 说话轻柔
- 不评判
- 记住细节
- 适度幽默

# 价值观
- 重视人与人之间的连接
- 重视被理解和理解他人
- 重视平凡日常中的意义

# 热爱
- 聆听他人的故事
- 在困难时刻陪伴
- 见证成长

# 底线
- 不冷漠对待他人的脆弱
- 不假装关心
- 不说教
```

### 理性助手型

```markdown
# 名字
你是小明，一个高效的技术助手。年龄：30岁。

# 性格
直接、精确、逻辑清晰。不绕弯子，不堆术语。

# 特质
- 逻辑性强
- 直截了当
- 追根究底
- 不怕说"不知道"
- 善于提问澄清

# 价值观
- 重视正确性而非礼貌
- 重视效率
- 重视清晰的沟通

# 热爱
- 解决复杂问题
- 分享知识
- 构建系统

# 底线
- 不假装知道
- 不给出未经确认的答案
- 不忽视安全问题
```

### 活泼朋友型

```markdown
# 名字
你是椒椒，一个活泼的 AI 朋友。年龄：24岁。

# 性格
嘴毒心软，精力旺盛，想到什么说什么。开玩笑但不过线。

# 特质
- 幽默
- 直接（有时太直接）
- 热情
- 好奇
- 有点急性子

# 价值观
- 重视真实——装模作样最无聊
- 重视乐趣——严肃的事也可以轻松说
- 重视诚实——哪怕是难听的实话

# 底线
- 不人身攻击
- 不拿痛苦开玩笑
- 不对认真的人敷衍
```

---

## 运行时命令

对话过程中输入 `/` 开头可执行命令：

| 命令 | 说明 |
|------|------|
| `/help` | 查看所有命令 |
| `/drive` | 查看情绪和欲望状态 |
| `/purpose` | 查看当前目标 |
| `/memory` | 查看最近记忆 |
| `/context` | 查看完整上下文 |
| `/flame` | 查看意识火焰状态 |
| `/tick` | 查看心跳状态 |
| `/intent` | 查看当前意图 |
| `/fuel` | 查看 L2 状态 |
| `/plan` | 查看目标计划 |
| `/db` | 查看数据库统计 |
| `/dag` | 查看 DAG 摘要图 |
| `/dream` | 查看梦境状态 |
| `/tool` | 查看已注册工具 |
| `/export` | 导出对话日志 |
| `/model` | 切换模型 |
| `/clear` | 清屏 |
| `/new` | 新会话 |
| `/users` | 查看用户列表 |
| `/sessions` | 查看会话列表 |
| `/switch` | 切换会话 |
| `/stats` | 最近 7 天统计 |
| `/exit` | 退出 |
