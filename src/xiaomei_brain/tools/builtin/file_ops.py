"""File operation tools."""

from __future__ import annotations

import json
import logging
import os
import sys

from ..base import Tool, tool

logger = logging.getLogger(__name__)

# 默认输出目录（LLM 写文件时如果给相对路径，自动拼接到此目录）
# 可通过 set_output_base() 按 agent 隔离
_output_base: str | None = None


def _build_sensitive_paths() -> tuple[str, ...]:
    """构建敏感路径列表。按平台区分，realpath 比较覆盖符号链接绕过。

    包含 SSH/凭证/系统目录，工具永远不能读写。
    """
    common = [
        os.path.expanduser("~/.ssh"),
        os.path.expanduser("~/.gnupg"),
        os.path.expanduser("~/.aws"),
        os.path.expanduser("~/.config/gcloud"),
        os.path.expanduser("~/.azure"),
        os.path.expanduser("~/.kube"),
        os.path.expanduser("~/.docker"),
        os.path.expanduser("~/.bash_history"),
        os.path.expanduser("~/.zsh_history"),
    ]
    if sys.platform == "win32":
        system_root = os.environ.get("SystemRoot", r"C:\Windows")
        common.extend([
            system_root,
            os.path.join(system_root, "System32"),
            os.path.join(system_root, "SysWOW64"),
            os.environ.get("ProgramFiles", r"C:\Program Files"),
            os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
            os.environ.get("ProgramData", r"C:\ProgramData"),
        ])
    else:
        common.extend([
            "/etc",
            "/proc",
            "/sys",
            "/var/log",
            "/boot",
            "/root/.ssh",
        ])
    return tuple(os.path.realpath(p) for p in common)


# 硬拒的敏感路径前缀（realpath 比较，覆盖符号链接绕过）。
_SENSITIVE_PATH_PREFIXES = _build_sensitive_paths()


def _get_output_dir() -> str:
    """获取输出根目录：agent workspace 优先，否则全局 fallback。"""
    if _output_base:
        return os.path.join(_output_base, "workspace")
    return os.environ.get(
        "XIAOMEI_OUTPUT_DIR",
        os.path.expanduser("~/.xiaomei-brain/global/workspace"),
    )


def set_output_base(base_dir: str) -> None:
    """设置 per-agent 输出根目录。由 agent_manager.init_agent() 调用。"""
    global _output_base
    _output_base = base_dir


def _get_allowed_roots() -> list[str]:
    """绝对路径允许的根目录列表。

    默认仅允许 agent workspace；可通过 `XIAOMEI_ALLOWED_PATHS`（用系统路径分隔符）追加。
    Linux 用冒号，Windows 用分号。
    """
    roots: list[str] = []
    workspace = _get_output_dir()
    if workspace:
        roots.append(os.path.realpath(workspace))
    extra = os.environ.get("XIAOMEI_ALLOWED_PATHS", "")
    for p in extra.split(os.pathsep):
        p = p.strip()
        if p:
            try:
                roots.append(os.path.realpath(p))
            except Exception:
                continue
    return roots


def _is_sensitive(real_path: str) -> str | None:
    """检查 real_path 是否落在敏感前缀下，返回拒绝原因；否则返回 None。"""
    for prefix in _SENSITIVE_PATH_PREFIXES:
        if real_path == prefix or real_path.startswith(prefix + os.sep):
            return prefix
    return None


def _resolve_path(path: str) -> tuple[str, str]:
    """将用户给的路径解析为 realpath，并校验可访问性。

    Returns:
        (real_full_path, error_message)。成功时 error_message 为空字符串。

    规则：
    - 先用 expanduser 展开 `~` / `~user`，避免 `~/.ssh/id_rsa` 被当相对路径绕过
    - 相对路径 → 拼接到 output_dir，然后 realpath。
    - 绝对路径 → 必须 realpath 后落在 `_get_allowed_roots()` 某个根下。
    - 任何路径 → realpath 后不能在 `_SENSITIVE_PATH_PREFIXES` 敏感前缀内。
    - 解析过程中任何 `..` / 符号链接都会被 realpath 展开后再检查。
    """
    if not path:
        return "", f"Error: empty path"

    # 必须先 expanduser：否则 `~/.ssh/id_rsa` 会落到 workspace 内
    expanded = os.path.expanduser(path)

    if os.path.isabs(expanded):
        full_path = expanded
    else:
        full_path = os.path.join(_get_output_dir(), expanded)

    try:
        real_path = os.path.realpath(full_path)
    except Exception as e:
        return "", f"Error: cannot resolve path '{path}': {e}"

    # 敏感路径硬拒：realpath 在前，`..` / 符号链接绕过都会被展开
    sensitive = _is_sensitive(real_path)
    if sensitive:
        return "", (
            f"Error: access denied. '{path}' resolves to '{real_path}', "
            f"which is under a sensitive location ({sensitive}). "
            f"For security, file tools cannot access SSH keys, cloud credentials, "
            f"shell history, or system files. Use a different method."
        )

    if os.path.isabs(path):
        allowed_roots = _get_allowed_roots()
        is_allowed = any(
            real_path == r or real_path.startswith(r + os.sep)
            for r in allowed_roots
        )
        if not is_allowed:
            allowed_display = ", ".join(allowed_roots) if allowed_roots else "(none)"
            return "", (
                f"Error: access denied. Absolute path '{path}' resolves to "
                f"'{real_path}', which is outside the allowed directories: "
                f"{allowed_display}. Use a RELATIVE path (resolved to the workspace) "
                f"or add the parent directory to XIAOMEI_ALLOWED_PATHS."
            )

    return real_path, ""


