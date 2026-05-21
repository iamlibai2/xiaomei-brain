"""Interoception: 内感受——采集身体指标、阈值判断、产出信号。

集中式设计：所有数据采集和阈值判断集中在此，各组件只读信号执行。
不做执行——限流/退避/SOS 由各组件按各自职责完成。

数据流：
    Layer0._run() → interoception.tick(queue_depth) → InteroceptionSignals
        ├─ signals.as_body_dict() → SelfBody（LLM 感知）
        ├─ signals.stress_level → Drive.on_system_stress()（情绪染色）
        ├─ signals.throttle → Living.put_message()（限流）
        ├─ signals.backoff_seconds → LLMClient（退避）
        └─ signals.sos → Living._heartbeat() → 渠道推送（SOS 告警）
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ── 常量 ──────────────────────────────────────────────────────

DEFAULT_MAX_QUEUE_SIZE = 100
SOS_COOLDOWN_SECONDS = 300          # 同一类型 SOS 5 分钟内只发一次
SOS_REMINDER_SECONDS = 1800         # 30 分钟未恢复，追加提醒
THROTTLE_QUEUE_PRESSURE = 0.8       # 队列压力 > 0.8 时限流
BACKOFF_CONSECUTIVE_FAILURES = 3    # 连续失败 >= 3 次退避
PROVIDER_SWITCH_CONSECUTIVE_FAILURES = 5  # 连续失败 >= 5 次切换 provider
SOS_LLM_CASCADE_THRESHOLD = 10      # 连续失败 >= 10 次触发 SOS
LLM_ERROR_WINDOW_SECONDS = 300      # LLM 错误统计窗口（5 分钟）


# ── 信号数据类 ───────────────────────────────────────────────

@dataclass
class InteroceptionSignals:
    """产出信号——各组件读取并执行。"""

    # 自愈信号
    throttle: bool = False               # 限流
    backoff_seconds: float = 0.0         # LLM 退避延迟（秒），0 = 不触发
    provider_switch: bool = False        # 切换 LLM provider

    # 告警信号
    sos: bool = False                    # SOS 紧急告警
    sos_reason: str = ""                 # SOS 原因
    sos_message: str = ""                # SOS 文案

    # 压力等级（给 Drive）
    stress_level: str = "none"           # none / mild / moderate / severe

    # 身体数据快照（给 SelfBody 写入）
    thread_health: dict[str, bool] = field(default_factory=dict)
    queue_pressure: float = 0.0
    llm_latency_ms: float = 0.0
    llm_error_rate: float = 0.0
    llm_consecutive_failures: int = 0
    token_usage: float = 0.0
    memory_fullness: str = "清爽"
    burning_duration: float = 0.0

    def as_body_dict(self) -> dict[str, Any]:
        """转为 SelfBody 可直接写入的数据字典。"""
        return {
            "thread_health": self.thread_health,
            "queue_pressure": self.queue_pressure,
            "llm_latency_ms": self.llm_latency_ms,
            "llm_error_rate": self.llm_error_rate,
            "token_usage": self.token_usage,
            "memory_fullness": self.memory_fullness,
            "burning_duration": self.burning_duration,
        }


# ── Interoception ────────────────────────────────────────────

class Interoception:
    """内感受：集中采集+判断+设信号。不执行。"""

    def __init__(
        self,
        max_queue_size: int = DEFAULT_MAX_QUEUE_SIZE,
        burn_start_time: float | None = None,
    ) -> None:
        self._max_queue_size = max_queue_size
        self._burn_start_time = burn_start_time or time.time()

        # LLM 错误追踪（滑动窗口）
        self._llm_error_window: list[tuple[float, bool]] = []  # [(timestamp, is_error)]
        self._llm_error_window_seconds = LLM_ERROR_WINDOW_SECONDS

        # SOS 冷却追踪
        self._sos_last_sent: dict[str, float] = {}       # reason → last sent time
        self._sos_reminder_sent: dict[str, bool] = {}    # reason → whether 30min reminder sent
        self._sos_recovered: set[str] = set()             # already-recovered reasons

        # 外部引用
        self._llm_callback: Any = None
        self._threads: dict[str, threading.Thread] = {}

    # ── 外部接口 ──────────────────────────────────────────────

    def set_llm_callback(self, callback: Any) -> None:
        """设置 LLM 客户端引用，预留扩展。"""
        self._llm_callback = callback

    def set_threads(self, threads: dict[str, threading.Thread]) -> None:
        """设置需监控的线程引用（线程 start 之后调用）。"""
        self._threads = threads

    def set_burn_start_time(self, t: float) -> None:
        self._burn_start_time = t

    def record_llm_call(self, latency_ms: float, is_error: bool) -> None:
        """记录一次 LLM 调用结果（供 LLMClient 调用）。"""
        now = time.time()
        self._llm_error_window.append((now, is_error))

        # 清理过期窗口
        cutoff = now - self._llm_error_window_seconds
        self._llm_error_window = [
            (ts, err) for ts, err in self._llm_error_window if ts > cutoff
        ]

    # ── 主 tick ───────────────────────────────────────────────

    def tick(self, queue_depth: int) -> InteroceptionSignals:
        """执行一次采集+判断，返回信号。

        Args:
            queue_depth: 当前 Living 消息队列深度。
        """
        signals = InteroceptionSignals()

        # 1. 采集
        self._collect_thread_health(signals)
        self._collect_queue(signals, queue_depth)
        self._collect_llm(signals)
        self._collect_burning(signals)
        self._collect_memory(signals)

        # 2. 自愈判断
        self._evaluate_self_heal(signals)

        # 3. SOS 判断
        self._evaluate_sos(signals)

        # 4. 压力等级
        self._evaluate_stress(signals)

        return signals

    # ── 采集 ──────────────────────────────────────────────────

    def _collect_thread_health(self, signals: InteroceptionSignals) -> None:
        health: dict[str, bool] = {}
        for name, thread in self._threads.items():
            health[name] = thread.is_alive()
        signals.thread_health = health

    def _collect_queue(self, signals: InteroceptionSignals, depth: int) -> None:
        signals.queue_pressure = min(
            1.0, depth / self._max_queue_size
        ) if self._max_queue_size > 0 else 0.0

    def _collect_llm(self, signals: InteroceptionSignals) -> None:
        if not self._llm_error_window:
            signals.llm_latency_ms = 0.0
            signals.llm_error_rate = 0.0
            signals.llm_consecutive_failures = 0
            return

        total = len(self._llm_error_window)
        errors = sum(1 for _, is_err in self._llm_error_window if is_err)
        signals.llm_error_rate = errors / total if total > 0 else 0.0

        # 最近一次延迟
        signals.llm_latency_ms = self._llm_error_window[-1][0] if self._llm_error_window else 0.0

        # 连续失败计数（从最近往前数）
        consecutive = 0
        for _, is_err in reversed(self._llm_error_window):
            if is_err:
                consecutive += 1
            else:
                break
        signals.llm_consecutive_failures = consecutive

    def _collect_burning(self, signals: InteroceptionSignals) -> None:
        signals.burning_duration = (time.time() - self._burn_start_time) / 3600.0

    def _collect_memory(self, signals: InteroceptionSignals) -> None:
        """评估记忆饱和度——当前基于 token_usage 和队列压力作为代理。"""
        if signals.token_usage > 0.9 or signals.queue_pressure > 0.85:
            signals.memory_fullness = "脑子要溢出了"
        elif signals.token_usage > 0.7 or signals.queue_pressure > 0.6:
            signals.memory_fullness = "有点满"
        elif signals.token_usage > 0.4:
            signals.memory_fullness = "正常"
        else:
            signals.memory_fullness = "清爽"

    # ── 自愈判断 ──────────────────────────────────────────────

    def _evaluate_self_heal(self, signals: InteroceptionSignals) -> None:
        # 限流
        if signals.queue_pressure > THROTTLE_QUEUE_PRESSURE:
            signals.throttle = True
            logger.warning(
                "[Interoception] 限流触发: queue_pressure=%.2f", signals.queue_pressure,
            )

        # LLM 退避
        if signals.llm_consecutive_failures >= BACKOFF_CONSECUTIVE_FAILURES:
            signals.backoff_seconds = min(30.0, 2 ** signals.llm_consecutive_failures)
            logger.warning(
                "[Interoception] 退避触发: consecutive_failures=%d, delay=%.1fs",
                signals.llm_consecutive_failures, signals.backoff_seconds,
            )

        # Provider 切换
        if signals.llm_consecutive_failures >= PROVIDER_SWITCH_CONSECUTIVE_FAILURES:
            signals.provider_switch = True
            logger.warning(
                "[Interoception] Provider 切换触发: consecutive_failures=%d",
                signals.llm_consecutive_failures,
            )

    # ── SOS 判断 ──────────────────────────────────────────────

    def _evaluate_sos(self, signals: InteroceptionSignals) -> None:
        now = time.time()

        # 检查线程死亡
        dead_threads = [name for name, alive in signals.thread_health.items() if not alive]
        if dead_threads:
            reason = f"thread_died_{'_'.join(sorted(dead_threads))}"
            if self._can_send_sos(reason, now):
                names_str = "、".join(dead_threads)
                signals.sos = True
                signals.sos_reason = reason
                signals.sos_message = f"我的心跳停了——{names_str} 线程已退出。"

        # LLM 级联失败
        if signals.llm_consecutive_failures >= SOS_LLM_CASCADE_THRESHOLD:
            reason = "llm_cascade"
            if self._can_send_sos(reason, now):
                signals.sos = True
                signals.sos_reason = reason
                signals.sos_message = "我完全动不了了——LLM 调用连续失败。"

        # 30 分钟追加提醒
        for reason, sent_time in list(self._sos_last_sent.items()):
            if reason not in self._sos_reminder_sent or not self._sos_reminder_sent[reason]:
                if now - sent_time >= SOS_REMINDER_SECONDS:
                    if not self._is_recovered(reason, signals):
                        signals.sos = True
                        signals.sos_reason = f"{reason}_reminder"
                        signals.sos_message = "还没恢复，可能需要你看一下。"
                        self._sos_reminder_sent[reason] = True

    def _can_send_sos(self, reason: str, now: float) -> bool:
        """检查是否可发送 SOS（冷却检查）。"""
        # 恢复后允许重新触发
        if reason in self._sos_recovered:
            self._sos_recovered.discard(reason)

        last = self._sos_last_sent.get(reason, 0)
        if now - last < SOS_COOLDOWN_SECONDS:
            return False
        self._sos_last_sent[reason] = now
        self._sos_reminder_sent[reason] = False
        return True

    def _is_recovered(self, reason: str, signals: InteroceptionSignals) -> bool:
        """检查异常是否已恢复。"""
        if reason.startswith("thread_died"):
            return all(signals.thread_health.values())
        if reason == "llm_cascade":
            return signals.llm_consecutive_failures < SOS_LLM_CASCADE_THRESHOLD
        return False

    def mark_recovered(self, reason: str) -> None:
        """标记异常已恢复，清空冷却允许再次触发。"""
        self._sos_recovered.add(reason)
        self._sos_last_sent.pop(reason, None)
        self._sos_reminder_sent.pop(reason, None)
        logger.info("[Interoception] 异常 %s 已恢复", reason)

    # ── 压力等级 ──────────────────────────────────────────────

    def _evaluate_stress(self, signals: InteroceptionSignals) -> None:
        score = 0.0
        score += signals.queue_pressure * 0.2
        score += signals.llm_error_rate * 0.4
        score += (1.0 if not all(signals.thread_health.values()) else 0.0) * 0.4

        if score > 0.7:
            signals.stress_level = "severe"
        elif score > 0.4:
            signals.stress_level = "moderate"
        elif score > 0.15:
            signals.stress_level = "mild"
        else:
            signals.stress_level = "none"
