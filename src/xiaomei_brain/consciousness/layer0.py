"""Layer0Autonomous: 自主层——人格维护线程。

算法驱动，不需要 LLM。独立线程，永远运行。

负责：
- L0：火焰骨架维护（每秒）
- L1：异常检测（每分钟，L0 累积计数）
- Drive 衰减：情绪/激素/欲望随时间变化
- SelfImage 快照：定期保存

跟聊什么、跟谁聊完全无关。它就是"我存在"。
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .core import Consciousness
    from ..drive import DriveEngine

logger = logging.getLogger(__name__)


class Layer0Autonomous:
    """自主层——人格维护线程。

    持有 consciousness 和 drive 引用，独立线程运行。
    Layer 1 / Layer 2 通过 RLock 安全读写共享状态。
    """

    def __init__(
        self,
        consciousness: Consciousness,
        drive: DriveEngine | None = None,
        tick_interval: float = 1.0,
        debug_file: str = "",        # 调试日志文件路径
        interoception: Any = None,   # Interoception 实例
        body: Any = None,            # Body 实例（物理感官）
    ) -> None:
        self._c = consciousness
        self._drive = drive
        self._tick_interval = tick_interval
        self._running = False
        self._thread: threading.Thread | None = None
        self._lock: threading.RLock = threading.RLock()
        self._debug_file = debug_file
        self._interoception = interoception           # 内感受
        self._body = body                             # 身体感官
        self._last_touch_check: float = 0.0           # 触觉在线检测节流
        self._touch_available: bool = False           # 触觉当前是否可用

        # TUI 日志缓冲区
        self._log_buffer: deque[str] = deque(maxlen=200)

        # 给外部读锁用
        self.lock = self._lock

    # ── Public ───────────────────────────────────────────────

    def start(self) -> None:
        """启动 Layer 0 线程。"""
        if self._running:
            logger.warning("[Layer0] 已在运行，跳过")
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="Layer0")
        self._thread.start()
        logger.info("[Layer0] 线程已启动（daemon, interval=%.1fs）", self._tick_interval)

    def stop(self) -> None:
        """停止 Layer 0 线程。"""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        logger.info("[Layer0] 线程已停止")

    # ── Internal ─────────────────────────────────────────────

    def _run(self) -> None:
        """主循环：每秒 tick_L0。

        tick_L0() 内部自动处理：
        - 火焰骨架维护（self_image.tick）
        - Drive 衰减（drive.tick）
        - 每 60 秒触发 L1 异常检测（_l0_count 计数 → tick_L1）
        - 快照保存（每 60 秒，有脏数据才写盘）
        """
        logger.info("[Layer0] 进入主循环")
        while self._running:
            with self._lock:
                try:
                    self._c.tick_L0(agent_state=None)

                    # ── 内感受：采集身体指标 + 写入 SelfBody ──
                    if self._interoception:
                        queue_depth = getattr(self._c, '_queue_depth', 0)
                        sig = self._interoception.tick(queue_depth)

                        # 写入 SelfBody（LLM 感知）
                        body_data = sig.as_body_dict()
                        si = self._c.get_self_image()
                        si.contribute_body_signals(body_data)

                        # 信号注入 consciousness（供 Living._heartbeat 读取）
                        self._c._interoception_signals = sig
                    # ── 内感受结束 ──

                    # ── 身体感官：采集各器官数据 + 写入 SelfBody ──
                    if self._body:
                        body_state = self._body.tick()
                        si.contribute_body_senses(body_state)

                        # 触觉快速通道：与 Drive 同级，直接进 SelfImage
                        # is_available() 会 spawn powershell（吃 stdin），节流到每 5s 一次
                        touch = self._body.get_sense("touch")
                        if touch:
                            _t = time.time()
                            if _t - self._last_touch_check >= 5.0:
                                self._last_touch_check = _t
                                self._touch_available = touch.is_available()
                            if self._touch_available:
                                try:
                                    touch_data = touch.feel_body(window_seconds=5.0)
                                    if touch_data and touch_data.get("active"):
                                        touch_data["_ts"] = time.time()
                                        si.body.sensory["触觉"] = touch_data
                                except Exception:
                                    pass
                    # ── 身体感官结束 ──

                    si = self._c.get_self_image()
                    ts = time.strftime("%H:%M:%S")
                    self._log(
                        f"{ts} L0 tick | energy={si.body.energy:.2f} "
                        f"mood={si.body.mood} state={si.perception.agent_state} "
                        f"queue={si.body.queue_pressure:.1f} err={si.body.llm_error_rate:.1f}"
                    )
                except Exception as e:
                    logger.warning("[Layer0] tick_L0 出错: %s", e)
                    self._log(f"{time.strftime('%H:%M:%S')} L0 ERROR: {e}")

            time.sleep(self._tick_interval)

    def _log(self, line: str) -> None:
        """写入内存缓冲区和调试文件。"""
        self._log_buffer.append(line)
        if self._debug_file:
            try:
                with open(self._debug_file, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except Exception as ex:
                logger.warning("[Layer0] 写调试日志失败: %s", ex)
