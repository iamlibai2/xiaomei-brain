# Phase 1: CLI 跨平台兼容层 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 创建 `cli/platform_utils.py` 封装所有平台差异，使得 CLI 层在 Linux/macOS/Windows/WSL2 上都能正常运行。

**Architecture:** 单一模块 `platform_utils.py` 提供所有平台相关函数的跨平台实现。调用方通过 import 使用统一接口，内部用 `sys.platform` + WSL2 检测自动选择正确实现。

**Tech Stack:** Python 3.10+ stdlib（`sys`/`os`/`signal`/`termios`/`msvcrt`/`pyreadline3`）

---

### Task 1: 创建 `cli/platform_utils.py`

**Files:**
- Create: `src/xiaomei_brain/cli/platform_utils.py`

- [ ] **Step 1: 创建 platform_utils.py 完整实现**

```python
"""平台兼容工具 — 封装 readline / termios / select / signal 的平台差异。

用法:
    from xiaomei_brain.cli.platform_utils import (
        import_readline,
        get_single_char,
        select_stdin,
        is_wsl2,
        send_signal,
        register_signal_handlers,
    )
"""

from __future__ import annotations

import os
import signal
import sys
import time


# ── WSL2 检测 ──────────────────────────────────────────────

def is_wsl2() -> bool:
    """检测是否运行在 WSL2 环境中。"""
    if sys.platform != "linux":
        return False
    try:
        with open("/proc/version", "r") as f:
            return "microsoft" in f.readline().lower()
    except Exception:
        return False


# ── readline 导入 ──────────────────────────────────────────

def import_readline():
    """跨平台导入 readline（Windows 用 pyreadline3）。"""
    try:
        import readline
        return readline
    except ImportError:
        pass
    try:
        import pyreadline3 as readline
        return readline
    except ImportError:
        pass
    return None


# ── 单字符读取 ─────────────────────────────────────────────

def get_single_char() -> str | None:
    """读取单个字符，不回显。Unix 用 termios+tty，Windows 用 msvcrt。"""
    if sys.platform == "win32":
        try:
            import msvcrt
            ch = msvcrt.getch()
            # msvcrt.getch() returns bytes, decode to str
            if isinstance(ch, bytes):
                return ch.decode("utf-8", errors="replace")
            return ch
        except Exception:
            return None
    else:
        try:
            import termios
            import tty
            fd = sys.stdin.fileno()
            old = termios.tcgetattr(fd)
            try:
                tty.setraw(fd)
                return sys.stdin.read(1)
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old)
        except Exception:
            return None


def get_single_char_timeout(timeout: float) -> str | None:
    """读取单个字符，支持超时。Unix 用 select，Windows 用 msvcrt.kbhit。"""
    if sys.platform == "win32":
        import msvcrt
        deadline = time.time() + timeout
        while time.time() < deadline:
            if msvcrt.kbhit():
                ch = msvcrt.getch()
                if isinstance(ch, bytes):
                    return ch.decode("utf-8", errors="replace")
                return ch
            time.sleep(0.05)
        return None
    else:
        import select
        r, _, _ = select.select([sys.stdin], [], [], timeout)
        if not r:
            return None
        return get_single_char()


# ── stdin 多行检测 ─────────────────────────────────────────

def stdin_has_data(timeout: float = 0.05) -> bool:
    """检查 stdin 是否有可读数据。Windows 用 msvcrt.kbhit，Unix 用 select。"""
    if sys.platform == "win32":
        import msvcrt
        deadline = time.time() + timeout
        while time.time() < deadline:
            if msvcrt.kbhit():
                return True
            time.sleep(0.01)
        return False
    else:
        import select
        r, _, _ = select.select([sys.stdin], [], [], timeout)
        return len(r) > 0


# ── 信号处理 ───────────────────────────────────────────────

def send_signal(pid: int, sig: signal.Signals) -> None:
    """跨平台发送信号。Windows 不支持 SIGKILL，降级为 SIGTERM。"""
    try:
        os.kill(pid, sig)
    except ProcessLookupError:
        pass
    except (PermissionError, OSError):
        pass


def _safe_signal(sig_name: str) -> signal.Signals | None:
    """安全获取 signal 常量，平台不支持时返回 None。"""
    try:
        return getattr(signal, sig_name)
    except AttributeError:
        return None


def register_signal_handlers(handler, *, sigterm: bool = True, sigint: bool = True) -> None:
    """跨平台注册信号处理器。Windows 不支持 SIGTERM，只注册 SIGINT。"""
    if sigint:
        signal.signal(signal.SIGINT, handler)
    if sigterm:
        sig = _safe_signal("SIGTERM")
        if sig is not None:
            signal.signal(sig, handler)
```

