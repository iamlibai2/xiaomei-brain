# Config 热重载设计

## 目标

`config.json` 修改后，agent 不重启即可感知变化并自动应用。

## 架构

```
base/file_watcher.py  →  FileWatcher（已有）
                          polling mtime，跨平台兼容
                              │
base/config.py        →  ConfigReloader（2026-06-28 新增）
                          │ 基于 FileWatcher
                          │ 变化时重新解析 JSON
                          │ dispatch 给多个 listener
                          │
         ┌────────────────────┼────────────────────┐
         │                    │                    │
   listener A            listener B           listener C
```

### ConfigReloader

```python
from xiaomei_brain.base.config import ConfigReloader

reloader = ConfigReloader("~/.xiaomei-brain/config.json")
reloader.add_listener(my_handler)  # my_handler(raw_config_dict)
reloader.start()
```

- `add_listener(fn)` — 注册回调，config 变化时收到完整 raw JSON dict
- `start()` / `stop()` — 启动/停止后台监听线程
- poll_interval: 5 秒
- 内置 debounce: 500ms

## 消费者实现状态

| 消费者 | 状态 | 说明 |
|--------|------|------|
| **MCP Server** | ✅ 已实现 | `mcp/client.py:_on_config_changed` — 调用 `bootstrap_mcp_servers()` 增量注册新工具 |
| **Plugin** | ❌ 待实现 | 需 `PluginRegistry.reload(config)` + 工具 diff（unload 旧、注册新） |
| **Models** | ❌ 待实现 | 需 LLM client 重建 + 上下文连续性处理 |
| **Agent** | ❌ 待实现 | 需 `AgentManager` 支持动态创建/销毁 agent 实例 |

## 待实现详细

### 1. Plugin 热重载

**当前**：`boot_plugins(agent_id)` 在 `init_agent()` 时调用一次，返回 `PluginRegistry`。

**要做**：
- `PluginRegistry.reload(raw_config)` — 对比新旧 plugin 列表
- `PluginRegistry.get_removed_tools()` — 返回需要卸载的工具名列表
- `PluginRegistry.get_new_tools()` — 返回需要注册的工具（已有）
- 在 `ConfigReloader` 的 listener 中：
  ```python
  def _on_plugin_config_changed(data):
      old_tools = set(registry.list_tools())
      registry.reload(data)
      new_tools = set(registry.list_tools())
      # unload removed, register new
  ```

### 2. Models 热切换

**当前**：LLM client 在 `init_agent()` 时创建，固定 provider/model。

**要做**：
- LLM client 支持 `reconfigure(provider, model)`
- 对话上下文保持不变（同一 session）
- `/model` 命令已支持手动切换，热重载就是让 `config.json` 中 models 段的变化自动触发同样的逻辑

### 3. Agent 热创建

**当前**：agent 在 `AgentManager.get() + init_agent()` 时创建。

**要做**：
- `AgentManager` 支持动态添加 agent
- 新 agent 的 lifecycle（Living 状态机）需要独立启动
- 可能需要 admin 后台主动触发，而非仅靠 config.json 变化自动创建（agent 的启动是重操作）

## 相关文件

- `src/xiaomei_brain/base/file_watcher.py` — FileWatcher（已有）
- `src/xiaomei_brain/base/config.py` — ConfigReloader（新增）
- `src/xiaomei_brain/mcp/client.py` — MCP listener
- `src/xiaomei_brain/agent/agent_manager.py:970-973` — ConfigReloader 启动点
- `src/xiaomei_brain/consciousness/living_commands.py` — `/mcp reload` 命令

## 变更记录

- 2026-06-28: 初始实现。ConfigReloader + MCP listener。
