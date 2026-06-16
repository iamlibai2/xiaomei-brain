"""xiaomei-brain setup — Her 式创建向导。

交互式问答 → 生成 identity.md + 播种 essence 底色表。

设计参考:
  - Her (2013) — 温暖、对话式、有呼吸感
  - Stripe CLI / gh auth login — 清晰的视觉层次
  - npm init — 流畅的默认值体验
"""

from __future__ import annotations

import os
import shutil
import sys

from rich.box import ROUNDED
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.text import Text
from rich.prompt import Prompt, Confirm
from rich.padding import Padding

# ── 主题 ────────────────────────────────────────────────────────

console = Console()

C = {
    "primary": "bright_magenta",
    "muted": "dim white",
    "accent": "cyan",
    "success": "green",
    "error": "red",
    "label": "bold white",
    "hint": "dim italic",
    "border": "bright_magenta",
}

BOX = ROUNDED             # rich Panel box style
W = min(60, shutil.get_terminal_size().columns - 6)  # panel width

# ── 数据 ────────────────────────────────────────────────────────

PERSONALITY_TAGS = [
    "温柔", "活泼", "理性", "幽默", "强势",
    "害羞", "好奇", "沉稳", "热情", "敏感",
    "大胆", "冷静", "细腻", "洒脱", "倔强",
]

STYLE_OPTIONS = {
    "1": {
        "name": "简洁直接",
        "desc": "说到点上，不绕弯子",
        "example_user": "今天天气不错，适合出门走走。",
        "example_her":  "嗯，确实。要去哪？",
    },
    "2": {
        "name": "温暖细腻",
        "desc": "用心回应，不浮于表面",
        "example_user": "今天天气真好，阳光暖暖的。",
        "example_her":  "是啊，这种天气让人想起春天的午后。你想出去走走吗？",
    },
    "3": {
        "name": "朋友随意",
        "desc": "像朋友一样，自然不做作",
        "example_user": "今天天气真不错！",
        "example_her":  "哈哈对啊，终于放晴了，憋坏我了。",
    },
    "4": {
        "name": "专业严谨",
        "desc": "逻辑清晰，准确可靠",
        "example_user": "这个方案你觉得怎么样？",
        "example_her":  "从三个维度分析：可行性方面...风险方面...资源方面...",
    },
}

TOTAL_STEPS = 11


# ── 渲染工具 ────────────────────────────────────────────────────

def _section(title: str) -> None:
    """章节标题。"""
    console.print()
    console.print(Rule(Text(title, style=C["border"]), style=C["muted"]))


def _step_marker(step: int) -> None:
    """进度标记 [3/11]"""
    bar = "".join(
        f"[{C['primary']}]●[/]" if i == step else
        f"[{C['muted']}]●[/]" if i < step else
        f"[{C['muted']}]○[/]"
        for i in range(1, TOTAL_STEPS + 1)
    )
    console.print(Padding(f"{bar}  [{C['muted']}]{step}/{TOTAL_STEPS}[/]", (1, 0, 0, 0)))


def _render_tags(selected: set[str]) -> None:
    """将性格标签渲染为 Rich 列布局。"""
    from rich.columns import Columns
    from rich.text import Text

    items: list[Text] = []
    for tag in PERSONALITY_TAGS:
        if tag in selected:
            items.append(Text(f" {tag} ", style=f"reverse {C['primary']}"))
        else:
            items.append(Text(f" {tag} ", style=C["muted"]))
    cols = Columns(items, equal=False, expand=False, padding=(0, 1))
    console.print(Padding(cols, (0, 2)))


def _render_style_card(key: str, opt: dict) -> None:
    """渲染一个风格选项卡片。"""
    from rich.table import Table
    table = Table(show_header=False, box=None, padding=(0, 1), show_edge=False)
    table.add_column("", style=C["muted"], width=1)
    table.add_column("", style=C["accent"], width=4)
    table.add_column("", style=C["primary"], width=4)
    table.add_column("", no_wrap=False)
    # Header row
    table.add_row(
        "", "", "",
        Text.assemble(
            (f"[{key}] ", C["primary"]),
            (opt["name"], "bold"),
            (f"  —  {opt['desc']}", C["muted"]),
        )
    )
    table.add_row("", "", "",
                  Text("─" * (W - 12), style=C["muted"]))
    table.add_row("", "用户", "", Text(f'"{opt["example_user"]}"'))
    table.add_row("", "她　", "", Text(f'"{opt["example_her"]}"'))
    table.add_row("", "", "",
                  Text("─" * (W - 12), style=C["muted"]))
    console.print(table)


