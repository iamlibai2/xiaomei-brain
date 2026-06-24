# 配置参考

> xiaomei-brain 的所有配置项。

---

## 全局配置

`~/.xiaomei-brain/config.json`（OpenClaw 兼容格式）：

```json
{
  "models": {
    "mode": "merge",
    "providers": {
      "zhipu": {
        "baseUrl": "https://open.bigmodel.cn/api/paas/v4/",
        "apiKey": "YOUR_API_KEY",
        "api": "openai-completions",
        "models": [
          { "id": "glm-5.1", "name": "GLM-5.1", "contextWindow": 160000, "maxTokens": 4096 }
        ]
      },
      "deepseek": {
        "baseUrl": "https://api.deepseek.com",
        "apiKey": "YOUR_API_KEY",
        "api": "openai-completions",
        "models": [
          { "id": "deepseek-v4-flash", "name": "DeepSeek V4 Flash", "contextWindow": 1000000, "maxTokens": 384000 }
        ]
      }
    }
  },
  "agents": {
    "defaults": {
      "model": { "primary": "zhipu/glm-5.1" },
      "workspace": "~/.xiaomei-brain/{agentId}"
    },
    "list": [
      {
        "id": "xiaomei",
        "default": true,
        "name": "小美",
        "model": { "primary": "zhipu/glm-5.1" },
        "tools": { "profile": "assistant" }
      }
    ]
  },
  "channels": {},
  "bindings": [
    { "agentId": "xiaomei", "match": { "channel": "cli" } }
  ],
  "xiaomei_brain": {
    "agent": {
      "max_steps": 10,
      "context": { "max_tokens": 4000, "recent_turns": 6 }
    },
    "memory": {
      "similarity_threshold": 0.3,
      "embedding_model": "BAAI/bge-m3"
    },
    "logging": { "level": "INFO" }
  }
}
```

参考 [config.example.json](../../config.example.json) 了解完整可配置项。

## Agent 级配置

每个 Agent 的专属文件位于 `~/.xiaomei-brain/{agent_id}/`：

### consciousness/identity.md

`~/.xiaomei-brain/<agent_id>/consciousness/identity.md` — 身份文件，系统提示词，修改即时生效。

### drive/drive_config.yaml

`~/.xiaomei-brain/<agent_id>/drive/drive_config.yaml` — Drive 参数（欲望初始值、阈值、情绪衰减率、激素衰减率）。

### consciousness/perception.md

`~/.xiaomei-brain/<agent_id>/consciousness/perception.md` — 社交感知规则。
