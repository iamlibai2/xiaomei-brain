"""声纹识别准确率测试。

加载已注册声纹 → 多轮录音 → 打印每个声纹的余弦相似度。
每轮有明确提示告诉用户何时说话。

用法：
    PYTHONPATH=src python3 tests/test_voiceprint_accuracy.py [agent_id]

参数：
    --rounds N      测试轮数（默认 5）
    --verbose, -v   显示所有声纹的详细分数
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
MAX_SPEECH_S = 30
MIN_SPEECH_S = 0.5


def _collect_speech(mic, timeout: float = 60) -> bytes | None:
    """等待并收集一段语音。返回 PCM bytes 或 None（超时/断开）。

    在收集到声音之前会一直阻塞等待。
    """
    gathering = False
    voice_buf = bytearray()
    silence_count = 0
    gather_start = 0.0
    deadline = time.time() + timeout

    while time.time() < deadline:
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
                gather_start = now
                voice_buf = bytearray()
                print("  🔊 检测到声音...", flush=True)
            voice_buf.extend(data)
            silence_count = 0
        elif gathering:
            voice_buf.extend(data)
            silence_count += 1
            silent_ms = silence_count * 250
            elapsed = now - gather_start

            if silent_ms >= SILENCE_GRACE_MS or elapsed > MAX_SPEECH_S:
                dur = len(voice_buf) / 32000
                gathering = False
                if dur >= MIN_SPEECH_S:
                    return bytes(voice_buf)
                print(f"  ⚠ 语音太短 ({dur:.1f}s)，重新等待...", flush=True)
                voice_buf = bytearray()

    return None


def main():
    parser = argparse.ArgumentParser(description="声纹识别准确率测试")
    parser.add_argument("agent_id", nargs="?", default="testbot",
                        help="Agent ID（默认: testbot）")
    parser.add_argument("--rounds", type=int, default=5,
                        help="测试轮数（默认 5）")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="显示所有声纹的详细分数")
    args = parser.parse_args()

    agent_id = args.agent_id

    # ── 加载声纹 ────────────────────────────────────────────
    contacts_dir = os.path.expanduser(f"~/.xiaomei-brain/{agent_id}/contacts")
    voices_dir = os.path.join(contacts_dir, "voices")

    if not os.path.isdir(voices_dir) or not os.listdir(voices_dir):
        print(f"\n  ❌ 未找到声纹: {voices_dir}")
        print(f"  请先注册: /register voice <identity_id>\n")
        return 1

    print("  加载声纹模型...", flush=True)
    from xiaomei_brain.body.perception import SpeakerID
    sp = SpeakerID()
    sp.load(voices_dir)
    known = sp.known_voices
    print(f"  已加载声纹 ({len(known)}): {', '.join(known)}")

    # ── 启动麦克风 ──────────────────────────────────────────
    print("  启动麦克风...", flush=True)
    from xiaomei_brain.plugins.body.ears.real_microphone import RealMicrophone
    mic = RealMicrophone()
    mic.open()
    if not mic.start_stream():
        print("  ❌ 无法启动麦克风")
        return 1

    print(f"\n  {'=' * 55}")
    print(f"  共 {args.rounds} 轮测试。")
    print(f"  每轮会提示你说话，说完停顿 1 秒即可。")
    print(f"  尽量用自然的音量、距离和语气。")
    print(f"  {'=' * 55}\n")

    results = []

    try:
        for r in range(args.rounds):
            # ── 倒计时 ─────────────────────────────────────
            for i in range(3, 0, -1):
                print(f"  \033[1;33m{i}\033[0m...", flush=True)
                time.sleep(1)
            print(f"  \033[1;32m▶ 第 {r+1}/{args.rounds} 轮 — 请说话！\033[0m", flush=True)

            pcm = _collect_speech(mic)
            if pcm is None:
                print("  ❌ 未检测到语音，跳过此轮\n")
                continue

            dur = len(pcm) / 32000
            print(f"  收声 {dur:.1f}s", flush=True)

            # ── 声纹比对 ──────────────────────────────────
            embedding = sp._extract_embedding(pcm, 16000)
            if embedding is None:
                print("  ❌ 特征提取失败\n")
                continue

            scores = []
            for name in known:
                for v in sp._voices:
                    if v["name"] == name:
                        sim = sp._cosine_sim(embedding, v["embedding"])
                        scores.append((name, sim))
                        break

            scores.sort(key=lambda x: -x[1])
            best_name, best_score = scores[0]
            matched = best_score > 0.5

            # ── 输出 ──────────────────────────────────────
            print(f"  {'─' * 45}")
            if args.verbose:
                for name, sim in scores:
                    bar = "█" * int(sim * 20) + "░" * (20 - int(sim * 20))
                    flag = " ← BEST" if name == best_name else ""
                    print(f"    {name:12s} [{bar}] {sim:.4f}{flag}")
            else:
                # 紧凑模式：只显示最佳
                for name, sim in scores:
                    bar = "█" * int(sim * 20) + "░" * (20 - int(sim * 20))
                    print(f"    {name:12s} [{bar}] {sim:.4f}")

            status = "✅ 匹配成功" if matched else "❌ 未通过"
            print(f"  {status}  best={best_name} score={best_score:.4f}")
            print()

            results.append({
                "round": r + 1,
                "dur": dur,
                "best_name": best_name,
                "best_score": best_score,
                "matched": matched,
                "all_scores": scores,
            })

    except KeyboardInterrupt:
        print("\n  用户中断\n")
    finally:
        mic.stop_stream()
        mic.close()

    # ── 汇总 ──────────────────────────────────────────────
    print(f"  {'=' * 55}")
    print(f"  测试汇总")
    print(f"  {'=' * 55}")
    if results:
        scores_list = [r["best_score"] for r in results]
        matched_count = sum(1 for r in results if r["matched"])
        print(f"  总轮数:       {len(results)}")
        print(f"  匹配成功:     {matched_count}/{len(results)} ({matched_count/len(results)*100:.0f}%)")
        print(f"  最高分:       {max(scores_list):.4f}")
        print(f"  最低分:       {min(scores_list):.4f}")
        print(f"  平均分:       {sum(scores_list)/len(scores_list):.4f}")
        print()
        print(f"  详细:")
        for r in results:
            status = "✅" if r["matched"] else "❌"
            print(f"    {r['round']}. {status} {r['best_name']} score={r['best_score']:.4f}  dur={r['dur']:.1f}s")
    else:
        print("  无有效结果")
    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
