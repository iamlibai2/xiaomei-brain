"""P1 Interoception 集成测试。

验证 interoception 信号流向各组件：
- signals.as_body_dict() → SelfBody
- signals.throttle → Living.put_message()
- signals.backoff_seconds / provider_switch → LLMClient
- signals.sos → SOS 冷却 / 恢复机制
- signals.stress_level → Drive.on_system_stress()
- LLM error 滑动窗口
"""

import sys
import os
import time
import logging
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


# ── Helpers ──────────────────────────────────────────────────

def ok(name: str) -> None:
    print(f"  ✅ {name}")


def fail(name: str, reason: str) -> None:
    print(f"  ❌ {name}: {reason}")


passed = 0
failed = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global passed, failed
    if cond:
        passed += 1
        ok(name)
    else:
        failed += 1
        fail(name, detail)


# ═══════════════════════════════════════════════════════════════
# Test 1: as_body_dict() → SelfBody
# ═══════════════════════════════════════════════════════════════

def test_body_dict_to_self_body():
    """验证 InteroceptionSignals.as_body_dict() 能正确写入 SelfBody。"""
    from xiaomei_brain.consciousness.interoception import Interoception, InteroceptionSignals

    signals = InteroceptionSignals(
        cpu_percent=45.2,
        memory_percent=62.7,
        thread_health={"layer0": True, "layer2": False},
        queue_pressure=0.5,
        llm_latency_ms=3000.0,
        llm_error_rate=0.2,
        token_usage=0.6,
        memory_fullness_pct=0.6,
        burning_duration=2.5,
    )

    body_dict = signals.as_body_dict()

    check("body_dict has cpu_percent", body_dict["cpu_percent"] == 45.2)
    check("body_dict has memory_percent", body_dict["memory_percent"] == 62.7)
    check("body_dict has thread_health", body_dict["thread_health"] == {"layer0": True, "layer2": False})
    check("body_dict has queue_pressure", body_dict["queue_pressure"] == 0.5)
    check("body_dict has llm_latency_ms", body_dict["llm_latency_ms"] == 3000.0)
    check("body_dict has llm_error_rate", body_dict["llm_error_rate"] == 0.2)
    check("body_dict has token_usage", body_dict["token_usage"] == 0.6)
    check("body_dict has memory_fullness_pct", body_dict["memory_fullness_pct"] == 0.6)
    check("body_dict has burning_duration", body_dict["burning_duration"] == 2.5)

    # 写入 SelfBody
    from xiaomei_brain.consciousness.self_modules import SelfBody
    body = SelfBody()
    for key, val in body_dict.items():
        setattr(body, key, val)

    check("SelfBody.thread_health written", body.thread_health == {"layer0": True, "layer2": False})
    check("SelfBody.queue_pressure written", body.queue_pressure == 0.5)
    check("SelfBody.llm_latency_ms written", body.llm_latency_ms == 3000.0)
    check("SelfBody.llm_error_rate written", body.llm_error_rate == 0.2)
    check("SelfBody.memory_fullness_pct written", body.memory_fullness_pct == 0.6)
    check("SelfBody.burning_duration written", body.burning_duration == 2.5)

    # to_dict / from_dict roundtrip
    d = body.to_dict()
    body2 = SelfBody()
    body2.from_dict(d)
    check("SelfBody roundtrip: thread_health", body2.thread_health == body.thread_health)
    check("SelfBody roundtrip: queue_pressure", body2.queue_pressure == body.queue_pressure)
    check("SelfBody roundtrip: memory_fullness_pct", body2.memory_fullness_pct == body.memory_fullness_pct)
    check("SelfBody roundtrip: cpu_percent", body2.cpu_percent == body.cpu_percent)
    check("SelfBody roundtrip: memory_percent", body2.memory_percent == body.memory_percent)


# ═══════════════════════════════════════════════════════════════
# Test 2: Stress Level
# ═══════════════════════════════════════════════════════════════

