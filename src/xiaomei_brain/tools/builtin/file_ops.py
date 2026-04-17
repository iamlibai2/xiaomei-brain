"""File operation tools."""

from __future__ import annotations

from ..base import Tool, tool


@tool(name="read_file", description="Read the contents of a file")
def read_file(path: str) -> str:
    """Read a file and return its contents."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return f"Error: file not found: {path}"
    except Exception as e:
        return f"Error: {e}"


@tool(name="write_file", description="Write content to a file")
def write_file(path: str, content: str) -> str:
    """Write content to a file."""
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Successfully wrote to {path}"
    except Exception as e:
        return f"Error: {e}"


read_file_tool: Tool = read_file
write_file_tool: Tool = write_file
