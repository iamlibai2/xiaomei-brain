# Phase 1:「5 分钟跑起来」Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A new user clones the repo, runs `pip install -e .`, completes `xiaomei-brain setup`, and has a working conversation within 5 minutes, without reading source code.

**Architecture:** Enhance the existing setup wizard (`cli/setup.py`) with model configuration, add startup loading hints to `conscious_living.py` / `run.py`, write core documentation, and add Docker support. All changes are incremental — no restructuring of existing code.

**Tech Stack:** Python 3.11+, Rich (terminal UI), Hatchling (build), Docker (optional)

---

### Task 1: Enhance setup wizard with model configuration step

**Files:**
- Modify: `src/xiaomei_brain/cli/setup.py:471-506`
- Read: `src/xiaomei_brain/cli/_config_template.py` (verify it exists and what's in it)

**Why:** The setup wizard currently creates the agent identity but skips LLM model configuration. Users have no idea they need to configure a model before starting.

- [ ] **Step 1: Check existing config template**

```bash
grep -n "provider\|model\|api_key\|base_url" src/xiaomei_brain/cli/_config_template.py 2>/dev/null || echo "FILE NOT FOUND"
```

Expected: Either the template file exists with model fields, or we need to handle model config differently.

- [ ] **Step 2: Add model config section to setup.py**

In `src/xiaomei_brain/cli/setup.py`, after the `_ask_all()` function ends (line 341), add a model config question function. Insert before the `_read_multiline` function (line 344):

```python
# ── 模型配置 ────────────────────────────────────────────────────

PROVIDERS = {
    "1": {
        "name": "智谱 AI",
        "id": "zhipu",
        "model": "glm-5.1",
        "env_var": "ZHIPU_API_KEY",
        "hint": "获取 API key: https://open.bigmodel.cn/",
    },
    "2": {
        "name": "火山引擎（豆包）",
        "id": "volcengine",
        "model": "doubao-pro-32k",
        "env_var": "VOLCENGINE_API_KEY",
        "hint": "获取 API key: https://console.volcengine.com/ark",
    },
    "3": {
        "name": "DeepSeek",
        "id": "deepseek",
        "model": "deepseek-v4-flash",
        "env_var": "DEEPSEEK_API_KEY",
        "hint": "获取 API key: https://platform.deepseek.com/",
    },
    "4": {
        "name": "OpenAI",
        "id": "openai",
        "model": "gpt-4o-mini",
        "env_var": "OPENAI_API_KEY",
        "hint": "获取 API key: https://platform.openai.com/api-keys",
    },
}


def _ask_model() -> dict[str, str]:
    """交互式配置 LLM 模型和 API key。

    Returns:
        {"provider": "zhipu", "model": "glm-5.1", "api_key": "sk-xxx"}
    """
    _section("模型配置")
    step = len(PROVIDERS)  # 虚拟步骤，不参与进度条
    _step_marker(TOTAL_STEPS - 1)

    console.print(f"  [{C['label']}]选择 LLM 模型[/]")
    console.print()
    for k in PROVIDERS:
        p = PROVIDERS[k]
        console.print(
            f"  [{C['primary']}]{k}.[/] [{C['accent']}]{p['name']}[/] "
            f"[{C['muted']}]({p['model']})[/]"
        )
    console.print()

    while True:
        choice = Prompt.ask(
            f"[{C['primary']}]❯[/] 选择 [1-4]",
            default="1",
            console=console,
        )
        if choice in PROVIDERS:
            break
        console.print(f"  [{C['error']}]请输入 1-4[/]")

    provider = PROVIDERS[choice]
    _step_marker(TOTAL_STEPS)

    console.print()
    console.print(f"  [{C['muted']}]提示: {provider['hint']}[/]")
    console.print()

    while True:
        api_key = Prompt.ask(
            f"[{C['primary']}]❯[/] 请输入 API Key",
            password=True,
            console=console,
        )
        if api_key.strip():
            break
        console.print(f"  [{C['error']}]API Key 不能为空[/]")

    return {
        "provider": provider["id"],
        "model": provider["model"],
        "api_key": api_key.strip(),
    }
```

- [ ] **Step 3: Wire model config into cmd_setup**

In `src/xiaomei_brain/cli/setup.py`, modify `cmd_setup()` (line 471) to call `_ask_model()` after identity answers and pass model config to agent creation.

Replace lines 471-506 of `cmd_setup()`:

```python
def cmd_setup(args: list[str]) -> None:
    """`xiaomei-brain setup` — Her 式创建向导。"""

    _welcome()

    # 交互问答 — 身份
    answers = _ask_all()

    # 确认身份
    if not _confirm(answers):
        console.print(f"\n  [{C['muted']}]已取消。重新运行 xiaomei-brain setup 再次创建。[/]\n")
        sys.exit(0)

    # 交互问答 — 模型
    model_config = _ask_model()

    # ── 创建 ─────────────────────────────────────────────
    from xiaomei_brain.agent.agent_manager import AgentManager
    from xiaomei_brain.consciousness.essence import Essence
    from xiaomei_brain.cli._config_template import CONFIG_YAML_TEMPLATE as DEFAULT_CONFIG_YAML

    name = answers["name"]

    manager = AgentManager()
    if name in [a.id for a in manager.list()]:
        console.print(f"\n  [{C['error']}]Agent '{name}' 已存在。[/]")
        sys.exit(1)

    identity_md = _build_identity(answers)

    # 写入模型配置到 config.json（通过 agent_manager 注册）
    # 先确保 config.json 存在，再写入 agent 条目
    info = manager.create_agent(name, identity_content=identity_md, config_yaml_content=DEFAULT_CONFIG_YAML)
    agent_dir = info["agent_dir"]

    # 写入 agent 特化的模型配置到 config.json
    _write_model_config(name, model_config, manager)

    essence_items = _build_essence(answers)
    brain_db = os.path.join(agent_dir, "memory", "brain.db")
    os.makedirs(os.path.dirname(brain_db), exist_ok=True)
    essence = Essence(brain_db)
    ids = essence.add_batch(essence_items)

    # 完成页 — 显示模型信息
    _finish_with_model(name, agent_dir, len(ids), model_config)
```

- [ ] **Step 4: Add helper functions for model config persistence**

Insert before the `cmd_setup` function (line 471) in `src/xiaomei_brain/cli/setup.py`:

```python
def _write_model_config(name: str, model_config: dict, manager) -> None:
    """将模型配置写入 config.json 中 agent 的特化配置。"""
    import json
    from pathlib import Path

    # 查找 config.json 路径
    config_path = Path(manager.base_dir) / "config.json"
    if not config_path.exists():
        return  # 由 AgentManager 后续初始化时创建

    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, FileNotFoundError):
        config = {}

    # 查找或创建 providers 条目
    if "models" not in config:
        config["models"] = {}
    if "providers" not in config["models"]:
        config["models"]["providers"] = {}

    provider_id = model_config["provider"]
    if provider_id not in config["models"]["providers"]:
        config["models"]["providers"][provider_id] = {
            "api_key": model_config["api_key"],
        }
    config["models"]["providers"][provider_id]["default_model"] = model_config["model"]

    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


def _finish_with_model(name: str, agent_dir: str, essence_count: int, model_config: dict) -> None:
    """完成页面（含模型信息）。"""
    provider_names = {p["id"]: p["name"] for p in PROVIDERS.values()}
    provider_display = provider_names.get(model_config["provider"], model_config["provider"])

    console.clear()
    title = Text(f"你好，我是 {name}", style=f"bold {C['primary']}", justify="center")
    subtitle = Text(f"连接 {provider_display} · {model_config['model']}", style=C["muted"], justify="center")
    start_hint = Text("我已准备好与你对话", style=C["accent"], justify="center")
    inner = Text("\n").join([title, Text(), subtitle, Text(), start_hint])
    panel = Panel(inner, box=BOX, border_style=C["border"], width=W, padding=(2, 4))
    console.print()
    console.print(Padding(panel, (0, 0)))
    console.print()

    console.print(Rule(style=C["muted"]))
    console.print(f"  [{C['muted']}]身份[/]  {agent_dir}/consciousness/identity.md")
    console.print(f"  [{C['muted']}]模型[/]  {provider_display} · {model_config['model']}")
    console.print(f"  [{C['muted']}]底色[/]  {essence_count} 条 essence 已播种")
    console.print()
    console.print(f"  [{C['primary']}]❯[/] [bold]xiaomei-brain run {name}[/]  [{C['muted']}]# 开始对话[/]")
    console.print(f"  [{C['primary']}]❯[/] [bold]xiaomei-brain run {name} --cli[/]  [{C['muted']}]# 命令行交互[/]")
    console.print()
```

- [ ] **Step 5: Run setup to verify it works**

Run: `PYTHONPATH=src python3 -m xiaomei_brain setup`
Expected: Wizard runs through identity questions, then model config, creates agent with model settings. Answer the questions interactively and confirm it completes without error.

- [ ] **Step 6: Commit**

```bash
git add src/xiaomei_brain/cli/setup.py
git commit -m "feat(setup): add LLM model configuration step to setup wizard"
```

---

### Task 2: Add startup loading hints

**Files:**
- Modify: `src/xiaomei_brain/cli/run.py` — Add progress messages during agent initialization
- Read: `src/xiaomei_brain/consciousness/conscious_living.py` — Find where subsystems are initialized (see ~500 line __init__)

**Why:** First startup takes 15-25s due to embedding model loading, with zero output. Users think it's hung.

- [ ] **Step 1: Identify subsystem init points in conscious_living.py**

```bash
grep -n "def _setup\|embedding\|lance\|LongTerm\|ConversationDB\|DAG" src/xiaomei_brain/consciousness/conscious_living.py | head -20
```

- [ ] **Step 2: Add startup progress messages in run.py**

In `src/xiaomei_brain/cli/run.py`, find where `ConsciousLiving` is instantiated (search for `ConsciousLiving(`) and wrap it with progress messages. Insert before the `ConsciousLiving(...)` call:

```python
# ── 启动进度提示 ──────────────────────────────────────

_BOOT_STEPS = [
    "加载记忆系统",
    "加载 Embedding 模型（首次约 20 秒）",
    "初始化意识引擎",
    "启动渠道服务",
]

def _print_boot_progress(msg: str, status: str = "....") -> None:
    """Linux boot 风格启动进度行。"""
    # 复用 boot.py 的格式
    from xiaomei_brain.cli.boot import boot_line
    boot_line(msg, status=status)
```

- [ ] **Step 3: Pass progress callback to ConsciousLiving init**

In `cli/run.py`, add a `on_boot_progress` parameter pattern. Actually simpler approach: print progress lines from `run.py` between each major init step rather than threading a callback through 500 lines of `__init__`.

In the `cmd_run` function (inside `cli/run.py`), find the section that initializes `ConsciousLiving` and add boot progress lines around it:

```python
    _print_boot_progress("加载记忆系统……")
    _print_boot_progress("加载 Embedding 模型（首次约 20 秒，请稍候）……")

    # --- existing ConsciousLiving init ---
    with boot_muted():
        living = ConsciousLiving(agent, config=cfg)
    # --- end existing init ---

    from xiaomei_brain.cli.boot import boot_line
    boot_line("记忆系统", status="OK", detail=f"{memory_count} 条长期记忆")
    boot_line("Embedding 模型", status="OK")
    boot_line("意识引擎", status="OK")
```

- [ ] **Step 4: Add memory count to boot success message**

After `living` is created, query memory count for the detail line:

```python
    memory_count = 0
    try:
        if hasattr(living, '_longterm_memory') and living._longterm_memory:
            # Count all non-extinct memories
            from xiaomei_brain.memory.longterm import LongTermMemory
            # Quick count from SQLite
            import sqlite3
            brain_db = living.agent_instance._agent.conversation_db.db_path if hasattr(living, 'agent_instance') else None
    except Exception:
        pass
```

Actually, let's keep it simpler — just show what's available:

```python
    # After living init, print success
    from xiaomei_brain.cli.boot import boot_line, boot_banner
    boot_line("记忆系统", status="OK")
    boot_line("意识引擎", status="OK")

    # Then the existing boot banner
    boot_banner(
        agent_name=agent_name,
        agent_id=agent_id,
        model=model_name,
    )
```

- [ ] **Step 5: Verify boot display**

Run: `PYTHONPATH=src python3 -m xiaomei_brain run xiaomei --cli`
Expected: See boot progress lines before the welcome card. If Embedding loads quickly (cached), it should show OK immediately.

- [ ] **Step 6: Commit**

```bash
git add src/xiaomei_brain/cli/run.py
git commit -m "feat(cli): add startup loading hints during agent initialization"
```

---

### Task 3: Write Quick Start documentation (README.md rewrite)

**Files:**
- Modify: `README.md`

**Why:** Current README is 116 lines and doesn't tell a new user how to start.

- [ ] **Step 1: Rewrite README.md**

Write `README.md` with the following structure. The file at `/home/iamlibai/workspace/claude-project/xiaomei-brain/README.md` currently exists — replace it completely.

```markdown
# xiaomei-brain

一个多 Agent AI 大脑框架。让 AI 拥有记忆、性格、情感和意识。

> 🚧 Alpha 阶段 (v0.2.0) — 架构完整，功能可用，API 可能变动。

## 5 分钟快速开始

### 前置要求

- Python 3.11+
- LLM API key（支持智谱 AI / 火山引擎 / DeepSeek / OpenAI）

### 1. 安装

```bash
git clone https://github.com/iamlibai2/xiaomei-brain.git
cd xiaomei-brain
pip install -e .
```

### 2. 创建你的 AI 伙伴

```bash
xiaomei-brain setup
```

交互式向导会引导你：选择 LLM 模型 → 输入 API key → 定义 AI 伙伴的身份。

### 3. 开始对话

```bash
xiaomei-brain run 小美        # 后台运行 + WebSocket
xiaomei-brain run 小美 --cli  # 命令行交互
```

### 4. 试试这些

```
你好！今天过得怎么样？
帮我查一下 Python 的 dataclass 用法
/identity   # 查看小美的自我认知
/memory     # 查看小美的长期记忆
/drive      # 查看小美的情绪和欲望
/help       # 查看更多命令
```

## 用 Docker 运行

```bash
docker run -it --rm \
  -e XIAOMEI_API_PROVIDER=zhipu \
  -e XIAOMEI_API_KEY=sk-xxx \
  -v ~/.xiaomei-brain:/root/.xiaomei-brain \
  ghcr.io/iamlibai2/xiaomei-brain:latest run 小美 --cli
```

## 核心能力

| 能力 | 说明 |
|------|------|
| 🧠 **记忆** | 5 层记忆架构 — 对话日志、DAG 摘要、向量长期记忆、模式记忆、叙事记忆 |
| 💓 **边缘系统** | 情绪/激素/欲望/动机四维驱动，纯算法规则 |
| 🔥 **意识火焰** | L0 自主心跳 → L1 异常感知 → L2 意图决策 → L3 深度反省 |
| 🎯 **目标管理** | 三层目标层级（意义 → 阶段 → 执行），PACE 执行循环 |
| 🤔 **元认知** | 自我审视、内心独白、多视角思考、能力画像 |
| 🔌 **多渠道** | CLI / 飞书 / 钉钉 / WebSocket / P2P Agent 间通信 |
| 🛠️ **工具** | Shell、文件读写、网页搜索、记忆搜索、目标管理等 17 个工具 |

## 架构

```
Consciousness（意识） → Metacognition（元认知） → Purpose（目的）
        ↕                      ↕                    ↕
     Drive（驱动） ←→ Memory（记忆，5层） ←→ Agent（ReAct 循环）
                                    ↕
                        Tools / Channels / LLM
```

## 文档

- [ARCHITECTURE.md](docs/ARCHITECTURE.md) — 完整架构说明（待完成）
- [CONTRIBUTING.md](CONTRIBUTING.md) — 如何参与贡献（待完成）
- [docs/](docs/) — 设计文档和对话记录

## License

MIT
```

- [ ] **Step 2: Verify README renders correctly**

```bash
head -30 README.md
```

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: rewrite README with quick start guide and capability overview"
```

---

### Task 4: Docker support

**Files:**
- Create: `Dockerfile`
- Create: `docker-compose.yml`

**Why:** Lowers the barrier for non-Python users. Docker eliminates Python version and dependency issues.

- [ ] **Step 1: Write Dockerfile**

```dockerfile
FROM python:3.12-slim

# System deps for sentence-transformers + sounddevice
RUN apt-get update && apt-get install -y --no-install-recommends \
    libportaudio2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install package
COPY pyproject.toml .
COPY src/ src/
COPY examples/ examples/

RUN pip install --no-cache-dir -e .[server,ws]

# Pre-download embedding model (optional but saves first-run time)
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-m3', cache_folder='/root/.cache/huggingface')" 2>/dev/null || true

VOLUME ["/root/.xiaomei-brain"]

ENTRYPOINT ["xiaomei-brain"]
CMD ["run", "xiaomei", "--cli"]
```

- [ ] **Step 2: Write docker-compose.yml**

```yaml
version: "3.8"

services:
  xiaomei:
    build: .
    image: xiaomei-brain:latest
    environment:
      - XIAOMEI_API_PROVIDER=${XIAOMEI_API_PROVIDER:-zhipu}
      - XIAOMEI_API_KEY=${XIAOMEI_API_KEY}
      - HF_HUB_OFFLINE=0
    volumes:
      - ~/.xiaomei-brain:/root/.xiaomei-brain
      - ~/.cache/huggingface:/root/.cache/huggingface
    stdin_open: true
    tty: true
    command: run xiaomei --cli
```

- [ ] **Step 3: Test Docker build**

```bash
docker build -t xiaomei-brain:test .
```

Expected: Build succeeds. Note: embedding model pre-download may timeout on slow networks — comment out that RUN line if needed.

- [ ] **Step 4: Test Docker run**

```bash
# Just verify it starts and shows help/error (API key not set is expected)
docker run --rm xiaomei-brain:test run xiaomei --cli 2>&1 | head -10
```

Expected: Either start successfully (if API key is in env) or show a clear error message about missing API configuration.

- [ ] **Step 5: Commit**

```bash
git add Dockerfile docker-compose.yml
git commit -m "feat: add Dockerfile and docker-compose for containerized deployment"
```

---

### Task 5: Verify end-to-end pip install flow

**Files:** None (verification only)

**Why:** The project uses `src/` layout with `packages = ["src/xiaomei_brain"]` in hatch config. We need to verify this actually installs correctly for an external user.

- [ ] **Step 1: Test pip install in a clean venv**

```bash
python3 -m venv /tmp/test-xiaomei-venv
source /tmp/test-xiaomei-venv/bin/activate
cd /home/iamlibai/workspace/claude-project/xiaomei-brain
pip install -e . 2>&1
```

Expected: Install succeeds without errors.

- [ ] **Step 2: Test console script is available**

```bash
which xiaomei-brain
xiaomei-brain 2>&1 | head -5
```

Expected: The `xiaomei-brain` command is available and prints usage or starts the agent (auto-bootstrap).

- [ ] **Step 3: Test import works**

```bash
python3 -c "from xiaomei_brain.agent.core import Agent; print('import OK')"
```

Expected: `import OK`

- [ ] **Step 4: Test optional dependency install**

```bash
pip install -e ".[server,ws]"
python3 -c "import fastapi; import websockets; print('optional deps OK')"
```

Expected: `optional deps OK`

- [ ] **Step 5: Clean up**

```bash
deactivate
rm -rf /tmp/test-xiaomei-venv
```

---

### Task 6: Final integration test

**Files:** None (verification only)

- [ ] **Step 1: Full flow from scratch**

```bash
# 1. Install
pip install -e .

# 2. Setup (interactive — answer the prompts)
xiaomei-brain setup

# 3. Start CLI
xiaomei-brain run xiaomei --cli
```

Expected: Boot screen appears → loading hints → welcome card → prompt `❯ ` appears → can type messages → Agent responds.

- [ ] **Step 2: Verify /help works**

At the prompt, type `/help` and confirm available commands are listed.

- [ ] **Step 3: Verify /memory shows memories after conversation**

After at least one exchange, type `/memory` and confirm the agent's memory is populated.

- [ ] **Step 4: Document any issues found**

If any step of the integration test fails, create a fix task before this Phase is considered complete.

---

## Completion Criteria

- [ ] `pip install -e .` works in clean venv
- [ ] `xiaomei-brain setup` runs interactive wizard with model config step
- [ ] `xiaomei-brain run <name> --cli` starts and shows boot progress + welcome card
- [ ] User can type a message and receive a response
- [ ] README.md contains a working 5-minute quick start
- [ ] `docker build` succeeds
- [ ] Full integration test passes end-to-end
