"""StreamAssembler — per-run delta 累积 + finalize 回退链。

参考 OpenClaw tui-stream-assembler.ts：
  - 增量 delta 累积到 text_buffer
  - finalize 时用回退链：final_text → text_buffer → "(no output)"
  - 解决某些 provider 的 final content 是流式子集导致视觉回跳的问题
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class _RunState:
    """单个 run 的内部状态。"""
    text_buffer: list[str] = field(default_factory=list)
    final_text: str = ""
    finalized: bool = False

    @property
    def accumulated(self) -> str:
        return "".join(self.text_buffer)


class StreamAssembler:
    """per-run_id 流式消息组装器。"""

    def __init__(self) -> None:
        self._runs: dict[str, _RunState] = {}

    # ── 写入 ────────────────────────────────────────────────

    def ingest(self, run_id: str, delta: str) -> None:
        """摄入一个 delta 块。"""
        run = self._runs.get(run_id)
        # 如果 run 已经 finalized，说明是新一轮消息，重置状态
        if run is not None and run.finalized:
            self._runs[run_id] = _RunState()
            run = self._runs[run_id]
        if run is None:
            run = _RunState()
            self._runs[run_id] = run
        run.text_buffer.append(delta)

    def finalize(self, run_id: str, final_text: str) -> None:
        """标记 run 已完成，存储 final text。"""
        run = self._runs.setdefault(run_id, _RunState())
        run.final_text = final_text
        run.finalized = True

    # ── 读取 ────────────────────────────────────────────────

    def get_text(self, run_id: str) -> str:
        """获取当前累积文本（用于流式显示）。"""
        run = self._runs.get(run_id)
        if run is None:
            return ""
        return run.accumulated

    def get_final_text(self, run_id: str) -> str:
        """获取最终文本，走回退链。

        final_text → accumulated → "(no output)"
        """
        run = self._runs.get(run_id)
        if run is None:
            return ""

        # 回退链
        if run.final_text:
            return run.final_text
        if run.accumulated:
            return run.accumulated
        return ""

    def is_finalized(self, run_id: str) -> bool:
        run = self._runs.get(run_id)
        return run is not None and run.finalized

    # ── 清理 ────────────────────────────────────────────────

    def drop(self, run_id: str) -> str:
        """移除 run 并返回最终文本。"""
        run = self._runs.pop(run_id, None)
        if run is None:
            return ""
        # 回退链：final_text → accumulated
        if run.final_text:
            return run.final_text
        if run.accumulated:
            return run.accumulated
        return ""

    @property
    def active_runs(self) -> list[str]:
        """当前正在流式输出的 run 列表。"""
        return [rid for rid, rs in self._runs.items() if not rs.finalized]

    @property
    def active_count(self) -> int:
        return len(self.active_runs)
