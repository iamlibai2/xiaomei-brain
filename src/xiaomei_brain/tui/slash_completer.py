"""SlashCompleter — prompt_toolkit 斜杠命令自动补全。

参考 OpenClaw components/slash-completer.ts。
"""

from __future__ import annotations

from prompt_toolkit.completion import Completer, Completion


# ── 所有可补全的命令 ─────────────────────────────────────────────

# TUI 内部命令（本地处理，不发送到 Gateway）
_TUI_COMMANDS = [
    ("clear", "清空屏幕消息"),
    ("quit", "退出 TUI"),
    ("exit", "退出 TUI"),
    ("help", "显示所有命令"),
    ("status", "显示连接状态"),
    ("history", "加载聊天历史"),
    ("theme", "切换主题: /theme dark|light|auto"),
    ("statusbar", "显示/隐藏状态栏"),
    ("tools", "开启/关闭工具卡片检测"),
]

# 意识层命令（发送到 Gateway，由 Agent 处理）
_CONSCIOUSNESS_COMMANDS = [
    ("intent", "显示当前意图"),
    ("fuel", "手动触发加柴"),
    ("flame", "显示火焰状态"),
    ("tick", "显示心跳计数"),
    ("think", "显示内在想法"),
    ("identity", "显示意识全景"),
    ("drive", "显示 Drive 状态"),
    ("purpose", "显示 Purpose 状态"),
    ("plan", "显示当前计划"),
    ("model", "切换模型"),
    ("export", "导出会话"),
    ("pace-stats", "PACE 统计报告"),
    ("sessions", "列出所有会话"),
    ("switch", "切换会话"),
    ("user", "查看/切换身份"),
]

# 记忆/Agent 命令
_MEMORY_COMMANDS = [
    ("db", "对话日志查询"),
    ("memory", "记忆查询"),
    ("dag", "DAG 图谱查看"),
    ("summarize", "触发摘要"),
    ("periodic", "触发定期提取"),
    ("dream", "触发梦境"),
    ("context", "显示上下文"),
    ("new", "新建会话"),
]

_ALL_COMMANDS = _TUI_COMMANDS + _CONSCIOUSNESS_COMMANDS + _MEMORY_COMMANDS

# 二级补全
_SUB_COMPLETIONS: dict[str, list[str]] = {
    "theme": ["dark", "light", "auto"],
    "model": [],  # 动态填充
    "tools": ["on", "off"],
    "statusbar": ["on", "off"],
    "user": [],  # 动态填充
    "switch": [],  # 动态填充
}


class SlashCompleter(Completer):
    """斜杠命令补全器。"""

    def __init__(self) -> None:
        self._sub_completions: dict[str, list[str]] = dict(_SUB_COMPLETIONS)

    def update_sub_completions(self, key: str, values: list[str]) -> None:
        """动态更新二级补全选项（如 model 列表）。"""
        self._sub_completions[key] = values

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        if not text.startswith("/"):
            return

        # 解析命令部分
        stripped = text[1:]  # 去掉 /
        parts = stripped.split(None, 1)
        cmd = parts[0] if parts else ""

        if len(parts) == 1 and not stripped.endswith(" "):
            # 补全命令名
            word_before_cursor = cmd
            for name, desc in _ALL_COMMANDS:
                if name.startswith(word_before_cursor):
                    yield Completion(
                        name,
                        start_position=-len(word_before_cursor),
                        display=f"/{name}",
                        display_meta=desc,
                    )
        elif len(parts) >= 2 or (len(parts) == 1 and stripped.endswith(" ")):
            # 补全参数
            arg_text = parts[1] if len(parts) >= 2 else ""
            sub = self._sub_completions.get(cmd, [])
            for value in sub:
                if value.startswith(arg_text):
                    yield Completion(
                        value,
                        start_position=-len(arg_text),
                        display=value,
                    )
