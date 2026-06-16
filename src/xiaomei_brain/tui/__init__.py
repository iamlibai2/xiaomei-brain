"""xiaomei-brain TUI — 基于 OpenClaw 模式的专业终端界面。

Usage:
    xiaomei-brain tui [--host localhost] [--port 19766] [--token TOKEN] [--user USER]

架构：
  - 保留模式组件树：ChatLog + StreamAssembler + ToolCard
  - 显式依赖注入：工厂函数 create_event_handler()
  - prompt_toolkit 渲染：BufferControl / FormattedTextControl / TextArea
  - 两层 Footer + 覆盖层系统 + 双调色板
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

logger = logging.getLogger(__name__)


def cmd_tui(args: list[str] | None = None) -> None:
    """`xiaomei-brain tui` CLI 入口。

    启动 TUI 界面，连接到 Gateway WebSocket 服务。
    """
    if args is None:
        args = sys.argv[1:]

    parser = argparse.ArgumentParser(
        prog="xiaomei-brain tui",
        description="启动 TUI 界面",
    )
    parser.add_argument("--host", default="localhost", help="Gateway 地址 (默认: localhost)")
    parser.add_argument("--port", "-p", type=int, default=19766, help="Gateway 端口 (默认: 19766)")
    parser.add_argument("--token", default="", help="认证 Token（默认从 GATEWAY_TOKEN 环境变量读取）")
    parser.add_argument("--user", "-u", default="", help="用户 ID（不传则交互式输入）")
    parser.add_argument("--debug", action="store_true", help="调试模式")

    parsed = parser.parse_args(args)

    if parsed.debug:
        logging.basicConfig(level=logging.DEBUG)
    else:
        # 非调试模式：抑制日志输出，避免污染 TUI 画面
        logging.basicConfig(level=logging.CRITICAL)

    # ── Token：CLI 参数 > 环境变量 ──────────────────────────────
    token = parsed.token or os.environ.get("GATEWAY_TOKEN", "")

    # ── 身份登录 ───────────────────────────────────────────────
    user_id = parsed.user
    if not user_id:
        print("\n  xiaomei-brain TUI\n")
        while not user_id:
            try:
                inp = input("  login: ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return
            if inp:
                user_id = inp

    from xiaomei_brain.tui.app import TUIApp

    app = TUIApp(
        host=parsed.host,
        port=parsed.port,
        token=token,
        user_id=user_id,
    )

    try:
        asyncio.run(app.run())
    except KeyboardInterrupt:
        pass
    except Exception as e:
        logger.error("TUI fatal: %s", e, exc_info=True)
        print(f"[错误] {e}", file=sys.stderr)
        sys.exit(1)