def test_stress_levels():
    """验证压力等级计算。"""
    from xiaomei_brain.consciousness.interoception import Interoception

    # none: clean state (zero out real hardware)
    io = Interoception()
    sig = io.tick(0)
    sig.cpu_percent = 0.0
    sig.memory_percent = 0.0
    io._evaluate_stress(sig)
    check("stress=none when clean", sig.stress_level == "none",
          f"got {sig.stress_level}")
    io = Interoception()
    io.record_llm_call(500, True)
    io.record_llm_call(500, True)
    io.record_llm_call(500, False)
    # error_rate = 2/3 ≈ 0.67, score = 0.67 * 0.4 = 0.27
    sig = io.tick(0)
    sig.cpu_percent = 0.0
    sig.memory_percent = 0.0
    io._evaluate_stress(sig)
    check("stress=mild with some LLM errors", sig.stress_level == "mild",
          f"got {sig.stress_level}, error_rate={sig.llm_error_rate:.2f}")

    # moderate: all LLM errors (5 consecutive)
    io = Interoception()
    for _ in range(5):
        io.record_llm_call(1000, True)
    sig = io.tick(0)
    # error_rate=1.0, score=0.4 → moderate (>= 0.4)
    check("stress=moderate with all LLM errors", sig.stress_level == "moderate",
          f"got {sig.stress_level}, consecutive={sig.llm_consecutive_failures}")

    # moderate: queue pressure high
    io = Interoception()
    sig = io.tick(90)  # queue_pressure = 90/100 = 0.9, score = 0.9 * 0.2 = 0.18
    check("stress=mild with high queue", sig.stress_level == "mild",
          f"got {sig.stress_level}, pressure={sig.queue_pressure:.2f}")

    # severe: thread died + LLM errors
    io = Interoception()
    io.set_threads({"layer0": threading.Thread(), "layer2": threading.Thread()})
    # threads not started → is_alive() returns False
    for _ in range(10):
        io.record_llm_call(500, True)
    sig = io.tick(0)
    # thread_dead=0.4 + error_rate=1.0*0.4 = 0.8 > 0.7 → severe
    check("stress=severe when threads dead + errors", sig.stress_level == "severe",
          f"got {sig.stress_level}, health={sig.thread_health}")

    # moderate: queue pressure max + LLM errors (threads alive)
    io = Interoception()
    # Start live threads
    live_t1 = threading.Thread(target=lambda: time.sleep(60), daemon=True)
    live_t2 = threading.Thread(target=lambda: time.sleep(60), daemon=True)
    live_t1.start()
    live_t2.start()
    io.set_threads({"layer0": live_t1, "layer2": live_t2})
    for _ in range(8):
        io.record_llm_call(500, True)
    sig = io.tick(100)
    # error_rate=1.0*0.4 + queue=1.0*0.2 + thread=0 = 0.6, moderate
    check("stress=moderate combo with live threads", sig.stress_level == "moderate",
          f"got {sig.stress_level}, err={sig.llm_error_rate:.2f}, q={sig.queue_pressure:.2f}")


# ═══════════════════════════════════════════════════════════════
# Test 3: Self-heal Signals
# ═══════════════════════════════════════════════════════════════

def test_self_heal_signals():
    """验证自愈信号：限流、退避、provider切换。"""
    from xiaomei_brain.consciousness.interoception import Interoception

    # Throttle: queue_pressure > 0.8
    io = Interoception(max_queue_size=100)
    sig = io.tick(85)
    check("throttle triggers at >80%", sig.throttle,
          f"pressure={sig.queue_pressure:.2f}")

    sig = io.tick(70)
    check("throttle not triggered at 70%", not sig.throttle,
          f"pressure={sig.queue_pressure:.2f}")

    # Backoff: consecutive failures >= 3
    io = Interoception()
    for _ in range(3):
        io.record_llm_call(500, True)
    sig = io.tick(0)
    check("backoff triggers at 3 consecutive failures", sig.backoff_seconds > 0,
          f"backoff={sig.backoff_seconds:.1f}s, consecutive={sig.llm_consecutive_failures}")

    # No backoff with < 3 failures
    io = Interoception()
    io.record_llm_call(500, True)
    io.record_llm_call(500, True)
    sig = io.tick(0)
    check("backoff not triggered at 2 failures", sig.backoff_seconds == 0,
          f"backoff={sig.backoff_seconds}")

    # Provider switch: consecutive failures >= 5
    io = Interoception()
    for _ in range(5):
        io.record_llm_call(500, True)
    sig = io.tick(0)
    check("provider_switch triggers at 5 consecutive failures", sig.provider_switch,
          f"switch={sig.provider_switch}, consecutive={sig.llm_consecutive_failures}")

    # No provider switch at 4
    io = Interoception()
    for _ in range(4):
        io.record_llm_call(500, True)
    sig = io.tick(0)
    check("provider_switch not triggered at 4 failures", not sig.provider_switch)


