"""ConsciousLiving CLI 启动脚本。

启动带意识的 Agent，支持交互对话和测试命令。

Usage:
    PYTHONPATH=src python3 examples/run_conscious_living.py [--no-consciousness]
    PYTHONPATH=src python3 examples/run_conscious_living.py -n  # 无意识模式
"""

import sys
import os
import threading
import time
import logging
import readline
import atexit
import argparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

# ── 日志：输出到 stderr ──────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stderr,
)

# 同时写到 xiaomei.log（DEBUG 级别，应有尽有）
_log_dir = os.path.expanduser("~/.xiaomei-brain/logs")
os.makedirs(_log_dir, exist_ok=True)
_file_handler = logging.FileHandler(os.path.join(_log_dir, "xiaomei.log"), encoding="utf-8")
_file_handler.setLevel(logging.DEBUG)
_file_handler.setFormatter(logging.Formatter(
    "%(asctime)s [%(name)s] %(levelname)s %(message)s", datefmt="%H:%M:%S"
))
logging.getLogger().addHandler(_file_handler)

# ── 关键模块：完全放行 ──────────────────────────────────────
KEY_MODULES = {
    "xiaomei_brain.consciousness.conscious_living",
    "xiaomei_brain.purpose",
    "xiaomei_brain.drive",
    "xiaomei_brain.consciousness.core",
    "xiaomei_brain.agent.agent_manager",
}

# ── 噪音模块：3秒内同类日志只显示一次 ───────────────────────
NOISE_MODULES = {
    "xiaomei_brain.memory.longterm",
    "xiaomei_brain.consciousness.context_assembler",
    "xiaomei_brain.memory.conversation_db",
    "xiaomei_brain.agent.core",
    "xiaomei_brain.base.llm",
    "xiaomei_brain.memory.extractor",
    "sentence_transformers",
    "xiaomei_brain.tools",
    "xiaomei_brain.ws",
}

_last_log: dict[str, float] = {}
_LOG_DEDUP_INTERVAL = 3.0


class NoiseFilter(logging.Filter):
    def filter(self, record):
        module = record.name
        for key in KEY_MODULES:
            if module.startswith(key):
                return True
        for noise in NOISE_MODULES:
            if module.startswith(noise):
                msg_short = record.getMessage()[:80]
                dedup_key = f"{module}:{msg_short}"
                now = time.time()
                last = _last_log.get(dedup_key, 0)
                if now - last < _LOG_DEDUP_INTERVAL:
                    return False
                _last_log[dedup_key] = now
                return True
        return True


logging.getLogger().addFilter(NoiseFilter())

from xiaomei_brain.agent.agent_manager import AgentManager
from xiaomei_brain.consciousness.conscious_living import ConsciousLiving
from xiaomei_brain.memory.conversation_db import estimate_tokens

# ── ❯ 提示符 ───────────────────────────────────────────────
PROMPT = "> "

# ── Tab 命令补齐 ───────────────────────────────────────────
_COMMANDS = [
    "/intent", "/fuel", "/flame", "/tick", "/think", "/identity",
    "/drive", "/purpose", "/plan",
    "/db", "/memory", "/context", "/dag", "/summarize", "/periodic", "/dream",
    "/tool ", "/tool list",
    "/export", "/model",
    "/help", "/exit", "/quit",
    "/clear", "/new", "/users",
]


def _completer(text: str, state: int) -> str | None:
    matches = [c for c in _COMMANDS if c.startswith(text)]
    if state < len(matches):
        return matches[state]
    return None


# ── readline 历史 ──────────────────────────────────────────
_HIST_DIR = os.path.expanduser("~/.xiaomei-brain/logs")
os.makedirs(_HIST_DIR, exist_ok=True)
_HIST_PATH = os.path.join(_HIST_DIR, "cli_history")
if os.path.exists(_HIST_PATH):
    try:
        readline.read_history_file(_HIST_PATH)
    except Exception:
        pass
atexit.register(lambda: readline.write_history_file(_HIST_PATH))
readline.parse_and_bind("tab: complete")
readline.parse_and_bind("set input-meta on")
readline.parse_and_bind("set output-meta on")
readline.parse_and_bind("set convert-meta off")
readline.set_completer(_completer)


# ── Token 估算 ─────────────────────────────────────────────
def _count_context_tokens(all_messages) -> int:
    """估算消息列表的总 token 数（CJK * 1.5 + ASCII / 4）"""
    total = 0
    for m in all_messages:
        content = m.get("content", "")
        if isinstance(content, str):
            total += estimate_tokens(content)
        for tc in m.get("tool_calls", []):
            args = str(tc.get("function", {}).get("arguments", ""))
            total += estimate_tokens(args)
    return total


