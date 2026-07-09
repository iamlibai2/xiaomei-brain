"""cli_tui.py — Claude Code 风格全屏 TUI。

完全独立入口，不依赖 run.py。启动即全屏，所有内容统一风格。

Usage:
    xiaomei-brain --tui
    或
    PYTHONPATH=src python3 -m xiaomei_brain.cli.cli_tui
"""

from __future__ import annotations

import io as _io
import logging
import os
import queue
import re
import sys
import threading
import time
from datetime import datetime

logger = logging.getLogger(__name__)

from prompt_toolkit.application import Application
from prompt_toolkit.layout import Layout, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.styles import Style
from prompt_toolkit.formatted_text import ANSI

from xiaomei_brain.tui.theme.theme import get_theme, build_style_dict
from xiaomei_brain.consciousness.living_commands import load_ears_enabled, load_eyes_enabled

_C_USER = "\033[38;5;203m"
_C_AGENT = "\033[38;5;73m"
_C_DIM = "\033[90m"
_C_ERR = "\033[91m"
_C_RST = "\033[0m"


class _MsgBuf:
    def __init__(self, max_lines: int = 2000):
        self._lines: list[str] = []
        self._max = max_lines

    @property
    def lines(self) -> list[str]:
        return self._lines

    def add(self, *lines: str) -> None:
        for line in lines:
            for sub in line.split('\n'):
                self._lines.append(sub)
        while len(self._lines) > self._max:
            self._lines.pop(0)

    def clear(self) -> None:
        self._lines.clear()


# ═══════════════════════════════════════════════════════════════
# CliTuiApp
# ═══════════════════════════════════════════════════════════════

