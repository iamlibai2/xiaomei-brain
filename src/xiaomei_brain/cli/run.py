"""xiaomei-brain run — 启动并交互式运行 Agent。

Usage:
    xiaomei-brain run <agent_id> [--cli] [--no-consciousness] [--legacy] [--port <port>]
"""

from __future__ import annotations

import argparse
import atexit
import logging
import os
import readline
import select
import shutil
import sys
import threading
import time

from xiaomei_brain.agent.agent_manager import AgentManager
from xiaomei_brain.llm.client import FatalLLMError
from xiaomei_brain.base.message_utils import estimate_tokens
from xiaomei_brain.consciousness.conscious_living import ConsciousLiving

# ── 提示符（纯 ASCII，WSL 下 readline 无法正确计算中文 prompt 宽度）──
PROMPT = "❯ "

# ── 项目主体色（256 色）────────────────────────────────────
C_ACCENT = "\033[38;5;203m"   # coral pink（主体色：退出/交互提示）
C_ACCENT2 = "\033[38;5;73m"  # dusty teal（搭配色：身份/标题）
C_CONTENT = "\033[38;5;250m" # light silver gray（Agent 输出）

# ── Tab 命令补齐 ───────────────────────────────────────────
_COMMANDS = [
    "/intent", "/fuel", "/flame", "/tick", "/think", "/identity",
    "/drive", "/purpose", "/plan", "/intask", "/inchat",
    "/db", "/memory", "/context", "/dag", "/summarize", "/periodic", "/dream",
    "/tool ", "/tool list",
    "/export", "/model",
    "/help", "/exit", "/quit",
    "/clear", "/new", "/users",
    "/sessions", "/switch ",
    "/eyes", "/ears", "/see ", "/hear ", "/l", "/touch",
]


def _completer(text: str, state: int) -> str | None:
    matches = [c for c in _COMMANDS if c.startswith(text)]
    if state < len(matches):
        return matches[state]
    return None


readline.parse_and_bind("tab: complete")
readline.parse_and_bind("set enable-bracketed-paste on")
readline.parse_and_bind("set input-meta on")
readline.parse_and_bind("set output-meta on")
readline.parse_and_bind("set convert-meta off")
readline.set_completer(_completer)


# ── 多行粘贴检测 ─────────────────────────────────────────

def _read_multiline(first_line: str, timeout: float = 0.05) -> str:
    """检测粘贴多行文本并一次性读取。"""
    r, _, _ = select.select([sys.stdin], [], [], timeout)
    if not r:
        return first_line

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

    if hasattr(living, '_load_consciousness') and living._load_consciousness:
        si = living.consciousness.get_self_image()
        if si:
            parts.append(f"🔥{si.perception.agent_state} e:{si.body.energy:.1f}")

    drive = getattr(living, 'drive', None)
    if drive and hasattr(drive, 'desire'):
        d = drive.desire
        parts.append(f"b:{d.belonging:.1f} c:{d.cognition:.1f}")

    try:
        db = getattr(living.agent, 'conversation_db', None)
        if db:
            stats = db.get_today_code_stats()
            if stats["added"] or stats["removed"]:
                parts.append(f"code:+{stats['added']}/-{stats['removed']}")
    except Exception:
        pass

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


# ── 启动 Agent ────────────────────────────────────────────────

