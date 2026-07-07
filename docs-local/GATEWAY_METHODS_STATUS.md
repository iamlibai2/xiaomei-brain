# OpenClaw Gateway 方法状态

**更新时间**：2026-04-16 (北京时间)

---

## 方法状态概览

| 状态 | 数量 |
|------|------|
| ✅ 已实现 | 9 |
| ⚠️ 部分实现 | 3 |
| ❌ 待实现 | 80+ |

---

## ✅ 已实现 (xiaomei-brain)

这些方法 xiaomei-brain 已有功能，只需适配 OpenClaw 协议格式即可工作。

| 方法 | 说明 | 备注 |
|------|------|------|
| `config.get` | 获取配置 | 已有 ConfigProvider |
| `config.patch` | 部分更新 | 已有 ConfigProvider |
| `config.apply` | 应用完整配置 | 已有 ConfigProvider |
| `agents.list` | Agent 列表 | 已有 AgentManager |
| `agents.get` | 获取 Agent | 已有 AgentManager |
| `chat.send` | 发送聊天 + 流式事件 | 已有 Agent.stream |
| `sessions.list` | 会话列表 | 已有 SessionManager |
| `sessions.get` | 获取会话 | 已有 SessionManager |
| `ping` | 心跳 | 已实现 |

---

## ⚠️ 部分实现

这些方法 xiaomei-brain 有部分功能，但需要完善。

| 方法 | 说明 | 当前状态 |
|------|------|----------|
| `chat.history` | 聊天历史 | 已有会话消息存储，需要适配协议 |
| `tts.*` | TTS 相关 | 已有 TTSProvider，需要暴露为 Gateway 方法 |
| `tools.effective` | 有效工具列表 | 已有工具注册，需要暴露为 Gateway 方法 |

---

## ❌ 待实现 (OpenClaw 有)

这些方法 xiaomei-brain 没有或需要新实现功能。

### P1 - 必须

这些是核心功能，必须实现。

| 方法 | 说明 |
|------|------|
| `health` | 健康检查 |
| `chat.abort` | 中止聊天（需要 Agent 支持中止） |
| `sessions.send` | 发送消息到会话（需要 Channel 发送功能） |
| `sessions.abort` | 中止会话（需要会话中止功能） |

### P2 - 核心

这些是重要的管理功能，建议实现。

| 方法 | 说明 |
|------|------|
| `config.schema` | 获取配置 schema |
| `config.set` | 设置配置值 |
| `agents.create` | 创建 Agent |
| `agents.update` | 更新 Agent |
| `agents.delete` | 删除 Agent |
| `tools.catalog` | 工具目录 |
| `skills.status` | Skills 状态 |
| `channels.status` | Channel 状态 |
| `sessions.subscribe` | 订阅会话变更 |
| `sessions.messages.subscribe` | 订阅消息 |
| `sessions.patch` | 修改会话 |
| `sessions.reset` | 重置会话 |
| `sessions.delete` | 删除会话 |
| `sessions.compact` | 压缩会话 |
| `models.list` | 模型列表 |

### P3 - 可选

这些是扩展功能，可以后续实现。

| 方法 | 说明 |
|------|------|
| `agents.files.list` | Agent 文件列表 |
| `agents.files.get` | 获取 Agent 文件 |
| `agents.files.set` | 设置 Agent 文件 |
| `skills.bins` | Skills 依赖 |
| `skills.install` | 安装 Skill |
| `skills.update` | 更新 Skill |
| `channels.logout` | Channel 登出 |
| `sessions.preview` | 预览会话 |
| `sessions.unsubscribe` | 取消订阅 |
| `sessions.messages.unsubscribe` | 取消订阅消息 |
| `exec.approvals.get` | 获取执行审批 |
| `exec.approvals.set` | 设置执行审批 |
| `exec.approvals.node.get` | 获取节点审批 |
| `exec.approvals.node.set` | 设置节点审批 |
| `exec.approval.request` | 请求执行审批 |
| `exec.approval.waitDecision` | 等待审批决定 |
| `exec.approval.resolve` | 解决执行审批 |
| `tts.status` | TTS 状态 |
| `tts.providers` | TTS 提供商列表 |
| `tts.enable` | 启用 TTS |
| `tts.disable` | 禁用 TTS |
| `tts.convert` | TTS 转换 |
| `tts.setProvider` | 设置 TTS 提供商 |
| `logs.tail` | 日志尾巴 |
| `doctor.memory.status` | 内存状态诊断 |
| `usage.status` | 使用状态 |
| `usage.cost` | 成本统计 |
| `secrets.reload` | 密钥重载 |
| `secrets.resolve` | 密钥解析 |
| `wizard.start` | 启动向导 |
| `wizard.next` | 向导下一步 |
| `wizard.cancel` | 取消向导 |
| `wizard.status` | 向导状态 |
| `talk.config` | 语音配置 |
| `talk.speak` | 语音说话 |
| `talk.mode` | 语音模式 |
| `update.run` | 运行更新 |
| `voicewake.get` | 获取语音唤醒 |
| `voicewake.set` | 设置语音唤醒 |
| `browser.request` | 浏览器请求 |
| `agent.wait` | Agent 等待 |
| `agent.identity.get` | 获取 Agent 身份 |
| `gateway.identity.get` | 获取 Gateway 身份 |
| `system-presence` | 系统存在 |
| `system-event` | 系统事件 |

