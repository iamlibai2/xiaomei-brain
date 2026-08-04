from __future__ import annotations

import json
from pathlib import Path
import sys

import numpy as np

from xiaomei_brain.body.perception.face_id import FaceID
from xiaomei_brain.body.perception.speaker_id import SpeakerID
from xiaomei_brain.body.perception.stt import STT
from xiaomei_brain.runtime_services.catalog import SERVICE_SPECS
from xiaomei_brain.runtime_services.manager import LocalAIRuntimeManager
from xiaomei_brain.runtime_services.selection import ModelSelectionStore
from xiaomei_brain.runtime_services.http_utils import health_payload
from xiaomei_brain.runtime_services import downloader
from xiaomei_brain.base.shared_embedder import SharedEmbedder


def test_runtime_catalog_separates_shared_inference_services() -> None:
    specs = {item.service_id: item for item in SERVICE_SPECS}

    assert specs["embedding"].required is True
    assert specs["embedding"].controllable is True
    assert specs["stt"].controllable is True
    assert specs["tts_voxcpm"].controllable is True
    assert specs["voiceprint"].controllable is True
    assert specs["face"].controllable is True
    assert specs["embedding"].downloadable is True
    assert specs["face"].downloadable is False


def test_runtime_health_reports_process_memory() -> None:
    health = health_payload(model="test", device="cpu")

    assert health["pid"] > 0
    assert health["memory_bytes"] > 0
    assert health["system_memory_total_bytes"] >= health["memory_bytes"]


def test_system_status_reports_host_load(tmp_path: Path, monkeypatch) -> None:
    manager = LocalAIRuntimeManager(tmp_path)
    monkeypatch.setattr(manager, "_gpu_status", lambda: [])

    status = manager.system_status()

    assert 0 <= status["cpu_percent"] <= 100
    assert 0 <= status["memory_percent"] <= 100
    assert status["memory_total_bytes"] > 0
    assert status["gpus"] == []


def test_runtime_status_prefers_live_health_over_untracked_process(
    tmp_path: Path,
    monkeypatch,
) -> None:
    manager = LocalAIRuntimeManager(tmp_path)
    monkeypatch.setattr(
        manager,
        "_health",
        lambda endpoint: {"status": "ok", "device": "cpu"} if endpoint else None,
    )

    status = manager.status("embedding")

    assert status["state"] == "online"
    assert status["device"] == "cpu"
    assert status["pid"] is None


def test_runtime_metadata_does_not_accept_reused_pid(tmp_path: Path) -> None:
    manager = LocalAIRuntimeManager(tmp_path)
    (tmp_path / "embedding.json").write_text(
        json.dumps({"pid": 99999999, "create_time": 1}),
        encoding="utf-8",
    )

    assert manager._tracked_process("embedding") is None


def test_dead_managed_process_is_reported_as_error(tmp_path: Path, monkeypatch) -> None:
    manager = LocalAIRuntimeManager(tmp_path)
    (tmp_path / "stt.json").write_text(
        json.dumps({"pid": 99999999, "create_time": 1}),
        encoding="utf-8",
    )
    (tmp_path / "stt.log").write_text("model initialization failed\n", encoding="utf-8")
    monkeypatch.setattr(manager, "_health", lambda _endpoint: None)

    status = manager.status("stt")

    assert status["state"] == "error"
    assert status["error"] == "model initialization failed"


def test_missing_model_is_reported_as_not_installed(tmp_path: Path, monkeypatch) -> None:
    manager = LocalAIRuntimeManager(tmp_path)
    monkeypatch.setattr("xiaomei_brain.runtime_services.manager.cached_model_path", lambda _spec: "")
    monkeypatch.setattr("xiaomei_brain.runtime_services.manager.cached_model_bytes", lambda _spec: 0)
    monkeypatch.setattr("xiaomei_brain.runtime_services.manager.missing_dependencies", lambda _spec: [])
    monkeypatch.setattr(manager, "_health", lambda _endpoint: None)

    status = manager.status("embedding")

    assert status["state"] == "not_installed"
    assert status["download_progress"] == 0