def _render_summary(answers: dict) -> str:
    """确认页摘要（Rich markup）。"""
    lines: list[str] = []
    lines.append(f"  [{C['label']}]名字[/]    {answers['name']}")
    lines.append(f"  [{C['label']}]年龄[/]    {answers['age']}岁  ·  {answers['gender']}")
    lines.append(f"  [{C['label']}]性格[/]    {'、'.join(answers['traits'])}")
    style = STYLE_OPTIONS[answers['style']]

    lines.append(f"  [{C['label']}]风格[/]    {style['name']} — {style['desc']}")

    if answers.get("boundaries"):
        lines.append(f"  [{C['label']}]底线[/]    {'、'.join(answers['boundaries'])}")
    if answers.get("passions"):
        lines.append(f"  [{C['label']}]热爱[/]    {'、'.join(answers['passions'])}")
    if answers.get("strengths"):
        lines.append(f"  [{C['label']}]擅长[/]    {'、'.join(answers['strengths'])}")
    if answers.get("interests"):
        lines.append(f"  [{C['label']}]兴趣[/]    {'、'.join(answers['interests'])}")
    if answers.get("values"):
        lines.append(f"  [{C['label']}]价值观[/]  {'、'.join(answers['values'])}")
    if answers.get("motto"):
        lines.append(f"  [{C['label']}]态度[/]    \"{answers['motto']}\"")

    return "\n".join(lines)


# ── 封面 / 完成页 ──────────────────────────────────────────────

def _welcome() -> None:
    """Her 式封面。"""
    console.clear()
    title = Text("创建你的 AI 伙伴", style=f"bold {C['primary']}", justify="center")
    subtitle = Text("回答几个问题，帮她认识自己", style=C["muted"], justify="center")
    inner = Text("\n").join([title, Text(), subtitle])
    panel = Panel(inner, box=BOX, border_style=C["border"], width=W,
                  padding=(2, 4))
    console.print()
    console.print(Padding(panel, (0, 0)))


def _finish(name: str, agent_dir: str, essence_count: int) -> None:
    """Her 式完成页面。"""
    console.clear()
    title = Text(f"你好，我是 {name}", style=f"bold {C['primary']}", justify="center")
    subtitle = Text("我已准备好与你对话", style=C["muted"], justify="center")
    inner = Text("\n").join([title, Text(), subtitle])
    panel = Panel(inner, box=BOX, border_style=C["border"], width=W,
                  padding=(2, 4))
    console.print()
    console.print(Padding(panel, (0, 0)))
    console.print()

    console.print(Rule(style=C["muted"]))
    console.print(f"  [{C['muted']}]身份[/]  {agent_dir}/consciousness/identity.md")
    console.print(f"  [{C['muted']}]底色[/]  {essence_count} 条 essence 已播种")
    console.print()
    console.print(f"  [{C['primary']}]❯[/] [bold]xiaomei-brain run {name}[/]  [{C['muted']}]# 开始对话[/]")
    console.print(f"  [{C['primary']}]❯[/] [bold]xiaomei-brain run {name} --cli[/]  [{C['muted']}]# 命令行交互[/]")
    console.print()


# ── 安全 input 包装 ─────────────────────────────────────────────

def _safe_input(prompt_text: str = "") -> str:
    """Rich console.input() 包装，Ctrl+C / EOF → 优雅退出。"""
    try:
        return console.input(prompt_text)
    except (KeyboardInterrupt, EOFError):
        console.print("\n\n  [dim]已取消。[/]")
        sys.exit(0)


# ── 交互式问答 ─────────────────────────────────────────────────