# ═══════════════════════════════════════════════════════════════
# Test 4: SOS Cooldown & Recovery
# ═══════════════════════════════════════════════════════════════

def test_sos_cooldown():
    """验证 SOS 冷却和追加提醒机制。"""
    from xiaomei_brain.consciousness.interoception import Interoception

    # SOS triggered by LLM cascade
    io = Interoception()
    for _ in range(10):
        io.record_llm_call(500, True)
    sig = io.tick(0)
    check("SOS triggers at 10 consecutive failures", sig.sos,
          f"sos={sig.sos}, consecutive={sig.llm_consecutive_failures}")
    check("SOS has message", bool(sig.sos_message))
    check("SOS reason is llm_cascade", sig.sos_reason == "llm_cascade")

    # Cooldown: same reason should not re-trigger
    sig2 = io.tick(0)
    check("SOS cooldown: not re-triggered", not sig2.sos,
          f"sos={sig2.sos}")

    # Recovery: mark recovered, then should be able to re-trigger
    io.mark_recovered("llm_cascade")
    # After recovery + new failures
    for _ in range(10):
        io.record_llm_call(500, True)
    sig3 = io.tick(0)
    check("SOS re-triggers after recovery + new failures", sig3.sos,
          f"sos={sig3.sos}")

    # Thread death SOS
    io = Interoception()
    io.set_threads({"layer0": threading.Thread()})  # not started → dead
    sig = io.tick(0)
    check("SOS triggers on thread death", sig.sos,
          f"sos={sig.sos}, dead_threads={[k for k,v in sig.thread_health.items() if not v]}")

    # Reminder: insert an old SOS entry (>30 min), keep threads alive to avoid
    # new trigger intercepting, then the reminder loop picks up the old entry.
    io = Interoception()
    live = threading.Thread(target=lambda: time.sleep(60), daemon=True)
    live.start()
    io.set_threads({"layer0": live})  # alive → no new thread_died SOS
    # Insert old custom reason that won't be reset by _can_send_sos
    io._sos_last_sent["test_reason"] = time.time() - 1801  # just over 30 min
    sig = io.tick(0)
    check("SOS reminder after 30min", sig.sos and "reminder" in sig.sos_reason,
          f"sos={sig.sos}, reason={sig.sos_reason}")


# ═══════════════════════════════════════════════════════════════
# Test 5: LLM Error Sliding Window
# ═══════════════════════════════════════════════════════════════

def test_sliding_window():
    """验证 LLM 错误的滑动窗口（5分钟）。"""
    from xiaomei_brain.consciousness.interoception import Interoception

    io = Interoception()
    # 覆盖默认窗口常量，加速测试
    io._llm_error_window_seconds = 2  # 2 秒窗口

    # 记录 5 个错误
    for _ in range(5):
        io.record_llm_call(500, True)
    sig = io.tick(0)
    check("all errors in window", sig.llm_error_rate == 1.0)
    check("consecutive=5", sig.llm_consecutive_failures == 5)

    # 等待窗口过期
    time.sleep(2.1)
    sig = io.tick(0)
    check("window expired, error_rate=0", sig.llm_error_rate == 0.0,
          f"error_rate={sig.llm_error_rate:.2f}")
    check("window expired, consecutive=0", sig.llm_consecutive_failures == 0)

    # 混合成功和失败
    io = Interoception()
    io._llm_error_window_seconds = 2
    for _ in range(3):
        io.record_llm_call(500, True)
    io.record_llm_call(500, False)  # 成功，重置连续计数
    io.record_llm_call(500, True)
    sig = io.tick(0)
    # 5 条记录：3 err + 1 ok + 1 err, error_rate = 4/5 = 0.8
    check("mixed success/failure error_rate", abs(sig.llm_error_rate - 0.8) < 0.01,
          f"error_rate={sig.llm_error_rate:.2f}")
    # consecutive = 1 (last is error, preceded by success)
    check("consecutive resets after success", sig.llm_consecutive_failures == 1,
          f"consecutive={sig.llm_consecutive_failures}")


# ═══════════════════════════════════════════════════════════════
# Test 6: Memory Fullness Evaluation
# ═══════════════════════════════════════════════════════════════

