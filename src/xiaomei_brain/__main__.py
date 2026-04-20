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
        living.on_proactive = lambda msg: print(f"\n[小美主动] {msg.content}\n")
        living.on_chat_chunk = lambda chunk: print(chunk, end="", flush=True)

        # Simple interactive loop: input → put_message → poll for response
        print("输入消息跟小美对话 (q退出):")
        while True:
            try:
                raw = input("You: ")
            except (KeyboardInterrupt, EOFError):
                print()
                break
            if raw.strip().lower() in ("q", "quit", "exit"):
                break
            if not raw.strip():
                continue

            living.put_message(raw, source="cli")

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

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    if args.command == "run":
        cmd_run(args.agent_id, attach_cli=args.cli)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