@tool(name="read_file",
      description="Read the contents of a file. "
      "Use a RELATIVE path for files in the workspace directory. "
      "Example: read_file('hello.py') reads ~/.xiaomei-brain/global/workspace/hello.py")
def read_file(path: str) -> str:
    """Read a file and return its contents. Relative paths resolved to workspace dir.

    Security: absolute paths must be under the agent workspace (or XIAOMEI_ALLOWED_PATHS).
    Sensitive paths (SSH keys, cloud credentials, /etc, etc.) are always rejected.
    """
    real_path, error = _resolve_path(path)
    if error:
        return error
    try:
        with open(real_path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return f"Error: file not found: {path}"
    except Exception as e:
        return f"Error: {e}"


@tool(name="write_file", description="Write content to a file. "
      "Always use a RELATIVE path — files are auto-saved to the examples directory. "
      "Example: write_file('hello_world.py', '...') saves to examples/hello_world.py")
def write_file(path: str, content: str) -> str:
    """Write content to a file. Relative paths are saved to the default output directory.

    Args:
        path: File path (relative paths are saved to examples/, absolute paths used as-is)
        content: File content

    Security: same access controls as read_file.
    """
    real_path, error = _resolve_path(path)
    if error:
        return error
    try:
        parent = os.path.dirname(real_path)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent, exist_ok=True)
        with open(real_path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Successfully wrote to {real_path}"
    except Exception as e:
        return f"Error: {e}"


@tool(name="edit_file",
      description="Edit an existing file by replacing old_string with new_string. "
      "Use this when modifying code — not for creating new files. "
      "The old_string must match the file content exactly (including whitespace).")
def edit_file(path: str, old_string: str, new_string: str) -> str:
    """Edit a file by replacing old_string with new_string.

    Performs a line-by-line diff and returns structured result
    so the caller can display a Claude-style diff.

    Args:
        path: File path (relative paths resolved to workspace dir)
        old_string: Exact text to find and replace (must match file content)
        new_string: Replacement text

    Returns:
        JSON with file_path, old_lines, new_lines, and diff output, or error message.
    """
    real_path, error = _resolve_path(path)
    if error:
        return json.dumps({"error": error})

    try:
        with open(real_path, "r", encoding="utf-8") as f:
            original = f.read()

        if old_string not in original:
            return json.dumps({
                "error": "old_string not found in file",
                "file": real_path,
            })

        new_content = original.replace(old_string, new_string, 1)
        with open(real_path, "w", encoding="utf-8") as f:
            f.write(new_content)

        idx = original.find(old_string)
        if idx < 0:
            added_l, removed_l = [], []
            removed_content, added_content = [], []
            base = 0
        else:
            base = original[:idx].count("\n") + 1
            # 不以 \n 结尾 → 最后一行算入；否则 \n 已是分隔符，下一行才开始
            removed_l = list(range(base, base + old_string.count("\n") + (0 if old_string.endswith("\n") else 1)))
            added_l = list(range(base, base + new_string.count("\n") + (0 if new_string.endswith("\n") else 1))) if new_string else []
            removed_content = old_string.split("\n")
            added_content = new_string.split("\n") if new_string else []

        return json.dumps({
            "file_path": real_path,
            "added_lines": added_l,
            "removed_lines": removed_l,
            "added_count": len(added_l),
            "removed_count": len(removed_l),
            "removed_content": removed_content,
            "added_content": added_content,
            "base_line": base,
        }, ensure_ascii=False)

    except Exception as e:
        return json.dumps({"error": str(e)})


read_file_tool: Tool = read_file
write_file_tool: Tool = write_file
edit_file_tool: Tool = edit_file