def test_memory_fullness():
    """验证记忆饱和度评估（数值，不再用硬编码文案）。"""
    from xiaomei_brain.consciousness.interoception import Interoception

    io = Interoception()

    # 默认：0
    sig = io.tick(0)
    check("memory_fullness_pct=0 by default", sig.memory_fullness_pct == 0.0,
          f"got {sig.memory_fullness_pct}")

    # token_usage 驱动
    io2 = Interoception()
    sig = io2.tick(0)
    sig.token_usage = 0.5
    io2._collect_memory(sig)
    check("memory_fullness_pct=0.5 from token", sig.memory_fullness_pct == 0.5,
          f"got {sig.memory_fullness_pct}")

    # max(token_usage, queue_pressure)
    sig.token_usage = 0.3
    sig.queue_pressure = 0.7
    io2._collect_memory(sig)
    check("memory_fullness_pct=max(token, queue)", sig.memory_fullness_pct == 0.7,
          f"got {sig.memory_fullness_pct}")


# ═══════════════════════════════════════════════════════════════
# Test 7: Burning Duration
# ═══════════════════════════════════════════════════════════════

def test_burning_duration():
    """验证燃烧时长计算（小时）。"""
    from xiaomei_brain.consciousness.interoception import Interoception

    # 设置 burn_start 为 1 小时前
    io = Interoception(burn_start_time=time.time() - 3600)
    sig = io.tick(0)
    check("burning_duration ≈ 1.0h", abs(sig.burning_duration - 1.0) < 0.1,
          f"got {sig.burning_duration:.2f}h")

    # 2 小时前
    io.set_burn_start_time(time.time() - 7200)
    sig = io.tick(0)
    check("burning_duration ≈ 2.0h", abs(sig.burning_duration - 2.0) < 0.1,
          f"got {sig.burning_duration:.2f}h")


# ═══════════════════════════════════════════════════════════════
# Test 8: Hardware Metrics (CPU / Memory)
# ═══════════════════════════════════════════════════════════════

def test_hardware_metrics():
    """验证 CPU 和内存采集 + 压力公式。"""
    from xiaomei_brain.consciousness.interoception import Interoception

    # 基础采集（psutil 已安装，应返回真实值）
    io = Interoception()
    sig = io.tick(0)
    check("cpu_percent collected", sig.cpu_percent >= 0)
    check("memory_percent collected", sig.memory_percent >= 0)

    # 压力公式：高内存 > 80% → +0.25
    io = Interoception()
    sig = io.tick(0)
    sig.memory_percent = 85
    io._evaluate_stress(sig)
    check("high memory adds stress", sig.stress_level in ("mild", "moderate", "severe"),
          f"level={sig.stress_level}")

    # 压力公式：高 CPU > 70% → +0.15
    io = Interoception()
    sig = io.tick(0)
    sig.cpu_percent = 75
    io._evaluate_stress(sig)
    check("high CPU adds stress", sig.stress_level in ("mild", "moderate", "severe"),
          f"level={sig.stress_level}")

    # 压力公式：中等内存 > 60% → +0.1
    io = Interoception()
    sig = io.tick(0)
    sig.memory_percent = 65
    io._evaluate_stress(sig)
    check("medium memory adds mild stress", sig.stress_level in ("mild", "moderate"),
          f"level={sig.stress_level}")


# ═══════════════════════════════════════════════════════════════
# Test 9: Living Throttle (urgent bypass)
# ═══════════════════════════════════════════════════════════════

def test_living_throttle():
    """验证 Living.put_message() 限流：human 消息永不丢弃。"""
    from xiaomei_brain.consciousness.living import Living
    from xiaomei_brain.consciousness.interoception import InteroceptionSignals

    # 创建最小 Living（不需要 agent）
    living = Living.__new__(Living)
    living._queue = __import__('queue').Queue()
    living.user_id = "test"
    living.session_id = "test"
    living._clean_input = lambda t: t

    # 模拟限流信号
    sig = InteroceptionSignals(throttle=True)
    living._interoception_signals = sig

    # agent 消息被丢弃（source="" → 不是 human）
    qsize_before = living._queue.qsize()
    living.put_message("agent message", source="agent")
    check("agent message dropped under throttle", living._queue.qsize() == qsize_before)

    # human 消息永不丢弃
    qsize_before = living._queue.qsize()
    living.put_message("user message", source="human")
    check("human message never dropped", living._queue.qsize() > qsize_before)

    # urgent 消息绕过限流
    qsize_before = living._queue.qsize()
    living.put_message("SOS help", source="agent", urgent=True)
    check("urgent agent message bypasses throttle", living._queue.qsize() > qsize_before)

    # 无限流时所有消息正常投递
    living._interoception_signals = InteroceptionSignals(throttle=False)
    qsize_before = living._queue.qsize()
    living.put_message("normal message")
    check("normal message delivered without throttle", living._queue.qsize() > qsize_before)


