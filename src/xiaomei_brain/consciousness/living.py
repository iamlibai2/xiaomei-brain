"""Living -- pure lifecycle management base class.

State machine + message queue + main loop + registered periodic tasks.
Contains NO consciousness / Drive / Purpose logic.
ConsciousLiving inherits this class and registers periodic tasks via
register_periodic().

State flow:
    DORMANT -> WAKING -> AWAKE <-> IDLE -> SLEEPING -> DREAMING -> SLEEPING ...

纯生命周期管理基类。

状态机 + 消息队列 + 主循环 + 注册式周期任务。
不包含任何 consciousness / Drive / Purpose 逻辑。
ConsciousLiving 继承此类，通过 register_periodic() 注册周期任务。

状态流转:
    DORMANT -> WAKING -> AWAKE <-> IDLE -> SLEEPING -> DREAMING -> SLEEPING ...
"""

from __future__ import annotations

import logging
import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from xiaomei_brain.llm.client import FatalLLMError

logger = logging.getLogger(__name__)


#---------------------------------------------------------------------------
#   States
#   状态枚举
#---------------------------------------------------------------------------


# Agent lifecycle states.
# Agent 生命周期状态。
class LivingState(Enum):
    # Dormant -- no activity, waiting for message.
    # 休眠 -- 无活动，等待消息。
    DORMANT = "dormant"
    # Waking transition -- loading memory, preparing context.
    # 苏醒过渡 -- 加载记忆，准备上下文。
    WAKING = "waking"
    # Awake -- processing messages, running periodic tasks.
    # 活跃 -- 处理消息，执行周期任务。
    AWAKE = "awake"
    # Idle -- light idle, ready to respond.
    # 空闲 -- 轻度空闲，随时响应。
    IDLE = "idle"
    # Working -- autonomous task execution (ReAct).  IDLE sub-state.
    # 工作 -- 自主任务执行（ReAct），IDLE 子状态。
    WORKING = "working"
    # Sleeping -- deeper idle, may trigger dreaming.
    # 睡眠 -- 深度空闲，可能触发梦境。
    SLEEPING = "sleeping"
    # Dreaming -- LLM-driven reflection / consolidation.
    # 梦境 -- LLM 驱动的反思与整合。
    DREAMING = "dreaming"


#---------------------------------------------------------------------------
#   Message
#   消息
#---------------------------------------------------------------------------


# External message delivered to the agent.
# 外部传入 agent 的消息。
@dataclass
class LivingMessage:
    content: str
    user_id: str = "global"
    session_id: str = "main"
    # "human" / "agent" / "system"
    # "human" / "agent" / "system"
    source: str = ""
    # Image paths or URLs.
    # 图片路径或 URL 列表。
    images: list[str] = field(default_factory=list)
    # Stable identity for one user input and its complete response lifecycle.
    turn_id: str = field(default_factory=lambda: str(uuid.uuid4()))


#---------------------------------------------------------------------------
#   Heartbeat results
#   心跳返回值
#---------------------------------------------------------------------------

# Normal cycle.
# 正常心跳。
HEARTBEAT_NORMAL = "normal"
# Trigger DREAMING transition.
# 触发 DREAMING 状态切换。
HEARTBEAT_DREAM = "dream"

# Sentinel sent by stop() to wake inner state loops.
# stop() 发出的停止信号，唤醒内层状态循环。
_STOP_SENTINEL = object()


#---------------------------------------------------------------------------
#   Periodic Task
#   周期任务
#---------------------------------------------------------------------------


# Registered periodic task.
# 注册式周期任务。
@dataclass
class PeriodicTask:
    name: str
    interval: float
    handler: Callable[[LivingState], Any]
    last_fired: float = 0.0


#---------------------------------------------------------------------------
#   Living
#   生命基类
#---------------------------------------------------------------------------


