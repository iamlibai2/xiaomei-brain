"""MFCC 说话人检测测试。

对比 ZCR，MFCC 13维向量自带声道形状信息，不受距离/音量影响。
测同一人不同场景下 MFCC 向量的余弦相似度稳定性。

用法：
    PYTHONPATH=src python3 tests/test_mfcc_speaker.py
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


def _extract_mfcc(pcm: bytes, sample_rate: int = 16000) -> np.ndarray | None:
    """从 PCM 提取 MFCC 均值向量 (13维)。"""
    import librosa
    arr = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
    if len(arr) < sample_rate * 0.5:
        return None
    mfcc = librosa.feature.mfcc(y=arr, sr=sample_rate, n_mfcc=13)
    return mfcc.mean(axis=1)  # (13,)


def _cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9))


def _extract_zcr(pcm: bytes) -> float:
    arr = np.frombuffer(pcm, dtype=np.int16).astype(np.float64)
    arr -= np.mean(arr)
    return float(np.sum(np.abs(np.diff(np.sign(arr)))) / (2.0 * len(arr)))


def _extract_rms(pcm: bytes) -> float:
    arr = np.frombuffer(pcm, dtype=np.int16).astype(np.float64)
    return float(np.sqrt(np.mean(arr ** 2)))


def _collect_speech(mic) -> bytes | None:
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


def main():
    parser = argparse.ArgumentParser(description="MFCC 说话人检测测试")
    parser.add_argument("--phase", type=int, choices=[1, 2], default=0,
                        help="只跑某个 Phase（0=全部）")
    args = parser.parse_args()

    # 预热 librosa
    print("  加载 librosa...", flush=True)
    import librosa
    # 用一段空数据预热，避免首次调用延迟
    _ = librosa.feature.mfcc(y=np.zeros(16000, dtype=np.float32), sr=16000, n_mfcc=13)
    print("  OK", flush=True)

    print("  启动麦克风...", flush=True)
    from xiaomei_brain.plugins.body.ears.real_microphone import RealMicrophone
    mic = RealMicrophone()
    mic.open()
    if not mic.start_stream():
        print("  ❌ 无法启动麦克风")
        return 1

    try:
        # ══════════════════════════════════════════════════════
        # Phase 1: 同一人 MFCC 稳定性
        # ══════════════════════════════════════════════════════
        if args.phase in (0, 1):
            scenarios = [
                ("正常距离·正常音量", "以你平时说话的姿势正常说话，说「你好小美你好」"),
                ("正常距离·大声",       "身体不动，用更大的音量说「你好小美你好」"),
                ("正常距离·轻声",       "身体不动，用较轻的声音说「你好小美你好」"),
                ("贴近麦克风·正常音量", "靠近麦克风一些，正常音量说「你好小美你好」"),
            ]

            print(f"\n{'='*60}")
            print("  Phase 1 — 同一人 MFCC 稳定性")
            print(f"{'='*60}")
            print("  目标：看同一人不同场景下 MFCC 向量余弦相似度变化")
            print(f"  总共 {len(scenarios)} 个场景，每个测 3 次")
            print(f"{'='*60}")

            all_mfcc = []           # 所有 MFCC 向量
            all_results = {}        # scenario -> [(mfcc_vec, zcr, rms, dur)]

            # 先建 baseline（正常场景第一轮）
            baseline_mfcc = None

            for scenario_name, instruction in scenarios:
                print(f"\n  ── {scenario_name} ──")
                print(f"  📋 {instruction}")
                print(f"  每轮提示后说话，说完自动收声")

                mfccs = []
                for t in range(3):
                    for i in range(3, 0, -1):
                        print(f"  \033[1;33m  {i}\033[0m...", flush=True)
                        time.sleep(1)
                    print(f"  \033[1;32m  ▶ 第 {t+1}/3 次 — 请说话！\033[0m", flush=True)

                    pcm = _collect_speech(mic)
                    if pcm is None:
                        print("  ❌ 未检测到语音")
                        continue

                    mfcc_vec = _extract_mfcc(pcm)
                    zcr = _extract_zcr(pcm)
                    rms = _extract_rms(pcm)
                    dur = len(pcm) / 32000

                    if mfcc_vec is None:
                        print("  ❌ MFCC 提取失败")
                        continue

                    if baseline_mfcc is None:
                        baseline_mfcc = mfcc_vec

                    all_mfcc.append(mfcc_vec)
                    sim_to_baseline = _cosine_sim(mfcc_vec, baseline_mfcc)
                    mfccs.append((mfcc_vec, zcr, rms, dur, sim_to_baseline))

                    print(f"  ✓ MFCC_sim={sim_to_baseline:.4f}  ZCR={zcr:.4f}  RMS={rms:.1f}  dur={dur:.1f}s", flush=True)

                all_results[scenario_name] = mfccs

            # ── 汇总 ──
            print(f"\n{'='*60}")
            print(f"  Phase 1 汇总 — MFCC vs ZCR 对比")
            print(f"{'='*60}")

            # MFCC 统计：两两之间余弦相似度
            all_sims_mfcc = []
            for i in range(len(all_mfcc)):
                for j in range(i + 1, len(all_mfcc)):
                    all_sims_mfcc.append(_cosine_sim(all_mfcc[i], all_mfcc[j]))

            print(f"\n  【MFCC 向量余弦相似度】（同一人所有样本两两对比）")
            print(f"    均值:     {np.mean(all_sims_mfcc):.4f}")
            print(f"    最小值:   {np.min(all_sims_mfcc):.4f}")
            print(f"    最大值:   {np.max(all_sims_mfcc):.4f}")
            print(f"    标准差:   {np.std(all_sims_mfcc):.4f}")
            print(f"    预期:     同一人应 > 0.85")

            # ZCR 统计对比
            all_zcrs = []
            for mfccs in all_results.values():
                all_zcrs.extend([z[1] for z in mfccs])
            global_mean_zcr = np.mean(all_zcrs)
            global_min_zcr = np.min(all_zcrs)
            global_max_zcr = np.max(all_zcrs)
            max_dev_zcr = (global_max_zcr - global_min_zcr) / (global_mean_zcr + 1e-9)

            print(f"\n  【ZCR 对比】")
            print(f"    范围:     [{global_min_zcr:.4f}, {global_max_zcr:.4f}]")
            print(f"    最大偏离: {max_dev_zcr*100:.1f}%")

            print(f"\n  场景详细:")

            for scenario_name, mfccs in all_results.items():
                sims = [m[4] for m in mfccs]
                zcrs = [m[1] for m in mfccs]
                print(f"    {scenario_name}")
                print(f"      MFCC sim to baseline: mean={np.mean(sims):.4f}  "
                      f"range=[{min(sims):.4f}, {max(sims):.4f}]")
                print(f"      ZCR:                  mean={np.mean(zcrs):.4f}  "
                      f"range=[{min(zcrs):.4f}, {max(zcrs):.4f}]")

        # ══════════════════════════════════════════════════════
        # Phase 2: 不同人 MFCC 区分度
        # ══════════════════════════════════════════════════════
        if args.phase in (0, 2):
            input(f"\n  按 Enter 开始 Phase 2（请换另一位说话人）...")

            print(f"\n{'='*60}")
            print(f"  Phase 2 — 不同人 MFCC 区分度")
            print(f"{'='*60}")
            print("  两人交替说话，各 5 次")
            print(f"  说话内容统一说「你好小美你好」")
            print(f"{'='*60}")

            mfcc_a = []
            mfcc_b = []

            for round_num in range(10):
                person = "A" if round_num % 2 == 0 else "B"
                person_label = f"{person} (第{round_num//2+1}次)"

                if round_num > 0:
                    color = "1;36" if person == "A" else "1;35"
                    print(f"\n  🔄 换说话人{'B→A' if person == 'A' else 'A→B'}")
                else:
                    color = "1;36"

                for i in range(3, 0, -1):
                    print(f"  \033[1;33m  {i}\033[0m...", flush=True)
                    time.sleep(1)
                print(f"  \033[{color}m  ▶ 说话人 {person} — 请说话！\033[0m", flush=True)

                pcm = _collect_speech(mic)
                if pcm is None:
                    print("  ❌ 未检测到语音")
                    continue

                mfcc_vec = _extract_mfcc(pcm)
                zcr = _extract_zcr(pcm)
                rms = _extract_rms(pcm)
                dur = len(pcm) / 32000

                if mfcc_vec is None:
                    print("  ❌ MFCC 提取失败")
                    continue

                if person == "A":
                    mfcc_a.append(mfcc_vec)
                else:
                    mfcc_b.append(mfcc_vec)

                print(f"  ✓ 说话人{person}  ZCR={zcr:.4f}  RMS={rms:.1f}  dur={dur:.1f}s", flush=True)

            # ── 汇总 ──
            print(f"\n{'='*60}")
            print(f"  Phase 2 汇总 — 两人 MFCC 区分度")
            print(f"{'='*60}")

            if mfcc_a and mfcc_b:
                # 同人相似度：A 内部、B 内部
                sim_aa = np.mean([_cosine_sim(mfcc_a[i], mfcc_a[j])
                                 for i in range(len(mfcc_a)) for j in range(i+1, len(mfcc_a))]) if len(mfcc_a) >= 2 else 0
                sim_bb = np.mean([_cosine_sim(mfcc_b[i], mfcc_b[j])
                                 for i in range(len(mfcc_b)) for j in range(i+1, len(mfcc_b))]) if len(mfcc_b) >= 2 else 0

                # 跨人相似度：A vs B
                sim_ab = np.mean([_cosine_sim(a, b) for a in mfcc_a for b in mfcc_b])

                mean_a = np.mean(mfcc_a, axis=0)
                mean_b = np.mean(mfcc_b, axis=0)
                sim_center = _cosine_sim(mean_a, mean_b)

                print(f"\n  【MFCC 余弦相似度】")
                print(f"    A 内部 (同人):     {sim_aa:.4f}")
                print(f"    B 内部 (同人):     {sim_bb:.4f}")
                print(f"    A vs B (跨人):     {sim_ab:.4f}")
                print(f"    均值中心对比:      {sim_center:.4f}")

                ratio = (min(sim_aa, sim_bb) - sim_ab) / (1 - min(sim_aa, sim_bb) + 1e-9)
                print(f"\n    同人/跨人差距:    {(min(sim_aa, sim_bb) - sim_ab):.4f}")
                print(f"    分离度:            {ratio:.4f} (>0 则可区分)")

                if sim_aa > sim_ab + 0.05 and sim_bb > sim_ab + 0.05:
                    print(f"    ✅ MFCC 可区分两人")
                elif sim_aa > sim_ab and sim_bb > sim_ab:
                    print(f"    ⚡ 边界可区分，差距较小")
                else:
                    print(f"    ❌ MFCC 无法区分两人")
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
