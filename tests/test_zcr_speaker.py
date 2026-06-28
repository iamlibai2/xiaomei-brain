"""ZCR 说话人检测测试。

测两件事：
1. 同一人的 ZCR 稳定性 — 不同音量、距离、说话内容下 ZCR 漂移多少
2. 不同人的 ZCR 区分度 — 两个人的 ZCR 差距够不够大

用法：
    PYTHONPATH=src python3 tests/test_zcr_speaker.py

流程：
    Phase 1 — 同一人测试：系统提示你变换 4 种场景说话，每轮测 3 次
    Phase 2 — 不同人测试：两人交替说话，看 ZCR 能否区分
"""

from __future__ import annotations

import os
import sys
import time
import argparse
import logging
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s %(levelname)-5s %(message)s",
    datefmt="%H:%M:%S",
)

ENERGY_THRESHOLD = 300
CHUNK_BYTES = 8000
SILENCE_GRACE_MS = 1000
MAX_SPEECH_S = 15
MIN_SPEECH_S = 0.5


def _extract_zcr(pcm: bytes) -> float:
    arr = np.frombuffer(pcm, dtype=np.int16).astype(np.float64)
    arr -= np.mean(arr)
    zcr = np.sum(np.abs(np.diff(np.sign(arr)))) / (2.0 * len(arr))
    return float(zcr)


def _extract_rms(pcm: bytes) -> float:
    arr = np.frombuffer(pcm, dtype=np.int16).astype(np.float64)
    return float(np.sqrt(np.mean(arr ** 2)))


def _collect_speech(mic) -> bytes | None:
    """收集一段语音。"""
    gathering = False
    voice_buf = bytearray()
    silence_count = 0

    while True:
        data = mic.read_chunk(timeout=0.3)
        if data is None:
            return None
        if not data:
            continue

        arr = np.frombuffer(data, dtype=np.int16)
        peak = int(np.max(np.abs(arr)))
        now = time.time()

        if peak >= ENERGY_THRESHOLD:
            if not gathering:
                gathering = True
                voice_buf = bytearray()
                print("  🔊 检测到声音...", flush=True)
            voice_buf.extend(data)
            silence_count = 0
        elif gathering:
            voice_buf.extend(data)
            silence_count += 1
            silent_ms = silence_count * 250

            if silent_ms >= SILENCE_GRACE_MS or len(voice_buf) / 32000 > MAX_SPEECH_S:
                dur = len(voice_buf) / 32000
                gathering = False
                if dur >= MIN_SPEECH_S:
                    return bytes(voice_buf)
                print(f"  ⚠ 太短 ({dur:.1f}s)，重新等...", flush=True)
                voice_buf = bytearray()


def _print_bar(value: float, min_v: float, max_v: float, label: str) -> None:
    """打印可视化条形图。"""
    if max_v - min_v < 1e-9:
        pct = 50
    else:
        pct = (value - min_v) / (max_v - min_v) * 100
    bar_len = int(pct / 2)
    bar = "█" * bar_len + "░" * (50 - bar_len)
    print(f"  {label:25s} [{bar}] {value:.4f}", flush=True)


