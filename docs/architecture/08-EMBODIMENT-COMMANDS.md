# Embodiment Command 协议

## 定位

Embodiment Command 用于让 Agent 控制当前对话来源的身体界面。它属于 Gateway
交互协议，不是 Desktop CLI，也不是任意远程执行协议。

第一版只允许可逆、明确的 Desktop 操作：

- `ui.left_sidebar.set`：打开、关闭或切换左侧栏；
- `ui.right_sidebar.set`：打开、关闭或切换右侧栏；
- `ui.right_sidebar.section.open`：打开右侧栏指定栏目；
- `ui.artifact.open`：在 Desktop 中打开当前会话产物；
- `file.artifact.open_external`：使用系统默认应用打开当前会话产物。

文件内容的生成和修改仍由 Agent 的 Skill 与 Tool 完成。本协议只负责把结果呈现到
具体身体，不传 JavaScript、Shell 或任意文件路径。

## 请求与应答

Agent 通过当前 `turn_id` 找到精确的 WebSocket 返回路由，向该 Desktop 发送：

```json
{
  "type": "embodiment.command.requested",
  "session_id": "session-123",
  "turn_id": "turn-456",
  "payload": {
    "command_id": "32位随机十六进制字符串",
    "embodiment_id": "desktop:device-id",
    "command": "ui.right_sidebar.section.open",
    "arguments": { "section": "memory" }
  }
}
```

Desktop 在本地命令注册表中找到处理器并执行，然后调用
`embodiment.command.respond`：

```json
{
  "command_id": "32位随机十六进制字符串",
  "status": "completed",
  "result": {},
  "error": ""
}
```

`status` 只能是 `completed`、`failed` 或 `rejected`。Agent 最多等待 8 秒；超时后
本次工具调用失败，不会无限阻塞对话。

## 路由和安全边界

- Desktop 注册身体时必须声明 `commands` 能力；
- 命令只沿当前 Turn 的路由发送，不广播到其他 Desktop 或渠道；
- Gateway 同时校验 `command_id`、`session_id` 和 `embodiment_id`；
- Desktop 只执行代码中注册的命令名，未知命令直接拒绝；
- 产物通过 `artifact_id` 定位，Desktop 不接受 Agent 提交的任意本机路径；
- 飞书、钉钉等没有 Desktop 身体的渠道调用该工具时会明确失败。

## 扩展方式

新增界面能力时，优先增加一个稳定、语义明确的命令名和 Desktop 处理器，不为每个
动作增加新 RPC。需要权限审批、长时间执行或跨应用自动化的操作不直接放入此协议，
应另行定义能力和安全边界。
