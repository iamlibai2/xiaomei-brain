"""InternalDisplay — 对话内部处理结果展示。

每轮对话结束后，以 boot 风格区块展示记忆提取、内心声音、DAG 压缩等。
同时输出结构化数据供 WebSocket/TUI 使用。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field


# ── 颜色（与 boot.py 保持一致）────────────────────────────
C_DIM = "\033[38;5;73m"   # dusty teal
C_OK = "\033[38;5;203m"  # coral pink — 内部动作标题
C_FREE = "\033[32m"       # green — 自由表达正文
RESET = "\033[0m"


def print_section(title: str, subtitle: str = "", icon: str = "", color: str = "") -> None:
    """打印内部动作标题行（统一格式）。

    Args:
        title: 标题文本（如 "意图决策"、"进入睡眠"）
        subtitle: 可选的副标题（dim 颜色）
        icon: 可选的 emoji 前缀（如 "🧠"、"🌙"）
        color: 可选的颜色覆盖，默认 C_OK
    """
    c = color or C_OK
    prefix = f"{icon} " if icon else ""
    print()
    print(f"  {c}── {prefix}{title} ──{RESET}", flush=True)
    if subtitle:
        print(f"  {C_DIM}{subtitle}{RESET}", flush=True)


@dataclass
class InternalDisplay:
    """收集并格式化展示内部处理结果。

    双通道输出：
    - CLI:  display() → ANSI 格式化文本打印到 stdout
    - WS:   to_dict() → 结构化 dict，供 TUI 自行渲染

    用法:
        display = InternalDisplay()
        display.record_memory("ADD|标签|内容")
        display.record_inner_voice("今天状态不错...", ["归属欲 0.5→0.6"], "user_happy(0.7)")
        display.display()   # CLI 输出
        ws.send(display.to_dict())  # WS 推送
        display.clear()
    """

    _memory_actions: list[dict] = field(default_factory=list)
    _inner_voice_thought: str = ""
    _inner_voice_drive: list[str] = field(default_factory=list)
    _inner_voice_signal: str = ""
    _social_signal: str = ""
    _social_events: list[str] = field(default_factory=list)
    _social_perception: str = ""
    _gaps_count: int = 0
    _gaps_topics: list[str] = field(default_factory=list)
    _insert_count: int = 0
    _insert_previews: list[str] = field(default_factory=list)
    _inner_voice_mode: str = ""
    _dag_msg_count: int = 0
    _dag_summary_tokens: int = 0
    _periodic_count: int = 0
    _intent_type: str = ""
    _intent_reason: str = ""
    _emergence_stored: int = 0
    _narr_extracted: int = 0
    _doubt_count: int = 0
    _recall_count: int = 0
    _recall_tags: list[str] = field(default_factory=list)
    _procedure_count: int = 0
    _narrative_count: int = 0

    # ── Record ────────────────────────────────────────────

    def record_memory(self, memory_block: str) -> None:
        """记录本轮记忆提取结果。

        Args:
            memory_block: LLM 输出的 <MEMORY> 原始文本
        """
        if not memory_block or not memory_block.strip():
            return
        for action in _parse_memory_actions(memory_block):
            self._memory_actions.append(action)

    def record_inner_voice(self, thought: str, drive_deltas: list[str], signal: str) -> None:
        """记录内心声音结果（来自上一轮的 daemon 线程）。"""
        if thought:
            self._inner_voice_thought = thought
        if drive_deltas:
            self._inner_voice_drive = list(drive_deltas)
        if signal:
            self._inner_voice_signal = signal

    def record_social_cognition(self, signal: str) -> None:
        """记录社交感知结果（来自 L2 SocialCognition.reflect()）。"""
        if signal:
            self._social_signal = signal

    def record_social_events(self, events: list[str]) -> None:
        """记录社交事件摘要（来自 L2 SocialCognition EVENTS 解析）。"""
        if events:
            self._social_events = list(events)

    def record_social_perception(self, text: str) -> None:
        """记录社交感知文本（来自 L2 SocialCognition PERCEPTION，只取第一条截断）。"""
        if text:
            self._social_perception = text[:60] + ("…" if len(text) > 60 else "")

    def record_gaps(self, count: int, topics: list[str]) -> None:
        """记录 InnerVoice 识别到的知识盲区。"""
        if count > 0:
            self._gaps_count = count
            self._gaps_topics = list(topics[:4])

    def record_inserts(self, count: int, previews: list[str]) -> None:
        """记录 InnerVoice 建议插入的步骤。"""
        if count > 0:
            self._insert_count = count
            self._insert_previews = list(previews[:2])

    def record_inner_voice_mode(self, mode: str) -> None:
        """记录 InnerVoice 上下文模式判断。"""
        if mode:
            self._inner_voice_mode = mode

    def record_dag_compact(self, msg_count: int, summary_tokens: int) -> None:
        """记录 DAG 压缩结果。"""
        self._dag_msg_count = msg_count
        self._dag_summary_tokens = summary_tokens

    def record_periodic_extract(self, count: int) -> None:
        """记录定期记忆提取结果。"""
        self._periodic_count = count

    def record_intent(self, intent_type: str, reason: str) -> None:
        """记录意图决策结果。"""
        if intent_type:
            self._intent_type = intent_type
        if reason:
            self._intent_reason = reason

    def record_emergence_stored(self, count: int) -> None:
        """记录内心独白全文已存储。"""
        if count:
            self._emergence_stored = count

    def record_emergence_stats(self, narr_count: int, doubt_count: int) -> None:
        """记录内心独白后处理结果。"""
        if narr_count:
            self._narr_extracted = narr_count
        if doubt_count:
            self._doubt_count = doubt_count

    def record_memory_recall(self, count: int, tags: list[str]) -> None:
        """记录记忆召回结果。"""
        self._recall_count = count
        self._recall_tags = list(tags)

    def record_procedure_learn(self, count: int) -> None:
        """记录流程学习结果。"""
        if count > 0:
            self._procedure_count = count

    def record_narrative_learn(self, count: int) -> None:
        """记录叙事学习结果。"""
        if count > 0:
            self._narrative_count = count

    # ── Has Data ──────────────────────────────────────────

    def has_data(self) -> bool:
        return bool(
            self._memory_actions
            or self._inner_voice_thought
            or self._social_signal
            or self._social_events
            or self._social_perception
            or self._gaps_count
            or self._insert_count
            or self._inner_voice_mode
            or self._dag_msg_count
            or self._periodic_count
            or self._intent_type
            or self._recall_count
            or self._procedure_count
            or self._narrative_count
            or self._emergence_stored
            or self._narr_extracted
            or self._doubt_count
        )

    # ── CLI 输出 ──────────────────────────────────────────

    def display(self) -> None:
        """CLI：直接打印 ANSI 格式化区块。无数据则 silence。"""
        if not self.has_data():
            return
        lines = self.render_lines()
        # 粗略估算最长行的显示宽度（非 ASCII 算 2 列），上限 60 避免过长
        max_w = min(
            max((sum(2 if ord(c) > 127 else 1 for c in line) for line in lines), default=30),
            60,
        )
        extra = max(max_w - 20, 0)
        pad = "─" * (extra // 2 + 2)
        print()
        print(f"  {C_DIM}──{pad} 📋 本轮内部处理 {pad}──{RESET}", flush=True)
        for line in lines:
            print(f"    {line}", flush=True)

    def render_lines(self) -> list[str]:
        """返回 ANSI 格式化的行列表（不含边框头尾）。"""
        lines: list[str] = []

        if self._intent_type:
            lines.append(f"🎯 意图决策结论: {self._intent_type}")
            if self._intent_reason:
                lines.append(f"💡 决策原因: {self._intent_reason}")

        if self._recall_count:
            tags_str = " · ".join(self._recall_tags[:4]) if self._recall_tags else "匹配记忆"
            lines.append(f"🔍 记忆召回: {self._recall_count} 条（{tags_str}）")

        if self._memory_actions:
            parts = []
            for a in self._memory_actions:
                action = a.get("action", "?")
                label = {"ADD": "新增", "UPDATE": "更新", "MERGE": "合并", "DELETE": "删除"}.get(action, action)
                preview = a.get("preview", "")
                parts.append(f'{label} "{preview}"')
            lines.append("🧠 " + " · ".join(parts))

        if self._inner_voice_thought:
            thought = self._inner_voice_thought.replace("\n", " ").strip()
            if len(thought) > 80:
                thought = thought[:80] + "…"
            lines.append(f'💭 内心声音: "{thought}"')

        if self._inner_voice_drive:
            lines.append("📈 Drive: " + " · ".join(self._inner_voice_drive))

        if self._gaps_count:
            topics_str = " · ".join(self._gaps_topics[:3])
            lines.append(f"📚 知识盲区: {self._gaps_count} 个（{topics_str}）")

        if self._insert_count:
            previews_str = " · ".join(f'"{p}"' for p in self._insert_previews)
            lines.append(f"📝 步骤建议: {self._insert_count} 条（{previews_str}）")

        if self._inner_voice_mode:
            label = {"daily": "日常", "task": "任务", "flow": "心流"}.get(self._inner_voice_mode, self._inner_voice_mode)
            lines.append(f"🔀 模式感知: {label}")

        if self._social_signal:
            lines.append(f"👤 社交感知: {self._social_signal}")
        elif self._inner_voice_signal:
            lines.append(f"👤 社交感知: {self._inner_voice_signal}")

        if self._social_events:
            lines.append("🎭 社交事件: " + " · ".join(self._social_events))

        if self._social_perception:
            lines.append(f'👁 感知: "{self._social_perception}"')

        if self._dag_msg_count:
            lines.append(f"📦 DAG: {self._dag_msg_count} 条消息 → 摘要 ({self._dag_summary_tokens} tokens)")

        if self._periodic_count:
            lines.append(f"🗂 定期提取: {self._periodic_count} 条记忆")

        if self._procedure_count:
            lines.append(f"🧭 流程学习: {self._procedure_count} 条")

        if self._narrative_count:
            lines.append(f"📖 叙事学习: {self._narrative_count} 条")

        if self._emergence_stored:
            lines.append(f"🗂  内心独白记忆: {self._emergence_stored} 篇")

        if self._narr_extracted:
            lines.append(f"✨ 叙事记忆: {self._narr_extracted} 条（NARR 结构化块）")

        if self._doubt_count:
            lines.append(f"🔮 自我不确定: {self._doubt_count} 条")

        return lines

    # ── WS/TUI 结构化输出 ─────────────────────────────────

    def to_dict(self) -> dict:
        """返回结构化数据，供 WebSocket/TUI 渲染。

        Returns:
            {"type": "internal_display", "data": {...}}
            只包含有数据的字段。
        """
        data: dict = {}

        if self._memory_actions:
            data["memory"] = self._memory_actions

        inner_voice: dict = {}
        if self._inner_voice_thought:
            inner_voice["thought"] = self._inner_voice_thought
        if self._inner_voice_drive:
            inner_voice["drive_deltas"] = self._inner_voice_drive
        if self._inner_voice_signal:
            inner_voice["signal"] = self._inner_voice_signal
        if inner_voice:
            data["inner_voice"] = inner_voice

        if self._social_signal:
            data["social_signal"] = self._social_signal
        if self._social_events:
            data["social_events"] = self._social_events
        if self._social_perception:
            data["social_perception"] = self._social_perception

        if self._gaps_count:
            data["gaps"] = {"count": self._gaps_count, "topics": self._gaps_topics}
        if self._insert_count:
            data["inserts"] = {"count": self._insert_count, "previews": self._insert_previews}
        if self._inner_voice_mode:
            data["inner_voice_mode"] = self._inner_voice_mode

        if self._dag_msg_count:
            data["dag"] = {
                "msg_count": self._dag_msg_count,
                "summary_tokens": self._dag_summary_tokens,
            }

        if self._periodic_count:
            data["periodic"] = {"count": self._periodic_count}

        if self._intent_type:
            data["intent"] = {"type": self._intent_type, "reason": self._intent_reason}

        if self._recall_count:
            data["recall"] = {"count": self._recall_count, "tags": self._recall_tags}

        if self._procedure_count:
            data["procedure"] = {"count": self._procedure_count}

        if self._narrative_count:
            data["narrative"] = {"count": self._narrative_count}

        if self._emergence_stored:
            data["emergence_stored"] = self._emergence_stored
        if self._narr_extracted:
            data["narr_extracted"] = self._narr_extracted
        if self._doubt_count:
            data["doubt_count"] = self._doubt_count

        return {"type": "internal_display", "data": data}

    def clear(self) -> None:
        """清空所有数据，准备下一轮。"""
        self._memory_actions.clear()
        self._inner_voice_thought = ""
        self._inner_voice_drive.clear()
        self._inner_voice_signal = ""
        self._social_signal = ""
        self._social_events.clear()
        self._social_perception = ""
        self._gaps_count = 0
        self._gaps_topics.clear()
        self._insert_count = 0
        self._insert_previews.clear()
        self._inner_voice_mode = ""
        self._dag_msg_count = 0
        self._dag_summary_tokens = 0
        self._periodic_count = 0
        self._intent_type = ""
        self._intent_reason = ""
        self._recall_count = 0
        self._recall_tags.clear()
        self._procedure_count = 0
        self._narrative_count = 0
        self._emergence_stored = 0
        self._narr_extracted = 0
        self._doubt_count = 0


# ── 记忆块解析 ────────────────────────────────────────────

def _parse_memory_actions(memory_block: str) -> list[dict]:
    """从 MEMORY block 中提取结构化动作列表。

    Returns:
        [{"action": "ADD", "preview": "用户喜欢Python"}, ...]
    """
    block = memory_block.strip()
    if not block:
        return []

    # JSON 格式
    try:
        data = json.loads(block)
        if isinstance(data, dict) and "actions" in data:
            return [
                {
                    "action": a.get("type", a.get("action", "?")),
                    "preview": _truncate(a.get("content", "")),
                }
                for a in data["actions"]
                if isinstance(a, dict)
            ]
    except (json.JSONDecodeError, TypeError):
        pass

    # 行格式: ADD|tag|content
    actions: list[dict] = []
    for line in block.split("\n"):
        line = line.strip()
        if not line:
            continue
        parts = line.split("|", 2)
        if len(parts) < 2:
            continue
        action = parts[0].strip().upper()
        if action not in ("ADD", "UPDATE", "MERGE", "DELETE"):
            continue
        content = parts[2].strip() if len(parts) > 2 else ""
        actions.append({"action": action, "preview": _truncate(content)})

    return actions


def _truncate(text: str, max_len: int = 30) -> str:
    t = text.replace("\n", " ").strip()
    if len(t) > max_len:
        return t[:max_len] + "…"
    return t


