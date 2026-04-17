"""Shell command execution tool."""

from __future__ import annotations

import subprocess

from ..base import Tool, tool


@tool(name="shell", description="Run a shell command and return its output")
def run_shell(command: str) -> str:
    """Run a shell command and return stdout/stderr."""
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
        return "Error: command timed out after 30 seconds"
    except Exception as e:
        return f"Error: {e}"


shell_tool: Tool = run_shell
