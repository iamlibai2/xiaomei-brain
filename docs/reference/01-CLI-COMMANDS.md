# CLI 命令参考

---

## 安装后命令

### `xiaomei-brain setup`

创建新的 Agent，卡片式向导。

```bash
xiaomei-brain setup
```

### `xiaomei-brain run <agent_id> [--cli]`

启动 Agent 并开始对话。

```bash
# CLI 模式（默认）
xiaomei-brain run 小美 --cli

# 后台模式（无交互）
xiaomei-brain run 小美
```

### `xiaomei-brain model`

管理 LLM 模型配置。

```bash
xiaomei-brain model
```

### `xiaomei-brain list`

列出所有已创建的 Agent。

```bash
xiaomei-brain list
```

### `xiaomei-brain remove <agent_id>`

删除 Agent 及其所有数据。

```bash
xiaomei-brain remove 小美
```

### `xiaomei-brain install`

下载并缓存 Embedding 模型（BAAI/bge-m3）。

```bash
xiaomei-brain install
```

---

## 运行时命令

在对话中通过 `/` 前缀使用。

### 核心命令

| 命令 | 说明 | 示例 |
|------|------|------|
| `/memory` | 查看最近的记忆 | `/memory` |
| `/drive` | 查看情绪和欲望状态 | `/drive` |
| `/purpose` | 查看当前目标 | `/purpose` |
| `/stats` | 最近 7 天统计 | `/stats` |
| `/help` | 查看所有命令 | `/help` |
| `/exit` | 退出对话 | `/exit` |

### 意识层命令

| 命令 | 说明 |
|------|------|
| `/flame` | 查看意识火焰状态 |
| `/tick` | 手动触发一次 tick |
| `/intent` | 查看当前意图 |
| `/fuel` | 查看燃料（token）消耗 |

### 记忆层命令

| 命令 | 说明 |
|------|------|
| `/db` | 查看数据库统计 |
| `/context` | 查看当前上下文 |
| `/dag` | 查看 DAG 摘要结构 |
| `/dream` | 手动触发梦境处理 |

### 操作命令

| 命令 | 说明 |
|------|------|
| `/clear` | 清除当前会话历史 |
| `/new` | 开启新会话 |
| `/users` | 查看所有用户 |
| `/sessions` | 查看所有会话 |
| `/switch` | 切换会话 |
| `/tool` | 查看可用工具 |
| `/export` | 导出对话数据 |