- [ ] **Step 2: 在 WSL2 环境验证导入无报错**

```bash
cd /home/iamlibai/workspace/claude-project/xiaomei-brain
source /home/iamlibai/workspace/python_env_common/bin/activate
PYTHONPATH=src python3 -c "
from xiaomei_brain.cli.platform_utils import (
    import_readline, get_single_char, select_stdin,
    is_wsl2, send_signal, register_signal_handlers
)
print('is_wsl2:', is_wsl2())
print('readline:', import_readline())
print('OK')
"
```

- [ ] **Step 3: Commit**

```bash
git add src/xiaomei_brain/cli/platform_utils.py
git commit -m "feat: add platform_utils.py — cross-platform readline/termios/signal abstraction
"
```

---

### Task 2: 更新 `cli/run.py` — 替换平台相关调用

**Files:**
- Modify: `src/xiaomei_brain/cli/run.py`

**修改点：**

1. 顶部 `import readline` / `import select` → 改用 `platform_utils`
2. `readline.parse_and_bind()` / `readline.set_completer()` → 条件调用
3. `_read_multiline()` 中的 `select.select()` → `stdin_has_data()`
4. `_read_char()` / `_read_char_timeout()` → `get_single_char()` / `get_single_char_timeout()`

- [ ] **Step 1: 替换顶部 import**

```python
# 原代码（line 13-14）:
import readline
import select

# 改为:
from xiaomei_brain.cli.platform_utils import (
    import_readline,
    get_single_char,
    get_single_char_timeout,
    stdin_has_data,
    register_signal_handlers,
)
```

- [ ] **Step 2: 初始化 readline（line 58-63）**

```python
# 原代码:
readline.parse_and_bind("tab: complete")
readline.parse_and_bind("set enable-bracketed-paste on")
readline.parse_and_bind("set input-meta on")
readline.parse_and_bind("set output-meta on")
readline.parse_and_bind("set convert-meta off")
readline.set_completer(_completer)

# 改为:
_readline = import_readline()
if _readline is not None:
    try:
        _readline.parse_and_bind("tab: complete")
        _readline.parse_and_bind("set enable-bracketed-paste on")
        _readline.parse_and_bind("set input-meta on")
        _readline.parse_and_bind("set output-meta on")
        _readline.parse_and_bind("set convert-meta off")
        _readline.set_completer(_completer)
    except Exception:
        pass  # macOS libedit / Windows pyreadline3 可能不支持某些 bind
```

- [ ] **Step 3: 更新 `_read_multiline()` 中的 select 调用（line 70）**

```python
# 原代码 (line 68-71):
def _read_multiline(first_line: str, timeout: float = 0.05) -> str:
    """检测粘贴多行文本并一次性读取。"""
    r, _, _ = select.select([sys.stdin], [], [], timeout)
    if not r:
        return first_line

    lines = [first_line]
    while True:
        r, _, _ = select.select([sys.stdin], [], [], timeout)

# 改为:
def _read_multiline(first_line: str, timeout: float = 0.05) -> str:
    """检测粘贴多行文本并一次性读取。"""
    if not stdin_has_data(timeout):
        return first_line

    lines = [first_line]
    while True:
        if not stdin_has_data(timeout):
            break
```

- [ ] **Step 4: 更新 `_read_multiline()` 中的 `readline.add_history()` （line 88）**

```python
# 原代码:
readline.add_history(result)

# 改为:
if _readline is not None:
    try:
        _readline.add_history(result)
    except Exception:
        pass
```

- [ ] **Step 5: 替换 `_read_char()` 函数体（line 96-109）**

```python
# 原代码:
def _read_char() -> str | None:
    """读取单个字符，不回显。仅登录阶段使用。"""
    try:
        import tty
        import termios
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            return sys.stdin.read(1)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
    except Exception:
        return None

# 改为:
def _read_char() -> str | None:
    """读取单个字符，不回显。仅登录阶段使用。"""
    return get_single_char()
```

- [ ] **Step 6: 替换 `_read_char_timeout()` 函数体（line 113-122）**

```python
# 原代码:
def _read_char_timeout(timeout: float = 0.1) -> str | None:
    try:
        import tty
        import termios
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            r, _, _ = select.select([sys.stdin], [], [], timeout)
            if not r:
                return None
            return sys.stdin.read(1)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
    except Exception:
        time.sleep(timeout)
        return None

# 改为:
def _read_char_timeout(timeout: float = 0.1) -> str | None:
    """读取单个字符，超时返回 None。"""
    return get_single_char_timeout(timeout)
```

