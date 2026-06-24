# 配置参考

> xiaomei-brain 的所有配置项。

---

## 全局配置

`~/.xiaomei-brain/config.json`：

```json
{
  "agents": {
    "xiaomei": {
      "identity": "~/.xiaomei-brain/xiaomei/identity.md",
      "drive_config": "~/.xiaomei-brain/xiaomei/drive_config.yaml",
      "perception": "~/.xiaomei-brain/xiaomei/perception.md"
    }
  },
  "llm": {
    "providers": [
      {
        "name": "zhipu",
        "api_key": "xxx",
        "api_base": "https://open.bigmodel.cn/api/paas/v4",
        "models": ["GLM-5.1", "GLM-4-Flash"]
      },
      {
        "name": "deepseek",
        "api_key": "xxx",
        "api_base": "https://api.deepseek.com",
        "models": ["deepseek-chat"]
      }
    ]
  },
  "embedding": {
    "model": "BAAI/bge-m3",
    "dimension": 1024,
    "device": "cpu"
  },
  "plugins": {
    "tools": {},
    "channels": {},
    "providers": {}
  }
}
```

## Agent 配置

### identity.md

`~/.xiaomei-brain/<agent_id>/identity.md` — 身份文件，修改即时生效。

### drive_config.yaml

`~/.xiaomei-brain/<agent_id>/drive_config.yaml` — Drive 参数配置。

### perception.md

`~/.xiaomei-brain/<agent_id>/perception.md` — 社交感知规则。

## Living 配置

`~/.xiaomei-brain/<agent_id>/living_config.yaml`：

```yaml
# 心跳间隔（秒）
heartbeat:
  l0_skeleton: 1
  l1_anomaly: 60
  l2_fueling: dynamic
  l3_dream: 300

# 对话配置
conversation:
  max_context_messages: 50
  dag_leaf_size: 8
  batch_extract_interval: 10

# 记忆配置
memory:
  recall_top_k: 8
  strength_decay_per_tick: 0.001
  extinction_threshold: 0.01
```
