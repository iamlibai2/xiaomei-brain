"""xiaomei-brain install — 一键预下载所有本地模型。

用法:
    xiaomei-brain install        # 下载所有模型
"""

from __future__ import annotations

import os
import sys

from rich.console import Console
from rich.table import Table

console = Console()

# ── 模型清单 ──────────────────────────────────────────────────────────
# 每个模型：name / desc / size / ms_id (ModelScope) / hf_id (HuggingFace)

ALL_MODELS = [
    {
        "name": "speechbrain/spkrec-ecapa-voxceleb",
        "desc": "声纹识别",
        "size": "~80 MB",
        "ms_id": None,
        "hf_id": "speechbrain/spkrec-ecapa-voxceleb",
    },
    {
        "name": "iic/SenseVoiceSmall",
        "desc": "语音识别 STT",
        "size": "~400 MB",
        "ms_id": "iic/SenseVoiceSmall",
        "hf_id": None,
    },
    {
        "name": "openbmb/VoxCPM1.5",
        "desc": "本地语音合成 TTS（可选）",
        "size": "~3 GB",
        "ms_id": None,
        "hf_id": "openbmb/VoxCPM1.5",
    },
    {
        "name": "BAAI/bge-m3",
        "desc": "Embedding 向量模型（记忆搜索、技能索引）",
        "size": "~4.6 GB",
        "ms_id": "BAAI/bge-m3",
        "hf_id": "BAAI/bge-m3",
    },
]


# ── 下载逻辑 ──────────────────────────────────────────────────────────

def _download_ms(model: dict) -> bool:
    """通过 ModelScope 下载，已缓存则秒过。"""
    from modelscope import snapshot_download

    mid = model["ms_id"]
    console.print(f"  [dim]魔搭: {mid} ({model['size']})[/]")
    try:
        path = snapshot_download(mid)
        console.print(f"  [green]完成[/] {path}")
        return True
    except KeyboardInterrupt:
        console.print(f"  [yellow]已取消[/]")
        return False
    except Exception as e:
        console.print(f"  [yellow]失败: {e}[/]")
        return False


def _download_hf(model: dict) -> bool:
    """通过 HuggingFace 镜像下载，已缓存则秒过。"""
    os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        console.print(f"  [red]缺少 huggingface_hub，跳过[/]")
        return False

    hid = model["hf_id"]
    console.print(f"  [dim]HF 镜像: {hid} ({model['size']})[/]")
    try:
        snapshot_download(hid)
        console.print(f"  [green]完成[/] {hid}")
        return True
    except KeyboardInterrupt:
        console.print(f"  [yellow]已取消[/]")
        return False
    except Exception as e:
        console.print(f"  [yellow]失败: {e}[/]")
        return False


def _download_one(model: dict) -> bool:
    """下载一个模型。先试魔搭，再试 HF 镜像。"""
    # ModelScope 优先（国内快）
    if model["ms_id"]:
        if _download_ms(model):
            return True
        if model["hf_id"]:
            console.print(f"  [dim]回退 HF 镜像...[/]")
            return _download_hf(model)
        return False

    # 只有 HF
    if model["hf_id"]:
        return _download_hf(model)

    return False


# ── 检查已缓存 ──────────────────────────────────────────────────────────

def _is_cached(model: dict) -> bool:
    """快速检查模型是否已在本地缓存。"""
    # 检查 ModelScope 缓存
    if model["ms_id"]:
        ms_dir = os.path.join(
            os.path.expanduser("~/.cache/modelscope/hub/models"),
            model["ms_id"],
        )
        # 不同模型有不同的标志文件，统一检查目录下是否有 .bin / .ckpt / .pt
        if os.path.isdir(ms_dir):
            for root, _, files in os.walk(ms_dir):
                for f in files:
                    if f.endswith((".bin", ".ckpt", ".pt", ".safetensors")):
                        return True

    # 检查 HF 缓存
    if model["hf_id"]:
        hf_dir = os.path.join(
            os.path.expanduser("~/.cache/huggingface/hub"),
            "models--" + model["hf_id"].replace("/", "--"),
        )
        if os.path.isdir(hf_dir):
            for root, _, files in os.walk(hf_dir):
                for f in files:
                    if f.endswith((".bin", ".ckpt", ".pt", ".safetensors")):
                        return True

    # 检查 VoxCPM 本地目录
    if "VoxCPM" in model["name"]:
        local = os.path.expanduser(f"~/{model['name'].split('/')[-1]}")
        if os.path.isdir(local):
            return True

    return False


