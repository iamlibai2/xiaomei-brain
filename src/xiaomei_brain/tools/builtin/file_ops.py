"""File operation tools."""

from __future__ import annotations

import os

from ..base import Tool, tool

# 默认输出目录（LLM 写文件时如果给相对路径，自动拼接到此目录）
# 可通过环境变量 XIAOMEI_OUTPUT_DIR 覆盖
DEFAULT_OUTPUT_DIR = os.environ.get(
    "XIAOMEI_OUTPUT_DIR",
    os.path.expanduser("~/.xiaomei-brain/workspace"),
)


def _read_file_content(path: str) -> str | None:
    """Read file content. Returns None if not found."""
    try:
        if not os.path.isabs(path):
            full_path = os.path.join(DEFAULT_OUTPUT_DIR, path)
        else:
            full_path = path
        with open(full_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None


@tool(name="read_file",
      description="Read the contents of a file. "
      "Use a RELATIVE path for files in the workspace directory. "
      "Example: read_file('hello.py') reads ~/.xiaomei-brain/workspace/hello.py")
def read_file(path: str) -> str:
    """Read a file and return its contents. Relative paths resolved to workspace dir."""
    content = _read_file_content(path)
    if content is None:
        return f"Error: file not found: {path}"
    return content


@tool(name="write_file", description="Write content to a file. "
      "Always use a RELATIVE path — files are auto-saved to the examples directory. "
      "Example: write_file('hello_world.py', '...') saves to examples/hello_world.py")
def write_file(path: str, content: str) -> str:
    """Write content to a file. Relative paths are saved to the default output directory.

    Args:
        path: File path (relative paths are saved to examples/, absolute paths used as-is)
        content: File content
    """
    try:
        # 相对路径 → 拼接到默认输出目录
        if not os.path.isabs(path):
            full_path = os.path.join(DEFAULT_OUTPUT_DIR, path)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
        else:
            full_path = path

        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Successfully wrote to {full_path}"
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
    import json

    try:
        if not os.path.isabs(path):
            full_path = os.path.join(DEFAULT_OUTPUT_DIR, path)
        else:
            full_path = path

        with open(full_path, "r", encoding="utf-8") as f:
            original = f.read()

        if old_string not in original:
            return json.dumps({
                "error": "old_string not found in file",
                "file": full_path,
            })

        new_content = original.replace(old_string, new_string, 1)
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(new_content)

        # Compute line numbers for the replaced region
        idx = original.find(old_string)
        if idx < 0:
            added_l, removed_l = [], []
        else:
            # base = line number where old_string starts (1-based)
            # count("\n") = number of full lines the string spans
            # If old_string ends with \n: it's full lines only, use count(newlines)
            # If old_string doesn't end with \n: last line included, use count+1
            base = original[:idx].count("\n") + 1
            removed_l = list(range(base, base + old_string.count("\n") + (0 if old_string.endswith("\n") else 1)))
            added_l = list(range(base, base + new_string.count("\n") + (0 if new_string.endswith("\n") else 1))) if new_string else []

        return json.dumps({
            "file_path": full_path,
            "added_lines": added_l,
            "removed_lines": removed_l,
            "added_count": len(added_l),
            "removed_count": len(removed_l),
        }, ensure_ascii=False)

    except Exception as e:
        return json.dumps({"error": str(e)})


read_file_tool: Tool = read_file
write_file_tool: Tool = write_file
edit_file_tool: Tool = edit_file