def test_active_download_exposes_progress(tmp_path: Path, monkeypatch) -> None:
    manager = LocalAIRuntimeManager(tmp_path)

    class Process:
        pid = 42

    monkeypatch.setattr("xiaomei_brain.runtime_services.manager.cached_model_path", lambda _spec: "")
    monkeypatch.setattr("xiaomei_brain.runtime_services.manager.cached_model_bytes", lambda spec: spec.expected_size_bytes // 4)
    monkeypatch.setattr("xiaomei_brain.runtime_services.manager.missing_dependencies", lambda _spec: [])
    monkeypatch.setattr(manager, "_health", lambda _endpoint: None)
    monkeypatch.setattr(manager, "_tracked_download", lambda _service_id: Process())

    status = manager.status("embedding")

    assert status["state"] == "downloading"
    assert status["download_progress"] == 25
    assert status["pid"] == 42


def test_downloader_writes_completion_record(tmp_path: Path, monkeypatch) -> None:
    model = tmp_path / "model"
    model.mkdir()
    completion = tmp_path / "embedding.model.json"
    monkeypatch.setattr(downloader, "download", lambda _service_id, _model_id: str(model))
    monkeypatch.setattr(sys, "argv", [
        "downloader",
        "embedding",
        "--model",
        "bge-m3",
        "--completion-file",
        str(completion),
    ])

    downloader.main()

    assert json.loads(completion.read_text(encoding="utf-8"))["model_path"] == str(model)


def test_huggingface_download_falls_back_from_mirror(monkeypatch) -> None:
    attempts: list[str] = []

    def fake_snapshot_download(repo_id: str, *, endpoint: str, max_workers: int) -> str:
        attempts.append(endpoint)
        assert repo_id == "openai/whisper-small"
        assert max_workers == 4
        if endpoint == "https://hf-mirror.com":
            raise RuntimeError("mirror metadata unavailable")
        return "/models/whisper-small"

    monkeypatch.delenv("HF_ENDPOINT", raising=False)
    monkeypatch.setattr("huggingface_hub.snapshot_download", fake_snapshot_download)

    assert downloader._download_huggingface("openai/whisper-small") == "/models/whisper-small"
    assert attempts == ["https://hf-mirror.com", "https://huggingface.co"]


def test_huggingface_download_respects_explicit_endpoint(monkeypatch) -> None:
    attempts: list[str] = []

    def fake_snapshot_download(repo_id: str, *, endpoint: str, max_workers: int) -> str:
        attempts.append(endpoint)
        raise RuntimeError("configured endpoint unavailable")

    monkeypatch.setenv("HF_ENDPOINT", "https://models.example.test/")
    monkeypatch.setattr("huggingface_hub.snapshot_download", fake_snapshot_download)

    try:
        downloader._download_huggingface("openai/whisper-small")
    except RuntimeError as exc:
        assert "models.example.test" in str(exc)
    else:
        raise AssertionError("download unexpectedly succeeded")
    assert attempts == ["https://models.example.test"]


def test_whisper_download_prefers_modelscope(monkeypatch) -> None:
    attempts: list[tuple[str, int, list[str]]] = []

    def fake_snapshot_download(
        repo_id: str,
        *,
        max_workers: int,
        allow_file_pattern: list[str],
    ) -> str:
        attempts.append((repo_id, max_workers, allow_file_pattern))
        return "/models/modelscope-whisper-small"

    monkeypatch.setattr("modelscope.snapshot_download", fake_snapshot_download)
    monkeypatch.setattr(
        downloader,
        "_download_huggingface",
        lambda _repo_id: (_ for _ in ()).throw(AssertionError("unexpected Hugging Face fallback")),
    )

    assert downloader._download_whisper_small() == "/models/modelscope-whisper-small"
    assert attempts[0][0:2] == ("openai-mirror/whisper-small", 4)
    assert "model.safetensors" in attempts[0][2]
    assert "flax_model.msgpack" not in attempts[0][2]
    assert "tf_model.h5" not in attempts[0][2]


def test_whisper_download_falls_back_to_huggingface(monkeypatch) -> None:
    def failing_modelscope(*_args, **_kwargs) -> str:
        raise RuntimeError("ModelScope unavailable")

    monkeypatch.setattr("modelscope.snapshot_download", failing_modelscope)
    monkeypatch.setattr(
        downloader,
        "_download_huggingface",
        lambda repo_id: f"/models/{repo_id}",
    )

    assert downloader._download_whisper_small() == "/models/openai/whisper-small"


def test_modelscope_download_progress_is_read_from_log(tmp_path: Path) -> None:
    manager = LocalAIRuntimeManager(tmp_path)
    (tmp_path / "stt.download.log").write_text(
        "\x1b[32mmodel.safetensors:  47%|████▋     | 454M/967M\x1b[0m\n",
        encoding="utf-8",
    )

    assert manager._download_log_progress("stt", "whisper-small") == 47


def test_model_selection_can_change_before_compatibility_lock(tmp_path: Path) -> None:
    selections = ModelSelectionStore(tmp_path)

    assert selections.selected("embedding") == "bge-m3"
    selections.select("embedding", "bge-small-zh-v1.5")

    assert selections.selected("embedding") == "bge-small-zh-v1.5"


def test_model_selection_cannot_change_after_compatibility_lock(tmp_path: Path) -> None:
    selections = ModelSelectionStore(tmp_path)
    selections.select("embedding", "bge-small-zh-v1.5")
    selections.lock("embedding", "bge-small-zh-v1.5", "已有向量数据")

    selections.select("embedding", "bge-small-zh-v1.5")
    try:
        selections.select("embedding", "bge-m3")
    except ValueError as exc:
        assert "已有向量数据" in str(exc)
    else:
        raise AssertionError("locked embedding selection changed")


def test_runtime_device_selection_is_persisted_per_service(tmp_path: Path) -> None:
    (tmp_path / "config.json").write_text(
        json.dumps({"providers": {"demo": {"baseUrl": "https://example.test"}}}),
        encoding="utf-8",
    )
    selections = ModelSelectionStore(tmp_path)

    assert selections.selected_device("embedding") == "auto"
    selections.select_device("embedding", "bge-m3", "cpu")

    assert ModelSelectionStore(tmp_path).selected_device("embedding") == "cpu"
    config = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
    assert config["providers"]["demo"]["baseUrl"] == "https://example.test"
    assert config["local_ai_services"]["embedding"]["device"] == "cpu"


def test_model_rejects_unsupported_runtime_device(tmp_path: Path) -> None:
    selections = ModelSelectionStore(tmp_path)

    try:
        selections.select_device("face", "dlib", "cuda")
    except ValueError as exc:
        assert "不支持" in str(exc)
    else:
        raise AssertionError("face model accepted unsupported CUDA device")


def test_runtime_status_lists_models_and_selected_model(tmp_path: Path, monkeypatch) -> None:
    manager = LocalAIRuntimeManager(tmp_path)
    monkeypatch.setattr("xiaomei_brain.runtime_services.manager.cached_model_path", lambda _spec: "")
    monkeypatch.setattr("xiaomei_brain.runtime_services.manager.cached_model_bytes", lambda _spec: 0)
    monkeypatch.setattr("xiaomei_brain.runtime_services.manager.missing_dependencies", lambda _spec: [])
    monkeypatch.setattr(manager, "_health", lambda _endpoint: None)

    status = manager.status("embedding")

    assert status["selected_model_id"] == "bge-m3"
    assert {item["id"] for item in status["models"]} == {"bge-m3", "bge-small-zh-v1.5"}
    assert status["selection_locked"] is False


def test_ensure_running_starts_shared_service_and_waits_for_health(tmp_path: Path, monkeypatch) -> None:
    manager = LocalAIRuntimeManager(tmp_path)
    states = iter(({
        "state": "stopped",
        "installed": True,
        "downloadable": True,
        "model_present": True,
        "name": "向量服务",
        "model": "BGE-M3",
    }, {
        "state": "online",
        "installed": True,
        "downloadable": True,
        "model_present": True,
        "name": "向量服务",
        "model": "BGE-M3",
    }))
    monkeypatch.setattr(manager, "status", lambda _service_id: next(states))
    monkeypatch.setattr(manager, "start", lambda _service_id, device: {
        "state": "starting",
        "installed": True,
        "downloadable": True,
        "model_present": True,
        "name": "向量服务",
        "model": "BGE-M3",
    })
    monkeypatch.setattr("xiaomei_brain.runtime_services.manager.time.sleep", lambda _seconds: None)

    assert manager.ensure_running("embedding")["state"] == "online"


def test_required_remote_embedder_never_loads_local_model() -> None:
    class OfflineRemote:
        available = False

    embedder = SharedEmbedder.__new__(SharedEmbedder)
    embedder._remote = OfflineRemote()
    embedder._remote_required = True

    try:
        embedder.embed("hello")
    except RuntimeError as exc:
        assert "共享向量服务不可用" in str(exc)
    else:
        raise AssertionError("required shared embedding unexpectedly fell back locally")


def test_stt_uses_shared_service_before_loading_local_model(monkeypatch) -> None:
    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self) -> bytes:
            return json.dumps({"text": "你好", "emotion": "中性", "events": []}).encode()

    monkeypatch.delenv("XIAOMEI_STT_LOCAL_ONLY", raising=False)
    monkeypatch.setattr("urllib.request.urlopen", lambda *_args, **_kwargs: Response())
    engine = STT()
    monkeypatch.setattr(engine, "_ensure_model", lambda: (_ for _ in ()).throw(AssertionError("local model loaded")))

    result = engine.transcribe((1000).to_bytes(2, "little", signed=True) * 200, sample_rate=16000)

    assert result == {"text": "你好", "emotion": "中性", "events": []}