# ── CLI ────────────────────────────────────────────────────────────────

def download_all_models() -> int:
    """下载所有模型。返回失败数量。"""
    # 列出所有模型
    table = Table(title="模型清单", title_style="bold white", box=None)
    table.add_column("模型", style="cyan", width=42)
    table.add_column("用途", style="dim", width=38)
    table.add_column("大小", style="yellow", width=12, justify="right")
    table.add_column("状态", width=12, justify="center")

    for m in ALL_MODELS:
        status = "[green]已缓存[/]" if _is_cached(m) else "[dim]待下载[/]"
        table.add_row(m["name"], m["desc"], m["size"], status)

    console.print(table)
    console.print()

    failed = 0
    for i, m in enumerate(ALL_MODELS, 1):
        if _is_cached(m):
            console.print(f"[{i}/{len(ALL_MODELS)}] [green]✓[/] {m['name']} — 已缓存，跳过")
            continue

        console.print(f"[{i}/{len(ALL_MODELS)}] [bold]{m['name']}[/] — {m['desc']}")
        if _download_one(m):
            console.print()
        else:
            failed += 1
            console.print(f"  [yellow]⚠ 将在首次使用时自动下载[/]\n")

    return failed


def cmd_install(args: list[str]) -> None:
    """`xiaomei-brain install` — 一键下载所有本地模型。"""
    console.print("\n[bold]xiaomei-brain 模型预下载[/]\n")

    failed = download_all_models()

    if failed == 0:
        console.print("[green]全部就绪，启动无需等待。[/]\n")
    else:
        console.print(f"[yellow]{failed} 个模型未下载，将在首次使用时自动下载。[/]\n")
        sys.exit(1)


# ── Setup 提示（兼容旧接口）─────────────────────────────────────────────

def download_embedding_model() -> bool:
    """兼容旧调用，下载 bge-m3。"""
    m = ALL_MODELS[-1]  # bge-m3 是最后一个
    if _is_cached(m):
        console.print(f"  [green]已缓存[/] {m['name']}")
        return True
    return _download_one(m)


def show_post_setup_prompt() -> None:
    """setup 完成后提示下载所有模型。"""
    from rich.panel import Panel
    from rich.text import Text
    from rich.prompt import Confirm
    from rich.box import ROUNDED

    # 检查还有哪些未缓存
    pending = [m for m in ALL_MODELS if not _is_cached(m)]
    if not pending:
        return

    total_size = sum(
        {"~4.6 GB": 4.6, "~400 MB": 0.4, "~80 MB": 0.08, "~3 GB": 3.0}[m["size"]]
        for m in pending
    )

    console.print()
    inner = Text("\n").join([
        Text(f"本地模型（{len(pending)} 个，共 ~{total_size:.1f} GB）", style="bold white", justify="center"),
        Text("首次启动时会自动下载，建议现在一次性下载完", style="dim", justify="center"),
    ])
    console.print(Panel(inner, box=ROUNDED, border_style="bright_magenta",
                         padding=(1, 3), width=60))

    try:
        download_now = Confirm.ask(
            f"  [bright_magenta]❯[/] 是否现在下载？",
            default=True,
            console=console,
        )
    except (KeyboardInterrupt, EOFError):
        console.print(f"\n\n  [dim]跳过。首次启动时自动下载。[/]\n")
        return

    if download_now:
        download_all_models()
    else:
        console.print(f"\n  [dim]跳过。首次启动时自动下载。[/]\n")
