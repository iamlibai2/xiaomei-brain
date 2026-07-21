"""EventHandler — Gateway 事件 → ChatLog + StreamAssembler 分发。

参考 OpenClaw tui-event-handlers.ts。
工厂函数模式：create_event_handler(chat_log, assembler, state) → EventHandler
"""

from __future__ import annotations

import logging
import time

from xiaomei_brain.tui.state import AppState, ConnectionStatus, ActivityState, get_state
from xiaomei_brain.tui.chat_log import ChatLog
from xiaomei_brain.tui.stream_assembler import StreamAssembler
from xiaomei_brain.tui.text_utils import sanitize, sanitize_streaming

logger = logging.getLogger(__name__)


class EventHandler:
    """Gateway 事件处理器。

    将 Gateway 推送的事件转换为 ChatLog 生命周期调用。
    """

    def __init__(
        self,
        chat_log: ChatLog | None = None,
        assembler: StreamAssembler | None = None,
        state: AppState | None = None,
    ) -> None:
        self.chat_log = chat_log or ChatLog()
        self.assembler = assembler or StreamAssembler()
        self.state = state or get_state()

    def handle(self, event_name: str, payload: dict) -> None:
        """主分发入口。"""
        if event_name == "message.delta":
            self._on_chat_chunk(payload)
        elif event_name == "message.complete":
            self._on_session_message(payload)
        elif event_name == "error":
            self._on_error(payload)
        else:
            logger.debug("Unknown event: %s", event_name)

    def handle_res(self, data: dict) -> None:
        """处理 res 帧（由 GatewayClient 传入）。"""
        if "result" in data:
            return
        err = data.get("error", {})
        msg = err.get("message", str(err))
        self.chat_log.add_error(f"[{err.get('code', 'ERR')}] {msg}")
        self.state.activity_state = ActivityState.ERROR
        self.state.connection_status = ConnectionStatus.ERROR

    # ── 私有 ────────────────────────────────────────────────

    def _on_chat_chunk(self, payload: dict) -> None:
        """流式文本块。"""
        text = payload.get("text", "")
        if not text:
            return

        text = sanitize_streaming(text)
        run_id = payload.get("run_id", "default")

        self.assembler.ingest(run_id, text)
        self.chat_log.update_assistant(self.assembler.get_text(run_id), run_id)

        self.state.streaming = True
        self.state.activity_state = ActivityState.STREAMING
        self.state.connection_status = ConnectionStatus.STREAMING
        if self.state.streaming_started == 0:
            self.state.streaming_started = time.monotonic()

    def _on_session_message(self, payload: dict) -> None:
        """最终完整消息。"""
        status = payload.get("status", "complete")
        if status == "interrupted":
            self._on_aborted(payload)
            return
        if status == "error" and not payload.get("text"):
            error = payload.get("error") or {}
            self._on_error({"text": error.get("message", "未知错误")})
            return
        text = payload.get("text", "")
        run_id = payload.get("run_id", "default")

        text = sanitize(text)

        # Finalize assembler（回退链）
        self.assembler.finalize(run_id, text)
        final_text = self.assembler.get_final_text(run_id)

        # Finalize chat log
        self.chat_log.finalize_assistant(run_id, final_text)

        # 恢复状态
        self.state.streaming = False
        self.state.streaming_started = 0
        self.state.activity_state = ActivityState.IDLE
        self.state.connection_status = ConnectionStatus.CONNECTED
        self.state.msg_count += 1

    def _on_aborted(self, payload: dict) -> None:
        """聊天已中断。"""
        run_id = payload.get("run_id", "default")
        self.assembler.drop(run_id)
        self.chat_log.drop_assistant(run_id)

        self.state.streaming = False
        self.state.streaming_started = 0
        self.state.activity_state = ActivityState.IDLE
        self.state.connection_status = ConnectionStatus.CONNECTED

    def _on_error(self, payload: dict) -> None:
        """聊天错误。"""
        err_msg = payload.get("error", payload.get("text", "未知错误"))
        self.chat_log.add_error(f"[错误] {err_msg}")

        self.state.streaming = False
        self.state.streaming_started = 0
        self.state.activity_state = ActivityState.ERROR
        self.state.connection_status = ConnectionStatus.ERROR


# ── Factory ─────────────────────────────────────────────────────

def create_event_handler(
    chat_log: ChatLog | None = None,
    assembler: StreamAssembler | None = None,
    state: AppState | None = None,
) -> EventHandler:
    """工厂函数：创建 EventHandler（OpenClaw 风格显式依赖注入）。"""
    return EventHandler(chat_log=chat_log, assembler=assembler, state=state)
