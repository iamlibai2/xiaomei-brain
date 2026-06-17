# Xiaomei Brain

A multi-agent AI framework inspired by human brain architecture. Agents have memory, consciousness, drive, purpose, and metacognition — not just ReAct loops.

## Architecture

```
Consciousness (flame skeleton + LLM fuel)
    └─ SelfImage (identity, body, mind, memory, intent)
        ├─ Drive (emotion, hormone, motivation, desire)
        ├─ Purpose (meaning → phase goals → executable goals)
        ├─ Metacognition (inner voice, social perception, self-review)
        └─ Memory
            ├─ ConversationDB (raw logs, never deleted)
            ├─ DAG Summary (hierarchical compression)
            ├─ Long-Term (vector search + strength decay)
            ├─ Experience (context → decision → outcome → lesson)
            ├─ Procedure (learned workflows)
            └─ Pattern (statistical behavior patterns)
```

## Quick Start

```bash
# Prerequisites
python3 -m venv venv
source venv/bin/activate
pip install -e .
```

# CLI interactive mode (full consciousness)
PYTHONPATH=src python3 examples/run_conscious_living.py --name xiaomei

# Diagnostics
PYTHONPATH=src python3 -m xiaomei_brain.doctor
```

## LLM Providers

Supports multiple providers configured via `~/.xiaomei-brain/config.json`:

- **Zhipu** (GLM series)
- **MiniMax**
- **Volcengine** (Doubao)
- OpenAI-compatible APIs

## Features

### Consciousness System
- Flame skeleton: code maintains structure, LLM adds fuel
- 4-layer heartbeat: L0 skeleton maintenance (1s) → L1 anomaly detection (1min) → L2 dynamic fueling (LLM) → L3 deep burn (dream)
- 13 intent types: WAIT, GREET, REMIND, RECALL, REFLECT, ACT, DREAM, CARE, LEARN, EXPRESS, PROGRESS, WORK, ALARM, TALK
- SelfImage: unified identity body/mind/memory/intent with context injection

### Drive System (Edge)
- 4 subsystems: Emotion (minute decay), Hormone (hour decay), Motivation (RPE), Desire (tension)
- Desire-driven behaviors: greet, learn, progress goals, express ideas
- Cross-session persistence

### Purpose System
- 3-level goal hierarchy: Meaning → Phase Goals → Executable Goals
- LLM-assisted goal decomposition and intent understanding
- Priority calculation with deadline and reinforcement weighting

### Memory System
- Raw conversation logs with FTS5 search
- Hierarchical DAG summarization (8 messages → leaf → higher)
- Vector semantic search via LanceDB + BAAI/bge-m3 embeddings
- Strength decay model (5 levels: active → extinct)
- Multi-user isolation with shared global knowledge
- Context → decision → outcome → lesson experience tuples

### Metacognition
- Inner voice: self-reflection every 2+ turns
- Social perception: detects user mood changes, maps to Drive signals
- Self-review: budget-controlled step checking (rule-based + lightweight LLM)

### Plugin System
- Channel adapters: CLI, Feishu/Lark, DingTalk, WebSocket, P2P
- One-line plugin bootstrap: `boot_plugins(agent_id)`
- Gateway router: rule-based message routing, LLM never sees routing logic

### Tools
- Shell execution, file read/write/edit
- Web search, web fetch
- TTS, image generation, music
- Memory query/management
- Custom tool registration via decorators

## CLI Commands

Available at runtime: `/flame`, `/tick`, `/intent`, `/fuel`, `/drive`, `/purpose`, `/plan`, `/db`, `/memory`, `/context`, `/dag`, `/dream`, `/tool`, `/export`, `/model`, `/clear`, `/new`, `/users`, `/sessions`, `/switch`.

## Configuration

- `~/.xiaomei-brain/config.json` — agent registry, LLM providers, tool config
- `~/.xiaomei-brain/{agent_id}/identity.md` — system prompt (edit to take effect immediately)
- `~/.xiaomei-brain/{agent_id}/perception.md` — perception rules
- `~/.xiaomei-brain/{agent_id}/drive_config.yaml` — drive parameters

## Testing

```bash
# Memory system
PYTHONPATH=src python3 examples/test_xiaomei_new.py

# Consciousness integration
PYTHONPATH=src python3 examples/test_conscious_living.py

# WebSocket server
PYTHONPATH=src python3 examples/ws_server.py
```

## License

MIT — see [LICENSE](LICENSE)
