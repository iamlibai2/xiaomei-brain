"""Layer2DefaultNetwork: 默认网络线程。

LLM 驱动，后台运行，面向自己。
负责：
- L2：动态加柴（自我反省 → SelfImage 更新）
- L3：深度沉思（梦境燃烧）
- DREAM 入梦信号
- 定期记忆提取（periodic/dream）

不面向任何对话方，输出是"思想"而非"行动"。
思想更新 SelfImage、存入长期记忆，不直接投递给任何人。
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .core import Consciousness

logger = logging.getLogger(__name__)


class Layer2DefaultNetwork:
    """默认网络——独立线程。

    持有 consciousness 引用，通过 RLock 安全读写共享状态。
    使用 consciousness 内建的 L2Engine / DreamEngine 进行 LLM 调用。
    """

    def __init__(
        self,
        consciousness: Consciousness,
        check_interval: float = 10.0,
        debug_file: str = "",        # 调试日志文件路径
    ) -> None:
        self._c = consciousness
        self._check_interval = check_interval
        self._running = False
        self._thread: threading.Thread | None = None
        self._lock: threading.RLock = threading.RLock()
        self._debug_file = debug_file

        # TUI 日志缓冲区
        self._log_buffer: deque[str] = deque(maxlen=200)

        # 给外部读锁用
        self.lock = self._lock

    # ── Public ───────────────────────────────────────────────

    def start(self) -> None:
        """启动 Layer 2 线程。"""
        if self._running:
            logger.warning("[Layer2] 已在运行，跳过")
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="Layer2")
        self._thread.start()
        logger.info("[Layer2] 线程已启动（daemon, interval=%.1fs）", self._check_interval)

    def stop(self) -> None:
        """停止 Layer 2 线程。"""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=15)  # LLM 调用可能需要更长的等待
        logger.info("[Layer2] 线程已停止")

    # ── Internal ─────────────────────────────────────────────

    def _get_agent_state(self) -> str:
        """读取当前 agent 状态（由主循环写到 consciousness._agent_state）。"""
        return getattr(self._c, "_agent_state", "awake")

    def _log(self, line: str) -> None:
        """写入内存缓冲区和调试文件。"""
        self._log_buffer.append(line)
        if self._debug_file:
            try:
                with open(self._debug_file, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except Exception as ex:
                logger.warning("[Layer2] 写调试日志失败: %s", ex)

    def _run(self) -> None:
        """主循环：每 check_interval 秒检查一次 L2/L3/DREAM。"""
        logger.info("[Layer2] 进入主循环")
        while self._running:
            with self._lock:
                try:
                    agent_state = self._get_agent_state()
                    ts = time.strftime("%H:%M:%S")

                    # L1 异常已触发 L2（绕过冷却），优先处理
                    anomaly_type = getattr(self._c, '_l2_triggered_by_anomaly', None)
                    if anomaly_type:
                        self._c._l2_triggered_by_anomaly = None
                        self._log(f"{ts} L2 触发 [异常 bypass] agent_state={agent_state} ctx={anomaly_type}")
                        logger.info("[Layer2] L2 触发（L1 异常=%s，agent_state=%s）", anomaly_type, agent_state)
                        self._c._last_intent_time = time.time()
                        try:
                            self._c.tick_L2_intent(anomaly_type)
                            self._log(f"{ts} L2 tick_L2_intent({anomaly_type}) 完成")
                        except Exception as e:
                            self._log(f"{ts} L2 tick_L2_intent({anomaly_type}) ERROR: {e}")
                            logger.warning("[Layer2] tick_L2_intent(%s) 出错: %s", anomaly_type, e)

                    # L2 意图决策（"我该做什么"——欲望驱动 + 时间兜底）
                    if self._c._should_intent(agent_state):
                        ctx = "idle" if agent_state == "idle" else "periodic"
                        self._log(f"{ts} L2 意图决策触发 agent_state={agent_state} ctx={ctx}")
                        logger.info("[Layer2] L2 意图决策（agent_state=%s, ctx=%s）", agent_state, ctx)
                        self._c._last_intent_time = time.time()
                        try:
                            self._c.tick_L2_intent(ctx)
                            self._log(f"{ts} L2 tick_L2_intent({ctx}) 完成")
                        except Exception as e:
                            self._log(f"{ts} L2 tick_L2_intent({ctx}) ERROR: {e}")
                            logger.warning("[Layer2] tick_L2_intent(%s) 出错: %s", ctx, e)

                    # L2 意识涌现（"我此刻怎样"——内在节律 + 素材驱动）
                    if self._c._should_emerge(agent_state):
                        self._log(f"{ts} L2 意识涌现触发 agent_state={agent_state}")
                        logger.info("[Layer2] L2 意识涌现（agent_state=%s）", agent_state)
                        self._c._last_emerge_time = time.time()
                        try:
                            self._c.tick_L2_emergence(agent_state)
                            self._log(f"{ts} L2 tick_L2_emergence 完成")
                        except Exception as e:
                            self._log(f"{ts} L2 tick_L2_emergence ERROR: {e}")
                            logger.warning("[Layer2] tick_L2_emergence 出错: %s", e)
                    else:
                        self._log(f"{ts} L2 跳过 [条件不满足] state={agent_state}")

                    # L3: 深度沉思（不在 DREAMING 中，由 _loop_dreaming 处理）
                    if agent_state != "dreaming" and self._c._should_l3():
                        self._log(f"{ts} L3 触发 [深度沉思] agent_state={agent_state} → tick_L3")
                        logger.info("[Layer2] L3 触发（深度沉思，agent_state=%s）", agent_state)
                        self._c._last_l3_time = time.time()
                        try:
                            self._c.tick_L3()
                            self._log(f"{ts} L3 tick_L3 完成")
                        except Exception as e:
                            self._log(f"{ts} L3 tick_L3 ERROR: {e}")
                            logger.warning("[Layer2] tick_L3 出错: %s", e)

                    # DREAM: 入梦信号（仅 SLEEPING）
                    if agent_state == "sleeping":
                        if self._c._sleep_start_time == 0:
                            self._c._sleep_start_time = time.time()
                        elapsed = time.time() - self._c._sleep_start_time
                        if elapsed >= self._c._cc.l3_dream_interval:
                            self._log(f"{ts} DREAM 入梦信号 已发送 sleep_elapsed={elapsed:.0f}s")
                            self._c._sleep_start_time = 0
                            self._c._dream_signal = True
                    else:
                        self._c._sleep_start_time = 0

                except Exception as e:
                    ts = time.strftime("%H:%M:%S")
                    self._log(f"{ts} Layer2 ERROR: {e}")
                    logger.warning("[Layer2] 主循环出错: %s", e)

            time.sleep(self._check_interval)
