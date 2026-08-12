"""Declarative catalog for host-local AI runtime services."""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RuntimeServiceSpec:
    service_id: str
    name: str
    description: str
    model: str
    expected_size: str
    endpoint: str
    required: bool
    controllable: bool
    dependencies: tuple[str, ...]
    cache_candidates: tuple[str, ...]
    downloadable: bool
    expected_size_bytes: int
    device_default: str = "cpu"


@dataclass(frozen=True)
class RuntimeModelSpec:
    service_id: str
    model_id: str
    name: str
    source: str
    expected_size: str
    expected_size_bytes: int
    cache_candidates: tuple[str, ...]
    dependencies: tuple[str, ...]
    recommended_device: str = "auto"
    supported_devices: tuple[str, ...] = ("auto", "cpu", "cuda")


def _home(value: str) -> str:
    return str(Path.home() / value)


SERVICE_SPECS: tuple[RuntimeServiceSpec, ...] = (
    RuntimeServiceSpec(
        service_id="embedding",
        name="向量服务",
        description="记忆搜索、能力与工具召回的核心依赖",
        model="BAAI/bge-m3",
        expected_size="约 4.6 GB",
        endpoint="http://127.0.0.1:18765",
        required=True,
        controllable=True,
        dependencies=("sentence_transformers", "modelscope"),
        cache_candidates=(
            _home(".cache/modelscope/hub/models/BAAI/bge-m3"),
            _home(".cache/huggingface/hub/models--BAAI--bge-m3"),
        ),
        downloadable=True,
        expected_size_bytes=4_587_311_901,
    ),
    RuntimeServiceSpec(
        service_id="stt",
        name="语音识别",
        description="将本机或远端身体收到的语音转换为文字",
        model="iic/SenseVoiceSmall",
        expected_size="约 0.9 GB",
        endpoint="http://127.0.0.1:18767",
        required=False,
        controllable=True,
        dependencies=("funasr", "soundfile"),
        cache_candidates=(
            _home(".cache/modelscope/hub/models/iic/SenseVoiceSmall"),
            _home(".cache/huggingface/hub/models--FunAudioLLM--SenseVoiceSmall"),
        ),
        downloadable=True,
        expected_size_bytes=940_019_161,
    ),
    RuntimeServiceSpec(
        service_id="tts_voxcpm",
        name="本地语音合成",
        description="使用 VoxCPM 生成并交给身体播放语音",
        model="openbmb/VoxCPM1.5",
        expected_size="约 2 GB",
        endpoint="http://127.0.0.1:18766",
        required=False,
        controllable=True,
        dependencies=("voxcpm", "soundfile"),
        cache_candidates=(
            _home("VoxCPM1.5"),
            _home(".cache/huggingface/hub/models--openbmb--VoxCPM1.5"),
        ),
        downloadable=True,
        expected_size_bytes=1_953_412_905,
        device_default="cuda",
    ),
    RuntimeServiceSpec(
        service_id="voiceprint",
        name="声纹识别",
        description="共享声纹特征提取模型；身份模板仍由每个 Agent 独立保存",
        model="speechbrain/spkrec-ecapa-voxceleb",
        expected_size="约 85 MB",
        endpoint="http://127.0.0.1:18768",
        required=False,
        controllable=True,
        dependencies=("speechbrain", "soundfile"),
        cache_candidates=(
            _home(".cache/huggingface/hub/models--speechbrain--spkrec-ecapa-voxceleb"),
        ),
        downloadable=True,
        expected_size_bytes=89_262_397,
    ),
    RuntimeServiceSpec(
        service_id="face",
        name="人脸识别",
        description="共享人脸检测与特征提取模型；人物绑定仍属于各 Agent",
        model="face_recognition/dlib",
        expected_size="随运行库安装",
        endpoint="http://127.0.0.1:18769",
        required=False,
        controllable=True,
        dependencies=("face_recognition",),
        cache_candidates=(),
        downloadable=False,
        expected_size_bytes=0,
    ),
)


