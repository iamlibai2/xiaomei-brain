"""xiaomei-brain CLI entry point.

Usage:
    python -m xiaomei_brain run <agent_id>
    python -m xiaomei_brain run <agent_id> --cli   # attach CLI input
"""

from __future__ import annotations

import argparse
import atexit
import os
import readline
import logging
import os
import signal
import sys


def cmd_run(agent_id: str, attach_cli: bool = False) -> None:
    """Start a living agent."""
    os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
    os.environ["HF_HUB_OFFLINE"] = "1"

    from xiaomei_brain.agent.agent_manager import AgentManager
    from xiaomei_brain.agent.living import AgentLiving
    from xiaomei_brain.base.llm import get_llm_call_count

    base_dir = os.path.expanduser("~/.xiaomei-brain")
    manager = AgentManager(base_dir=base_dir)

    print(f"[Living] Building agent: {agent_id}")
    instance = manager.build_agent(agent_id)

    print(f"[Living] ID:       {instance.id}")
    print(f"[Living] Name:     {instance.name}")
    print(f"[Living] Tools:    {[t.name for t in instance.tools.list_tools()]}")
    print()

    living = AgentLiving(instance)

    # ── SIGINT 处理：Ctrl+C 取消 ReAct 循环，不退出程序 ──────────
    living_ref = living  # 闭包引用

    def _on_sigint(signum, frame):
        living_ref.cancel()
        print("\n[Ctrl+C] 正在取消...", flush=True)

    if attach_cli:
        from xiaomei_brain.agent.living import AgentState
        living.on_wake = lambda: print("[阶段] WAKING - 初始化中...")
        living.on_proactive = lambda msg: print(f"\n[小美主动] {msg.content}\n")
        living.on_wake_up = lambda: print("[阶段] AWAKE - 收到消息唤醒")
        living.on_sleep = lambda: print("[阶段] SLEEPING - 空闲中，等待...")
        living.on_dream = lambda: print("[阶段] DREAMING - 梦境处理中...")
        living.on_dream_end = lambda: print("[阶段] DREAMING 完成，返回 SLEEPING")
        living.on_chat_chunk = lambda chunk: print(chunk, end="", flush=True)

        # 手动触发启动流程（CLI 模式不走 living.run() 的循环）
        living.state = AgentState.WAKING
        living._on_wake()  # 触发 proactive.check(WAKE) + 问候 + 记忆
        living.state = AgentState.AWAKE
        print(f"[阶段] AWAKE - 准备就绪 | LLM calls: {get_llm_call_count()}")
        # 启用 readline 历史（上下键翻历史）
        hist_path = os.path.expanduser("~/.xiaomei-brain/cli_history")
        if os.path.exists(hist_path):
            readline.read_history_file(hist_path)
        atexit.register(readline.write_history_file, hist_path)

        # 安装 SIGINT handler：ReAct 循环中 Ctrl+C → cancel()
        signal.signal(signal.SIGINT, _on_sigint)

        print("输入消息跟小美对话 (q退出，↑↓翻历史):")
        while True:
            # 暂时恢复默认 SIGINT，让 input() 正常触发 KeyboardInterrupt
            signal.signal(signal.SIGINT, signal.SIG_DFL)
            try:
                raw_input = input("You: ")
            except (KeyboardInterrupt, EOFError):
                print()
                break
            finally:
                # 重新安装自定义 handler
                signal.signal(signal.SIGINT, _on_sigint)

            from xiaomei_brain.agent.message_utils import clean_input
            user_input = clean_input(raw_input).strip()

            if not user_input:
                continue
            if user_input.lower() in ("q", "quit", "exit"):
                break

            # /image <path> [text] — 发送图片
            images = []
            if user_input.startswith("/image "):
                parts = user_input[7:].strip()
                # 找到图片路径（空格分隔的第一段）
                # 路径可能包含空格但没引号 → 简化：取第一个"看起来像路径"的部分
                space_idx = parts.find(" ")
                if space_idx > 0:
                    img_path = parts[:space_idx]
                    text = parts[space_idx:].strip()
                else:
                    img_path = parts
                    text = ""
                images.append(img_path)
                user_input = text or "请看这张图片"
                print(f"[图片] {img_path}")

            living.put_message(user_input, source="cli", images=images)

            # Process all pending messages synchronously
            while True:
                msg = living._wait_message(timeout=0)
                if msg is None:
                    break
                living._handle_message(msg)
                living._last_active = __import__("time").time()

            # 打印 LLM 调用次数到"输入框下方"
            print(f"\033[1A\033[K[LLM calls: {get_llm_call_count()}]")  # 光标上移1行，清行，打印计数
    else:
        living.run()


def main():
    parser = argparse.ArgumentParser(
        prog="xiaomei-brain",
        description="xiaomei-brain: multi-agent AI brain framework",
    )
    sub = parser.add_subparsers(dest="command")

    # run
    run_parser = sub.add_parser("run", help="Start a living agent")
    run_parser.add_argument("agent_id", help="Agent ID to start (e.g. xiaomei)")
    run_parser.add_argument(
        "--cli", action="store_true",
        help="Attach CLI input for interactive chat",
    )

    args = parser.parse_args()

    import os
    log_dir = os.path.expanduser("~/.xiaomei-brain/logs")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "xiaomei.log")

    # Console: INFO only; File: DEBUG (full detail)
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    for h in root.handlers[:]:
        root.removeHandler(h)
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(name)s] %(levelname)s %(message)s", datefmt="%H:%M:%S"
    ))
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(name)s] %(levelname)s %(message)s", datefmt="%H:%M:%S"
    ))
    root.addHandler(file_handler)
    root.addHandler(console_handler)

    if args.command == "run":
        cmd_run(args.agent_id, attach_cli=args.cli)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
