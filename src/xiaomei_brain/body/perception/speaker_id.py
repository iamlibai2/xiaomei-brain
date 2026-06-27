"""SpeakerID — 声纹识别。

基于 speechbrain ECAPA-TDNN，本地离线，不上传。
- enroll(): 从音频注册声纹
- verify(): 验证两段音频是否同一人
- identify(): 识别说话人
"""

from __future__ import annotations

import logging
import os
import io
import wave
import tempfile
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

_MODEL_SOURCE = "speechbrain/spkrec-ecapa-voxceleb"


class SpeakerID:
    """声纹注册 + 验证 + 识别。

    Lazy loading，首次调用时下载模型（~80MB）。
    """

    _loaded: bool = False
    _recognizer: Any = None

    def __init__(self) -> None:
        self._voices: list[dict] = []  # [{"name": "李白", "embedding": np.array}, ...]

    # ── 懒加载 ────────────────────────────────────────────

    def _ensure_loaded(self) -> None:
        if SpeakerID._loaded:
            return
        from speechbrain.inference.speaker import SpeakerRecognition
        import torch
        device = "cuda:0" if torch.cuda.is_available() else "cpu"
        logger.info("加载声纹模型: %s (device=%s)...", _MODEL_SOURCE, device)
        SpeakerID._recognizer = SpeakerRecognition.from_hparams(
            source=_MODEL_SOURCE,
            savedir=os.path.expanduser("~/.cache/speechbrain/"),
            run_opts={"device": device},
        )
        SpeakerID._loaded = True
        logger.info("SpeakerID 就绪")

    # ── 公共 API ──────────────────────────────────────────

    def verify(self, pcm1: bytes, pcm2: bytes, sample_rate: int = 16000) -> tuple[bool, float]:
        """验证两段 PCM 是否同一说话人。

        返回: (是否同人, 置信度分数)
        分数 > 0.5 通常视为同人。
        """
        self._ensure_loaded()

        wav1 = self._pcm_to_wav_path(pcm1, sample_rate)
        wav2 = self._pcm_to_wav_path(pcm2, sample_rate)
        try:
            score, prediction = SpeakerID._recognizer.verify_files(wav1, wav2)
            is_same = bool(prediction.item()) if hasattr(prediction, 'item') else bool(prediction)
            return is_same, float(score.item()) if hasattr(score, 'item') else float(score)
        except Exception:
            logger.exception("声纹验证失败")
            return False, 0.0
        finally:
            os.unlink(wav1)
            os.unlink(wav2)

    def enroll(self, name: str, pcm: bytes, sample_rate: int = 16000) -> bool:
        """注册一个声纹。

        pcm: 至少 5 秒的 16kHz 16-bit mono PCM。
        返回是否成功。
        """
        embedding = self._extract_embedding(pcm, sample_rate)
        if embedding is None:
            return False

        for v in self._voices:
            if v["name"] == name:
                v["embedding"] = embedding
                logger.info("更新 %s 的声纹", name)
                return True

        self._voices.append({"name": name, "embedding": embedding})
        logger.info("已注册声纹: %s", name)
        return True

    @staticmethod
    def check_enrollment_quality(pcm: bytes, sample_rate: int = 16000,
                                  min_chunk_s: float = 2.5) -> tuple[float, str]:
        """评估注册音频的声纹质量。

        将音频拆成多段，提取每段 embedding，计算两两之间的余弦相似度。
        平均相似度越高，说明声纹越一致，注册质量越好。

        返回: (quality_score, label)
            >= 0.7 → "优秀"（嵌入很稳定）
            >= 0.5 → "一般"（勉强可用）
            < 0.5  → "较差"（建议重新注册，说话更稳定些）
        """
        chunk_bytes = int(sample_rate * 2 * min_chunk_s)
        total = len(pcm)
        if total < chunk_bytes * 2:
            return 0.0, "太短"

        # 拆成不重叠的多段
        n = total // chunk_bytes
        if n < 2:
            return 0.0, "太短"
        if n > 5:
            n = 5  # 最多取 5 段

        temp_sp = SpeakerID()
        temp_sp._ensure_loaded()
        embeddings = []
        for i in range(n):
            start = i * chunk_bytes
            end = start + chunk_bytes
            emb = temp_sp._extract_embedding(pcm[start:end], sample_rate)
            if emb is not None:
                embeddings.append(emb)

        if len(embeddings) < 2:
            return 0.0, "未能提取特征"

        # 两两相似度
        sims = []
        for i in range(len(embeddings)):
            for j in range(i + 1, len(embeddings)):
                sims.append(SpeakerID._cosine_sim(embeddings[i], embeddings[j]))

        avg = sum(sims) / len(sims)
        if avg >= 0.7:
            label = "优秀"
        elif avg >= 0.5:
            label = "一般"
        else:
            label = "较差"
        return avg, label

    def identify(self, pcm: bytes, sample_rate: int = 16000) -> str | None:
        """识别说话人。返回匹配的 name 或 None。"""
        embedding = self._extract_embedding(pcm, sample_rate)
        if embedding is None or not self._voices:
            return None

        # 余弦相似度比对
        best_score = -1.0
        best_name = None
        for v in self._voices:
            sim = self._cosine_sim(embedding, v["embedding"])
            logger.info("SpeakerID 比对 %s: score=%.4f", v["name"], sim)
            if sim > best_score:
                best_score = sim
                best_name = v["name"]

        logger.warning("SpeakerID identify: best=%s score=%.4f threshold=0.5 → %s",
                       best_name, best_score, best_name if best_score > 0.5 else "NO MATCH")
        if best_score > 0.5:
            return best_name
        return None

    @property
    def known_voices(self) -> list[str]:
        """已注册的声纹名列表。"""
        return [v["name"] for v in self._voices]

    # ── 私有 ──────────────────────────────────────────────

    def _extract_embedding(self, pcm: bytes, sample_rate: int) -> np.ndarray | None:
        """PCM → 声纹特征向量。"""
        self._ensure_loaded()
        wav_path = self._pcm_to_wav_path(pcm, sample_rate)
        try:
            embedding = SpeakerID._recognizer.encode_batch(
                SpeakerID._recognizer.load_audio(wav_path).unsqueeze(0)
            )
            return embedding.squeeze().detach().cpu().numpy()
        except Exception:
            logger.exception("声纹提取失败")
            return None
        finally:
            os.unlink(wav_path)

    @staticmethod
    def _pcm_to_wav_path(pcm: bytes, sample_rate: int) -> str:
        """16-bit mono PCM → 临时 WAV 文件路径。"""
        fd, path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        arr = np.frombuffer(pcm, dtype=np.int16)
        with wave.open(path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(arr.tobytes())
        return path

    # ── 持久化 ──────────────────────────────────────────────

    def save(self, voices_dir: str) -> None:
        """保存所有声纹到 voices_dir/*.npy。

        每副声纹一个 .npy，文件名 = name + ".npy"。
        """
        os.makedirs(voices_dir, exist_ok=True)
        for v in self._voices:
            path = os.path.join(voices_dir, f"{v['name']}.npy")
            np.save(path, v["embedding"])
        logger.info("SpeakerID 已保存 %d 副声纹到 %s", len(self._voices), voices_dir)

    def load(self, voices_dir: str) -> None:
        """从 voices_dir/*.npy 加载声纹。"""
        if not os.path.isdir(voices_dir):
            return
        for filename in sorted(os.listdir(voices_dir)):
            if not filename.endswith(".npy"):
                continue
            name = filename[:-4]
            path = os.path.join(voices_dir, filename)
            embedding = np.load(path)
            if name in self.known_voices:
                continue
            self._voices.append({"name": name, "embedding": embedding})
            logger.info("SpeakerID 加载: %s", name)

    @staticmethod
    def _cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
        a, b = np.asarray(a).flatten(), np.asarray(b).flatten()
        denom = np.linalg.norm(a) * np.linalg.norm(b)
        if denom == 0:
            return 0.0
        return float(np.dot(a, b) / denom)