### 节点相关 (node.*)

| 方法 | 说明 |
|------|------|
| `node.pair.request` | 节点配对请求 |
| `node.pair.list` | 节点配对列表 |
| `node.pair.approve` | 批准节点配对 |
| `node.pair.reject` | 拒绝节点配对 |
| `node.pair.verify` | 验证节点配对 |
| `node.rename` | 重命名节点 |
| `node.list` | 节点列表 |
| `node.describe` | 节点描述 |
| `node.pending.drain` | 节点待处理排出 |
| `node.pending.enqueue` | 节点待处理入队 |
| `node.invoke` | 调用节点 |
| `node.pending.pull` | 节点待处理拉取 |
| `node.pending.ack` | 节点待处理确认 |
| `node.invoke.result` | 节点调用结果 |
| `node.event` | 节点事件 |
| `node.canvas.capability.refresh` | 节点画布能力刷新 |

### 设备相关 (device.*)

| 方法 | 说明 |
|------|------|
| `device.pair.list` | 设备配对列表 |
| `device.pair.approve` | 批准设备配对 |
| `device.pair.reject` | 拒绝设备配对 |
| `device.pair.remove` | 移除设备配对 |
| `device.token.rotate` | 轮换设备令牌 |
| `device.token.revoke` | 撤销设备令牌 |

### 定时任务相关 (cron.*)

| 方法 | 说明 |
|------|------|
| `cron.list` | 定时任务列表 |
| `cron.status` | 定时任务状态 |
| `cron.add` | 添加定时任务 |
| `cron.update` | 更新定时任务 |
| `cron.remove` | 删除定时任务 |
| `cron.run` | 运行定时任务 |
| `cron.runs` | 定时任务运行记录 |

---

## 实现优先级建议

### Phase 1: 协议兼容 (已完成)
- [x] config.get/apply/patch
- [x] agents.list/get
- [x] chat.send
- [x] sessions.list/get
- [x] ping

### Phase 2: P1 必须
- [ ] health
- [ ] chat.abort
- [ ] sessions.send
- [ ] sessions.abort

### Phase 3: P2 核心
- [ ] config.schema/set
- [ ] agents.create/update/delete
- [ ] tools.catalog
- [ ] skills.status
- [ ] channels.status
- [ ] sessions.subscribe/messages.subscribe
- [ ] sessions.patch/reset/delete/compact
- [ ] models.list

### Phase 4: P3 可选
- [ ] 其他所有方法

---

## OpenClaw Gateway 事件列表

xiaomei-brain 还需要支持以下事件推送：

| 事件 | 说明 |
|------|------|
| `connect.challenge` | 连接挑战 |
| `agent` | Agent 事件 |
| `chat` | 聊天事件 (delta/final/error) |
| `session.message` | 会话消息 |
| `session.tool` | 会话工具调用 |
| `sessions.changed` | 会话变更 |
| `presence` | 在线状态 |
| `tick` | 心跳 |
| `talk.mode` | 语音模式 |
| `shutdown` | 关闭 |
| `health` | 健康状态 |
| `heartbeat` | 心跳 |
| `cron` | 定时任务事件 |
| `node.pair.requested` | 节点配对请求 |
| `node.pair.resolved` | 节点配对解决 |
| `node.invoke.request` | 节点调用请求 |
| `device.pair.requested` | 设备配对请求 |
| `device.pair.resolved` | 设备配对解决 |
| `voicewake.changed` | 语音唤醒变更 |
| `exec.approval.requested` | 执行审批请求 |
| `exec.approval.resolved` | 执行审批解决 |
| `update.available` | 有可用更新 |
