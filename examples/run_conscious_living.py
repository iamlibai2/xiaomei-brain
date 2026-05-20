"""ConsciousLiving CLI 启动脚本。

启动带意识的 Agent，支持交互对话和测试命令。

Usage:
    PYTHONPATH=src python3 examples/run_conscious_living.py --name xiaomei
    PYTHONPATH=src python3 examples/run_conscious_living.py --name xiaoming
    PYTHONPATH=src python3 examples/run_conscious_living.py -n  # 无意识模式
"""

import sys
import os
import select
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

# agent 日志文件 handler — agent_id 已知后添加

# 开发中：不做日志过滤，所有模块 INFO 全部输到 stderr

from xiaomei_brain.agent.agent_manager import AgentManager
from xiaomei_brain.consciousness.conscious_living import ConsciousLiving
from xiaomei_brain.memory.conversation_db import estimate_tokens

# ── 提示符（必须纯 ASCII，WSL 下 readline 无法正确计算中文 prompt 宽度）──
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
    "/sessions", "/switch ",
]


def _completer(text: str, state: int) -> str | None:
    matches = [c for c in _COMMANDS if c.startswith(text)]
    if state < len(matches):
        return matches[state]
    return None


readline.parse_and_bind("tab: complete")
readline.parse_and_bind("set enable-bracketed-paste on")  # 消除终端多行粘贴警告
readline.parse_and_bind("set input-meta on")
readline.parse_and_bind("set output-meta on")
readline.parse_and_bind("set convert-meta off")
readline.set_completer(_completer)


# ── 多行粘贴检测 ─────────────────────────────────────────
def _read_multiline(first_line: str, timeout: float = 0.05) -> str:
    """检测粘贴多行文本并一次性读取。

    粘贴时 stdin 缓冲区会有多行数据。先读取首行，再用 select 检测
    是否有更多数据，有则一次性读完并合并。
    """
    # select 检测 stdin 是否还有数据
    r, _, _ = select.select([sys.stdin], [], [], timeout)
    if not r:
        return first_line

    # 读取剩余行，拼接
    lines = [first_line]
    while True:
        r, _, _ = select.select([sys.stdin], [], [], timeout)
        if not r:
            break
        line = sys.stdin.readline()
        if not line:
            break
        line = line.rstrip('\n')
        lines.append(line)

    result = '\n'.join(lines)
    if len(lines) > 1:
        # 多行粘贴，加入 history
        try:
            readline.add_history(result)
        except Exception:
            pass
    return result


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
        "--name", "-a",
        default="xiaomei",
        help="Agent ID to start (e.g. xiaomei, xiaoming)"
    )
    parser.add_argument(
        "-n", "--no-consciousness",
        action="store_true",
        help="生命存在但无意识（无意识模式）"
    )
    parser.add_argument(
        "--legacy",
        action="store_true",
        help="使用旧 context_assembler 格式的上下文注入（找回旧版小美）"
    )
    parser.add_argument(
        "--port", "-p",
        type=int,
        default=0,
        help="通讯端口（0=自动分配, -1=禁用, >0=指定端口）"
    )
    args = parser.parse_args()

    agent_id = args.name

    # ── Per-agent 日志 ────────────────────────────────────────
    agent_log_dir = os.path.expanduser(f"~/.xiaomei-brain/{agent_id}/logs")
    os.makedirs(agent_log_dir, exist_ok=True)
    _file_handler = logging.FileHandler(os.path.join(agent_log_dir, "agent.log"), encoding="utf-8")
    _file_handler.setLevel(logging.DEBUG)
    _file_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(name)s] %(levelname)s %(message)s", datefmt="%H:%M:%S"
    ))
    logging.getLogger().addHandler(_file_handler)

    # LLM 日志 + intent 日志按 agent 分
    from xiaomei_brain.base.llm import set_log_agent as _set_llm_log
    from xiaomei_brain.consciousness.task_orchestrator import set_log_agent as _set_intent_log
    _set_llm_log(agent_id)
    _set_intent_log(agent_id)

    # CLI 历史
    _hist_path = os.path.join(agent_log_dir, "cli_history")
    if os.path.exists(_hist_path):
        try:
            readline.read_history_file(_hist_path)
        except Exception:
            pass
    atexit.register(lambda p=_hist_path: readline.write_history_file(p))
    # ────────────────────────────────────────────────────────

    manager = AgentManager()

    # 验证 agent 是否存在
    available = [a.id for a in manager.list()]
    if agent_id not in available:
        print(f"\033[31m[错误] agent '{agent_id}' 不存在。可用: {', '.join(available)}\033[0m")
        return

    agent = manager.build_agent(agent_id)
    agent_name = agent.name or agent_id

    print("\n" + "=" * 50)
    print(f"       \033[36mConsciousLiving\033[0m CLI — \033[1m{agent_name}\033[0m")
    print("=" * 50)
    if args.no_consciousness:
        print("       \033[33m[无意识模式]\033[0m")
    if args.legacy:
        print("       \033[33m[Legacy 上下文模式]\033[0m")
    print("=" * 50 + "\n")

    # 通讯端口：CLI > config.json > 自动分配
    comms_port = args.port  # 0=自动, -1=禁用, >0=指定
    if comms_port == 0:
        # 从 config.json 读取 per-agent 端口
        config_json = os.path.expanduser("~/.xiaomei-brain/config.json")
        if os.path.exists(config_json):
            try:
                import json
                with open(config_json) as f:
                    data = json.load(f)
                agents_cfg = data.get("xiaomei_brain", {}).get("agents", {})
                agent_cfg = agents_cfg.get(agent_id, {})
                comms_port = agent_cfg.get("comms_port", 0)
            except Exception:
                pass

    from xiaomei_brain.consciousness.config import LivingConfig
    cfg = LivingConfig()
    cfg.living.comms_port = comms_port
    living = ConsciousLiving(agent, load_consciousness=not args.no_consciousness, config=cfg)
    living.assemble_context = True

    if args.legacy:
        living.force_mode = "legacy"

    # ── 回调 ────────────────────────────────────────────────
    _stream_lock = threading.Lock()

    def on_proactive(content):
        with _stream_lock:
            print(f"\n\033[33m[{agent_name}]\033[0m {content}\n", end="", flush=True)

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
                try:
                    bar_w = os.get_terminal_size().columns
                except Exception:
                    bar_w = 78
                print("\033[90m" + "─" * bar_w + "\033[0m")
                # 用纯 ASCII prompt，中文 agent 名已在状态行显示
                # WSL 下 readline 无法正确计算中文 prompt 的显示宽度，
                # 导致回删中文时字节错位，输入内容损坏
                first_line = input(PROMPT)
                msg = _read_multiline(first_line)
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