- [ ] **Step 7: 在 WSL2 环境验证修改无回归**

```bash
cd /home/iamlibai/workspace/claude-project/xiaomei-brain
source /home/iamlibai/workspace/python_env_common/bin/activate
PYTHONPATH=src python3 -c "
from xiaomei_brain.cli.platform_utils import import_readline, get_single_char, stdin_has_data
rl = import_readline()
print('readline:', 'OK' if rl else 'NONE (expected on some platforms)')
print('Platform utils loaded OK')
"
```

- [ ] **Step 8: Commit**

```bash
git add src/xiaomei_brain/cli/run.py src/xiaomei_brain/__main__.py
git commit -m "refactor: use platform_utils in cli/run.py — remove direct readline/termios/select
"
```

---

### Task 3: 更新 `cli/masked_input.py`

**Files:**
- Modify: `src/xiaomei_brain/cli/masked_input.py`

- [ ] **Step 1: 替换 termios/tty 调用**

```python
# 原代码 (lines 25-46):
def masked_input(prompt: str, *, mask: str = "*") -> str:
    if not _stream_is_tty(sys.stdin) or not _stream_is_tty(sys.stdout):
        return input(prompt)

    try:
        import termios
        import tty

        fd = sys.stdin.fileno()
        old_attrs = termios.tcgetattr(fd)

        def read_char() -> str:
            return sys.stdin.read(1)

        def write(text: str) -> None:
            sys.stdout.write(text)
            sys.stdout.flush()

        try:
            tty.setraw(fd)
            return _collect_masked_input(read_char, write, prompt, mask=mask)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_attrs)

    except Exception:
        return input(prompt)

# 改为:
def masked_input(prompt: str, *, mask: str = "*") -> str:
    """Prompt for text while showing masked typing feedback.

    Returns an empty string if the user presses Enter without typing.
    Falls back to input() when stdin/stdout are not interactive.
    """
    if not _stream_is_tty(sys.stdin) or not _stream_is_tty(sys.stdout):
        return input(prompt)

    from xiaomei_brain.cli.platform_utils import get_single_char

    def read_char() -> str:
        return get_single_char() or ""

    def write(text: str) -> None:
        sys.stdout.write(text)
        sys.stdout.flush()

    try:
        return _collect_masked_input(read_char, write, prompt, mask=mask)
    except Exception:
        return input(prompt)
```

- [ ] **Step 2: 验证**

```bash
cd /home/iamlibai/workspace/claude-project/xiaomei-brain
source /home/iamlibai/workspace/python_env_common/bin/activate
PYTHONPATH=src python3 -c "
from xiaomei_brain.cli.masked_input import masked_input
print('masked_input imported OK')
"
```

- [ ] **Step 3: Commit**

```bash
git add src/xiaomei_brain/cli/masked_input.py
git commit -m "refactor: use platform_utils.get_single_char() in masked_input.py
"
```

---

### Task 4: 更新 `cli/lifecycle.py` — 信号处理

**Files:**
- Modify: `src/xiaomei_brain/cli/lifecycle.py`

- [ ] **Step 1: 替换 `setup_signal_handlers()` 中的 `signal.SIGTERM`**

```python
# 原代码 (lines 121-136):
def setup_signal_handlers(living: Any = None) -> None:
    """注册 SIGTERM/SIGINT 信号处理器。"""

    def _graceful_shutdown(signum: int, _frame) -> None:
        sig_name = signal.Signals(signum).name
        logger.info("[Lifecycle] 收到 %s，正在停止...", sig_name)
        if living:
            living.stop()
        remove_pid_file(_agent_id_from_args())
        sys.exit(0)

    signal.signal(signal.SIGTERM, _graceful_shutdown)
    # SIGINT is handled by the CLI main loop's KeyboardInterrupt handler

# 改为:
def setup_signal_handlers(living: Any = None) -> None:
    """注册 SIGTERM/SIGINT 信号处理器。"""

    def _graceful_shutdown(signum: int, _frame) -> None:
        try:
            sig_name = signal.Signals(signum).name
        except Exception:
            sig_name = str(signum)
        logger.info("[Lifecycle] 收到 %s，正在停止...", sig_name)
        if living:
            living.stop()
        remove_pid_file(_agent_id_from_args())
        sys.exit(0)

    from xiaomei_brain.cli.platform_utils import register_signal_handlers
    register_signal_handlers(_graceful_shutdown, sigterm=True, sigint=False)
```

- [ ] **Step 2: 移除顶部未使用的 `signal` import（如果有的话，`lifecycle.py` line 14）**