def _status_line(living) -> str:
    """生成提示符上方的状态行"""
    parts = []

    # 目标
    purpose = living.purpose
    if purpose and purpose.current_goal:
        g = purpose.current_goal
        if g.parent_id:
            siblings = purpose.get_sub_goals(g.parent_id)
            done = sum(1 for s in siblings if s.is_completed())
            total = len(siblings)
            bar_w = 8
            filled = int(bar_w * done / total) if total else 0
            bar = "█" * filled + "░" * (bar_w - filled)
            parts.append(f"{g.description[:25]} {bar} {done}/{total}")
        else:
            parts.append(g.description[:25])

    # 火焰（仅当意识系统已加载时显示）
    if hasattr(living, '_load_consciousness') and living._load_consciousness:
        si = living.consciousness.get_self_image()
        if si:
            parts.append(f"🔥{si.perception.agent_state} e:{si.body.energy:.1f}")

    # Drive
    drive = getattr(living, 'drive', None)
    if drive and hasattr(drive, 'desire'):
        d = drive.desire
        parts.append(f"b:{d.belonging:.1f} c:{d.cognition:.1f}")

    # 今日代码量
    try:
        db = getattr(living.agent, 'conversation_db', None)
        if db:
            stats = db.get_today_code_stats()
            if stats["added"] or stats["removed"]:
                parts.append(f"code:+{stats['added']}/-{stats['removed']}")
    except Exception:
        pass

    # 上下文 token
    try:
        core = living.agent._get_agent()
        msgs = getattr(core, '_last_all_messages', None)
        if msgs:
            tokens = _count_context_tokens(msgs)
            parts.append(f"上下文:{tokens//1000}k")
    except Exception:
        pass

    if not parts:
        return ""
    return "  ".join(parts)


def main():
    parser = argparse.ArgumentParser(description="ConsciousLiving CLI")
    parser.add_argument(
        "-n", "--no-consciousness",
        action="store_true",
        help="生命存在但无意识（无意识模式）"
    )
    args = parser.parse_args()

    print("\n" + "=" * 50)
    print("       \033[36mConsciousLiving\033[0m CLI")
    print("=" * 50)
    if args.no_consciousness:
        print("       \033[33m[无意识模式]\033[0m")
    print("=" * 50 + "\n")

    manager = AgentManager()
    agent = manager.build_agent("xiaomei")
    living = ConsciousLiving(agent, load_consciousness=not args.no_consciousness)

    # 上下文组装开关：False 时跳过 DAG/长期记忆/system prompt，只保留原始消息
    living.assemble_context = True

    # ── 回调 ────────────────────────────────────────────────
    _stream_lock = threading.Lock()

    def on_proactive(content):
        with _stream_lock:
            print(f"\n\033[33m[小美]\033[0m {content}\n", end="", flush=True)

    def on_chat_chunk(chunk):
        with _stream_lock:
            print(chunk, end="", flush=True)

    living.on_proactive = on_proactive
    living.on_chat_chunk = on_chat_chunk

    print("命令: /intent | /fuel | /flame | /tick | /identity")
    print("存储: /db | /memory | /context | /dag")
    print("任务: !描述 (直接创建目标)")
    print()
    print("工具: tool <N> | tool list")
    print("管理: drive | purpose | clear | new | users")
    print()

    # ── 后台启动 ────────────────────────────────────────────
    thread = threading.Thread(target=living.run, daemon=True)
    thread.start()
    time.sleep(2)

    _DOUBLE_PRESS_WINDOW = 2.0
    _last_interrupt = 0.0

    try:
        while living.is_running:
            try:
                status = _status_line(living)
                if status:
                    print(f"\n\033[90m{status}\033[0m", flush=True)
                # 98% 宽度实心线
                try:
                    cols = os.get_terminal_size().columns
                    bar_w = os.get_terminal_size().columns
                except Exception:
                    bar_w = 78
                print("\033[90m" + "─" * bar_w + "\033[0m")
                msg = input(f"{PROMPT}")
            except (KeyboardInterrupt, EOFError):
                print()
                now = time.time()
                if now - _last_interrupt < _DOUBLE_PRESS_WINDOW:
                    print("\033[31m强制退出\033[0m")
                    living.stop()
                    break
                _last_interrupt = now
                living.cancel()
                print("\033[90m[取消] 已中断当前操作 (再次 Ctrl+C 退出)\033[0m")
                continue

            msg = msg.strip()
            if msg.lower() in ("exit", "quit", "stop"):
                print("\033[90m正在停止...\033[0m")
                living.stop()
                break
            if not msg:
                continue

            # /image <path> [text] — 发送图片
            images = []
            if msg.startswith("/image "):
                parts = msg[7:].strip()
                space_idx = parts.find(" ")
                if space_idx > 0:
                    img_path = parts[:space_idx]
                    text = parts[space_idx:].strip()
                else:
                    img_path = parts
                    text = ""
                images.append(img_path)
                msg = text or "请看这张图片"
                print(f"[图片] {img_path}")

            living._command_done.clear()
            living.put_message(msg, images=images)

            # 命令消息：等 living 线程处理完再刷新
            if msg.startswith("/"):
                living._command_done.wait(timeout=3)

            # 等待 chat 完成（_chatting 由 living 线程管理）
            while living._chatting:
                time.sleep(0.1)

            # ── Token 用量移到了状态栏 ─────────────────────

    except KeyboardInterrupt:
        print("\n\033[90m正在停止...\033[0m")
        living.stop()

    try:
        thread.join(timeout=5)
    except KeyboardInterrupt:
        print("\n\033[90m强制中断，等待线程退出...\033[0m")
        thread.join(timeout=2)
    print("\033[90m已停止\033[0m")


if __name__ == "__main__":
    main()