def main():
    parser = argparse.ArgumentParser(description="ZCR 说话人检测测试")
    parser.add_argument("--phase", type=int, choices=[1, 2], default=0,
                        help="只跑某个 Phase（0=全部）")
    args = parser.parse_args()

    print("  启动麦克风...", flush=True)
    from xiaomei_brain.plugins.body.ears.real_microphone import RealMicrophone
    mic = RealMicrophone()
    mic.open()
    if not mic.start_stream():
        print("  ❌ 无法启动麦克风")
        return 1

    try:
        # ══════════════════════════════════════════════════════
        # Phase 1: 同一人 ZCR 稳定性
        # ══════════════════════════════════════════════════════
        if args.phase in (0, 1):
            scenarios = [
                ("正常距离·正常音量", "以你平时说话的姿势正常说话，说「小美好」"),
                ("正常距离·大声",         "身体不动，用更大的音量说「小美好」"),
                ("正常距离·轻声",         "身体不动，用较轻的声音说「小美好」"),
                ("贴近麦克风·正常音量",   "靠近麦克风一些，正常音量说「小美好」"),
            ]

            print(f"\n{'='*60}")
            print("  Phase 1 — 同一人 ZCR 稳定性")
            print(f"{'='*60}")
            print("  目标：看同一人不同场景下 ZCR 变化幅度")
            print(f"  总共 {len(scenarios)} 个场景，每个测 3 次")
            print(f"{'='*60}")

            all_results = {}  # scenario_name -> [(zcr, rms, dur)]

            for scenario_name, instruction in scenarios:
                print(f"\n  ── {scenario_name} ──")
                print(f"  📋 {instruction}")
                print(f"  每轮提示后说话，说完自动收声")

                zcrs = []
                for t in range(3):
                    for i in range(3, 0, -1):
                        print(f"  \033[1;33m  {i}\033[0m...", flush=True)
                        time.sleep(1)
                    print(f"  \033[1;32m  ▶ 第 {t+1}/3 次 — 请说话！\033[0m", flush=True)

                    pcm = _collect_speech(mic)
                    if pcm is None:
                        print("  ❌ 未检测到语音")
                        continue

                    zcr = _extract_zcr(pcm)
                    rms = _extract_rms(pcm)
                    dur = len(pcm) / 32000
                    zcrs.append((zcr, rms, dur))
                    print(f"  ✓ ZCR={zcr:.4f}  RMS={rms:.1f}  dur={dur:.1f}s", flush=True)

                all_results[scenario_name] = zcrs

            # ── 汇总 ──
            print(f"\n{'='*60}")
            print(f"  Phase 1 汇总 — ZCR 分布")
            print(f"{'='*60}")

            # 收集所有 ZCR 值计算整体范围
            all_zcrs = []
            for zcrs in all_results.values():
                all_zcrs.extend([z[0] for z in zcrs])
            global_min = min(all_zcrs)
            global_max = max(all_zcrs)
            global_mean = np.mean(all_zcrs)
            global_std = np.std(all_zcrs)

            print(f"\n  场景对比:")
            for scenario_name, zcrs in all_results.items():
                vals = [z[0] for z in zcrs]
                mean_zcr = np.mean(vals)
                std_zcr = np.std(vals)
                print(f"    {scenario_name}")
                print(f"      mean={mean_zcr:.4f}  std={std_zcr:.4f}  "
                      f"range=[{min(vals):.4f}, {max(vals):.4f}]")

            print(f"\n  整体统计:")
            print(f"    全部 ZCR 均值:     {global_mean:.4f}")
            print(f"    全部 ZCR 标准差:   {global_std:.4f}")
            print(f"    全部 ZCR 范围:     [{global_min:.4f}, {global_max:.4f}]")

            # 计算最大相对偏离（同一人场景内的最大变化）
            max_dev = (global_max - global_min) / (global_mean + 1e-9)
            print(f"    最大相对偏离:      {max_dev*100:.1f}%")
            print(f"    当前阈值:          50%")
            if max_dev < 0.5:
                print(f"    ✅ 同一人 ZCR 偏离 ({max_dev*100:.1f}%) < 50%，阈值合理")
            else:
                print(f"    ⚠ 同一人 ZCR 偏离 ({max_dev*100:.1f}%) >= 50%，阈值可能太严格")

            print(f"\n  可视化 (所有采样点):")
            for val, scenario_name in [(zcr, sn) for sn, zcrs in all_results.items() for zcr, _, _ in zcrs]:
                _print_bar(val, global_min, global_max, scenario_name)

        # ══════════════════════════════════════════════════════
        # Phase 2: 不同人 ZCR 区分度
        # ══════════════════════════════════════════════════════
        if args.phase in (0, 2):
            input(f"\n  按 Enter 开始 Phase 2（请先换另一位说话人，或使用不同声调来模拟）...")

            print(f"\n{'='*60}")
            print(f"  Phase 2 — 不同人 ZCR 区分度")
            print(f"{'='*60}")
            print("  两人交替说话，各 5 次")
            print(f"  说话内容统一说「小美好」")
            print(f"{'='*60}")

            person_a_name = "A"
            person_b_name = "B"
            person_a = []
            person_b = []

            for round_num in range(10):
                person = person_a_name if round_num % 2 == 0 else person_b_name
                person_label = f"{person} (第{round_num//2+1}次)"

                if round_num % 2 == 0 and round_num > 0:
                    print(f"\n  🔄 换说话人 {person_a_name} → {person_b_name}")

                for i in range(3, 0, -1):
                    print(f"  \033[1;33m  {i}\033[0m...", flush=True)
                    time.sleep(1)

                if round_num == 0:
                    print(f"  \033[1;36m  ▶ 说话人 {person_a_name} — 请说话！\033[0m", flush=True)
                elif round_num == 1:
                    print(f"  \033[1;35m  ▶ 说话人 {person_b_name} — 请说话！\033[0m", flush=True)
                else:
                    color = "1;36" if person == person_a_name else "1;35"
                    print(f"  \033[{color}m  ▶ 说话人 {person} — 请说话！\033[0m", flush=True)

                pcm = _collect_speech(mic)
                if pcm is None:
                    print("  ❌ 未检测到语音")
                    continue

                zcr = _extract_zcr(pcm)
                rms = _extract_rms(pcm)
                dur = len(pcm) / 32000

                if round_num % 2 == 0:
                    person_a.append(zcr)
                else:
                    person_b.append(zcr)

                print(f"  ✓ 说话人{person}  ZCR={zcr:.4f}  "
                      f"RMS={rms:.1f}  dur={dur:.1f}s", flush=True)

            # ── 汇总 ──
            print(f"\n{'='*60}")
            print(f"  Phase 2 汇总 — 两人 ZCR 区分度")
            print(f"{'='*60}")

            if person_a and person_b:
                mean_a = np.mean(person_a)
                mean_b = np.mean(person_b)
                std_a = np.std(person_a)
                std_b = np.std(person_b)

                print(f"\n  说话人 A:")
                print(f"    样本:  {[f'{z:.4f}' for z in person_a]}")
                print(f"    mean:  {mean_a:.4f}")
                print(f"    std:   {std_a:.4f}")

                print(f"\n  说话人 B:")
                print(f"    样本:  {[f'{z:.4f}' for z in person_b]}")
                print(f"    mean:  {mean_b:.4f}")
                print(f"    std:   {std_b:.4f}")

                # 两人均值差距（相对小的那方）
                diff = abs(mean_a - mean_b)
                rel_diff = diff / (min(mean_a, mean_b) + 1e-9)
                print(f"\n  区分度分析:")
                print(f"    均值差:    {diff:.4f}")
                print(f"    相对差距:  {rel_diff*100:.1f}%")

                # 判断：如果相对差距 > 30%，同一阈值 50% 就能区分
                if rel_diff > 0.5:
                    print(f"    ✅ 相对差距 ({rel_diff*100:.1f}%) > 50%，ZCR 可区分两人")
                elif rel_diff > 0.3:
                    print(f"    ⚡ 相对差距 ({rel_diff*100:.1f}%) 30-50%，边界可区分")
                else:
                    print(f"    ❌ 相对差距 ({rel_diff*100:.1f}%) < 30%，ZCR 难以区分两人")

                # 可视化
                all_vals = person_a + person_b
                vmin = min(all_vals)
                vmax = max(all_vals)

                print(f"\n  可视化:")
                for z in person_a:
                    _print_bar(z, vmin, vmax, f"说话人A")
                for z in person_b:
                    _print_bar(z, vmin, vmax, f"说话人B")

            else:
                print("  数据不足")

    except KeyboardInterrupt:
        print("\n  用户中断")
    finally:
        mic.stop_stream()
        mic.close()

    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
