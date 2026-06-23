"""Layer2DefaultNetwork: DMN 线程（默认模式网络）。

LLM 驱动，后台运行，面向自己。
负责：
- L2：意图决策 + 内心独白（自我参照 + 走神）
- social_cognition：对话后社会感知（社会认知 + 心理理论）
- L3：LLM 沉思（清醒态，独立于梦境）
- DREAM：入梦信号（仅 SLEEPING）
- 定期记忆提取（periodic）

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
    """DMN（默认模式网络）——独立线程。

    持有 consciousness 引用，通过 RLock 安全读写共享状态。
    使用 consciousness 内建的 L2Engine / DreamEngine / SocialCognition 进行 LLM 调用。
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

    def _display_internal(self, intent=None, sc_result=None) -> None:
        """idle 路径展示 InternalDisplay（无 ConversationDriver）。"""
        from xiaomei_brain.consciousness.internal_display import InternalDisplay
        c = self._c
        display = InternalDisplay()
        if intent:
            display.record_intent(intent.type.value, intent.content or "")
        if sc_result:
            if sc_result.get("signal"):
                display.record_social_cognition(sc_result["signal"])
            if sc_result.get("events"):
                display.record_social_events(sc_result["events"])
            if sc_result.get("perception"):
                display.record_social_perception(sc_result["perception"])
        stored = getattr(c, "_last_emergence_stored", 0)
        if stored:
            display.record_emergence_stored(stored)
            c._last_emergence_stored = 0
        narr = getattr(c, "_last_emergence_narr", 0)
        doubt = getattr(c, "_last_emergence_doubt", 0)
        if narr or doubt:
            display.record_emergence_stats(narr, doubt)
            c._last_emergence_narr = 0
            c._last_emergence_doubt = 0
        if display.has_data():
            display.display()

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
                            intent = self._c.tick_L2_intent(anomaly_type)
                            self._display_internal(intent=intent)
                            self._log(f"{ts} L2 tick_L2_intent({anomaly_type}) 完成")
                        except Exception as e:
                            self._log(f"{ts} L2 tick_L2_intent({anomaly_type}) ERROR: {e}")
                            logger.warning("[Layer2] tick_L2_intent(%s) 出错: %s", anomaly_type, e)

                    # L2 意图决策（"我该做什么"——欲望驱动 + 时间兜底）
                    skip_l3 = False
                    if self._c._should_intent(agent_state):
                        ctx = "idle" if agent_state == "idle" else "periodic"
                        self._log(f"{ts} L2 意图决策触发 agent_state={agent_state} ctx={ctx}")
                        logger.info("[Layer2] L2 意图决策（agent_state=%s, ctx=%s）", agent_state, ctx)
                        self._c._last_intent_time = time.time()
                        try:
                            intent = self._c.tick_L2_intent(ctx)
                            self._display_internal(intent=intent)
                            self._log(f"{ts} L2 tick_L2_intent({ctx}) 完成")
                            # 如果 L2 决定睡眠，跳过同轮 L3（状态切换由主循环处理，DMN 线程看到的还是旧状态）
                            if intent and getattr(intent, 'type', None):
                                itype = intent.type.value if hasattr(intent.type, 'value') else str(intent.type)
                                if itype.lower() == 'sleep':
                                    skip_l3 = True
                                    self._log(f"{ts} L2 intent=SLEEP → 跳过本轮 L3")
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
                            self._display_internal()
                            self._log(f"{ts} L2 tick_L2_emergence 完成")
                        except Exception as e:
                            self._log(f"{ts} L2 tick_L2_emergence ERROR: {e}")
                            logger.warning("[Layer2] tick_L2_emergence 出错: %s", e)
                    else:
                        self._log(f"{ts} L2 跳过 [条件不满足] state={agent_state}")

                    # social_cognition: 对话后社会感知（社会认知 + 心理理论）
                    if self._c._should_social_cognition(agent_state):
                        self._log(f"{ts} social_cognition 触发 agent_state={agent_state}")
                        logger.info("[Layer2] social_cognition 触发（agent_state=%s）", agent_state)
                        try:
                            sc_result = self._c.tick_social_cognition(agent_state)
                            self._display_internal(sc_result=sc_result)
                            self._log(f"{ts} social_cognition 完成")
                        except Exception as e:
                            self._log(f"{ts} social_cognition ERROR: {e}")
                            logger.warning("[Layer2] social_cognition 出错: %s", e)

                    # L3: 沉思（sleep guard 在 _should_l3() 内，同轮 L2=SLEEP 也跳过）
                    if not skip_l3 and self._c._should_l3(agent_state):
                        self._log(f"{ts} L3 触发 [沉思] agent_state={agent_state} → tick_L3")
                        logger.info("[Layer2] L3 触发（沉思，agent_state=%s）", agent_state)
                        self._c._last_l3_time = time.time()
                        try:
                            self._c.tick_L3()
                            self._log(f"{ts} L3 tick_L3 完成")
                        except Exception as e:
                            self._log(f"{ts} L3 tick_L3 ERROR: {e}")
                            logger.warning("[Layer2] tick_L3 出错: %s", e)

                    # DREAM: 入梦信号（仅 SLEEPING，每次睡眠只触发一次）
                    if agent_state == "sleeping":
                        if not self._c._dreamed_this_sleep:
                            if self._c._sleep_start_time == 0:
                                self._c._sleep_start_time = time.time()
                            elapsed = time.time() - self._c._sleep_start_time
                            if elapsed >= self._c._cc.sleep_to_dream_threshold:
                                self._log(f"{ts} DREAM 入梦信号 已发送 sleep_elapsed={elapsed:.0f}s")
                                self._c._sleep_start_time = 0
                                self._c._dreamed_this_sleep = True
                                self._c._dream_signal = True
                    elif agent_state != "dreaming":
                        # AWAKE/IDLE/DORMANT：重置睡眠状态
                        self._c._sleep_start_time = 0
                        self._c._dreamed_this_sleep = False

                except Exception as e:
                    ts = time.strftime("%H:%M:%S")
                    self._log(f"{ts} Layer2 ERROR: {e}")
                    logger.warning("[Layer2] 主循环出错: %s", e)

                except BaseException as e:
                    # KeyboardInterrupt / SystemExit 必须穿透
                    if isinstance(e, (KeyboardInterrupt, SystemExit)):
                        raise
                    # FatalLLMError（401/402/403）等 BaseException 子类不会被
                    # except Exception 捕获。记录日志并优雅停止线程。
                    ts = time.strftime("%H:%M:%S")
                    from xiaomei_brain.llm.client import FatalLLMError
                    if isinstance(e, FatalLLMError):
                        self._log(f"{ts} Layer2 FATAL LLM: {e}")
                        logger.error("[Layer2] 致命 LLM 错误，停止 DMN 线程: %s", e)
                        # 通知主循环（interoception signal）
                        intero = getattr(self._c, '_interoception_signals', None)
                        if intero is not None:
                            intero.stress_level = "critical"
                            intero.sos = True
                            intero.sos_message = f"[Layer2] LLM 致命错误: {e}"
                    else:
                        self._log(f"{ts} Layer2 FATAL: {type(e).__name__}: {e}")
                        logger.error("[Layer2] 致命错误，停止 DMN 线程: %s", e)
                    self._running = False

            time.sleep(self._check_interval)
