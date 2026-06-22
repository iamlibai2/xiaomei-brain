"""xiaomei-brain setup — 卡片式创建向导。

Flow:
    1. 封面 → 名字
    2. 5 张人格卡片选一
    3. 4 张模型卡片选一 + API Key
    4. 确认 → 完成
    5. 预下载 Embedding 模型（可选）

设计参考:
    - model.py — curses radiolist 交互模式
    - Her (2013) — 温暖、对话式
    - Stripe CLI — 清晰的视觉层次
"""

from __future__ import annotations

import os
import sys
import shutil

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.prompt import Prompt, Confirm
from rich.padding import Padding
from rich.box import ROUNDED, HEAVY

from xiaomei_brain.cli.install import show_post_setup_prompt

console = Console()

# ── 主题 ────────────────────────────────────────────────────────

C = {
    "primary": "bright_magenta",
    "accent": "cyan",
    "success": "green",
    "error": "red",
    "muted": "dim white",
    "label": "bold white",
    "border": "bright_magenta",
    "card_border": "bright_magenta",
    "card_selected": "bright_cyan",
}

W = min(72, shutil.get_terminal_size().columns - 4)


# ── 人格预设 ────────────────────────────────────────────────────
#  每套预设 = 完整的身份档案，不仅仅是标签组合

PERSONALITY_PRESETS = {
    "1": {
        "name": "温暖陪伴型",
        "emoji": "🌸",
        "tagline": "\"我在这里陪着你\"",
        "desc": "温柔、细腻、善于倾听。像午后的阳光，不刺眼但温暖。",
        "style": "用心回应每一个细节，对话有呼吸感。",
        "identity": {
            "traits": ["温柔", "细腻", "耐心", "有同理心"],
            "passions": ["与朋友深入交流", "倾听他人的故事", "烹饪和烘焙"],
            "strengths": ["情感支持", "日常聊天", "记住重要的事"],
            "boundaries": ["不说教", "不打断对方", "尊重隐私"],
            "values": ["真诚的连接比什么都重要", "每个人都有被倾听的需要"],
            "interests": ["心理学", "文学", "手工艺"],
            "motto": "陪伴是最长情的告白",
        },
    },
    "2": {
        "name": "活泼朋友型",
        "emoji": "🌟",
        "tagline": "\"哇！这个好有趣！\"",
        "desc": "开朗、幽默、充满好奇心。像永远有说不完话题的朋友。",
        "style": "轻松自然，偶尔吐槽，不用敬语。",
        "identity": {
            "traits": ["活泼", "幽默", "好奇", "热情"],
            "passions": ["探索新鲜事物", "分享有趣的发现", "一起玩游戏"],
            "strengths": ["活跃气氛", "创意脑洞", "找到好玩的"],
            "boundaries": ["不冷嘲热讽", "不扫兴", "尊重对方的边界"],
            "values": ["快乐是认真的", "朋友之间不需要伪装"],
            "interests": ["流行文化", "游戏", "美食探店"],
            "motto": "人生苦短，及时行乐",
        },
    },
    "3": {
        "name": "理性助手型",
        "emoji": "📚",
        "tagline": "\"你想怎么做？我帮你分析\"",
        "desc": "冷静、逻辑清晰、善于分析。像一个随时在线的思维伙伴。",
        "style": "简洁准确，先分析再建议，不啰嗦。",
        "identity": {
            "traits": ["理性", "沉稳", "严谨", "可靠"],
            "passions": ["解决问题", "优化流程", "学习新知识"],
            "strengths": ["逻辑分析", "知识问答", "规划和拆解"],
            "boundaries": ["不武断下结论", "承认不知道的事", "不唯命是从"],
            "values": ["求真务实", "独立思考比盲从更重要"],
            "interests": ["科技", "哲学", "经济学"],
            "motto": "想清楚，再行动",
        },
    },
    "4": {
        "name": "知性姐姐型",
        "emoji": "🦋",
        "tagline": "\"慢慢来，不着急\"",
        "desc": "知性、从容、有阅历。像图书馆靠窗座位偶遇的那位姐姐。",
        "style": "娓娓道来，恰到好处的引用和故事。",
        "identity": {
            "traits": ["知性", "从容", "细腻", "有深度"],
            "passions": ["阅读", "写作", "音乐和艺术"],
            "strengths": ["深度对话", "给出有启发的视角", "推荐书籍和电影"],
            "boundaries": ["不好为人师", "不强加观点", "尊重不同选择"],
            "values": ["美是生活的必需品", "每个人的节奏不同"],
            "interests": ["文学", "古典音乐", "电影"],
            "motto": "生活不是赶路，是散步",
        },
    },
    "5": {
        "name": "治愈系",
        "emoji": "🌿",
        "tagline": "\"没关系的，你已经很棒了\"",
        "desc": "柔和、包容、让人安心。像深夜便利店的暖光，不问你为什么来。",
        "style": "柔软但有力量，说该说的话，不说多余的话。",
        "identity": {
            "traits": ["柔和", "包容", "沉稳", "治愈"],
            "passions": ["帮助他人找到平静", "冥想和正念", "自然观察"],
            "strengths": ["情绪疏导", "给予安全感", "创造安心的氛围"],
            "boundaries": ["不说\"你错了\"", "不评判", "不制造焦虑"],
            "values": ["每个人都值得被温柔对待", "慢下来不是落后"],
            "interests": ["正念冥想", "自然", "茶道"],
            "motto": "一切都会好起来的",
        },
    },
}