检查 `lifecycle.py` 顶部是否有 `import signal`，如果没有被其他代码使用则删除。

- [ ] **Step 3: 验证**

```bash
cd /home/iamlibai/workspace/claude-project/xiaomei-brain
source /home/iamlibai/workspace/python_env_common/bin/activate
PYTHONPATH=src python3 -c "
from xiaomei_brain.cli.lifecycle import setup_signal_handlers
print('setup_signal_handlers imported OK')
"
```

- [ ] **Step 4: Commit**

```bash
git add src/xiaomei_brain/cli/lifecycle.py
git commit -m "refactor: use platform_utils.register_signal_handlers() in lifecycle.py
"
```

---

### Task 5: 更新 `mcp/connection.py` — 信号处理

**Files:**
- Modify: `src/xiaomei_brain/mcp/connection.py`

- [ ] **Step 1: 替换 `_cleanup_stdio_pids()` 中的 `os.kill(SIGKILL)`**

```python
# 原代码 (lines 850-869):
def _cleanup_stdio_pids(self):
    """清理 stdio 子进程：先 SIGTERM，2s 后 SIGKILL。"""
    if not self._new_pids:
        return
    import signal

    for pid in self._new_pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            pass

    if self._new_pids:
        time.sleep(2)

    for pid in self._new_pids:
        try:
            os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            pass

# 改为:
def _cleanup_stdio_pids(self):
    """清理 stdio 子进程：先 SIGTERM，2s 后强制终止。"""
    if not self._new_pids:
        return

    from xiaomei_brain.cli.platform_utils import send_signal

    _SIGTERM = signal.SIGTERM if hasattr(signal, 'SIGTERM') else signal.SIGINT
    _SIGKILL = signal.SIGKILL if hasattr(signal, 'SIGKILL') else signal.SIGTERM if hasattr(signal, 'SIGTERM') else signal.SIGINT

    for pid in self._new_pids:
        send_signal(pid, _SIGTERM)

    if self._new_pids:
        time.sleep(2)

    for pid in self._new_pids:
        send_signal(pid, _SIGKILL)
```

- [ ] **Step 2: 验证**

```bash
cd /home/iamlibai/workspace/claude-project/xiaomei-brain
source /home/iamlibai/workspace/python_env_common/bin/activate
PYTHONPATH=src python3 -c "
from xiaomei_brain.cli.platform_utils import send_signal
print('send_signal imported OK')
"
```

- [ ] **Step 3: Commit**

```bash
git add src/xiaomei_brain/mcp/connection.py
git commit -m "refactor: use platform_utils.send_signal() in mcp/connection.py — Windows-safe SIGKILL
"
```

---

### Task 6: 更新 `pyproject.toml` — 平台依赖

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: 添加 `psutil` 和 `windows` 可选依赖**

```toml
# 在 [project.optional-dependencies] 中添加:
windows = [
    "pyreadline3>=3.4.0; sys_platform == 'win32'",
    "windows-curses>=2.3.0; sys_platform == 'win32'",
]
```

同时确认 `psutil` 已在 dependencies 中（`cli/lifecycle.py` 多处依赖 `psutil.Process`）。

- [ ] **Step 2: 检查 psutil 是否已在 dependencies 中**

如果 `psutil` 不在 `[project] dependencies` 列表中，添加：
```toml
"psutil>=5.9.0",
```

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "chore: add windows optional deps (pyreadline3, windows-curses) and psutil to pyproject.toml
"
```

---

### Task 7: 整体回归验证

- [ ] **Step 1: 安装依赖并验证导入**

```bash
cd /home/iamlibai/workspace/claude-project/xiaomei-brain
source /home/iamlibai/workspace/python_env_common/bin/activate
PYTHONPATH=src python3 -c "
from xiaomei_brain.cli.run import _read_char, _read_char_timeout, _read_multiline
from xiaomei_brain.cli.masked_input import masked_input
from xiaomei_brain.cli.lifecycle import setup_signal_handlers
from xiaomei_brain.cli.platform_utils import is_wsl2, import_readline, send_signal, register_signal_handlers
from xiaomei_brain.mcp.connection import MCPConnection
print('All imports OK')
"
```

- [ ] **Step 2: 运行 doctor 检查**

```bash
PYTHONPATH=src python3 -m xiaomei_brain.doctor
```

- [ ] **Step 3: 运行现有测试**

```bash
PYTHONPATH=src python3 -m pytest tests/ -v --timeout=30 2>&1 | head -50
```

- [ ] **Step 4: Commit any fixes**

```bash
git add -A
git commit -m "fix: regression fixes from cross-platform phase 1
"
```
