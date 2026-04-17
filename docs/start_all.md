# Unified Startup Guide

## Overview

`start_all.py` is the unified entry point for xiaomei-brain that integrates:

- **Gateway** - Manages all communication channels
- **Channels** - Feishu (Lark), DingTalk, WeChat, etc.
- **WebSocket Server** - Real-time API for web clients
- **AgentManager** - Multi-agent support with independent memories

## Usage

```bash
PYTHONPATH=src python3 examples/start_all.py
```

## Configuration

Configuration is loaded from `~/.xiaomei-brain/config.json` (OpenClaw format).

### Key Sections

```json
{
  "channels": {
    "feishu": {
      "enabled": true,
      "accounts": {
        "default": {
          "appId": "cli_...",
          "appSecret": "..."
        },
        "xiaomei": {
          "appId": "cli_...",
          "appSecret": "..."
        }
      }
    }
  },
  "bindings": [
    {
      "agentId": "xiaomei",
      "match": {
        "channel": "feishu",
        "accountId": "xiaomei"
      }
    }
  ],
  "agents": {
    "list": [
      {
        "id": "xiaomei",
        "name": "小美",
        "talent": "你叫小美，是一个温柔体贴的AI伴侣..."
      }
    ]
  }
}
```

## Architecture

```
start_all.py
├── Config.from_json()          # Load configuration
├── AgentManager                # Multi-agent registry
│   ├── xiaomei/             # Agent instance
│   │   ├── talent.md         # System prompt
│   │   ├── memory/           # Vector store
│   │   └── sessions/         # Chat history
│   └── xiaoming/            # Another agent
├── AgentGateway              # Message routing
│   ├── FeishuChannel (account: default)
│   ├── FeishuChannel (account: xiaomei)
│   └── bindings[...]         # Route channel+account -> agent
└── WebSocket Server          # ws://0.0.0.0:8765/ws
```

## Message Flow

1. User sends message on Feishu (account: xiaomei)
2. FeishuChannel receives message, adds `account_id: "xiaomei"` to `InboundMsg.extra`
3. AgentGateway looks up binding: `{"channel": "feishu", "accountId": "xiaomei"}`
4. Routes to agent `xiaomei`
5. Agent processes message and returns response
6. FeishuChannel sends response back to user

## Environment Variables

| Variable | Default | Description |
|----------|----------|-------------|
| `WS_HOST` | `0.0.0.0` | WebSocket host |
| `WS_PORT` | `8765` | WebSocket port |

## Features

### Multi-Agent Support

- Each agent has independent memory, sessions, and talent.md
- Agents can be routed based on channel + account
- WebSocket clients can specify agent_id in `session_start` message

### Multi-Account Support

- Same channel (e.g., Feishu) can have multiple accounts
- Each account can be bound to a different agent
- Useful for different bots on the same platform

### Hot Reload

- Editing `~/.xiaomei-brain/agents/{id}/talent.md` immediately affects that agent's behavior
- No restart required

## Adding New Channels

1. Create a new channel in `src/xiaomei_brain/channels/`
2. Inherit from `Channel` base class
3. Add to `load_channels_from_config()` in `start_all.py`

Example:

```python
from xiaomei_brain.channels.myplatform import MyPlatformChannel

if channels_cfg.get("myplatform", {}).get("enabled", False):
    channel = MyPlatformChannel(...)
    gateway.add_channel(channel)
```

## Troubleshooting

### Channel not starting

- Check `config.json` has `channels.<name>.enabled: true`
- Verify credentials are correct
- Check logs for error messages

### Wrong agent responding

- Verify `bindings` section in config.json
- Check that `accountId` matches the channel account
- Use WebSocket with explicit `agent_id` for testing

### Agent not found

- Ensure agent is defined in `agents.list`
- Check that agent directory exists in `~/.xiaomei-brain/agents/`