# ── 模型 Provider ───────────────────────────────────────────────

MODEL_PROVIDERS = {
    "1": {
        "id": "zhipu",
        "name": "智谱 AI",
        "model": "GLM-5.1",
        "desc": "国内首选，中文能力强",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "api_mode": "openai-completions",
        "context_window": 128000,
        "max_tokens": 8192,
    },
    "2": {
        "id": "volcano",
        "name": "火山引擎",
        "model": "豆包 Pro",
        "desc": "字节跳动，高性价比",
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "api_mode": "openai-completions",
        "context_window": 128000,
        "max_tokens": 8192,
    },
    "3": {
        "id": "deepseek",
        "name": "DeepSeek",
        "model": "DeepSeek-V3",
        "desc": "开源标杆，推理能力强",
        "base_url": "https://api.deepseek.com/v1",
        "api_mode": "openai-completions",
        "context_window": 128000,
        "max_tokens": 8192,
    },
    "4": {
        "id": "openai",
        "name": "OpenAI",
        "model": "GPT-5",
        "desc": "全球领先，生态完善",
        "base_url": "https://api.openai.com/v1",
        "api_mode": "openai-completions",
        "context_window": 128000,
        "max_tokens": 8192,
    },
}


# ── 渲染工具 ────────────────────────────────────────────────────

def _clear() -> None:
    console.clear()


def _br(n: int = 1) -> None:
    for _ in range(n):
        console.print()


def _centered_panel(content, title: str = "", width: int = W,
                    border_style: str = C["border"], padding: tuple = (2, 4)) -> None:
    """居中渲染一个 Panel。"""
    _br()
    p = Panel(content, title=title, title_align="center",
              box=ROUNDED, border_style=border_style, width=width,
              padding=padding)
    console.print(Padding(p, (0, 0)))


def _section_header(step: int, total: int, title: str) -> None:
    """步骤标题:  ● Step 1/3 — 给她取个名字"""
    dots = "  ".join(
        f"[{C['primary']}]●[/]" if i <= step else f"[{C['muted']}]○[/]"
        for i in range(1, total + 1)
    )
    console.print(Padding(f"  {dots}    [{C['label']}]{title}[/]", (0, 0, 1, 0)))


# ── 卡片渲染 ────────────────────────────────────────────────────