def _run_agent(
    living: ConsciousLiving,
    agent,
    agent_id: str,
    agent_name: str,
    no_consciousness: bool = False,
    legacy: bool = False,
) -> None:
    """启动 Agent 主循环（CLI 交互模式）。"""
    _stream_lock = threading.Lock()
    _login_done = threading.Event()
    _pending_proactive: list[tuple[str, str]] = []  # [(content, user_id), ...]
    _MAX_PENDING = 200  # 防止长时间未登录积压大量消息

    _in_thinking = False  # 跟踪 LLM 输出是否处于思考段
    _para_buf = ""        # 段落缓冲（按 \n\n 拆分渲染）

    # Rich console for paragraph-based markdown rendering
    from rich.console import Console as _RichConsole
    from rich.markdown import Markdown as _RichMarkdown
    _rich_console = _RichConsole(highlight=False)

    _term_width = shutil.get_terminal_size().columns

    def _render_proactive(content: str) -> None:
        """以对话回复统一格式渲染主动消息。"""
        print("\n\033[90m" + "─" * _term_width + "\033[0m", flush=True)
        print(f"  \033[38;5;203m{agent_name}\033[0m: ", end="", flush=True)
        _rich_console.print(_RichMarkdown(content, code_theme="monokai"))

    def on_proactive(content, user_id=""):
        with _stream_lock:
            if _login_done.is_set():
                _render_proactive(content)
            else:
                if len(_pending_proactive) >= _MAX_PENDING:
                    _pending_proactive.pop(0)
                _pending_proactive.append((content, user_id))

    def _count_open_fences(text: str) -> int:
        """统计代码围栏是否打开。返回1表示当前在围栏内（奇数个```）。"""
        count = 0
        for line in text.split("\n"):
            stripped = line.strip()
            if stripped.startswith("```") or stripped.startswith("~~~"):
                count += 1
        return count & 1

    def _split_stable(text: str) -> tuple[str, str]:
        """在代码围栏外的第一个 \\n\\n 处切分。返回 (paragraph, rest)。"""
        idx = 0
        while True:
            pos = text.find("\n\n", idx)
            if pos == -1:
                return text, ""
            before = text[:pos]
            if not _count_open_fences(before):
                return before, text[pos + 2:]
            idx = pos + 2

    def _render_para(text: str) -> None:
        """渲染一个段落，交 Rich Markdown。"""
        t = text.strip()
        if t:
            _rich_console.print(_RichMarkdown(t, code_theme="monokai"))

    def _flush_para():
        nonlocal _para_buf
        _render_para(_para_buf)
        _para_buf = ""

    def on_chat_chunk(chunk):
        nonlocal _in_thinking, _para_buf
        with _stream_lock:
            # 思考段由 stream_iter 用 \033[2m (dim) 标记，保持原样
            if "\033[2m" in chunk:
                _in_thinking = True
            if "\033[0m" in chunk:
                _in_thinking = False

            if _in_thinking or "\033" in chunk:
                # 思考内容 / ANSI 控制码：先 flush 缓冲的段落，再原样输出
                _flush_para()
                print(chunk, end="", flush=True)
            else:
                _para_buf += chunk
                # 段落边界：只在代码围栏外切分
                while True:
                    para, rest = _split_stable(_para_buf)
                    if rest:
                        _render_para(para)
                        _rich_console.print()
                        _para_buf = rest
                    else:
                        break

    living.on_proactive = on_proactive
    living.on_chat_chunk = on_chat_chunk
    living.on_chat_flush = _flush_para

    thread = threading.Thread(target=living.run, daemon=True)
    thread.start()

    try:
        time.sleep(2)

        # ── 登录 ──────────────────────────────────────────────
        from xiaomei_brain.contacts.manager import IdentityManager
        contacts_dir = os.path.expanduser(f"~/.xiaomei-brain/{agent_id}/contacts")
        identity_mgr = IdentityManager(contacts_dir)
        ids = identity_mgr.list_ids()

        if ids:
            print()
            parts = []
            for i, uid in enumerate(ids, 1):
                info = identity_mgr._identities.get(uid, {})
                name = info.get("name", uid)
                parts.append(f"{C_ACCENT2}{i}. {name}\033[0m\033[90m({uid})\033[0m")
            print(f"  \033[90m请登录，可用身份：\033[0m " + " ".join(parts))
            print()

        user_id = None
        while not user_id:
            try:
                user_id = input("  login: ").strip()
            except (KeyboardInterrupt, EOFError):
                print("\r\033[K" + C_ACCENT + "  再见\033[0m", flush=True)
                import sys as _sys
                _sys.exit(0)

            if not user_id:
                continue

            # 尝试按序号选择
            try:
                idx = int(user_id) - 1
                if 0 <= idx < len(ids):
                    user_id = ids[idx]
            except ValueError:
                pass

            identity = identity_mgr.resolve(user_id)
            if identity:
                display_name = identity["name"]
                living.user_id = user_id
                agent_core = agent._get_agent()
                agent_core.user_id = user_id
                agent_core.user_display_name = display_name
                if hasattr(living, 'consciousness') and living.consciousness:
                    si = living.consciousness.get_self_image()
                    if si:
                        si.current_user_name = display_name
                        ltm = getattr(agent, 'longterm_memory', None)
                        si.load_preferred_names(user_id, ltm)
                print(f"\n  {C_ACCENT}你好，{display_name}\033[0m\n")
                # ── 等待 Embedding 模型就绪 ──────────────────
                ltm = getattr(agent, 'longterm_memory', None)
                if ltm and not ltm.is_embedder_ready():
                    print(f"  \033[90m[....] Embedding 模型加载中（首次约 20 秒），请稍候...\033[0m", flush=True)
                    ltm.wait_embedder()
                    print(f"  \033[90m[ OK ] Embedding 模型就绪\033[0m", flush=True)
                living.load_fresh_tail()
                if hasattr(living, '_attention') and living._attention:
                    cli_sid = f"cli-{agent_id}"
                    living._attention.save_session(cli_sid)
                    living._attention._current_session = cli_sid
                # 在 Router 注册 CLI peer，主动消息才能路由到 CLI
                if hasattr(living, '_router') and living._router:
                    living._router.register_peer(
                        peer_type="human", peer_id=user_id, channel="cli",
                        session_id=f"cli-{agent_id}",
                        output_type="cli", output_target="stdout",
                        priority=10,
                    )
            else:
                print(f"  \033[31m用户 '{user_id}' 不存在\033[0m", flush=True)
                user_id = None
    except KeyboardInterrupt:
        print("\r\033[K" + C_ACCENT + "  再见\033[0m", flush=True)
        living.stop()
        import sys as _sys
        _sys.exit(0)

    # 登录完成，重放登录期间缓冲的主动输出（仅当前用户）
    _login_done.set()
    with _stream_lock:
        own, others = [], []
        for content, uid in _pending_proactive:
            if uid == user_id or not uid or uid == "global":
                own.append(content)
            else:
                others.append((content, uid))
        _pending_proactive[:] = others
    for content in own:
        _render_proactive(content)

    _exiting = False  # 防止退出阶段重复触发
    _DOUBLE_PRESS_WINDOW = 2.0
    _last_interrupt = 0.0
    _in_exit_window = False  # 第一次 Ctrl+C 后跳过 status/分隔线

    def _do_exit(reason: str = "再见") -> None:
        """退出：保存关键状态，通知 living 线程停止，立即退出。

        living 线程在 run() 的 finally 块中自行清理（_on_stop），
        主线程不等待 —— 用 os._exit(0) 瞬间退出，不等 daemon 线程。
        """
        nonlocal _exiting
        if _exiting:
            return
        _exiting = True

        # \033[1A 上移一行（覆盖 "再按 Ctrl+C 退出"），\r\033[K 清到行尾
        print(f"\r\033[K\033[1A\r\033[K{C_ACCENT}  {reason}\033[0m", flush=True)

        # 主线程保存关键状态
        try:
            if living.drive:
                living.drive.save()
            if living.purpose:
                living.purpose.save()
        except Exception:
            pass

        # 通知 living 线程停止（它在 finally 里自行 _on_stop）
        living.stop()

        # 清理 PID 文件
        from xiaomei_brain.cli.lifecycle import remove_pid_file
        remove_pid_file(agent_id)

        # 立即退出，不等待 daemon 线程
        import os as _os
        _os._exit(0)

    def _handle_clarify_if_needed() -> bool:
        """处理 clarify 请求（如果有）。返回 True 表示处理了请求。"""
        from xiaomei_brain.tools.builtin.clarify import poll_clarify_request, answer_clarify_request
        req = poll_clarify_request()
        if req is None:
            return False
        question = req.get("question", "")
        choices = req.get("choices")
        print()
        print(f"  ❓ {question}")
        if choices:
            for i, c in enumerate(choices, 1):
                print(f"     {i}. {c}")
            print(f"     {len(choices) + 1}. 其他（请输入你的答案）")
            print()
        try:
            response = input("  > ").strip()
        except (KeyboardInterrupt, EOFError):
            response = ""
        answer_clarify_request(response)
        return True

    try:
        while living.is_running:
            try:
                # 第一次 Ctrl+C 后跳过 status/分隔线，保持界面干净
                if not _in_exit_window:
                    status = _status_line(living)
                    if status:
                        print(f"\n\033[90m{status}\033[0m", flush=True)
                    try:
                        bar_w = os.get_terminal_size().columns
                    except Exception:
                        bar_w = 78
                    print("\033[90m" + "─" * bar_w + "\033[0m")
                first_line = input(PROMPT)
                msg = _read_multiline(first_line)
                _in_exit_window = False  # 正常输入了，退出窗口结束
            except (KeyboardInterrupt, EOFError):
                # 清掉当前行（❯ 提示符），不残留
                print("\r\033[K", end="", flush=True)
                now = time.time()
                if now - _last_interrupt < _DOUBLE_PRESS_WINDOW:
                    _do_exit("再见")
                    break
                _last_interrupt = now
                _in_exit_window = True
                living.cancel()
                print(C_ACCENT + "  再按一次 Ctrl+C 退出\033[0m", flush=True)
                continue

            msg = msg.strip()
            if msg.lower() in ("exit", "quit", "stop"):
                _do_exit("正在停止...")
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
            gw = getattr(living, '_gateway_inbound', None)
            if gw:
                from xiaomei_brain.gateway.inbound import RawMessage
                result = gw.accept(RawMessage(
                    content=msg, source="human", channel="cli",
                    peer_id=user_id or "cli-user", peer_type="human",
                    images=images, session_id=f"cli-{agent_id}",
                ))
                if hasattr(result, 'reason'):
                    if getattr(result, 'silent', False):
                        pass  # EMPTY / HANDLED — 不打扰用户
                    else:
                        print(f"\n[Gateway] 消息被拒绝: {result.reason}", flush=True)
            else:
                living.put_message(msg, images=images, session_id=f"cli-{agent_id}")

            if msg.startswith("/"):
                living._command_done.wait(timeout=3)
                continue

            from xiaomei_brain.tools.builtin.clarify import _clarify_request_ready

            if living._clarify_listening.wait(timeout=3):
                while living._clarify_listening.is_set():
                    if _clarify_request_ready.wait(timeout=1):
                        _handle_clarify_if_needed()

    except KeyboardInterrupt:
        _do_exit("正在停止...")