MODEL_SPECS: tuple[RuntimeModelSpec, ...] = (
    RuntimeModelSpec(
        service_id="embedding",
        model_id="bge-m3",
        name="BGE-M3",
        source="BAAI/bge-m3",
        expected_size="约 4.6 GB",
        expected_size_bytes=4_587_311_901,
        cache_candidates=(
            _home(".cache/modelscope/hub/models/BAAI/bge-m3"),
            _home(".cache/huggingface/hub/models--BAAI--bge-m3"),
        ),
        dependencies=("sentence_transformers", "modelscope"),
    ),
    RuntimeModelSpec(
        service_id="embedding",
        model_id="bge-small-zh-v1.5",
        name="BGE Small 中文 1.5",
        source="BAAI/bge-small-zh-v1.5",
        expected_size="约 95 MB",
        expected_size_bytes=100_000_000,
        cache_candidates=(
            _home(".cache/huggingface/hub/models--BAAI--bge-small-zh-v1.5"),
        ),
        dependencies=("sentence_transformers",),
        recommended_device="cpu",
    ),
    RuntimeModelSpec(
        service_id="stt",
        model_id="sensevoice-small",
        name="SenseVoice Small",
        source="iic/SenseVoiceSmall",
        expected_size="约 0.9 GB",
        expected_size_bytes=940_019_161,
        cache_candidates=(
            _home(".cache/modelscope/hub/models/iic/SenseVoiceSmall"),
            _home(".cache/huggingface/hub/models--FunAudioLLM--SenseVoiceSmall"),
        ),
        dependencies=("funasr", "soundfile"),
        recommended_device="cpu",
    ),
    RuntimeModelSpec(
        service_id="stt",
        model_id="whisper-small",
        name="Whisper Small",
        source="openai/whisper-small",
        expected_size="约 1.0 GB",
        expected_size_bytes=1_000_000_000,
        cache_candidates=(
            _home(".cache/modelscope/models/openai-mirror--whisper-small/snapshots/master"),
            _home(".cache/modelscope/hub/models/openai-mirror/whisper-small"),
            _home(".cache/huggingface/hub/models--openai--whisper-small"),
        ),
        dependencies=("transformers",),
    ),
    RuntimeModelSpec(
        service_id="tts_voxcpm",
        model_id="voxcpm-1.5",
        name="VoxCPM 1.5",
        source="openbmb/VoxCPM1.5",
        expected_size="约 2 GB",
        expected_size_bytes=1_953_412_905,
        cache_candidates=(
            _home("VoxCPM1.5"),
            _home(".cache/huggingface/hub/models--openbmb--VoxCPM1.5"),
        ),
        dependencies=("voxcpm", "soundfile"),
        recommended_device="cuda",
    ),
    RuntimeModelSpec(
        service_id="voiceprint",
        model_id="ecapa-voxceleb",
        name="ECAPA-TDNN VoxCeleb",
        source="speechbrain/spkrec-ecapa-voxceleb",
        expected_size="约 85 MB",
        expected_size_bytes=89_262_397,
        cache_candidates=(
            _home(".cache/huggingface/hub/models--speechbrain--spkrec-ecapa-voxceleb"),
        ),
        dependencies=("speechbrain", "soundfile"),
        recommended_device="cpu",
    ),
    RuntimeModelSpec(
        service_id="face",
        model_id="dlib",
        name="dlib 人脸识别",
        source="face_recognition/dlib",
        expected_size="随运行库安装",
        expected_size_bytes=0,
        cache_candidates=(),
        dependencies=("face_recognition",),
        recommended_device="cpu",
        supported_devices=("cpu",),
    ),
)


DEFAULT_MODELS = {
    "embedding": "bge-m3",
    "stt": "sensevoice-small",
    "tts_voxcpm": "voxcpm-1.5",
    "voiceprint": "ecapa-voxceleb",
    "face": "dlib",
}

DEFAULT_DEVICES = {
    "embedding": "auto",
    "stt": "auto",
    "tts_voxcpm": "auto",
    "voiceprint": "auto",
    "face": "cpu",
}


def get_service_spec(service_id: str) -> RuntimeServiceSpec:
    for spec in SERVICE_SPECS:
        if spec.service_id == service_id:
            return spec
    raise KeyError(service_id)


def list_model_specs(service_id: str) -> list[RuntimeModelSpec]:
    return [model for model in MODEL_SPECS if model.service_id == service_id]


def get_model_spec(service_id: str, model_id: str) -> RuntimeModelSpec:
    for model in MODEL_SPECS:
        if model.service_id == service_id and model.model_id == model_id:
            return model
    raise KeyError(f"{service_id}:{model_id}")


def missing_dependencies(spec: RuntimeServiceSpec | RuntimeModelSpec) -> list[str]:
    return [name for name in spec.dependencies if importlib.util.find_spec(name) is None]


def cached_model_path(spec: RuntimeServiceSpec | RuntimeModelSpec) -> str:
    for candidate in spec.cache_candidates:
        path = Path(candidate)
        if path.is_dir() and _directory_size(path) >= spec.expected_size_bytes * 0.85:
            return str(path)
    return ""


def cached_model_bytes(spec: RuntimeServiceSpec | RuntimeModelSpec) -> int:
    sizes = [_directory_size(Path(candidate)) for candidate in spec.cache_candidates]
    return max(sizes, default=0)


def _directory_size(path: Path) -> int:
    if not path.is_dir():
        return 0
    total = 0
    try:
        for item in path.rglob("*"):
            if item.is_file():
                try:
                    total += item.stat().st_size
                except OSError:
                    pass
    except OSError:
        return total
    return total