class CliTuiApp:
    """Claude Code 风格 TUI — 启动即全屏，boot/login/chat 统一。"""

    def __init__(self, living, agent, agent_id: str, agent_name: str,
                 agent_model: str, cfg):
        self.living = living
        self.agent = agent
        self.agent_id = agent_id
        self.agent_name = agent_name
        self.agent_model = agent_model
        self.cfg = cfg

        self._app: Application | None = None
        self._running = False
        self._theme = get_theme()
        self._pending = queue.Queue()
        self._msgs = _MsgBuf()

        # Phases: warmup -> login -> chat
        self._phase = 'warmup'
        self._warmup_msg = ''
        self._warmup_done = False

        # Auth
        self._logged_in = False
        self._user_id = ''
        self._user_name = ''
        self._ids: list[str] = []
        self._identity_mgr = None
        self._login_input = ''

        # Input / streaming
        self._input_buf = ''
        self._streaming = False
        self._current_text = ''

    # ── Run ──────────────────────────────────────────────────

    def run(self) -> None:
        self._running = True

        warmup_thread = threading.Thread(target=self._do_warmup, daemon=True)
        warmup_thread.start()

        self.living.on_chat_chunk = self._on_chunk
        self.living.on_chat_flush = self._on_flush
        self.living.on_proactive = self._on_proactive

        self._app = self._build_app()
        try:
            self._app.run()
        finally:
            self._running = False

    def _do_warmup(self) -> None:
        try:
            from xiaomei_brain.contacts.manager import IdentityManager
            contacts_dir = os.path.expanduser(
                "~/.xiaomei-brain/%s/contacts" % self.agent_id)
            self._identity_mgr = IdentityManager(contacts_dir)

            self._warmup_msg = '加载 Identity...'
            self._notify()

            self._ids = self._identity_mgr.list_ids()
            if not self._ids:
                self._identity_mgr.create_identity("user", "default", "cli")
                self._ids = self._identity_mgr.list_ids()

            self._warmup_msg = '加载 Embedding 模型...'
            self._notify()

            from xiaomei_brain.base.shared_embedder import SharedEmbedder
            emb_model = (self.cfg.embedding_model if hasattr(self.cfg, 'embedding_model')
                         else "BAAI/bge-m3")
            SharedEmbedder.get_or_create(model_name=emb_model)

            self._warmup_msg = '就绪'
            self._warmup_done = True
            self._notify()
            time.sleep(0.6)
            self._phase = 'login'
        except Exception as e:
            self._warmup_msg = 'Warmup 失败: %s' % e
            self._warmup_done = True
        self._notify()

    def _notify(self) -> None:
        if self._app and self._app.loop and self._app.loop.is_running():
            self._app.loop.call_soon_threadsafe(self._invalidate)

    def _invalidate(self) -> None:
        if self._app:
            self._app.invalidate()

    # ── Build ────────────────────────────────────────────────

    def _build_app(self) -> Application:
        kb = KeyBindings()

        @kb.add('c-c')
        def _(event):
            if self._streaming:
                self.living.cancel()
                self._streaming = False
            else:
                self._do_exit()

        @kb.add('enter')
        def _(event):
            if self._phase == 'login':
                self._login_confirm()
            elif self._logged_in:
                self._send()

        @kb.add('backspace')
        def _(event):
            if self._phase == 'login':
                if self._login_input:
                    self._login_input = self._login_input[:-1]
            elif self._logged_in:
                if self._input_buf:
                    self._input_buf = self._input_buf[:-1]

        @kb.add('c-h')
        def _(event):
            if self._phase == 'login':
                self._login_input = re.sub(r'\S+$', '', self._login_input).rstrip()
            elif self._logged_in:
                self._input_buf = re.sub(r'\S+$', '', self._input_buf).rstrip()

        @kb.add('<any>')
        def _(event):
            if event.data and len(event.data) == 1 and not event.data.startswith('\x1b'):
                if self._phase == 'login':
                    self._login_input += event.data
                elif self._logged_in:
                    self._input_buf += event.data

        @kb.add('c-d')
        def _(event):
            if self._phase in ('warmup', 'login'):
                self._do_exit()
            elif self._logged_in and not self._input_buf:
                self._do_exit()

        @kb.add('escape')
        def _(event):
            if self._phase == 'login':
                self._login_input = ''

        layout = Layout(
            Window(
                content=FormattedTextControl(
                    text=self._render_all,
                    focusable=True,
                ),
                wrap_lines=False,
                always_hide_cursor=False,
            )
        )

        style = Style.from_dict(build_style_dict(self._theme))
        return Application(
            layout=layout, key_bindings=kb, style=style,
            full_screen=True, mouse_support=False,
        )

    # ── Render ────────────────────────────────────────────────

    def _render_all(self) -> ANSI:
        if self._phase == 'warmup':
            return self._render_warmup()
        elif self._phase == 'login':
            return self._render_login()
        else:
            return self._render_chat()

    def _render_warmup(self) -> ANSI:
        try:
            width, height = os.get_terminal_size().columns, os.get_terminal_size().lines
        except Exception:
            width, height = 80, 24

        buf = []

        buf.append('')
        buf.append('  %sxiaomei-brain%s  %sv0.1.0%s' % (_C_USER, _C_RST, _C_AGENT, _C_RST))
        buf.append('  %s多 Agent AI 大脑框架%s' % (_C_AGENT, _C_RST))
        buf.append('')
        buf.append('  %sAgent     %s%s %s%s' % (
            _C_AGENT, _C_RST, '\u2502', self.agent_name.ljust(20), _C_RST))
        buf.append('  %sModel     %s%s %s%s' % (
            _C_AGENT, _C_RST, '\u2502', (self.agent_model or '?').ljust(20), _C_RST))
        buf.append('')

        if self._warmup_done:
            buf.append('  %s[ OK ] %s%s' % (_C_AGENT, _C_RST, self._warmup_msg))
        else:
            buf.append('  %s[....] %s%s' % (_C_DIM, _C_RST, self._warmup_msg))

        content_h = len(buf)
        if content_h < height:
            pad = (height - content_h) // 2
            buf = [''] * pad + buf

        return ANSI('\n'.join(buf))

    def _render_login(self) -> ANSI:
        try:
            width, height = os.get_terminal_size().columns, os.get_terminal_size().lines
        except Exception:
            width, height = 80, 24

        buf = []

        buf.append('')
        buf.append('  %s%s%s' % (_C_AGENT, self.agent_name, _C_RST))
        buf.append('  %s%s%s' % (_C_DIM, '\u2500' * 30, _C_RST))
        buf.append('')

        if self._identity_mgr:
            for i, uid in enumerate(self._ids, 1):
                info = self._identity_mgr._identities.get(uid, {})
                name = info.get("name", uid)
                buf.append('  %s%2d.%s %-20s %s(%s)%s' % (
                    _C_AGENT, i, _C_RST, name, _C_DIM, uid, _C_RST))

        buf.append('')

        cur = '\u2588'
        disp = self._login_input + cur if self._login_input else cur
        buf.append('  %slogin:%s %s' % (_C_USER, _C_RST, disp))
        buf.append('')
        buf.append('  %s输入序号或 ID，Enter 确认%s' % (_C_DIM, _C_RST))

        content_h = len(buf)
        if content_h < height:
            pad = (height - content_h) // 2
            buf = [''] * pad + buf

        return ANSI('\n'.join(buf))

    def _render_chat(self) -> ANSI:
        buf = []
        try:
            width, height = os.get_terminal_size().columns, os.get_terminal_size().lines
        except Exception:
            width, height = 80, 24

        visible = self._msgs.lines
        total_lines = len(visible) + 3
        if len(visible) > height - 3:
            visible = visible[-(height - 3):]

        buf.extend(visible)

        if total_lines < height:
            buf = [''] * (height - total_lines) + buf

        buf.append('%s%s%s' % (_C_DIM, '\u2500' * width, _C_RST))
        cur = '\u2588'
        buf.append('%s\u276f %s%s%s' % (_C_AGENT, _C_RST, self._input_buf, cur))

        now = datetime.now().strftime('%H:%M')
        parts = [self.agent_id]
        if self._streaming:
            parts.append('\u26a1 thinking')
        si = getattr(self.living, 'consciousness', None)
        if si:
            try:
                img = si.get_self_image()
                if img:
                    state = getattr(img.perception, 'agent_state', '')
                    energy = getattr(img.body, 'energy', 0)
                    parts.append('\U0001f525%s e:%.1f' % (state, energy))
            except Exception:
                pass
        drive = getattr(self.living, 'drive', None)
        if drive and hasattr(drive, 'desire'):
            d = drive.desire
            parts.append('b:%.1f c:%.1f' % (d.belonging, d.cognition))
        parts.append(now)
        buf.append('%s %s %s' % (_C_DIM, ' \u2502 '.join(parts), _C_RST))

        return ANSI('\n'.join(buf))

    # ── Login ────────────────────────────────────────────────

    def _login_confirm(self) -> None:
        raw = self._login_input.strip()
        self._login_input = ''

        if not raw:
            return

        user_id = raw
        try:
            idx = int(user_id) - 1
            if 0 <= idx < len(self._ids):
                user_id = self._ids[idx]
        except ValueError:
            pass

        identity = self._identity_mgr.resolve(user_id)
        if not identity:
            return

        self._user_id = user_id
        self._user_name = identity["name"]
        self._logged_in = True

        living = self.living
        living.user_id = user_id
        living._ears_enabled = load_ears_enabled(self.agent_id)
        living._eyes_enabled = load_eyes_enabled(self.agent_id)

        agent_core = self.agent._get_agent()
        agent_core.user_id = user_id
        agent_core.user_display_name = self._user_name

        if hasattr(living, 'consciousness') and living.consciousness:
            si = living.consciousness.get_self_image()
            if si:
                si.current_user_name = self._user_name
                si.current_user_id = user_id
                si.current_user_relation = self._identity_mgr.get_relation(user_id)
                ltm = getattr(self.agent, 'longterm_memory', None)
                si.load_preferred_names(user_id, ltm)

        ltm = getattr(self.agent, 'longterm_memory', None)
        if ltm and not ltm.is_embedder_ready():
            ltm.wait_embedder()

        living.load_fresh_tail()
        sid = 'cli-%s' % self.agent_id
        if hasattr(living, '_attention') and living._attention:
            living._attention.save_session(sid)
            living._attention._current_session = sid
        if hasattr(living, '_router') and living._router:
            living._router.register_peer(
                peer_type="human", peer_id=user_id, channel="cli",
                session_id=sid, output_type="cli", output_target="stdout",
                priority=10,
            )

        self._msgs.add(
            '',
            '%s%s%s \u2014 Enter \u53d1\u9001\uff0cCtrl+C \u9000\u51fa' % (
                _C_DIM, self._user_name, _C_RST),
            '',
        )

    # ── Thread Bridge ────────────────────────────────────────

    def _on_chunk(self, chunk: str) -> None:
        chunk = re.sub(r'\x1b\[[0-9;]*m', '', chunk)
        if not chunk:
            return
        self._pending.put(('chunk', chunk))
        if self._app and self._app.loop and self._app.loop.is_running():
            self._app.loop.call_soon_threadsafe(self._apply)

    def _on_flush(self) -> None:
        self._pending.put(('flush', None))
        if self._app and self._app.loop and self._app.loop.is_running():
            self._app.loop.call_soon_threadsafe(self._apply)

    def _on_proactive(self, content: str, user_id: str = '') -> None:
        self._pending.put(('proactive', content))
        if self._app and self._app.loop and self._app.loop.is_running():
            self._app.loop.call_soon_threadsafe(self._apply)

    def _apply(self) -> None:
        if not self._running:
            return
        try:
            while not self._pending.empty():
                kind, data = self._pending.get_nowait()
                if kind == 'chunk':
                    self._handle_chunk(data)
                elif kind == 'flush':
                    self._handle_flush()
                elif kind == 'proactive':
                    self._handle_proactive(data)
        except queue.Empty:
            pass
        if self._app:
            self._app.invalidate()

    def _handle_chunk(self, chunk: str) -> None:
        if not self._streaming:
            self._streaming = True
            self._current_text = ''
            self._msgs.add('')
            self._msgs.add('%s\u25b6 %s' % (_C_AGENT, _C_RST))
        self._current_text += chunk
        while self._msgs.lines and not self._msgs.lines[-1].strip():
            self._msgs.lines.pop()
        self._msgs.add('%s\u25b6 %s%s' % (_C_AGENT, _C_RST, self._current_text))

    def _handle_flush(self) -> None:
        self._streaming = False
        self._msgs.add('')
        self._current_text = ''

    def _handle_proactive(self, content: str) -> None:
        bar = '\u2500' * 40
        self._msgs.add(
            '', '%s%s%s' % (_C_DIM, bar, _C_RST),
            '  %s%s:%s' % (_C_AGENT, self.agent_name, _C_RST),
        )
        for line in content.split('\n'):
            self._msgs.add('  ' + line)
        self._msgs.add('%s%s%s' % (_C_DIM, bar, _C_RST), '')

    # ── Input ────────────────────────────────────────────────

    def _send(self) -> None:
        text = self._input_buf.strip()
        self._input_buf = ''

        if not text:
            return

        if text.startswith('/'):
            if self._handle_cmd(text):
                return

        self._msgs.add('', '%s\u25b6 %s%s' % (_C_USER, _C_RST, text), '')
        sid = 'cli-%s' % self.agent_id
        gw = getattr(self.living, '_gateway_inbound', None)
        if gw:
            from xiaomei_brain.gateway.inbound import RawMessage
            gw.accept(RawMessage(
                content=text, source='human', channel='cli',
                peer_id=self._user_id, peer_type='human',
                session_id=sid,
            ))
        else:
            self.living.put_message(text, session_id=sid)

    def _handle_cmd(self, cmd: str) -> bool:
        cmd = cmd.lower().strip()
        if cmd in ('/exit', '/quit'):
            self._do_exit()
            return True
        elif cmd == '/clear':
            self._msgs.clear()
            return True
        elif cmd == '/help':
            self._msgs.add(
                '',
                '%s/help /clear /exit%s | '
                '/flame /drive /purpose /intent /fuel /tick /think /identity | '
                '/db /memory /dag /summarize /dream /context%s'
                % (_C_DIM, _C_RST, ''),
                '',
            )
            return True
        return False

    def _do_exit(self) -> None:
        self._running = False
        if self._app:
            self._app.exit()