# ── CLI 入口 ─────────────────────────────────────────────

def cmd_run(args: list[str]) -> None:
    """`xiaomei-brain run` 命令入口。

    Args:
        args: sys.argv 中 "run" 之后的参数列表
    """
    parser = argparse.ArgumentParser(
        prog="xiaomei-brain run",
        description="启动并交互式运行 Agent",
    )
    parser.add_argument("agent_id", nargs="?", default="xiaomei", help="Agent ID")
    parser.add_argument("--cli", action="store_true", default=True, help="CLI 交互模式（默认）")
    parser.add_argument("-n", "--no-consciousness", action="store_true", help="无意识模式")
    parser.add_argument("--legacy", action="store_true", help="旧版上下文模式")
    parser.add_argument("--port", "-p", type=int, default=0, help="通讯端口（0=自动, -1=禁用）")
    parsed = parser.parse_args(args)

    agent_id = parsed.agent_id

    # ── 日志配置 ──────────────────────────────────────────────
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )
    logging.getLogger().handlers[0].setLevel(logging.WARNING)

    agent_log_dir = os.path.expanduser(f"~/.xiaomei-brain/{agent_id}/logs")
    os.makedirs(agent_log_dir, exist_ok=True)
    _file_handler = logging.FileHandler(os.path.join(agent_log_dir, "agent.log"), encoding="utf-8")
    _file_handler.setLevel(logging.DEBUG)
    _file_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(name)s] %(levelname)s %(message)s", datefmt="%H:%M:%S"
    ))
    logging.getLogger().addHandler(_file_handler)

    from xiaomei_brain.llm.client import set_log_agent as _set_llm_log
    from xiaomei_brain.consciousness.goal_manager import set_log_agent as _set_intent_log
    _set_llm_log(agent_id)
    _set_intent_log(agent_id)

    _hist_path = os.path.join(agent_log_dir, "cli_history")
    if os.path.exists(_hist_path):
        try:
            readline.read_history_file(_hist_path)
        except Exception:
            pass
    atexit.register(lambda p=_hist_path: readline.write_history_file(p))

    # ── 验证 agent ──────────────────────────────────────────
    manager = AgentManager()
    available = [a.id for a in manager.list()]
    if agent_id not in available:
        print(f"\033[31m[错误] agent '{agent_id}' 不存在。可用: {', '.join(available)}\033[0m")
        sys.exit(1)

    # 获取 agent 名称（在 build 之前，避免 boot 信息夹在 banner 中间）
    agent_info = next(a for a in manager.list() if a.id == agent_id)
    agent_name = agent_info.name or agent_id

    from xiaomei_brain.cli.boot import boot_banner, boot_muted
    model = getattr(agent_info, 'model', '')
    extra = []
    if parsed.no_consciousness:
        extra.append("[无意识模式]")
    if parsed.legacy:
        extra.append("[Legacy 上下文模式]")
    boot_banner(
        agent_name=agent_name,
        agent_id=agent_id,
        model=model,
        extra_lines=extra or None,
    )

    with boot_muted():
        agent = manager.build_agent(agent_id)

        # ── 通讯端口 ──────────────────────────────────────────
        comms_port = parsed.port
        if comms_port == 0:
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

        from xiaomei_brain.config.agent_config import load_agent_config
        agent_cfg = load_agent_config(agent_id)
        cfg = agent_cfg.consciousness
        cfg.living.comms_port = comms_port
        living = ConsciousLiving(agent, load_consciousness=not parsed.no_consciousness, config=cfg)

    # ── 上线标语 ──────────────────────────────────────────
    from xiaomei_brain.cli.boot import C_OK, C_DIM, BOLD, RESET, boot_sep
    si = living.consciousness.self_image if hasattr(living, 'consciousness') and living.consciousness else None
    name = si.being.name if si else agent_name

    parts = []
    ltm = getattr(agent, 'longterm_memory', None)
    if ltm:
        try:
            mem_count = ltm.count()
            parts.append(f"{mem_count} 条记忆")
        except Exception:
            pass
    purpose = getattr(living, 'purpose', None)
    if purpose:
        n_goals = len(getattr(purpose, 'goals', {}))
        if n_goals:
            parts.append(f"{n_goals} 个目标")
    essence = getattr(agent, 'essence', None)
    if essence:
        try:
            n_essence = essence.count()
            if n_essence:
                parts.append(f"{n_essence} 条底色")
        except Exception:
            pass

    tagline = f"{name}大脑系统已上线"
    if parts:
        tagline += f"，现有{' · '.join(parts)}"
    boot_sep(tagline)

    living.assemble_context = True
    # daemon 线程里 os.get_terminal_size() 拿不到正确值，从主线程传入
    try:
        living.conversation_driver.term_width = os.get_terminal_size().columns
    except Exception:
        living.conversation_driver.term_width = 80
    living._show_prompt = False  # CLI 模式：主循环统一管理提示符

    if parsed.legacy:
        living.force_mode = "legacy"

    # ── 生命周期管理 ──────────────────────────────────────────
    from xiaomei_brain.cli.lifecycle import write_pid_file, setup_signal_handlers, remove_pid_file
    write_pid_file(agent_id)
    setup_signal_handlers(living)

    try:
        _run_agent(living, agent, agent_id, agent_name,
                   no_consciousness=parsed.no_consciousness,
                   legacy=parsed.legacy)
    except FatalLLMError as e:
        ts = time.strftime("%H:%M:%S")
        print(f"\n\033[91m[FATAL] {ts} LLM API 致命错误，程序终止\033[0m", flush=True)
        print(f"\033[91m[FATAL] HTTP {e.status_code}: {e}\033[0m", flush=True)
        sys.exit(1)
