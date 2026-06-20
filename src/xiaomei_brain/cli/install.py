"""xiaomei-brain install — 预下载 Embedding 模型。

用法:
    xiaomei-brain install        # 下载 BAAI/bge-m3
"""

from __future__ import annotations

import os
import sys

from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.prompt import Confirm
from rich.box import ROUNDED

console = Console()

EMBEDDING_MODEL = "BAAI/bge-m3"
EMBEDDING_MODEL_SIZE = "~1.3 GB"


def download_embedding_model() -> bool:
    """下载 Embedding 模型到本地缓存。返回 True 表示成功。

    使用 HF_ENDPOINT=https://hf-mirror.com（国内镜像）加速下载。
    """
    os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        console.print(f"\n  [red]错误:[/] 需要安装 huggingface_hub")
        console.print(f"  [dim]pip install huggingface_hub[/]\n")
        return False

    console.print(f"\n  [dim]正在从镜像下载 {EMBEDDING_MODEL}（{EMBEDDING_MODEL_SIZE}）...[/]")
    console.print(f"  [dim]镜像: https://hf-mirror.com[/]\n")

    try:
        snapshot_download(EMBEDDING_MODEL)
        console.print(f"\n  [green]下载完成[/] {EMBEDDING_MODEL}\n")
        return True
    except KeyboardInterrupt:
        console.print(f"\n\n  [yellow]下载已取消[/]")
        console.print(f"  [dim]模型将在首次启动时自动下载[/]\n")
        return False
    except Exception as e:
        console.print(f"\n  [red]下载失败:[/] {e}")
        console.print(f"  [dim]模型将在首次启动时自动下载。也可以手动下载:[/]")
        console.print(f"  [dim]HF_ENDPOINT=https://hf-mirror.com huggingface-cli download {EMBEDDING_MODEL}[/]\n")
        return False


def show_post_setup_prompt() -> None:
    """setup 完成后的 Embedding 模型下载提示。

    在 _step_done 之后调用，询问用户是否现在下载。
    """
    console.print()
    inner = Text("\n").join([
        Text("Embedding 模型（" + EMBEDDING_MODEL + "）", style="bold white", justify="center"),
        Text("首次启动时会自动下载（" + EMBEDDING_MODEL_SIZE + "，需几分钟）", style="dim", justify="center"),
        Text("建议现在下载，免去首次启动等待", style="dim", justify="center"),
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
        download_embedding_model()
    else:
        console.print(f"\n  [dim]跳过。首次启动时自动下载。[/]\n")


def cmd_install(args: list[str]) -> None:
    """`xiaomei-brain install` — 预下载 Embedding 模型。"""
    success = download_embedding_model()
    if not success:
        sys.exit(1)
