"""ChatLog — 消息生命周期管理。

参考 OpenClaw components/chat-log.ts：
  - dequ e[MessageEntry] 管理有序消息
  - Map<runId> 追踪流式 assistant 消息
  - Map<toolId> 追踪 tool 卡片
  - 溢出剪枝（最多 500 条）

生命周期：
  add_user → start_assistant(run_id) → update_assistant × N → finalize_assistant
                                                                  drop_assistant (中断)
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum


class MessageType(Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"
    ERROR = "error"


@dataclass
class MessageEntry:
    """单条消息实体。"""
    type: MessageType
    content: str
    run_id: str | None = None       # streaming assistant 的 run_id
    tool_id: str | None = None      # tool 卡片的 tool_call_id
    tool_name: str = ""             # tool 名称
    tool_args: str = ""             # tool 参数
    tool_state: str = ""            # "pending" | "success" | "error"
    tool_result: str = ""           # tool 结果摘要
    timestamp: float = field(default_factory=time.monotonic)
    is_streaming: bool = False      # 正在接收 chunks
    is_finalized: bool = False      # 已完成


class ChatLog:
    """消息日志容器。"""

    MAX_ENTRIES = 500

    def __init__(self) -> None:
        self._entries: deque[MessageEntry] = deque()
        self._streaming: dict[str, MessageEntry] = {}  # run_id → entry
        self._tools: dict[str, MessageEntry] = {}       # tool_id → entry
        self._dirty: bool = True

    # ── 属性 ────────────────────────────────────────────────

    @property
    def entries(self) -> list[MessageEntry]:
        return list(self._entries)

    @property
    def dirty(self) -> bool:
        return self._dirty

    def mark_clean(self) -> None:
        self._dirty = False

    # ── User / System / Error ────────────────────────────────

    def add_user(self, text: str) -> MessageEntry:
        entry = MessageEntry(type=MessageType.USER, content=text)
        self._append(entry)
        return entry

    def add_system(self, text: str) -> MessageEntry:
        entry = MessageEntry(type=MessageType.SYSTEM, content=text)
        self._append(entry)
        return entry

    def add_error(self, text: str) -> MessageEntry:
        entry = MessageEntry(type=MessageType.ERROR, content=text)
        self._append(entry)
        return entry

    # ── Assistant（流式）─────────────────────────────────────

    def start_assistant(self, run_id: str) -> MessageEntry:
        """创建流式 assistant 消息。"""
        if run_id in self._streaming:
            return self._streaming[run_id]
        entry = MessageEntry(
            type=MessageType.ASSISTANT,
            content="",
            run_id=run_id,
            is_streaming=True,
        )
        self._streaming[run_id] = entry
        self._append(entry)
        return entry

    def update_assistant(self, text: str, run_id: str) -> MessageEntry:
        """更新流式内容（增量替换，不是追加）。"""
        entry = self._streaming.get(run_id)
        if entry is None:
            entry = self.start_assistant(run_id)
        entry.content = text  # 使用累积文本替换
        self._dirty = True
        return entry

    def add_assistant(self, content: str, run_id: str = "") -> MessageEntry:
        """添加已完成的助手消息（用于历史加载和非流式响应）。"""
        entry = MessageEntry(
            type=MessageType.ASSISTANT,
            content=content,
            run_id=run_id,
            is_streaming=False,
            is_finalized=True,
        )
        self._append(entry)
        return entry

    def finalize_assistant(self, run_id: str, text: str = "") -> None:
        """标记流式完成。如果 entry 不存在则创建（处理无 delta 的 message.complete）。"""
        entry = self._streaming.pop(run_id, None)
        if entry is None:
            if text:
                self.add_assistant(text, run_id)
            return
        if text:
            entry.content = text
        entry.is_streaming = False
        entry.is_finalized = True
        self._dirty = True

    def drop_assistant(self, run_id: str) -> None:
        """丢弃流式消息（中断/空输出时调用）。"""
        entry = self._streaming.pop(run_id, None)
        if entry is not None:
            # 从 entries 中移除
            try:
                self._entries.remove(entry)
            except ValueError:
                pass
            self._dirty = True

    # ── Tool ─────────────────────────────────────────────────

    def add_tool(self, tool_id: str, name: str, args: str = "",
                 state: str = "pending") -> MessageEntry:
        """添加 tool 卡片。"""
        entry = MessageEntry(
            type=MessageType.TOOL,
            content="",
            tool_id=tool_id,
            tool_name=name,
            tool_args=args,
            tool_state=state,
        )
        self._tools[tool_id] = entry
        self._append(entry)
        return entry

    def update_tool(self, tool_id: str, result: str = "",
                    state: str = "success", is_error: bool = False) -> None:
        """更新 tool 结果。"""
        entry = self._tools.pop(tool_id, None)
        if entry is None:
            return
        entry.tool_state = "error" if is_error else state
        entry.tool_result = result
        self._dirty = True

    # ── 清空 ─────────────────────────────────────────────────

    def clear(self) -> None:
        """清空所有消息。"""
        self._entries.clear()
        self._streaming.clear()
        self._tools.clear()
        self._dirty = True

    # ── 内部 ─────────────────────────────────────────────────

    def _append(self, entry: MessageEntry) -> None:
        self._entries.append(entry)
        self._dirty = True
        self._prune()

    def _prune(self) -> None:
        """溢出剪枝：超过 MAX_ENTRIES 时移除最旧的。"""
        while len(self._entries) > self.MAX_ENTRIES:
            old = self._entries.popleft()
            # 清理追踪映射
            if old.run_id and old.run_id in self._streaming:
                self._streaming.pop(old.run_id, None)
            if old.tool_id and old.tool_id in self._tools:
                self._tools.pop(old.tool_id, None)