def _ask_all() -> dict:
    """逐题交互，返回答案 dict。"""
    TOTAL = TOTAL_STEPS
    answers: dict = {}
    step = 0

    # ── 1. 基本身份 ─────────────────────────────────────
    _section("基本身份")

    step += 1
    _step_marker(step)
    while True:
        name = Prompt.ask(f"[{C['primary']}]❯[/] 她的名字是什么？", console=console)
        if name.strip():
            break
        console.print(f"  [{C['error']}]名字不能为空，请重新输入。[/]")
    answers["name"] = name.strip()
    console.print()

    step += 1
    _step_marker(step)
    gender = Prompt.ask(
        f"[{C['primary']}]❯[/] 她的性别？",
        default="女",
        console=console,
    )
    answers["gender"] = gender if gender in ("女", "男", "不限") else "女"
    console.print()

    step += 1
    _step_marker(step)
    age = Prompt.ask(
        f"[{C['primary']}]❯[/] 她的年龄？",
        default="25",
        console=console,
    )
    answers["age"] = age.strip() or "25"
    console.print()

    # ── 2. 性格 ────────────────────────────────────────
    _section("性格")
    step += 1
    _step_marker(step)
    console.print(f"  [{C['label']}]她是一个什么样的人？[/] [{C['muted']}]（选 2-5 个标签）[/]")
    console.print()
    _render_tags(set())
    console.print()
    console.print(f"  [{C['muted']}]输入标签名，空格分隔[/]")
    while True:
        raw = _safe_input(f"  [{C['primary']}]❯[/] ") or ""
        if not raw:
            answers["traits"] = ["温柔", "理性"]
        else:
            selected = [t for t in raw.split() if t in PERSONALITY_TAGS][:5]
            if len(selected) >= 1:
                answers["traits"] = selected
                break
            console.print(f"  [{C['error']}]至少选 1 个标签[/]")
            continue
        break
    console.print()
    _render_tags(set(answers["traits"]))
    console.print()

    # ── 3. 风格 ────────────────────────────────────────
    _section("说话风格")
    step += 1
    _step_marker(step)
    console.print(f"  [{C['label']}]她应该怎么说话？[/]")
    console.print()
    for k in STYLE_OPTIONS:
        _render_style_card(k, STYLE_OPTIONS[k])
        console.print()
    while True:
        style = Prompt.ask(
            f"[{C['primary']}]❯[/] 选择风格 [1-4]",
            default="2",
            console=console,
        )
        if style in STYLE_OPTIONS:
            break
        console.print(f"  [{C['error']}]请输入 1-4[/]")
    answers["style"] = style
    console.print()

    # ── 4. 底线 ────────────────────────────────────────
    _section("底线")
    step += 1
    _step_marker(step)
    console.print(f"  [{C['primary']}]❯[/] [{C['label']}]她的底线是什么？[/] [{C['muted']}]什么事情她绝对不会做？[/]")
    console.print(f"  [{C['muted']}]（每行一条，直接回车结束）[/]")
    answers["boundaries"] = _read_multiline()

    # ── 5. 内在世界 ────────────────────────────────────
    _section(f"内在世界  [{C['muted']}](回车跳过)[/]")

    step += 1
    _step_marker(step)
    console.print(f"  [{C['primary']}]❯[/] [{C['label']}]她热爱什么？[/] [{C['muted']}]让她眼睛发光的事情[/]")
    answers["passions"] = _read_multiline()

    step += 1
    _step_marker(step)
    console.print(f"  [{C['primary']}]❯[/] [{C['label']}]她擅长什么？[/] [{C['muted']}]她的优势和能力[/]")
    answers["strengths"] = _read_multiline()

    step += 1
    _step_marker(step)
    console.print(f"  [{C['primary']}]❯[/] [{C['label']}]她对什么感兴趣？[/] [{C['muted']}]想学习或探索的领域[/]")
    answers["interests"] = _read_multiline()

    step += 1
    _step_marker(step)
    console.print(f"  [{C['primary']}]❯[/] [{C['label']}]她的价值观是什么？[/] [{C['muted']}]她相信什么？看重什么？[/]")
    answers["values"] = _read_multiline()

    step += 1
    _step_marker(step)
    motto = Prompt.ask(
        f"[{C['primary']}]❯[/] [{C['label']}]用一句话描述她的人生态度[/]",
        default="",
        console=console,
    )
    answers["motto"] = motto.strip()
    console.print()

    return answers


def _read_multiline() -> list[str]:
    """读取多行输入。"""
    lines: list[str] = []
    try:
        while True:
            n = len(lines) + 1
            line = _safe_input(f"  [{C['muted']}]{n}.[/] ") or ""
            line = line.rstrip()
            if not line:
                break
            lines.append(line)
    except (KeyboardInterrupt, EOFError):
        console.print("\n  已取消。")
        sys.exit(0)
    return lines


# ── 确认页 ─────────────────────────────────────────────────────