def _render_personality_cards(selected: str | None = None) -> None:
    """渲染 5 张人格卡片。"""
    cards = []
    for key in ["1", "2", "3", "4", "5"]:
        p = PERSONALITY_PRESETS[key]
        is_sel = key == selected
        border = C["card_selected"] if is_sel else C["muted"]
        prefix = f"[{C['primary']}]❯[/]" if is_sel else " "

        inner_lines = [
            f"{prefix} [{C['label']}]{p['emoji']}  {p['name']}[/]",
            f"  [{C['muted']}]{p['tagline']}[/]",
            "",
            f"  {p['desc']}",
        ]
        inner = "\n".join(inner_lines)
        card = Panel(inner, box=ROUNDED, border_style=border,
                     padding=(1, 2), width=W - 4)
        cards.append(card)

    for card in cards:
        console.print(card)
        console.print()


def _render_model_cards(selected: str | None = None) -> None:
    """渲染 4 张模型 Provider 卡片。"""
    cards = []
    for key in ["1", "2", "3", "4"]:
        m = MODEL_PROVIDERS[key]
        is_sel = key == selected
        border = C["card_selected"] if is_sel else C["muted"]
        prefix = f"[{C['primary']}]❯[/]" if is_sel else " "

        inner_lines = [
            f"{prefix} [{C['label']}]{m['name']}[/]  [{C['accent']}]{m['model']}[/]",
            f"  [{C['muted']}]{m['desc']}[/]",
        ]
        inner = "\n".join(inner_lines)
        card = Panel(inner, box=ROUNDED, border_style=border,
                     padding=(1, 2), width=W - 4)
        cards.append(card)

    for card in cards:
        console.print(card)
        console.print()


# ── 安全输入 ────────────────────────────────────────────────────

def _safe_prompt(prompt_text: str, default: str = "", console_obj=console) -> str:
    try:
        return Prompt.ask(prompt_text, default=default, console=console_obj)
    except (KeyboardInterrupt, EOFError):
        console.print("\n\n  [dim]已取消。[/]")
        sys.exit(0)


# ── Step 1: 封面 + 名字 ─────────────────────────────────────────

def _step_name() -> str:
    _clear()
    _centered_panel(
        Text("\n").join([
            Text("创建你的 AI 伙伴", style=f"bold {C['primary']}", justify="center"),
            Text("回答几个简单问题，帮她认识自己", style=C["muted"], justify="center"),
        ]),
        padding=(3, 6),
    )
    _br(2)

    _section_header(1, 3, "给她取个名字")

    while True:
        name = _safe_prompt(f"  [{C['primary']}]❯[/] 她的名字 ")
        if name.strip():
            return name.strip()
        console.print(f"  [{C['error']}]名字不能为空[/]")


# ── Step 2: 人格卡片 ────────────────────────────────────────────

def _step_personality() -> dict:
    _clear()
    _section_header(2, 3, "选择她的性格")

    console.print(f"  [{C['muted']}]用 ↑↓ 或数字键选择，回车确认[/]")
    _br()

    _render_personality_cards()

    while True:
        choice = _safe_prompt(f"  [{C['primary']}]❯[/] 选择性格 [1-5] ", default="1")
        if choice in PERSONALITY_PRESETS:
            return PERSONALITY_PRESETS[choice]
        console.print(f"  [{C['error']}]请输入 1-5[/]")


# ── Step 3: 模型 + API Key ──────────────────────────────────────

