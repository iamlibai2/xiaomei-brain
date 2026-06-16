"""SlashCompleter — prompt_toolkit 斜杠命令自动补全。

从 CommandHandler 注册表动态读取命令列表，支持二级参数补全。
"""

from __future__ import annotations

from prompt_toolkit.completion import Completer, Completion


class SlashCompleter(Completer):
    """斜杠命令补全器 — 从 CommandHandler 动态获取命令列表。"""

    def __init__(self, command_handler) -> None:
        self._command_handler = command_handler

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        if not text.startswith("/"):
            return

        stripped = text[1:]
        parts = stripped.split(None, 1)
        cmd = parts[0] if parts else ""

        if len(parts) == 1 and not stripped.endswith(" "):
            # 补全命令名
            word_before_cursor = cmd
            for c in self._command_handler.list_all():
                if c.name.startswith(word_before_cursor):
                    yield Completion(
                        c.name,
                        start_position=-len(word_before_cursor),
                        display=f"/{c.name}",
                        display_meta=c.description,
                    )
        elif len(parts) >= 2 or (len(parts) == 1 and stripped.endswith(" ")):
            # 补全参数（仅 switch 命令有 session_id 提示）
            arg_text = parts[1] if len(parts) >= 2 else ""
            if cmd == "switch":
                yield Completion(
                    "session_id",
                    start_position=-len(arg_text),
                    display="<session_id>",
                    display_meta="切换到的会话 ID",
                )