def _confirm(answers: dict) -> bool:
    """展示摘要，让用户确认。"""
    console.clear()
    console.print()
    summary = _render_summary(answers)
    panel = Panel(summary, title="她 是 谁 ？", title_align="center",
                  box=BOX, border_style=C["border"], width=W,
                  padding=(1, 2))
    console.print(Padding(panel, (0, 0)))
    console.print()
    return Confirm.ask(
        f"[{C['primary']}]❯[/] 这样就可以了吗？",
        default=True,
        console=console,
    )


# ── 构建 identity.md ───────────────────────────────────────────

def _build_identity(answers: dict) -> str:
    parts = [
        "# 名字",
        f"你是{answers['name']}。",
        "",
        "# 年龄",
        f"{answers['age']}岁。性别：{answers['gender']}。",
        "",
        "# 性格",
        f"{'、'.join(answers['traits'])}。",
        "",
        "# 对话风格",
        f"{STYLE_OPTIONS[answers['style']]['desc']}。",
    ]
    if answers.get("boundaries"):
        parts.append("\n# 底线")
        for b in answers["boundaries"]:
            parts.append(f"- {b}")
    if answers.get("passions"):
        parts.append("\n# 热爱")
        for p in answers["passions"]:
            parts.append(f"- {p}")
    if answers.get("strengths"):
        parts.append("\n# 擅长")
        for s in answers["strengths"]:
            parts.append(f"- {s}")
    if answers.get("interests"):
        parts.append("\n# 学习兴趣")
        for i in answers["interests"]:
            parts.append(f"- {i}")
    if answers.get("values"):
        parts.append("\n# 价值观")
        for v in answers["values"]:
            parts.append(f"- {v}")
    if answers.get("motto"):
        parts.append("\n# 人生态度")
        parts.append(f'"{answers["motto"]}"')
    return "\n".join(parts) + "\n"


# ── 构建 essence ───────────────────────────────────────────────

def _build_essence(answers: dict) -> list[dict]:
    items: list[dict] = []
    items.append({
        "category": "narrative",
        "content": f"我叫{answers['name']}，{answers['age']}岁，{answers['gender']}。",
        "priority": 0.9,
    })
    for t in answers["traits"]:
        items.append({
            "category": "trait",
            "content": f"我{t}。",
            "priority": 0.7,
        })
    items.append({
        "category": "style",
        "content": f"我的说话风格是{STYLE_OPTIONS[answers['style']]['name']}。",
        "priority": 0.8,
    })
    for b in answers.get("boundaries", []):
        items.append({
            "category": "boundary",
            "content": b,
            "priority": 0.9,
        })
    for p in answers.get("passions", []):
        items.append({
            "category": "passions",
            "content": p,
            "priority": 0.6,
        })
    for v in answers.get("values", []):
        items.append({
            "category": "value",
            "content": v,
            "priority": 0.7,
        })
    if answers.get("motto"):
        items.append({
            "category": "meaning",
            "content": f"我的人生态度：{answers['motto']}",
            "priority": 0.8,
        })
    return items


# ── 入口 ────────────────────────────────────────────────────────

def cmd_setup(args: list[str]) -> None:
    """`xiaomei-brain setup` — Her 式创建向导。"""

    _welcome()

    # 交互问答
    answers = _ask_all()

    # 确认
    if not _confirm(answers):
        console.print(f"\n  [{C['muted']}]已取消。重新运行 xiaomei-brain setup 再次创建。[/]\n")
        sys.exit(0)

    # ── 创建 ─────────────────────────────────────────────
    # 延迟导入，避免影响交互流畅度
    from xiaomei_brain.agent.agent_manager import AgentManager
    from xiaomei_brain.consciousness.essence import Essence
    from xiaomei_brain.cli._config_template import CONFIG_YAML_TEMPLATE as DEFAULT_CONFIG_YAML

    name = answers["name"]

    manager = AgentManager()
    if name in [a.id for a in manager.list()]:
        console.print(f"\n  [{C['error']}]Agent '{name}' 已存在。[/]")
        sys.exit(1)

    identity_md = _build_identity(answers)
    info = manager.create_agent(name, identity_content=identity_md, config_yaml_content=DEFAULT_CONFIG_YAML)
    agent_dir = info["agent_dir"]

    essence_items = _build_essence(answers)
    brain_db = os.path.join(agent_dir, "memory", "brain.db")
    os.makedirs(os.path.dirname(brain_db), exist_ok=True)
    essence = Essence(brain_db)
    ids = essence.add_batch(essence_items)

    _finish(name, agent_dir, len(ids))
