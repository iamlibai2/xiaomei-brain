"""xiaomei-brain CLI entry point.

Usage:
    python -m xiaomei_brain run <agent_id>
    python -m xiaomei_brain run <agent_id> --cli   # attach CLI input
"""

from __future__ import annotations

import argparse
import logging
import os
import sys


def cmd_run(agent_id: str, attach_cli: bool = False) -> None:
    """Start a living agent."""
    os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
    os.environ["HF_HUB_OFFLINE"] = "1"

    from xiaomei_brain.agent.agent_manager import AgentManager
    from xiaomei_brain.agent.living import AgentLiving

    base_dir = os.path.expanduser("~/.xiaomei-brain")
    manager = AgentManager(base_dir=base_dir)

    print(f"[Living] Building agent: {agent_id}")
    instance = manager.build_agent(agent_id)

    print(f"[Living] ID:       {instance.id}")
    print(f"[Living] Name:     {instance.name}")
    print(f"[Living] Tools:    {[t.name for t in instance.tools.list_tools()]}")
    print()

    living = AgentLiving(instance)

    if attach_cli:
        from xiaomei_brain.agent.living import AgentState
        living.on_wake = lambda: print("[阶段] WAKING - 初始化中...")
        living.on_proactive = lambda msg: print(f"\n[小美主动] {msg.content}\n")
        living.on_wake_up = lambda: print("[阶段] AWAKE - 收到消息唤醒")
        living.on_sleep = lambda: print("[阶段] SLEEPING - 空闲中，等待...")
        living.on_dream = lambda: print("[阶段] DREAMING - 梦境处理中...")
        living.on_dream_end = lambda: print("[阶段] DREAMING 完成，返回 SLEEPING")
        _chunk_count = [0]
        def _print_chunk(chunk):
            _chunk_count[0] += 1
            import sys
            sys.stderr.write(f"[CHUNK #{_chunk_count[0]}] ")
            sys.stderr.write(repr(chunk[:30]))
            sys.stderr.write("\n")
            print(chunk, end="", flush=True)
        living.on_chat_chunk = _print_chunk

        # 手动触发启动流程（CLI 模式不走 living.run() 的循环）
        living.state = AgentState.WAKING
        living._on_wake()  # 触发 proactive.check(WAKE) + 问候 + 记忆
        living.state = AgentState.AWAKE
        print("[阶段] AWAKE - 准备就绪")
        print("输入消息跟小美对话 (q退出):")
        while True:
            try:
                raw_input = input("You: ")
            except (KeyboardInterrupt, EOFError):
                print()
                break

            # 清理控制字符 + 退格处理
            buf: list[str] = []
            for ch in raw_input:
                if ch == "\x08" or ch == "\x7f":
                    if buf:
                        buf.pop()
                elif ord(ch) < 0x20 and ch not in ("\t", "\n", "\r"):
                    pass
                else:
                    buf.append(ch)
            user_input = "".join(buf)

            # 移除 UTF-16LE 编码异常混入的孤立 Trail 字节（\udc80~\udcff）
            # WSL/WSL2 终端输入法在某些键位下会残留这类字节
            user_input = "".join(
                c for c in user_input
                if not ("\udc80" <= c <= "\udcff")
            ).strip()

            if not user_input:
                continue
            if user_input.lower() in ("q", "quit", "exit"):
                break

            living.put_message(user_input, source="cli")

            # Process all pending messages synchronously
            while True:
                msg = living._wait_message(timeout=0)
                if msg is None:
                    break
                living._handle_message(msg)
                living._last_active = __import__("time").time()
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
