"""Living: 纯生命周期管理基类。

状态机 + 消息队列 + 主循环，不包含任何意识/Drive/Purpose 逻辑。
ConsciousLiving 继承此类，通过 hook 方法注入意识行为。

状态流转：
    DORMANT → WAKING → AWAKE ⇄ IDLE → SLEEPING → DREAMING → SLEEPING ...
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable

logger = logging.getLogger(__name__)


# ── States ──────────────────────────────────────────────────────────────

class LivingState(Enum):
    DORMANT = "dormant"
    WAKING = "waking"
    AWAKE = "awake"
    IDLE = "idle"
    SLEEPING = "sleeping"
    DREAMING = "dreaming"


# ── Message ─────────────────────────────────────────────────────────────

@dataclass
class LivingMessage:
    """外部消息"""
    content: str
    user_id: str = "global"
    session_id: str = "main"
    source: str = ""


# ── Heartbeat results ───────────────────────────────────────────────────

HEARTBEAT_NORMAL = "normal"
HEARTBEAT_DREAM = "dream"          # 触发 DREAMING 状态切换


# ── Living ──────────────────────────────────────────────────────────────

class Living:
    """纯生命周期管理。

    提供：状态机、消息队列、主循环、4 个状态循环。
    不包含：意识、Drive、Purpose、Intent、聊天。

    Hook 方法（子类覆盖）：
    - _heartbeat(state, **kwargs) → str
    - _handle_message(msg) → None
    - _on_wake()
    - _on_wake_up()
    - _on_stop()
    - _on_transition(old, new)
    """

    def __init__(
        self,
        agent_instance: Any,
        idle_threshold: float = 1800,
        dream_interval: float = 300,
        idle_short: float = 300,
        session_id: str = "main",
        user_id: str = "global",
        tick_interval: float = 1.0,
    ) -> None:
        self.agent = agent_instance
        self.state = LivingState.DORMANT

        self.idle_threshold = idle_threshold
        self.dream_interval = dream_interval
        self.idle_short = idle_short
        self.session_id = session_id
        self.user_id = user_id
        self.tick_interval = tick_interval

        # 消息队列
        self._queue: queue.Queue[LivingMessage | None] = queue.Queue()
        self._last_active: float = 0
        self._running: bool = False
        self._cancel_requested: bool = False
        self._chatting = False
        self._command_done = threading.Event()

        # 回调
        self.on_proactive: Callable[[Any], Any] | None = None
        self.on_chat_chunk: Callable[[str], Any] | None = None
        self.on_confirm_required: Callable[[dict], Any] | None = None

        # CLI 提示符
        self._show_prompt: bool = True

        # 目标确认
        self._pending_confirm: dict | None = None
        self._waiting_confirm: bool = False
        self._pending_confirm_msg: LivingMessage | None = None
        self._pending_confirm_intent: Any = None

        # 意图模式
        self._intent_mode: bool = False

    # ── Public API ──────────────────────────────────────────────────

    def put_message(
        self,
        content: str,
        user_id: str | None = None,
        session_id: str | None = None,
        source: str = "",
    ) -> None:
        """放入消息（字符级过滤）"""
        if isinstance(content, str):
            content = self._clean_input(content)
        msg = LivingMessage(
            content=content,
            user_id=user_id or self.user_id,
            session_id=session_id or self.session_id,
            source=source,
        )
        self._queue.put_nowait(msg)

    @staticmethod
    def _clean_input(text: str) -> str:
        from xiaomei_brain.agent.message_utils import clean_input
        return clean_input(text)

    def run(self) -> None:
        """主循环，阻塞运行"""
        print(f"[Living] 启动生命循环（当前状态: {self.state.value}）", flush=True)
        self._running = True

        self._transition(LivingState.WAKING)
        self._on_wake()
        self._transition(LivingState.AWAKE)

        while self._running:
            if self.state == LivingState.AWAKE:
                self._loop_awake()
            elif self.state == LivingState.IDLE:
                self._loop_idle()
            elif self.state == LivingState.SLEEPING:
                self._loop_sleeping()
            elif self.state == LivingState.DREAMING:
                self._loop_dreaming()
            else:
                logger.warning("[Living] Unexpected state: %s", self.state)
                time.sleep(1)

    def stop(self) -> None:
        """停止主循环"""
        self._running = False
        self._queue.put_nowait(None)
        self._on_stop()

    def cancel(self) -> None:
        """请求取消当前动作"""
        self._cancel_requested = True

    def reset_cancel(self) -> None:
        """重置取消标志"""
        self._cancel_requested = False

    # ── Properties ──────────────────────────────────────────────────

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def living_state(self) -> str:
        return self.state.value

    # ── State transitions ───────────────────────────────────────────

    def _transition(self, new_state: LivingState) -> None:
        old = self.state
        self.state = new_state
        if old != new_state:
            logger.info("[Living] 状态转换: %s → %s", old.value, new_state.value)
        self._on_transition(old, new_state)

    # ── Prompt ──────────────────────────────────────────────────────

    def _print_prompt(self) -> None:
        """print 输入提示符"""
        if self._show_prompt:
            import shutil
            width = shutil.get_terminal_size().columns
            print("\n" + "─" * width)
            print("> ", end="", flush=True)

    # ── Message wait ────────────────────────────────────────────────

    def _wait_message(self, timeout: float) -> LivingMessage | None:
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    # ── Loop: AWAKE ─────────────────────────────────────────────────

    def _loop_awake(self) -> None:
        logger.debug("[Living/AWAKE] tick 间隔=%.1f秒, idle阈值=%.1f秒",
                     self.tick_interval, self.idle_threshold)

        self._heartbeat(self.state)

        msg = self._wait_message(timeout=self.tick_interval)
        if msg is not None:
            logger.info("[Living/AWAKE] 收到消息")
            self._handle_message(msg)
            self._last_active = time.time()
            return

        idle_time = time.time() - self._last_active
        if idle_time >= self.idle_threshold:
            logger.info("[Living/AWAKE] 空闲 %.1f秒 ≥ %.1f，进入 SLEEPING",
                        idle_time, self.idle_threshold)
            self._transition(LivingState.SLEEPING)
        elif idle_time >= self.idle_short:
            logger.info("[Living/AWAKE] 空闲 %.1f秒 ≥ %.1f，进入 IDLE",
                        idle_time, self.idle_short)
            self._transition(LivingState.IDLE)

    # ── Loop: IDLE ──────────────────────────────────────────────────

    def _loop_idle(self) -> None:
        while True:
            self._heartbeat(self.state)

            msg = self._wait_message(timeout=self.tick_interval)
            if msg is not None:
                logger.info("[Living/IDLE] 收到消息，唤醒回 AWAKE")
                self._on_wake_up()
                self._transition(LivingState.AWAKE)
                self._handle_message(msg)
                self._last_active = time.time()
                return

            idle_time = time.time() - self._last_active
            if idle_time >= self.idle_threshold:
                logger.info("[Living/IDLE] 空闲 %.1f秒 ≥ %.1f，进入 SLEEPING",
                            idle_time, self.idle_threshold)
                self._transition(LivingState.SLEEPING)
                return

    # ── Loop: SLEEPING ──────────────────────────────────────────────

    def _loop_sleeping(self) -> None:
        dream_start = time.time()

        while True:
            result = self._heartbeat(self.state, dream_start=dream_start)

            if result == HEARTBEAT_DREAM:
                logger.info("[Living/SLEEPING] 触发 DREAMING")
                self._transition(LivingState.DREAMING)
                return

            msg = self._wait_message(timeout=self.tick_interval)
            if msg is not None:
                logger.info("[Living/SLEEPING] 收到消息，唤醒回 AWAKE")
                self._on_wake_up()
                self._transition(LivingState.AWAKE)
                self._handle_message(msg)
                self._last_active = time.time()
                return

    # ── Loop: DREAMING ──────────────────────────────────────────────

    def _loop_dreaming(self) -> None:
        logger.info("[Living/DREAMING] 开始梦境循环")

        if self._should_skip_dreaming():
            self._transition(LivingState.SLEEPING)
            return

        dream_start = time.time()
        l3_fired = False

        while True:
            result = self._heartbeat(
                self.state, in_dream=True, dream_start=dream_start,
            )

            if result == HEARTBEAT_DREAM and not l3_fired:
                l3_fired = True
                continue

            if l3_fired:
                logger.info("[Living/DREAMING] 已完成，切回 SLEEPING")
                self._transition(LivingState.SLEEPING)
                return

            msg = self._wait_message(timeout=self.dream_interval)
            if msg is not None:
                logger.info("[Living/DREAMING] 收到消息，唤醒回 AWAKE")
                self._on_wake_up()
                self._transition(LivingState.AWAKE)
                self._handle_message(msg)
                self._last_active = time.time()
                return

            elapsed = time.time() - dream_start
            if elapsed >= self.dream_interval * 2:
                logger.warning("[Living/DREAMING] 超时(%.1f秒)，强制切回 SLEEPING", elapsed)
                self._transition(LivingState.SLEEPING)
                return

    # ── Hooks (no-op in base) ───────────────────────────────────────

    def _should_skip_dreaming(self) -> bool:
        return False

    def _heartbeat(self, state: LivingState, **kwargs) -> str:
        """每个 tick 周期调用。子类覆盖实现意识/Drive tick。

        Returns:
            HEARTBEAT_NORMAL 或 HEARTBEAT_DREAM。
        """
        return HEARTBEAT_NORMAL

    def _handle_message(self, msg: LivingMessage) -> None:
        """处理收到的消息。子类必须覆盖。"""
        raise NotImplementedError

    def _on_wake(self) -> None:
        """DORMANT → AWAKE 转换时调用一次。"""

    def _on_wake_up(self) -> None:
        """从 SLEEPING/IDLE 唤醒回 AWAKE 时调用。"""

    def _on_stop(self) -> None:
        """停止时调用（保存状态等）。"""

    def _on_transition(self, old: LivingState, new_state: LivingState) -> None:
        """每次状态转换后调用。"""
