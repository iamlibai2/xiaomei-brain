"""RoundScheduler — 轮次频率调度器。

每轮调用 tick()，按注册的间隔自动分发到对应 handler。
handler 内部自行判断是否真正执行（数据就绪、冷却等）。

Usage:
    scheduler = RoundScheduler()
    scheduler.every(1, self._salience_feedback)
    scheduler.every(3, self._invoke_inner_voice_chat_turn)

    # 每轮对话后：
    scheduler.tick(user_msg=..., response_len=..., ...)
"""

from __future__ import annotations

from typing import Any, Callable


class RoundScheduler:
    def __init__(self) -> None:
        self._round: int = 0
        self._handlers: list[tuple[int, Callable[..., Any]]] = []

    def every(self, interval: int, fn: Callable[..., Any]) -> None:
        """注册每 `interval` 轮执行一次的 handler。"""
        self._handlers.append((interval, fn))

    def tick(self, **ctx: Any) -> None:
        """每轮调用，按频率分发到已注册 handler。"""
        self._round += 1
        for interval, fn in self._handlers:
            if self._round % interval == 0:
                fn(**ctx)

    @property
    def round(self) -> int:
        return self._round