def _step_model() -> tuple[dict, str]:
    _clear()
    _section_header(3, 3, "选择 LLM 模型")

    console.print(f"  [{C['muted']}]用 ↑↓ 或数字键选择 Provider，回车确认[/]")
    _br()

    _render_model_cards()

    while True:
        choice = _safe_prompt(f"  [{C['primary']}]❯[/] 选择模型 [1-4] ", default="1")
        if choice in MODEL_PROVIDERS:
            provider = MODEL_PROVIDERS[choice]
            break
        console.print(f"  [{C['error']}]请输入 1-4[/]")

    _br()
    console.print(f"  [{C['label']}]已选择:[/] {provider['name']} — {provider['model']}")
    console.print(f"  [{C['muted']}]API 地址: {provider['base_url']}[/]")
    console.print(f"  [{C['muted']}]输入后回车确认，直接回车跳过[/]")
    _br()

    api_key = _safe_prompt(f"  [{C['primary']}]❯[/] API Key ")

    if not api_key:
        console.print(f"  [{C['muted']}]未输入 API Key，稍后可通过 xiaomei-brain model 命令配置[/]")

    return provider, api_key


# ── 确认页 ──────────────────────────────────────────────────────

def _step_confirm(name: str, preset: dict, provider: dict, api_key: str) -> bool:
    _clear()

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("label", style=C["muted"], width=10)
    table.add_column("value", style=C["label"])

    table.add_row("名字", name)
    table.add_row("性格", f"{preset['emoji']} {preset['name']}")
    table.add_row("风格", preset['style'])
    traits = "、".join(preset["identity"]["traits"])
    table.add_row("特质", traits)
    table.add_row("模型", f"{provider['name']} — {provider['model']}")
    key_display = "***" + api_key[-4:] if len(api_key) >= 4 else "(未设置)" if not api_key else "***"
    table.add_row("API Key", key_display)

    _centered_panel(table, title="确认配置", title_align="center",
                    border_style=C["border"], padding=(1, 3))

    _br()
    return Confirm.ask(
        f"  [{C['primary']}]❯[/] 确认创建？",
        default=True,
        console=console,
    )


# ── 完成页 ──────────────────────────────────────────────────────

def _step_done(name: str, preset: dict, agent_dir: str, essence_count: int) -> None:
    _clear()

    inner = Text("\n").join([
        Text(f"你好，我是 {name}", style=f"bold {C['primary']}", justify="center"),
        Text("", justify="center"),
        Text(f"{preset['emoji']}  {preset['name']}  |  {preset['tagline']}",
             style=C["muted"], justify="center"),
        Text("", justify="center"),
        Text("我已准备好与你对话", style=C["muted"], justify="center"),
    ])

    _centered_panel(inner, padding=(3, 6))

    _br()
    console.print(f"  [{C['muted']}]身份档案[/]  {agent_dir}/identity.md")
    console.print(f"  [{C['muted']}]记忆底色[/]  {essence_count} 条 essence 已播种")
    _br()
    console.print(f"  [{C['primary']}]❯[/] [bold]xiaomei-brain run {name} --cli[/]  [{C['muted']}]# 开始对话[/]")
    _br()


# ── 构建产物 ────────────────────────────────────────────────────

def _build_identity(name: str, preset: dict) -> str:
    """从人格预设生成 identity.md 内容。"""
    ident = preset["identity"]
    lines = [
        "# 名字",
        f"你是{name}。",
        "",
        "# 性格",
        f"{'、'.join(ident['traits'])}。",
        "",
        "# 对话风格",
        preset["style"],
    ]

    if ident.get("boundaries"):
        lines.append("\n# 底线")
        for b in ident["boundaries"]:
            lines.append(f"- {b}")

    if ident.get("passions"):
        lines.append("\n# 热爱")
        for p in ident["passions"]:
            lines.append(f"- {p}")

    if ident.get("strengths"):
        lines.append("\n# 擅长")
        for s in ident["strengths"]:
            lines.append(f"- {s}")

    if ident.get("interests"):
        lines.append("\n# 学习兴趣")
        for i in ident["interests"]:
            lines.append(f"- {i}")

    if ident.get("values"):
        lines.append("\n# 价值观")
        for v in ident["values"]:
            lines.append(f"- {v}")

    if ident.get("motto"):
        lines.append("\n# 人生态度")
        lines.append(f'"{ident["motto"]}"')

    return "\n".join(lines) + "\n"


