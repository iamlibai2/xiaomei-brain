# CLI 命令参考

> 所有 `xiaomei-brain` 命令行命令的完整参考。

---

## 启动命令

### `xiaomei-brain run <agent_id>`

启动一个 Agent 实例。

```bash
xiaomei-brain run 小美              # 自动模式（检测 TUI/CLI）
xiaomei-brain run 小美 --cli        # 强制 CLI 模式
xiaomei-brain run 小美 --tui        # 强制 TUI 模式（开发中）
xiaomei-brain run 小美 --no-consciousness  # 无意识层（纯 ReAct）
xiaomei-brain run 小美 --port 8080  # 指定 Gateway 端口
```

### `xiaomei-brain tui`

启动 TUI 终端界面（开发中）。

```bash
xiaomei-brain tui                   # 默认 localhost:8765
xiaomei-brain tui --host 0.0.0.0   # 监听所有网络接口
xiaomei-brain tui --port 9000      # 指定端口
```

### `xiaomei-brain setup`

交互式初始化向导——创建第一个 Agent。

```bash
xiaomei-brain setup                 # 三步向导：模型 → API Key → 性格
```

---

## Agent 管理

### `xiaomei-brain agent list`

列出所有已创建的 Agent。

```bash
xiaomei-brain agent list
```

输出：
```
已注册的 Agent：
  - 小美 (xiaomei) [默认] — 温柔体贴的AI伴侣
  - 小明 (xiaoming) — 高效的技术助手
```

### `xiaomei-brain agent info <name>`

查看 Agent 详细信息。

```bash
xiaomei-brain agent info 小美
```

输出包含：名称、ID、模型、工具集、描述、数据库统计。

### `xiaomei-brain agent create <name>`

创建新 Agent。

```bash
xiaomei-brain agent create 小明              # 全新创建
xiaomei-brain agent create 小明 --copy-from 小美  # 从已有 Agent 复制配置
```

### `xiaomei-brain agent delete <name>`

删除 Agent（确认提示）。

```bash
xiaomei-brain agent delete 小明          # 交互式确认
xiaomei-brain agent delete 小明 --force  # 直接删除
```

---

## 配置管理

### `xiaomei-brain config get <path>`

查看配置项。

```bash
xiaomei-brain config get agents.list          # 查看 Agent 列表
xiaomei-brain config get models.providers     # 查看所有 Provider
```

### `xiaomei-brain config set <path> <value>`

修改配置项。

```bash
xiaomei-brain config set agents.list[0].name 小美酱
```

### `xiaomei-brain config validate`

验证配置文件格式和完整性。

```bash
xiaomei-brain config validate
```

### `xiaomei-brain config file`

打开配置文件所在目录。

```bash
xiaomei-brain config file
```

---

## 模型管理

### `xiaomei-brain model`

交互式模型管理。

```bash
xiaomei-brain model                    # 打开交互式菜单
```

支持：添加/切换 Provider、修改 API Key、选择模型。

### `xiaomei-brain install`

预下载 Embedding 模型（BAAI/bge-m3）。

```bash
xiaomei-brain install                  # 下载约 1.3GB
```

---

## 渠道管理

### `xiaomei-brain channel add`

交互式添加渠道。

```bash
xiaomei-brain channel add              # 选择渠道类型 → 输入凭证
```

### `xiaomei-brain channel list`

列出已配置的渠道。

```bash
xiaomei-brain channel list
```

### `xiaomei-brain channel remove <channel_name>`

移除渠道配置。

```bash
xiaomei-brain channel remove feishu
```

---

## 插件管理

### `xiaomei-brain plugins list`

列出所有可用插件。

```bash
xiaomei-brain plugins list
```

### `xiaomei-brain plugins enable <name>`

启用插件。

```bash
xiaomei-brain plugins enable weather
```

### `xiaomei-brain plugins disable <name>`

禁用插件。

```bash
xiaomei-brain plugins disable weather
```

---

## 调试与诊断

### `xiaomei-brain doctor`

系统诊断。

```bash
xiaomei-brain doctor                   # 检查配置、依赖、文件权限
xiaomei-brain doctor --fix             # 尝试自动修复
xiaomei-brain doctor --verbose         # 详细信息
```

### `xiaomei-brain logs <agent_id>`

查看 Agent 日志。

```bash
xiaomei-brain logs 小美                # 查看最近日志
xiaomei-brain logs 小美 --follow       # 持续跟踪（类似 tail -f）
xiaomei-brain logs 小美 --lines 50     # 指定行数
```

---

## 运行时命令

Agent 运行中，在对话界面输入 `/` 开头的命令：

| 命令 | 说明 |
|------|------|
| `/help` | 查看所有命令 |
| `/exit` | 退出对话 |
| `/clear` | 清屏 |
| `/new` | 开始新会话 |
| `/switch` | 切换会话 |
| `/sessions` | 查看会话列表 |
| `/users` | 查看用户列表 |
| `/model` | 切换当前模型 |
| `/drive` | 查看情绪和欲望 |
| `/purpose` | 查看当前目标 |
| `/plan` | 查看目标计划 |
| `/memory` | 查看最近记忆 |
| `/context` | 查看完整上下文 |
| `/flame` | 查看意识状态 |
| `/tick` | 查看心跳 |
| `/intent` | 查看当前意图 |
| `/fuel` | 查看 L2 状态 |
| `/dag` | 查看 DAG 摘要 |
| `/dream` | 查看梦境状态 |
| `/db` | 查看数据库统计 |
| `/tool` | 查看已注册工具 |
| `/export` | 导出对话记录 |
| `/stats` | 最近 7 天统计 |
