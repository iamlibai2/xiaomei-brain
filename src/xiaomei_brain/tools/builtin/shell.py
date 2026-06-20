"""Shell command execution tool."""

from __future__ import annotations

import re
import subprocess

from ..base import Tool, tool

# 会导致挂起的命令前缀（需要交互输入，在无 TTY 环境下必然超时）
_BLOCKED_PATTERNS = [
    (r'^\s*sudo\b', 'sudo needs a password and will hang. Use non-root alternatives or '
                   'report to the user that this operation requires root.'),
    (r'^\s*su\b', 'su is interactive and cannot run here.'),
    (r'^\s*passwd\b', 'passwd is interactive and cannot run here.'),
    (r'^\s*ssh\b(?!.*-o\s*BatchMode)', 'ssh may require password/interaction. '
                                       'Use ssh -o BatchMode=yes for non-interactive connections.'),
    (r'^\s*vim?\b|^\s*nano\b|^\s*emacs\b', 'Interactive editor cannot run here. Use write_file/edit_file tools instead.'),
    (r'^\s*less\b|^\s*more\b', 'Interactive pager will hang. Use cat instead.'),
    (r'^\s*(mysql|psql|sqlite3)\b(?!.*<<)', 'Database CLI is interactive. Pipe SQL via stdin or use a script.'),
    # ── 解释器 -c/-e：可绕过任意黑名单执行任意代码（要求脚本落地）──
    (r'^\s*python[0-9.]*\s+(-c)\b', 'python -c executes arbitrary code from CLI. '
                                     'Write the code to a .py file and run it instead.'),
    (r'^\s*node\s+(-e|--eval|-p)\b', 'node -e executes arbitrary JS. '
                                      'Write to a .js file and run it instead.'),
    (r'^\s*ruby\s+-e\b', 'ruby -e executes arbitrary code. '
                          'Write to a .rb file and run it instead.'),
    (r'^\s*perl\s+-e\b', 'perl -e executes arbitrary code. '
                          'Write to a .pl file and run it instead.'),
    # ── Shell -c：可绕过黑名单（要求脚本落地）──
    (r'^\s*bash\s+-c\b', 'bash -c executes arbitrary shell. '
                          'Use a script file or call commands directly.'),
    (r'^\s*sh\s+-c\b', 'sh -c executes arbitrary shell. '
                        'Use a script file or call commands directly.'),
    # ── 管道到 shell：远程 payload 直接执行 ──
    (r'\|\s*(sh|bash|zsh|dash)\b', 'Piping downloaded content to a shell is dangerous. '
                                     'Download, inspect, then run explicitly.'),
    # ── eval / exec：可执行任意表达式 ──
    (r'^\s*eval\b', 'eval is too dangerous. Call the command directly.'),
    (r';\s*eval\b', 'eval is too dangerous. Call the command directly.'),
    (r'^\s*exec\b', 'exec replaces the shell process. Avoid in this context.'),
    # ── Windows: 命令行解释器 + 系统管理工具 ──
    (r'^\s*powershell\s+(-Command|-c|-EncodedCommand|-e|-Enc)\b',
     'powershell -Command executes arbitrary code. Write a .ps1 file and run it instead.'),
    (r'^\s*cmd\s+/[cC]\b', 'cmd /c executes arbitrary shell. Use a script file or call commands directly.'),
    (r'^\s*wmic\b', 'wmic is deprecated and dangerous.'),
    (r'^\s*reg\s+(add|delete|import|export)\b', 'Direct registry manipulation is blocked.'),
    # ── IIS / 服务管理（系统级变更）──
    (r'^\s*sc\s+(stop|delete|config)\b', 'Service control is blocked.'),
    (r'^\s*(net\s+stop|net\s+user|net\s+localgroup)\b', 'System service/account management is blocked.'),
]

# apt-get 需要非交互模式
_APT_WARNING = (
    "Warning: apt-get/apt requires DEBIAN_FRONTEND=noninteractive. "
    "Please retry with: DEBIAN_FRONTEND=noninteractive apt-get ..."
)


def _check_command(command: str) -> str | None:
    """检查命令是否会挂起。返回错误消息，或 None 表示放行。"""
    for pattern, message in _BLOCKED_PATTERNS:
        if re.search(pattern, command, re.IGNORECASE):
            return f"Command blocked: {message}"
    # apt-get/apt without DEBIAN_FRONTEND
    if re.search(r'^\s*(apt-get|apt)\s', command) and 'DEBIAN_FRONTEND' not in command:
        return _APT_WARNING
    # pip/uv install — 提示用 uv 和正确的 Python 环境
    if re.search(r'^\s*pip\s+install', command):
        return ("Use 'uv pip install <pkg>' with the correct Python environment instead of pip install. "
                "Do NOT use sudo.")
    return None


@tool(name="shell", description="Run a shell command and return its output")
def run_shell(command: str) -> str:
    """Run a shell command and return stdout/stderr."""
    block_msg = _check_command(command)
    if block_msg:
        return block_msg

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        output = result.stdout
        if result.stderr:
            output += f"\nSTDERR:\n{result.stderr}"
        if result.returncode != 0:
            output += f"\nExit code: {result.returncode}"
        return output or "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: command timed out after 30 seconds. Do NOT retry the same command — it will hang again."
    except Exception as e:
        return f"Error: {e}"


shell_tool: Tool = run_shell