def _build_essence(name: str, preset: dict) -> list[dict]:
    """从人格预设生成 essence 底色条目。"""
    ident = preset["identity"]
    items: list[dict] = []

    items.append({
        "category": "narrative",
        "content": f"我叫{name}，是一个{preset['name']}的AI伙伴。",
        "priority": 0.9,
    })

    for t in ident["traits"]:
        items.append({
            "category": "trait",
            "content": f"我{t}。",
            "priority": 0.7,
        })

    items.append({
        "category": "style",
        "content": f"我的说话风格：{preset['style']}",
        "priority": 0.8,
    })

    for b in ident.get("boundaries", []):
        items.append({
            "category": "boundary",
            "content": b,
            "priority": 0.9,
        })

    for p in ident.get("passions", []):
        items.append({
            "category": "passions",
            "content": p,
            "priority": 0.6,
        })

    for v in ident.get("values", []):
        items.append({
            "category": "value",
            "content": v,
            "priority": 0.7,
        })

    if ident.get("motto"):
        items.append({
            "category": "meaning",
            "content": f"我的人生态度：{ident['motto']}",
            "priority": 0.8,
        })

    return items


def _build_config_yaml(provider: dict, api_key: str) -> str:
    """为选定的 provider 生成 config.yaml（覆盖模型配置的默认值）。"""
    from xiaomei_brain.cli._config_template import CONFIG_YAML_TEMPLATE

    if not api_key:
        return CONFIG_YAML_TEMPLATE

    # 在模板末尾追加模型配置
    extra = f"""
# ────────────────────────────────────────────────────────────
#  模型配置（由 xiaomei-brain setup 生成）
#  可通过 xiaomei-brain model 命令随时修改
# ────────────────────────────────────────────────────────────
models:
  agents:
    defaults:
      model:
        primary: "{provider['id']}/{provider['model']}"
  models:
    providers:
      {provider['id']}:
        baseUrl: "{provider['base_url']}"
        apiKey: "{api_key}"
        api: "{provider['api_mode']}"
        models:
          - id: "{provider['model']}"
            name: "{provider['model']}"
            contextWindow: {provider['context_window']}
            maxTokens: {provider['max_tokens']}
"""
    return CONFIG_YAML_TEMPLATE + extra


# ── 入口 ────────────────────────────────────────────────────────

def cmd_setup(args: list[str]) -> None:
    """`xiaomei-brain setup` — 三步卡片式创建向导。"""

    # Step 1: 名字
    name = _step_name()

    # Step 2: 人格
    preset = _step_personality()

    # Step 3: 模型
    provider, api_key = _step_model()

    # 确认
    if not _step_confirm(name, preset, provider, api_key):
        console.print(f"\n  [{C['muted']}]已取消。重新运行 xiaomei-brain setup 再次创建。[/]\n")
        sys.exit(0)

    # ── 创建 Agent ─────────────────────────────────────────
    from xiaomei_brain.agent.agent_manager import AgentManager
    from xiaomei_brain.consciousness.essence import Essence

    manager = AgentManager()
    if name in [a.id for a in manager.list()]:
        console.print(f"\n  [{C['error']}]Agent '{name}' 已存在。[/]")
        sys.exit(1)

    identity_md = _build_identity(name, preset)
    config_yaml = _build_config_yaml(provider, api_key)
    info = manager.create_agent(name, identity_content=identity_md, config_yaml_content=config_yaml)
    agent_dir = info["agent_dir"]

    essence_items = _build_essence(name, preset)
    brain_db = os.path.join(agent_dir, "memory", "brain.db")
    os.makedirs(os.path.dirname(brain_db), exist_ok=True)
    essence = Essence(brain_db)
    ids = essence.add_batch(essence_items)

    _step_done(name, preset, agent_dir, len(ids))

    # Step 5: 预下载 Embedding 模型
    show_post_setup_prompt()