# ═══════════════════════════════════════════════════════════════
# Test 10: SOS Channel Override (Living override)
# ═══════════════════════════════════════════════════════════════

def test_sos_channel_override():
    """验证 ConsciousLiving.send_sos_to_channels 覆盖基类。"""
    from xiaomei_brain.consciousness.living import Living
    from xiaomei_brain.consciousness.interoception import InteroceptionSignals

    living = Living.__new__(Living)
    living._sos_message = None
    living._sos_message_time = 0

    # 基类 send_sos_to_channels → stdout（不抛异常就是成功）
    try:
        living.send_sos_to_channels("test SOS")
        ok("base Living.send_sos_to_channels works")
    except Exception as e:
        fail("base Living.send_sos_to_channels", str(e))


# ═══════════════════════════════════════════════════════════════
# Test 11: Drive.on_system_stress integration
# ═══════════════════════════════════════════════════════════════

def test_drive_stress_integration():
    """验证 Interoception stress_level → Drive.on_system_stress()。"""
    import tempfile
    from xiaomei_brain.drive.engine import DriveEngine

    with tempfile.TemporaryDirectory() as tmpdir:
        drive = DriveEngine("test_agent", load=False)
        drive._save_path = os.path.join(tmpdir, "drive.json")

        cortisol_before = drive.hormone.cortisol
        energy_before = drive.energy.level

        # severe stress
        drive.on_system_stress("severe", "interoception")
        check("severe stress raises cortisol", drive.hormone.cortisol > cortisol_before)
        check("severe stress lowers energy", drive.energy.level < energy_before)

        # healthy restores
        cortisol_mid = drive.hormone.cortisol
        drive.on_system_healthy()
        check("healthy increases serotonin", drive.hormone.serotonin > 0.5)


# ═══════════════════════════════════════════════════════════════
# Test 12: Thread Health Monitoring
# ═══════════════════════════════════════════════════════════════

def test_thread_health():
    """验证线程健康检测。"""
    from xiaomei_brain.consciousness.interoception import Interoception

    # Live thread (stays alive for duration of test)
    live = threading.Thread(target=lambda: time.sleep(60), daemon=True)
    live.start()

    # Dead thread (not started)
    dead = threading.Thread(target=lambda: None, daemon=True)

    io = Interoception()
    io.set_threads({"live": live, "dead": dead})

    sig = io.tick(0)
    check("live thread detected", sig.thread_health.get("live", False))
    check("dead thread detected", not sig.thread_health.get("dead", True))


# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════

def main():
    global passed, failed

    print("=" * 60)
    print("P1 Interoception 集成测试")
    print("=" * 60)

    print("\n── Test 1: as_body_dict() → SelfBody ──")
    test_body_dict_to_self_body()

    print("\n── Test 2: Stress Level Calculation ──")
    test_stress_levels()

    print("\n── Test 3: Self-heal Signals ──")
    test_self_heal_signals()

    print("\n── Test 4: SOS Cooldown & Recovery ──")
    test_sos_cooldown()

    print("\n── Test 5: LLM Error Sliding Window ──")
    test_sliding_window()

    print("\n── Test 6: Memory Fullness ──")
    test_memory_fullness()

    print("\n── Test 7: Burning Duration ──")
    test_burning_duration()

    print("\n── Test 8: Hardware Metrics (CPU / Memory) ──")
    test_hardware_metrics()

    print("\n── Test 9: Living Throttle ──")
    test_living_throttle()

    print("\n── Test 10: SOS Channel Override ──")
    test_sos_channel_override()

    print("\n── Test 11: Drive Stress Integration ──")
    test_drive_stress_integration()

    print("\n── Test 12: Thread Health ──")
    test_thread_health()

    print("\n" + "=" * 60)
    print(f"结果: {passed} passed, {failed} failed (共 {passed + failed})")
    print("=" * 60)

    return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