def test_voiceprint_uses_shared_service_before_loading_local_model(monkeypatch) -> None:
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self) -> bytes:
            return json.dumps({"embedding": [0.25, -0.5]}).encode()

    monkeypatch.delenv("XIAOMEI_VOICEPRINT_LOCAL_ONLY", raising=False)
    monkeypatch.setattr("urllib.request.urlopen", lambda *_args, **_kwargs: Response())
    engine = SpeakerID()
    monkeypatch.setattr(engine, "_ensure_loaded", lambda: (_ for _ in ()).throw(AssertionError("local model loaded")))

    embedding = engine._extract_embedding(b"\x00\x00" * 200, 16000)

    assert embedding is not None
    assert embedding.tolist() == [0.25, -0.5]


def test_face_uses_shared_service_before_loading_local_model(tmp_path: Path, monkeypatch) -> None:
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self) -> bytes:
            return json.dumps({
                "faces": [{
                    "bbox": [1, 4, 5, 0],
                    "encoding": [0.1, 0.2],
                    "landmarks": {"left_eye": [[1, 2], [2, 2]]},
                }],
            }).encode()

    image = tmp_path / "face.jpg"
    image.write_bytes(b"image")
    monkeypatch.delenv("XIAOMEI_FACE_LOCAL_ONLY", raising=False)
    monkeypatch.setattr("urllib.request.urlopen", lambda *_args, **_kwargs: Response())
    engine = FaceID()
    monkeypatch.setattr(engine, "_ensure_loaded", lambda: (_ for _ in ()).throw(AssertionError("local model loaded")))

    faces = engine.detect_all(str(image))

    assert faces[0]["bbox"] == (1, 4, 5, 0)
    assert faces[0]["encoding"].tolist() == [0.10000000149011612, 0.20000000298023224]
    assert faces[0]["landmarks"]["left_eye"] == [(1, 2), (2, 2)]


def test_voiceprint_verification_compares_shared_embeddings(monkeypatch) -> None:
    engine = SpeakerID()
    values = iter((np.asarray([1.0, 0.0]), np.asarray([0.9, 0.1])))
    monkeypatch.setattr(engine, "_extract_embedding", lambda *_args: next(values))

    matched, score = engine.verify(b"first", b"second")

    assert matched is True
    assert score > 0.9


def test_face_templates_load_without_loading_inference_model(tmp_path: Path, monkeypatch) -> None:
    np.save(tmp_path / "person_a.npy", np.asarray([0.1, 0.2], dtype=np.float32))
    engine = FaceID()
    monkeypatch.setattr(engine, "_ensure_loaded", lambda: (_ for _ in ()).throw(AssertionError("model loaded")))

    engine.load(str(tmp_path))

    assert engine.known_names == ["person_a"]
    assert engine.match(np.asarray([0.1, 0.2], dtype=np.float32)) == "person_a"
