"""无意识系统 CLI 启动脚本。

使用方法：
    PYTHONPATH=src python3 examples/run_unconscious.py --name xiaomei
    PYTHONPATH=src python3 examples/run_unconscious.py --name xiaoming
"""

from __future__ import annotations

import argparse
import atexit
import logging
import os
import readline
import signal
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ["HF_HUB_OFFLINE"] = "1"

# ── 日志：输出到 stderr ──────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stderr,
)

# ── 噪音模块 ────────────────────────────────────────────────
class NoiseFilter(logging.Filter):
    _NOISY = {"urllib3", "httpx", "httpcore", "openai", "requests", "sentence_transformers"}
    _last_logged: dict[str, float] = {}
    _INTERVAL = 3.0

    def __init__(self):
        super().__init__()
        import time as _t
        self._now = _t.time

    def filter(self, record):
        module = record.name.split(".")[0] if record.name else ""
        if module not in self._NOISY:
            return True
        now = self._now()
        last = self._last_logged.get(module, 0)
        if now - last > self._INTERVAL:
            self._last_logged[module] = now
            return True
        if record.levelno >= logging.WARNING:
            return True
        return False

logging.getLogger().addFilter(NoiseFilter())


def main():
    parser = argparse.ArgumentParser(description="无意识系统 — AgentLiving 交互模式")
    parser.add_argument("--name", "-a", type=str, default="xiaomei", help="Agent ID")
    args = parser.parse_args()

    agent_id = args.name

    from xiaomei_brain.agent.agent_manager import AgentManager
    manager = AgentManager()

    available = [a.id for a in manager.list()]
    if agent_id not in available:
        print(f"\033[31m[错误] agent '{agent_id}' 不存在。可用: {', '.join(available)}\033[0m")
        return

    # ── Per-agent 日志 ────────────────────────────────────────
    agent_log_dir = os.path.expanduser(f"~/.xiaomei-brain/{agent_id}/logs")
    os.makedirs(agent_log_dir, exist_ok=True)
    _file_handler = logging.FileHandler(os.path.join(agent_log_dir, "agent.log"), encoding="utf-8")
    _file_handler.setLevel(logging.DEBUG)
    _file_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(name)s] %(levelname)s %(message)s", datefmt="%H:%M:%S"
    ))
    logging.getLogger().addHandler(_file_handler)

    from xiaomei_brain.base.llm import set_log_agent as _set_llm_log
    _set_llm_log(agent_id)

    # CLI 历史
    _hist_path = os.path.join(agent_log_dir, "cli_history")
    if os.path.exists(_hist_path):
        try:
            readline.read_history_file(_hist_path)
        except Exception:
            pass
    atexit.register(lambda p=_hist_path: readline.write_history_file(p))

    # ── 启动 AgentLiving ──────────────────────────────────────
    instance = manager.build_agent(agent_id)
    agent_name = instance.name or agent_id

    from xiaomei_brain.unconscious.living import AgentLiving, AgentState
    from xiaomei_brain.base.llm import get_llm_call_count

    living = AgentLiving(instance)
    living_ref = living

    def _on_sigint(signum, frame):
        living_ref.cancel()
        print("\n[Ctrl+C] 正在取消...", flush=True)

    living.on_wake = lambda: print("[阶段] WAKING - 初始化中...")
    living.on_proactive = lambda msg: print(f"\n[{agent_name}主动] {msg.content}\n")
    living.on_wake_up = lambda: print("[阶段] AWAKE - 收到消息唤醒")
    living.on_sleep = lambda: print("[阶段] SLEEPING - 空闲中，等待...")
    living.on_dream = lambda: print("[阶段] DREAMING - 梦境处理中...")
    living.on_dream_end = lambda: print("[阶段] DREAMING 完成，返回 SLEEPING")
    living.on_chat_chunk = lambda chunk: print(chunk, end="", flush=True)

    living.state = AgentState.WAKING
    living._on_wake()
    living.state = AgentState.AWAKE

    print("\n" + "=" * 50)
    print(f"       \033[33mAgentLiving\033[0m（无意识系统）— \033[1m{agent_name}\033[0m")
    print("=" * 50)
    print(f"[阶段] AWAKE - 准备就绪 | LLM calls: {get_llm_call_count()}")
    print("=" * 50 + "\n")

    signal.signal(signal.SIGINT, _on_sigint)

    from xiaomei_brain.agent.message_utils import clean_input
    print(f"输入消息跟{agent_name}对话 (q退出，↑↓翻历史):")
    while True:
        signal.signal(signal.SIGINT, signal.SIG_DFL)
        try:
            raw_input = input("You: ")
        except (KeyboardInterrupt, EOFError):
            print()
            break
        finally:
            signal.signal(signal.SIGINT, _on_sigint)

        user_input = clean_input(raw_input).strip()
        if not user_input:
            continue
        if user_input.lower() in ("q", "quit", "exit"):
            break

        # /image <path> [text]
        images = []
        if user_input.startswith("/image "):
            parts = user_input[7:].strip()
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

        import time as _time
        while True:
            msg = living._wait_message(timeout=0)
            if msg is None:
                break
            living._handle_message(msg)
            living._last_active = _time.time()

        print(f"\033[1A\033[K[LLM calls: {get_llm_call_count()}]")


if __name__ == "__main__":
    main()