# ═══════════════════════════════════════════════════════════════
# 完全独立入口 — 不依赖 run.py
# ═══════════════════════════════════════════════════════════════

def run_cli_tui(agent_id: str = "xiaomei") -> None:
    """独立 TUI 入口。自己处理 build_agent / ConsciousLiving / warmup / login / chat。"""

    # ── 日志配置 ──────────────────────────────────────────────
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stderr,
    )
    logging.getLogger().handlers[0].setLevel(logging.WARNING)

    agent_log_dir = os.path.expanduser("~/.xiaomei-brain/%s/logs" % agent_id)
    os.makedirs(agent_log_dir, exist_ok=True)

    try:
        from xiaomei_brain.base.config import Config
        _cfg = Config.from_json()
        _file_level = getattr(logging, _cfg.log_level.upper(), logging.INFO)
    except Exception:
        _file_level = logging.INFO

    _file_handler = logging.FileHandler(
        os.path.join(agent_log_dir, "agent.log"), encoding="utf-8")
    _file_handler.setLevel(_file_level)
    _file_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(name)s] %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"))
    logging.getLogger().addHandler(_file_handler)

    for _noisy in ["markdown_it", "httpx", "httpcore", "urllib3", "asyncio"]:
        logging.getLogger(_noisy).setLevel(logging.WARNING)

    from xiaomei_brain.llm.client import set_log_agent as _set_llm_log
    from xiaomei_brain.consciousness.goal_manager import set_log_agent as _set_intent_log
    _set_llm_log(agent_id)
    _set_intent_log(agent_id)

    # ── PID 锁 ─────────────────────────────────────────────
    from xiaomei_brain.cli.lifecycle import write_pid_file, read_pid_file
    existing = read_pid_file(agent_id)
    if existing:
        print("\033[31m[错误] agent '%s' 已在运行 (PID %s)。"
              "请先停止或等待退出后再启动。\033[0m" % (agent_id, existing['pid']))
        sys.exit(1)
    write_pid_file(agent_id)

    # ── 验证 agent ──────────────────────────────────────────
    from xiaomei_brain.agent.agent_manager import AgentManager
    manager = AgentManager()
    available = [a.id for a in manager.list()]
    if agent_id not in available:
        print("\033[31m[错误] agent '%s' 不存在。可用: %s\033[0m" % (
            agent_id, ', '.join(available)))
        sys.exit(1)

    # ── 从此刻开始捕获 stdout，防止 boot 信息泄露到终端 ──────
    _boot_buf = _io.StringIO()
    _real_stdout = sys.stdout
    sys.stdout = _boot_buf

    living = None
    living_thread = None

    try:
        # ── 获取 agent 信息 ──────────────────────────────────
        agent_info = next(a for a in manager.list() if a.id == agent_id)
        agent_name = agent_info.name or agent_id
        model = getattr(agent_info, 'model', '')

        # ── Build agent（触发 plugin 加载，输出进 boot_buf）───
        agent = manager.build_agent(agent_id)

        # ── 通讯端口 ─────────────────────────────────────────
        comms_port = 0
        config_json = os.path.expanduser("~/.xiaomei-brain/config.json")
        if os.path.exists(config_json):
            try:
                import json
                with open(config_json) as f:
                    data = json.load(f)
                agents_cfg = data.get("xiaomei_brain", {}).get("agents", {})
                agent_cfg_json = agents_cfg.get(agent_id, {})
                comms_port = agent_cfg_json.get("comms_port", 0)
            except Exception:
                pass

        from xiaomei_brain.config.agent_config import load_agent_config
        agent_cfg = load_agent_config(agent_id)
        cfg = agent_cfg.consciousness
        cfg.living.comms_port = comms_port

        # ── Config（给 warmup 用）─────────────────────────────
        from xiaomei_brain.base.config import Config as _TuiCfg
        try:
            _tui_cfg = _TuiCfg.from_json()
        except Exception:
            _tui_cfg = None

        # ── ConsciousLiving ──────────────────────────────────
        from xiaomei_brain.consciousness.conscious_living import ConsciousLiving
        living = ConsciousLiving(agent, load_consciousness=True, config=cfg)

        # 音乐回调
        try:
            from xiaomei_brain.plugins.tools.music_minimax.music import set_generation_callback
            def _on_music_done(filename: str, success: bool, message: str):
                living.put_message(message, source="system")
            set_generation_callback(_on_music_done)
        except Exception:
            pass

        living.assemble_context = True
        living._show_prompt = False

        # ── 生命周期管理 ────────────────────────────────────
        from xiaomei_brain.cli.lifecycle import setup_signal_handlers
        write_pid_file(agent_id)
        setup_signal_handlers(living)

        # ── 启动 living 线程（输出进 boot_buf）────────────────
        living_thread = threading.Thread(target=living.run, daemon=False)
        living_thread.start()
        time.sleep(2)

        # ── 恢复 stdout，boot 信息全部锁定在 boot_buf ────────
        sys.stdout = _real_stdout
        _boot_output = _boot_buf.getvalue()

        # ── 创建 TUI App ─────────────────────────────────────
        app = CliTuiApp(living, agent, agent_id, agent_name, model, _tui_cfg)

        # 将 boot 信息注入消息缓冲（登录后在聊天区可见）
        if _boot_output.strip():
            for line in _boot_output.strip().split('\n'):
                line = line.strip()
                if line:
                    app._msgs.add('  %s%s%s' % (_C_DIM, line, _C_RST))
            app._msgs.add('')

        app.run()

    except Exception:
        sys.stdout = _real_stdout
        raise
    finally:
        if living is not None:
            voice_listener = getattr(living, '_voice_listener', None)
            if voice_listener:
                voice_listener.stop()
            em = getattr(living, '_expression_monitor', None)
            if em:
                em.stop()
            body = getattr(living, 'body', None)
            if body and body.eyes and body.eyes._device:
                body.eyes._device.close()
            if hasattr(living, 'drive') and living.drive:
                living.drive.save()
            if hasattr(living, 'purpose') and living.purpose:
                living.purpose.save()
            living.stop()
        if living_thread is not None:
            living_thread.join(timeout=10)

        from xiaomei_brain.cli.lifecycle import remove_pid_file
        remove_pid_file(agent_id)


if __name__ == "__main__":
    run_cli_tui()
