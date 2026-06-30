"""VoxCPM TTS Provider — 远程服务优先，本地回退。

设计：
- 优先连接 voxcpm_server.py 常驻服务（http://127.0.0.1:18766）
- 远程不可用时，回退到加载本地模型
- 自举式声音克隆：首次用 voice_desc 生成种子音频，后续用 prompt_wav_path 克隆
"""

from __future__ import annotations

import io
import json
import logging
import os
import urllib.request

import numpy as np

logger = logging.getLogger(__name__)

DEFAULT_VOICE_DESC = "(一位温柔的年轻女性，声音甜美、亲切，略带俏皮感)"
DEFAULT_MODEL_ID = "openbmb/VoxCPM1.5"
DEFAULT_SERVER_URL = "http://127.0.0.1:18766"
BOOTSTRAP_SEED_TEXT = "你好，这是我的声音样本，用于后续的语音克隆参考。"

# 本地路径优先
_local = os.path.expanduser("~/VoxCPM1.5")
if os.path.isdir(_local):
    DEFAULT_MODEL_ID = _local


class VoxCPMProvider:
    """VoxCPM TTS 引擎 — 远程服务优先，本地回退。"""

    def __init__(
        self,
        model_id: str | None = None,
        voice_desc: str = DEFAULT_VOICE_DESC,
        cfg_value: float = 2.0,
        inference_timesteps: int = 10,
        device: str | None = None,
        local_files_only: bool = False,
        agent_id: str = "default",
    ):
        self.model_id = model_id or DEFAULT_MODEL_ID
        self.voice_desc = voice_desc
        self.cfg_value = cfg_value
        self.inference_timesteps = inference_timesteps
        self.device = device or "cuda"
        self.local_files_only = local_files_only
        self._model = None

        # 远程服务
        self._server_url = os.environ.get(
            "VOXCPM_SERVER_URL", DEFAULT_SERVER_URL
        )
        self._remote_available: bool | None = None
        self._remote_sample_rate: int | None = None

        # 声音克隆 — 自举式
        self._voice_ref_dir = os.path.expanduser(
            f"~/.xiaomei-brain/{agent_id}/voice_reference"
        )
        self._prompt_wav_path: str | None = None
        self._prompt_text: str | None = None
        self._init_voice_ref()

    # ── 远程检测 ─────────────────────────────────────────────────

    def _check_remote(self) -> bool:
        """检测远程 VoxCPM 服务是否可用。只缓存成功，失败每次重试。"""
        if self._remote_available:
            return True

        try:
            req = urllib.request.Request(
                f"{self._server_url}/health", method="GET"
            )
            resp = urllib.request.urlopen(req, timeout=2)
            if resp.status == 200:
                data = json.loads(resp.read())
                self._remote_sample_rate = data.get("sample_rate", 44100)
                logger.info(
                    "VoxCPM remote server available at %s (sr=%s)",
                    self._server_url, self._remote_sample_rate,
                )
                self._remote_available = True
                return True
        except Exception:
            pass

        return False

    # ── 本地模型 ─────────────────────────────────────────────────

    @property
    def model(self):
        """延迟加载本地 VoxCPM 模型（仅远端不可用时调用）。"""
        if self._model is None:
            import torch

            torch.set_float32_matmul_precision("high")
            logger.info("加载 VoxCPM 模型: %s (device=%s)", self.model_id, self.device)
            try:
                from voxcpm import VoxCPM

                if os.path.isdir(self.model_id):
                    self._model = VoxCPM(
                        voxcpm_model_path=self.model_id,
                        enable_denoiser=False,
                        device=self.device,
                    )
                else:
                    self._model = VoxCPM.from_pretrained(
                        self.model_id,
                        load_denoiser=False,
                        device=self.device,
                        local_files_only=self.local_files_only,
                    )
                logger.info(
                    "VoxCPM 模型加载完成，采样率=%d",
                    self._model.tts_model.sample_rate,
                )
            except ImportError:
                raise RuntimeError("VoxCPM 未安装。请执行: pip install voxcpm")
            except Exception as e:
                raise RuntimeError(f"加载 VoxCPM 模型失败: {e}")
        return self._model

    @property
    def loaded(self) -> bool:
        return self._model is not None

    @property
    def sample_rate(self) -> int:
        """获取采样率（远端/本地自动选择）。"""
        if self._check_remote():
            return self._remote_sample_rate or 44100
        return self.model.tts_model.sample_rate

    # ── 声音克隆（自举式）─────────────────────────────────────────

    def _init_voice_ref(self) -> None:
        """检查是否已有参考音频，有则直接启用克隆模式。"""
        ref_wav = os.path.join(self._voice_ref_dir, "reference.wav")
        if os.path.exists(ref_wav):
            self._prompt_wav_path = ref_wav
            self._prompt_text = self._load_prompt_text()
            logger.info("声音参考已加载: %s", ref_wav)

    def _load_prompt_text(self) -> str | None:
        """加载 prompt_text。优先 reference.txt，否则用 voice_desc 去掉括号。"""
        txt_file = os.path.join(self._voice_ref_dir, "reference.txt")
        if os.path.exists(txt_file):
            with open(txt_file, "r") as f:
                return f.read().strip()
        # 兜底：用 voice_desc，但不保留括号（VoxCPM1.5 参考音频不含描述）
        return None

    def _ensure_voice_reference(self) -> None:
        """确保声音参考存在。首次使用时自动生成种子音频。"""
        if self._prompt_wav_path is not None and self._prompt_text is not None:
            return

        ref_wav = os.path.join(self._voice_ref_dir, "reference.wav")
        if os.path.exists(ref_wav):
            self._prompt_wav_path = ref_wav
            # 重新尝试加载 prompt_text（可能在 init 之后才放置 reference.txt）
            if not self._prompt_text:
                self._prompt_text = self._load_prompt_text()
            # 仍然没有则用种子文本兜底
            if not self._prompt_text:
                self._prompt_text = BOOTSTRAP_SEED_TEXT
            return

        logger.info("自举声音参考（首次使用 voice_desc 生成种子音频）...")
        os.makedirs(self._voice_ref_dir, exist_ok=True)
        import soundfile as sf

        if self._check_remote():
            wav, sr = self._generate_remote_bare(self._wrap_text(BOOTSTRAP_SEED_TEXT))
        else:
            model = self.model
            import warnings
            text = self._wrap_text(BOOTSTRAP_SEED_TEXT)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                wav = model.generate(
                    text=text,
                    cfg_value=self.cfg_value,
                    inference_timesteps=self.inference_timesteps,
                )
            sr = model.tts_model.sample_rate

        sf.write(ref_wav, wav, sr)
        self._prompt_wav_path = ref_wav
        self._prompt_text = BOOTSTRAP_SEED_TEXT
        logger.info("声音参考自举完成: %s (%.1fs)", ref_wav, len(wav) / sr)

    @property
    def _use_cloning(self) -> bool:
        return self._prompt_wav_path is not None

    # ── 生成 ─────────────────────────────────────────────────────

    def _wrap_text(self, text: str) -> str:
        """包裹 voice_desc 前缀（仅在无克隆参考时使用）。"""
        text = text.strip()
        if text.startswith("("):
            return text
        return f"{self.voice_desc}{text}"

    def generate(self, text: str) -> tuple[np.ndarray, int]:
        """生成语音，返回 (wav_float32_1d, sample_rate)。

        首次调用自动自举声音参考，后续用 prompt_wav_path 克隆确保声音一致。
        """
        self._ensure_voice_reference()

        if self._check_remote():
            return self._generate_remote(text)

        if self._use_cloning:
            logger.info("VoxCPM generate (clone): %s", text[:60])
        else:
            text = self._wrap_text(text)
            logger.info("VoxCPM generate: %s", text[:80])

        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            wav = self.model.generate(
                text=text,
                cfg_value=self.cfg_value,
                inference_timesteps=self.inference_timesteps,
                prompt_wav_path=self._prompt_wav_path,
                prompt_text=self._prompt_text,
            )
        return wav, self.model.tts_model.sample_rate

    def generate_streaming(self, text: str):
        """流式生成语音。远端走 /tts/stream，本地走 generate_streaming。

        yield 本地: float32 numpy 数组；远端: raw bytes。
        """
        self._ensure_voice_reference()

        if self._check_remote():
            yield from self._generate_streaming_remote(text)
        else:
            if self._use_cloning:
                logger.info("VoxCPM stream (clone): %s", text[:60])
            else:
                text = self._wrap_text(text)
                logger.info("VoxCPM stream generate: %s", text[:80])
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                yield from self.model.generate_streaming(
                    text=text,
                    cfg_value=self.cfg_value,
                    inference_timesteps=self.inference_timesteps,
                    prompt_wav_path=self._prompt_wav_path,
                    prompt_text=self._prompt_text,
                )

    def _stream_body(self, text: str) -> dict:
        d = {
            "text": text,
            "cfg_value": self.cfg_value,
            "inference_timesteps": self.inference_timesteps,
        }
        if self._use_cloning:
            d["prompt_wav_path"] = self._prompt_wav_path
            if self._prompt_text:
                d["prompt_text"] = self._prompt_text
        elif self.voice_desc and not text.startswith("("):
            d["voice_desc"] = self.voice_desc
        return d

    def _generate_remote_bare(self, text: str) -> tuple[np.ndarray, int]:
        """仅用于自举：强制发 voice_desc 请求，不带 prompt_wav_path。"""
        import soundfile as sf

        body = json.dumps({
            "text": text,
            "cfg_value": self.cfg_value,
            "inference_timesteps": self.inference_timesteps,
            "voice_desc": self.voice_desc,
        }).encode("utf-8")

        req = urllib.request.Request(
            f"{self._server_url}/tts",
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        resp = urllib.request.urlopen(req, timeout=120)
        wav_bytes = resp.read()
        sr = int(resp.headers.get("X-Sample-Rate", 44100))
        buf = io.BytesIO(wav_bytes)
        wav, samplerate = sf.read(buf, dtype="float32")
        return wav, samplerate

    def _generate_streaming_remote(self, text: str):
        """通过远程 HTTP 流式端点生成语音，yield raw bytes。"""
        body = json.dumps(self._stream_body(text)).encode("utf-8")

        req = urllib.request.Request(
            f"{self._server_url}/tts/stream",
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        resp = urllib.request.urlopen(req, timeout=120)

        while True:
            chunk = resp.read(8192)
            if not chunk:
                break
            yield chunk

    def _generate_remote(self, text: str) -> tuple[np.ndarray, int]:
        """通过远程 HTTP 服务生成语音。"""
        import soundfile as sf

        body = json.dumps(self._stream_body(text)).encode("utf-8")

        req = urllib.request.Request(
            f"{self._server_url}/tts",
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        resp = urllib.request.urlopen(req, timeout=120)
        wav_bytes = resp.read()
        sr = int(resp.headers.get("X-Sample-Rate", 44100))

        buf = io.BytesIO(wav_bytes)
        wav, samplerate = sf.read(buf, dtype="float32")
        return wav, samplerate

    def generate_to_bytes(self, text: str, fmt: str = "WAV") -> bytes:
        """生成语音并编码为音频字节。"""
        import soundfile as sf

        self._ensure_voice_reference()

        if self._check_remote():
            body = json.dumps(self._stream_body(text)).encode("utf-8")
            req = urllib.request.Request(
                f"{self._server_url}/tts",
                data=body,
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            resp = urllib.request.urlopen(req, timeout=120)
            return resp.read()

        wav, sr = self.generate(text)
        buf = io.BytesIO()
        sf.write(buf, wav, sr, format=fmt.upper())
        return buf.getvalue()

    def generate_to_file(self, text: str, path: str) -> None:
        wav, sr = self.generate(text)
        import soundfile as sf

        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        sf.write(path, wav, sr)
        logger.info("VoxCPM 音频已保存: %s (%d 采样)", path, len(wav))
