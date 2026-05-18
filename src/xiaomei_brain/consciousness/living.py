"""Living: 纯生命周期管理基类。

状态机 + 消息队列 + 主循环 + 注册式周期任务，不包含任何意识/Drive/Purpose 逻辑。
ConsciousLiving 继承此类，通过 register_periodic() 注册周期任务。

状态流转：
    DORMANT → WAKING → AWAKE ⇄ IDLE → SLEEPING → DREAMING → SLEEPING ...
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass, field
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
    images: list[str] = field(default_factory=list)  # 图片路径或 URL 列表


# ── Heartbeat results ───────────────────────────────────────────────────

HEARTBEAT_NORMAL = "normal"
HEARTBEAT_DREAM = "dream"          # 触发 DREAMING 状态切换


# ── Periodic Task ───────────────────────────────────────────────────────

@dataclass
class PeriodicTask:
    """注册式周期任务"""
    name: str
    interval: float
    handler: Callable[[LivingState], Any]
    last_fired: float = 0.0


# ── Living ──────────────────────────────────────────────────────────────

class Living:
    """纯生命周期管理。

    提供：状态机、消息队列、主循环、4 个状态循环、注册式周期任务。
    不包含：意识、Drive、Purpose、Intent、聊天。

    Hook 方法（子类覆盖）：
    - _handle_message(msg) → None
    - _on_wake()
    - _on_wake_up()
    - _on_stop()
    - _on_transition(old, new)
    - _get_heartbeat_result() → str

    周期任务注册：
    - register_periodic(name, interval, handler)
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

        # 周期任务
        self._periodic_tasks: list[PeriodicTask] = []
        self._heartbeat_result: str = HEARTBEAT_NORMAL

        # 回调
        self.on_proactive: Callable[[Any], Any] | None = None
        self.on_chat_chunk: Callable[[str], Any] | None = None
        self.on_confirm_required: Callable[[dict], Any] | None = None

        # CLI 提示符
        self._show_prompt: bool = True

    # ── Periodic task registration ──────────────────────────────────

    def register_periodic(
        self, name: str, interval: float, handler: Callable[[LivingState], Any],
    ) -> None:
        """注册周期任务。

        Args:
            name: 任务名称（唯一标识，用于日志）
            interval: 触发间隔（秒）
            handler: 回调函数，接收 LivingState 参数
        """
        # 同名任务替换
        self._periodic_tasks = [t for t in self._periodic_tasks if t.name != name]
        self._periodic_tasks.append(PeriodicTask(name=name, interval=interval, handler=handler))
        logger.info("[Living] 注册周期任务: %s (间隔%.1fs)", name, interval)

    def _tick_periodic(self, state: LivingState) -> None:
        """在每个状态循环中调用，触发到期的周期任务。"""
        now = time.time()
        for task in self._periodic_tasks:
            if now - task.last_fired >= task.interval:
                try:
                    task.handler(state)
                    task.last_fired = now
                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    logger.warning("[Living] 周期任务 %s 出错: %s", task.name, e)

    def _get_heartbeat_result(self) -> str:
        """子类覆盖：返回心跳结果（HEARTBEAT_NORMAL / HEARTBEAT_DREAM）。

        ConsciousLiving 在 _heartbeat() 中设置 self._heartbeat_result，
        此方法供基类循环读取。
        """
        return self._heartbeat_result

    # ── Public API ──────────────────────────────────────────────────

    def put_message(
        self,
        content: str,
        user_id: str | None = None,
        session_id: str | None = None,
        source: str = "",
        images: list[str] | None = None,
    ) -> None:
        """放入消息（字符级过滤）"""
        if isinstance(content, str):
            content = self._clean_input(content)
        msg = LivingMessage(
            content=content,
            user_id=user_id or self.user_id,
            session_id=session_id or self.session_id,
            source=source,
            images=images or [],
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
        """print 输入提示符（纯 ASCII，避免 WSL readline 中文宽度计算错误）"""
        if self._show_prompt:
            print("\n> ", end="", flush=True)

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

        self._heartbeat_result = HEARTBEAT_NORMAL
        self._tick_periodic(self.state)

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
            self._heartbeat_result = HEARTBEAT_NORMAL
            self._tick_periodic(self.state)

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
            self._heartbeat_result = HEARTBEAT_NORMAL
            self._tick_periodic(self.state)

            if self._get_heartbeat_result() == HEARTBEAT_DREAM:
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
            self._heartbeat_result = HEARTBEAT_NORMAL
            self._tick_periodic(self.state)

            if self._get_heartbeat_result() == HEARTBEAT_DREAM and not l3_fired:
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