class Living:
    """Pure lifecycle management.

    Provides: state machine, message queue, main loop, 6 state loops,
    registered periodic tasks.
    Does NOT contain: consciousness, Drive, Purpose, Intent, chat.

    Hook methods (subclass override):
        - _handle_message(msg) -> None
        - _on_wake()
        - _on_wake_up()
        - _on_stop()
        - _on_transition(old, new)
        - _heartbeat_result -> str

    Periodic task registration:
        - register_periodic(name, interval, handler)

    纯生命周期管理。

    提供：状态机、消息队列、主循环、6 个状态循环、注册式周期任务。
    不包含：consciousness、Drive、Purpose、Intent、chat。

    Hook 方法（子类覆盖）:
        - _handle_message(msg) -> None
        - _on_wake()
        - _on_wake_up()
        - _on_stop()
        - _on_transition(old, new)
        - _heartbeat_result -> str

    周期任务注册:
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

        # Message queue.
        # 消息队列。
        self._queue: queue.Queue[LivingMessage | None] = queue.Queue()
        self._last_active: float = 0
        self._running: bool = False
        self._cancel_requested: bool = False
        self._chatting = False
        self._clarify_listening = threading.Event()  # 主线程需要监听 clarify 请求
        self._command_done = threading.Event()

        # Interoception signals.
        # 内感受信号。
        self._interoception_signals: Any = None
        self._sos_message: str | None = None
        self._sos_message_time: float = 0.0
        # Suspension reason, empty = running (e.g. LLM 402).
        # 暂停原因（如 LLM 402），空表示正常运行。
        self._suspended_reason: str = ""

        # Periodic tasks.
        # 周期任务。
        self._periodic_tasks: list[PeriodicTask] = []
        self._heartbeat_result: str = HEARTBEAT_NORMAL

        # Callbacks.
        # 回调。
        self.on_proactive: Callable[[Any], Any] | None = None
        self.on_chat_chunk: Callable[[str], Any] | None = None
        self.on_chat_flush: Callable[[], Any] | None = None  # 段落 buffer flush
        self.on_confirm_required: Callable[[dict], Any] | None = None

        # CLI prompt flag.
        # CLI 提示符开关。
        self._show_prompt: bool = True

    #---------------------------------------------------------------------------
    #   Periodic task registration
    #   周期任务注册
    #---------------------------------------------------------------------------

    def register_periodic(
        self, name: str, interval: float, handler: Callable[[LivingState], Any],
    ) -> None:
        """Register a periodic task.

        Tasks with the same name replace previous registrations.

        注册周期任务。

        同名任务会替换之前注册的任务。
        """
        self._periodic_tasks = [t for t in self._periodic_tasks if t.name != name]
        self._periodic_tasks.append(PeriodicTask(name=name, interval=interval, handler=handler))
        logger.info("[Living] 注册周期任务: %s (间隔%.1fs)", name, interval)

    def _tick_periodic(self, state: LivingState) -> None:
        """Fire due periodic tasks.

        Called in every state loop. FatalLLMError propagates to main loop.

        触发到期的周期任务。

        在每个状态循环中调用。FatalLLMError 穿透到主循环。
        """
        now = time.time()
        for task in self._periodic_tasks:
            if now - task.last_fired >= task.interval:
                try:
                    task.handler(state)
                    task.last_fired = now
                except FatalLLMError:
                    # Fatal (401/402/403) -> propagate to main loop.
                    # 致命错误（401/402/403）-> 穿透到主循环。
                    raise
                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    logger.warning("[Living] 周期任务 %s 出错: %s", task.name, e)

    #---------------------------------------------------------------------------
    #   Public API
    #   公开接口
    #---------------------------------------------------------------------------

    def put_message(
        self,
        content: str,
        user_id: str | None = None,
        session_id: str | None = None,
        source: str = "",
        images: list[str] | None = None,
        urgent: bool = False,
        display_name: str | None = None,
        turn_id: str | None = None,
    ) -> LivingMessage:
        """Enqueue a message.

        Sanitization, throttle, and busy checks are handled by
        Gateway.accept() which calls this method after preprocessing.

        将消息放入队列。清洗、限流、busy 检查由 Gateway.accept() 处理。
        """
        msg = LivingMessage(
            content=content,
            user_id=user_id or self.user_id,
            session_id=session_id or self.session_id,
            source=source,
            images=images or [],
            turn_id=turn_id or str(uuid.uuid4()),
        )
        if display_name:
            msg.user_display_name = display_name
        self._queue.put_nowait(msg)
        return msg

    @staticmethod
    def _clean_input(text: str) -> str:
        from xiaomei_brain.agent.message_utils import clean_input
        return clean_input(text)

    def run(self) -> None:
        """Main loop -- blocking.

        DORMANT -> WAKING -> AWAKE -> (state loops) -> DORMANT -> ...
        FatalLLMError 402 (insufficient balance) triggers DORMANT with periodic
        recovery. FatalLLMError 401/403 terminates the program.

        主循环，阻塞运行。

        DORMANT -> WAKING -> AWAKE -> (状态循环) -> DORMANT -> ...
        FatalLLMError 402（欠费）触发 DORMANT 并定期恢复。
        FatalLLMError 401/403 终止程序。
        """
        from ..cli.boot import boot_section, boot_line, boot_sep

        boot_section("生命循环")
        boot_line("状态转换", "....", f"{self.state.value} → waking")
        self._running = True

        self._transition(LivingState.WAKING)

        try:
            boot_line("状态转换", "....", "waking → awake")
            self._transition(LivingState.AWAKE)
            boot_line("状态转换", "OK", f"{self.state.value}")
            boot_sep("Agent 已启动生命循环")

            # 启动展示完成后再做运行时初始化（_on_wake 会触发 dispatcher tick，
            # 其中规则通知等输出不应插入 boot 行之间）
            self._on_wake()

            while self._running:
                try:
                    if self.state == LivingState.AWAKE:
                        self._loop_awake()
                    elif self.state == LivingState.IDLE:
                        self._loop_idle()
                    elif self.state == LivingState.SLEEPING:
                        self._loop_sleeping()
                    elif self.state == LivingState.DREAMING:
                        self._loop_dreaming()
                    elif self.state == LivingState.WORKING:
                        self._loop_idle()   # fallback: WORKING 应只由 _run_idle 内管理
                    elif self.state == LivingState.DORMANT:
                        self._loop_dormant()
                    else:
                        print(f"\n[异常] 生命状态异常: {self.state}", flush=True)
                        logger.warning("[Living] Unexpected state: %s", self.state)
                        time.sleep(1)
                except FatalLLMError as e:
                    if e.status_code == 402:
                        # Insufficient balance -> suspend, periodic recovery.
                        # 欠费 -> 暂停，定期探活。
                        print("\n[欠费] LLM API 余额不足，暂停服务。充值后自动恢复。", flush=True)
                        logger.warning("[Living] LLM 欠费，暂停（进入 DORMANT）")
                        self._suspended_reason = f"LLM API 欠费 (HTTP 402)"
                        self._transition(LivingState.DORMANT)
                        continue
                    # 401/403 -> propagate to outer, terminate program.
                    # 401/403 -> 穿透到外层，终止程序。
                    raise
        except FatalLLMError as e:
            ts = time.strftime("%H:%M:%S")
            print(f"\n\033[91m[FATAL] {ts} LLM API 致命错误，程序终止\033[0m", flush=True)
            print(f"\033[91m[FATAL] HTTP {e.status_code}: {e}\033[0m", flush=True)
            logger.error("[Living] 致命错误，程序终止: HTTP %d %s", e.status_code, e)
            self.stop()
        finally:
            # Clean up when thread exits (normal stop or exception).
            # 线程退出时清理（正常停止或异常）。
            self._on_stop()

    def stop(self) -> None:
        # Stop the main loop — just signal, no I/O.
        # _on_stop() runs in run()'s finally block when the thread exits.
        # 停止主循环 — 只发信号，不做 I/O。
        # _on_stop() 在线程退出的 finally 块中执行。
        self._running = False
        self._queue.put_nowait(_STOP_SENTINEL)

    #---------------------------------------------------------------------------
    #   SOS emergency push
    #   SOS 紧急推送
    #---------------------------------------------------------------------------

    def set_sos_message(self, message: str) -> None:
        # Set SOS message (called by _heartbeat).
        # 设置 SOS 消息（由 _heartbeat 调用）。
        self._sos_message = message
        self._sos_message_time = time.time()

    def get_and_clear_sos(self) -> str | None:
        # Read and clear the SOS message.
        # 读取并清空 SOS 消息。
        msg = self._sos_message
        self._sos_message = None
        return msg

    def send_sos_to_channels(self, message: str, channels: list | None = None) -> None:
        """Send SOS directly to channels -- bypasses LLM, bypasses anti-spam.

        Subclass (ConsciousLiving) overrides to access actual channel list.
        Base class default: stdout.

        直接通过 channel 发送 SOS 消息 -- 绕过 LLM，绕过 anti-spam。

        子类（ConsciousLiving）覆盖此方法以访问实际的 channel 列表。
        基类默认：stdout。
        """
        ts = time.strftime("%H:%M:%S")
        print(f"\n\033[91m[SOS] {ts} {message}\033[0m", flush=True)

    def cancel(self) -> None:
        # Request cancellation of current action.
        # Also clear _chatting so Gateway accepts new messages immediately.
        # 请求取消当前动作，同时清除 _chatting 允许立即接收新消息。
        self._cancel_requested = True
        self._chatting = False

    def abort_chat(self) -> None:
        """Abort current LLM generation.

        Used by Gateway chat.abort RPC.

        中断当前 LLM 生成。

        由 Gateway chat.abort RPC 调用。
        """
        self.cancel()

    def reset_cancel(self) -> None:
        # Reset cancellation flag.
        # 重置取消标志。
        self._cancel_requested = False

    #---------------------------------------------------------------------------
    #   Properties
    #   属性
    #---------------------------------------------------------------------------

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def living_state(self) -> str:
        return self.state.value

    #---------------------------------------------------------------------------
    #   State transitions
    #   状态转换
    #---------------------------------------------------------------------------

    def _transition(self, new_state: LivingState) -> None:
        old = self.state
        self.state = new_state
        if old != new_state:
            logger.info("[Living] 状态转换: %s -> %s", old.value, new_state.value)
        self._on_transition(old, new_state)

    #---------------------------------------------------------------------------
    #   Prompt
    #   提示符
    #---------------------------------------------------------------------------

    def _print_prompt(self) -> None:
        """Print input prompt.

        Pure ASCII to avoid WSL readline CJK width bugs.

        print 输入提示符。

        纯 ASCII，避免 WSL readline 中文宽度计算错误。
        """
        if self._show_prompt:
            print("\n> ", end="", flush=True)

    #---------------------------------------------------------------------------
    #   Message wait
    #   消息等待
    #---------------------------------------------------------------------------

    def _wait_message(self, timeout: float) -> LivingMessage | None:
        # Wait for a message with timeout.
        # 等待消息，超时返回 None。
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    #---------------------------------------------------------------------------
    #   Loop: AWAKE
    #   活跃循环
    #---------------------------------------------------------------------------

    def _loop_awake(self) -> None:
        # AWAKE loop -- process messages, transition to IDLE/SLEEPING on idle.
        # 活跃循环 -- 处理消息，空闲时进入 IDLE 或 SLEEPING。
        self._heartbeat_result = HEARTBEAT_NORMAL
        self._tick_periodic(self.state)

        msg = self._wait_message(timeout=self.tick_interval)
        if msg is _STOP_SENTINEL:
            return
        if msg is not None:
            logger.debug("[Living/AWAKE] 收到消息")
            self._handle_message(msg)
            self._last_active = time.time()
            return

        idle_time = time.time() - self._last_active
        if idle_time >= self.idle_threshold:
            logger.info("[Living/AWAKE] 空闲 %.1f秒 >= %.1f，进入 SLEEPING",
                        idle_time, self.idle_threshold)
            self._transition(LivingState.SLEEPING)
        elif idle_time >= self.idle_short:
            logger.info("[Living/AWAKE] 空闲 %.1f秒 >= %.1f，进入 IDLE",
                        idle_time, self.idle_short)
            self._transition(LivingState.IDLE)

    #---------------------------------------------------------------------------
    #   Loop: IDLE
    #   空闲循环
    #---------------------------------------------------------------------------

    def _loop_idle(self) -> None:
        # IDLE loop -- light idle, wake on message.
        # 空闲循环 -- 轻度空闲，收到消息立即唤醒。
        while True:
            self._heartbeat_result = HEARTBEAT_NORMAL
            self._tick_periodic(self.state)

            msg = self._wait_message(timeout=self.tick_interval)
            if msg is _STOP_SENTINEL:
                return
            if msg is not None:
                logger.info("[Living/IDLE] 收到消息，唤醒回 AWAKE")
                self._on_wake_up()
                self._transition(LivingState.AWAKE)
                self._handle_message(msg)
                self._last_active = time.time()
                return

            idle_time = time.time() - self._last_active
            if idle_time >= self.idle_threshold:
                logger.info("[Living/IDLE] 空闲 %.1f秒 >= %.1f，进入 SLEEPING",
                            idle_time, self.idle_threshold)
                self._transition(LivingState.SLEEPING)
                return

    #---------------------------------------------------------------------------
    #   Loop: SLEEPING
    #   睡眠循环
    #---------------------------------------------------------------------------

    def _loop_sleeping(self) -> None:
        # SLEEPING loop -- deep idle, may trigger DREAMING.
        # 睡眠循环 -- 深度空闲，可能触发 DREAMING。
        dream_start = time.time()

        while True:
            self._heartbeat_result = HEARTBEAT_NORMAL
            self._tick_periodic(self.state)

            if self._heartbeat_result == HEARTBEAT_DREAM:
                logger.info("[Living/SLEEPING] 触发 DREAMING")
                self._transition(LivingState.DREAMING)
                return

            msg = self._wait_message(timeout=self.tick_interval)
            if msg is _STOP_SENTINEL:
                return
            if msg is not None:
                logger.info("[Living/SLEEPING] 收到消息，唤醒回 AWAKE")
                self._on_wake_up()
                self._transition(LivingState.AWAKE)
                self._handle_message(msg)
                self._last_active = time.time()
                return

    #---------------------------------------------------------------------------
    #   Loop: DORMANT
    #   休眠循环
    #---------------------------------------------------------------------------

    def _loop_dormant(self) -> None:
        """DORMANT loop -- suspended, waiting for message or recovery.

        Message received -> revive, transition to AWAKE.
        Suspended recovery -> subclass override _try_recover().

        休眠循环 -- 暂停中，等待消息或恢复。

        收到消息 -> 复活，transition to AWAKE。
        暂停恢复 -> 子类覆盖 _try_recover() 实现。
        """
        msg = self._wait_message(timeout=self.tick_interval)
        if msg is _STOP_SENTINEL:
            return
        if msg is not None:
            logger.info("[Living/DORMANT] 收到消息，复活 -> AWAKE")
            self._on_wake_up()
            self._transition(LivingState.AWAKE)
            self._handle_message(msg)
            self._last_active = time.time()
            return

        # Recovery check: e.g. LLM 402 -> periodic health probe.
        # 暂停恢复检查：LLM 402 欠费 -> 定期探活。
        if self._suspended_reason:
            self._try_recover()

    def _try_recover(self) -> None:
        """Subclass override: attempt to recover from suspension.

        Default no-op. e.g. ConsciousLiving probes LLM health every 5 minutes.

        子类覆盖：尝试从暂停中恢复。

        默认无操作。例如 ConsciousLiving 每 5 分钟探活 LLM。
        """

    #---------------------------------------------------------------------------
    #   Loop: DREAMING
    #   梦境循环
    #---------------------------------------------------------------------------

    def _loop_dreaming(self) -> None:
        # DREAMING loop -- LLM-driven reflection / consolidation.
        # 梦境循环 -- LLM 驱动的反思与整合。
        logger.info("[Living/DREAMING] 开始梦境循环")

        if self._should_skip_dreaming():
            self._transition(LivingState.SLEEPING)
            return

        dream_start = time.time()
        l3_fired = False

        while True:
            self._heartbeat_result = HEARTBEAT_NORMAL
            self._tick_periodic(self.state)

            if self._heartbeat_result == HEARTBEAT_DREAM and not l3_fired:
                l3_fired = True
                continue

            if l3_fired:
                logger.info("[Living/DREAMING] 已完成，切回 SLEEPING")
                self._transition(LivingState.SLEEPING)
                return

            msg = self._wait_message(timeout=self.dream_interval)
            if msg is _STOP_SENTINEL:
                return
            if msg is not None:
                logger.info("[Living/DREAMING] 收到消息，唤醒回 AWAKE")
                self._on_wake_up()
                self._transition(LivingState.AWAKE)
                self._handle_message(msg)
                self._last_active = time.time()
                return

            elapsed = time.time() - dream_start
            if elapsed >= self.dream_interval * 2:
                print(f"\n[超时] 梦境处理超时({elapsed:.0f}秒)，强制切回睡眠", flush=True)
                logger.warning("[Living/DREAMING] 超时(%.1f秒)，强制切回 SLEEPING", elapsed)
                self._transition(LivingState.SLEEPING)
                return

    #---------------------------------------------------------------------------
    #   Hooks (no-op in base)
    #   钩子（基类空实现）
    #---------------------------------------------------------------------------

    def _should_skip_dreaming(self) -> bool:
        return False

    def _handle_message(self, msg: LivingMessage) -> None:
        # Handle received message. Subclass MUST override.
        # 处理收到的消息。子类必须覆盖。
        raise NotImplementedError

    def _on_wake(self) -> None:
        # Called once on DORMANT -> WAKING transition.
        # DORMANT -> WAKING 时调用一次。
        pass

    def _on_wake_up(self) -> None:
        # Called when waking from SLEEPING/IDLE back to AWAKE.
        # 从 SLEEPING/IDLE 唤醒回 AWAKE 时调用。
        pass

    def _on_stop(self) -> None:
        # Called on stop (save state, shutdown channels, etc.).
        # 停止时调用（保存状态、关闭 channel 等）。
        pass

    def _on_transition(self, old: LivingState, new_state: LivingState) -> None:
        # Called after every state transition.
        # 每次状态转换后调用。
        pass
